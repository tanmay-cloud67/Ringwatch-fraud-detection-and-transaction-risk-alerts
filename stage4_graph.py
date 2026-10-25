"""Stage 4: aggregate scored transactions into a directed weighted account graph."""
from __future__ import annotations

from typing import Any, cast

import networkx as nx
import pandas as pd

from config import risk_band


def _stamp(value: Any) -> str:
    stamp = pd.Timestamp(value)
    return "" if stamp is pd.NaT else cast(pd.Timestamp, stamp).isoformat()


def build_graph(data: pd.DataFrame, accounts: dict[str, dict[str, Any]], account_features: pd.DataFrame | None = None, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a NetworkX DiGraph, serialized nodes/edges and structural metrics."""
    graph = nx.DiGraph()
    feature_map = {}
    if account_features is not None and not account_features.empty:
        feature_map = {str(row["account_id"]): row for row in account_features.to_dict(orient="records")}

    all_accounts = sorted(set(data["from_account"].astype(str)) | set(data["to_account"].astype(str)))
    for account in all_accounts:
        details = accounts[account]
        extra = feature_map.get(account, {})
        graph.add_node(
            account,
            id=account,
            risk_score=float(details["risk_score"]),
            ml_score=float(details["ml_score"]),
            risk_band=str(details["risk_band"]),
            flagged=bool(details["flagged"]),
            transaction_volume=int(details["transaction_count"]),
            in_degree=int(extra.get("in_degree", 0)),
            out_degree=int(extra.get("out_degree", 0)),
            top_reason=details["reasons"][0]["explanation"] if details["reasons"] else "No rule-based finding.",
            case_id=None,
            ring_ids=[],
        )

    edges: list[dict[str, Any]] = []
    grouped_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in cast(list[dict[str, Any]], data.to_dict(orient="records")):
        key = (str(row["from_account"]), str(row["to_account"]))
        grouped_rows.setdefault(key, []).append(row)
    # A single pass preserves Stage 2's stable timestamp/transaction-ID order.
    for source, target in sorted(grouped_rows):
        rows = grouped_rows[(source, target)]
        transactions = [
            {
                "txn_id": str(row["txn_id"]),
                "timestamp": _stamp(row["timestamp"]),
                "amount": round(float(row["amount"]), 2),
                "risk_score": round(float(row["risk_score"]), 1),
                "risk_band": str(row["risk_band"]),
            }
            for row in rows
        ]
        amounts = [float(row["amount"]) for row in rows]
        risk_scores = [float(row["risk_score"]) for row in rows]
        total = round(sum(amounts), 2)
        max_risk = round(max(risk_scores), 1) if risk_scores else 0.0
        mean_risk = round(sum(risk_scores) / len(risk_scores), 1) if risk_scores else 0.0
        edge_id = f"{source}→{target}"
        edge = {
            "id": edge_id,
            "from": str(source),
            "to": str(target),
            "amount": total,
            "total_amount": total,
            "weight": total,
            "transaction_count": int(len(rows)),
            "first_timestamp": transactions[0]["timestamp"],
            "last_timestamp": transactions[-1]["timestamp"],
            "time_range": {"start": transactions[0]["timestamp"], "end": transactions[-1]["timestamp"]},
            "risk_score": max_risk,
            "max_transaction_risk_score": max_risk,
            "mean_transaction_risk_score": mean_risk,
            "risk_band": risk_band(max_risk, settings),
            "transaction_ids": [item["txn_id"] for item in transactions],
            "transactions": transactions,
            "ring_ids": [],
            "ring_types": [],
            "is_ring": False,
            "is_circular": False,
            "case_id": None,
        }
        graph.add_edge(str(source), str(target), **edge)
        edges.append(edge)

    nodes = []
    for account in all_accounts:
        attributes = dict(graph.nodes[account])
        attributes["reasons"] = accounts[account]["reasons"]
        nodes.append(attributes)

    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()
    directed_possible = node_count * max(node_count - 1, 0)
    non_self_edges = sum(1 for source, target in graph.edges if source != target)
    density = non_self_edges / directed_possible if directed_possible else 0.0
    components = list(nx.weakly_connected_components(graph)) if node_count else []
    stats = {
        "node_count": int(node_count),
        "edge_count": int(edge_count),
        "weakly_connected_components": int(len(components)),
        "component_count": int(len(components)),
        "directed_density": round(float(density), 6),
        "density": round(float(density), 6),
        "self_loop_edge_count": int(sum(1 for source, target in graph.edges if source == target)),
    }
    return {"graph": graph, "nodes": nodes, "edges": edges, "stats": stats}
