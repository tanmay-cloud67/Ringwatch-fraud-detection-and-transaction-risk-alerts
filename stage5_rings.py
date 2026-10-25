"""Stage 5: detect graph rings and attach deterministic evidence to graph nodes/edges."""
from __future__ import annotations

import hashlib
from typing import Any, cast

import networkx as nx
import pandas as pd

from config import DEFAULT_SETTINGS, risk_band

RING_NAMES = {
    "cycle": "Circular flow",
    "community": "Dense account community",
    "fan_in": "Fan-in hub",
    "fan_out": "Fan-out hub",
}


def _ring_id(kind: str, accounts: list[str], txn_ids: list[str]) -> str:
    digest = hashlib.sha1((kind + "|" + "|".join(sorted(accounts)) + "|" + "|".join(sorted(txn_ids))).encode()).hexdigest()[:8].upper()
    return f"RW-RING-{digest}"


def _edge_ids_for_txns(edges: list[dict[str, Any]], txn_ids: set[str]) -> list[str]:
    return sorted(edge["id"] for edge in edges if txn_ids.intersection(edge["transaction_ids"]))


def detect_rings(
    graph_result: dict[str, Any],
    data: pd.DataFrame,
    accounts: dict[str, dict[str, Any]],
    findings: list[dict[str, Any]],
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Find cycles, dense communities, fan-in cohorts and outbound hubs."""
    settings = {**DEFAULT_SETTINGS, **(settings or {})}
    graph: nx.DiGraph = graph_result["graph"]
    edges = graph_result["edges"]
    rings: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()

    def add_ring(kind: str, members, txn_ids, explanation: str, *, cycle_order=None, density=None, hub=None) -> None:
        member_list = sorted({str(item) for item in members})
        txn_set = {str(item) for item in txn_ids}
        if not member_list or not txn_set:
            return
        key = (kind, tuple(member_list), tuple(sorted(txn_set)))
        if key in seen_keys:
            return
        seen_keys.add(key)
        selected = cast(pd.DataFrame, data.loc[data["txn_id"].astype(str).isin(list(txn_set))])
        actual_ids = set(selected["txn_id"].astype(str))
        if not actual_ids:
            return
        member_scores = [float(accounts[item]["risk_score"]) for item in member_list if item in accounts]
        relevant_edges = _edge_ids_for_txns(edges, actual_ids)
        edge_scores = [float(edge["risk_score"]) for edge in edges if edge["id"] in relevant_edges]
        score = max(member_scores + edge_scores + [0.0])
        total_value = sum(float(value) for value in cast(list[Any], selected["amount"].tolist()))
        ring = {
            "id": _ring_id(kind, member_list, sorted(actual_ids)),
            "ring_id": _ring_id(kind, member_list, sorted(actual_ids)),
            "type": kind,
            "type_label": RING_NAMES[kind],
            "accounts": member_list,
            "member_accounts": member_list,
            "transaction_ids": sorted(actual_ids),
            "transaction_count": int(len(actual_ids)),
            "edge_ids": relevant_edges,
            "total_value": round(total_value, 2),
            "amount": round(total_value, 2),
            "cycle_length": int(len(cycle_order)) if cycle_order else None,
            "cycle_order": [str(item) for item in cycle_order] if cycle_order else None,
            "density": round(float(density), 3) if density is not None else None,
            "hub_account": str(hub) if hub else None,
            "risk_score": round(score, 1),
            "risk_band": risk_band(score, settings),
            "reasons": [str(explanation)],
            "explanation": str(explanation),
            "score_basis": "Maximum attached Stage 3 account or edge risk score; not a calibrated fraud probability.",
        }
        rings.append(ring)

    # Stage 3's configurable cycle rule validates the actual edge transactions and rolling time window.
    # Stage 5 turns that evidence into a graph ring instead of re-enumerating paths over the full multi-month graph.
    min_len = int(settings["cycle_min_accounts"])
    max_len = int(settings["cycle_max_accounts"])
    for finding in findings:
        if finding.get("source") != "rule" or finding.get("rule_id") != "circular_flow":
            continue
        members = sorted(set(str(item) for item in finding.get("accounts", [])))
        txn_ids = [str(item) for item in finding.get("txn_ids", [])]
        if not min_len <= len(members) <= max_len or len(txn_ids) < len(members):
            continue
        selected_frame = cast(pd.DataFrame, data.loc[data["txn_id"].astype(str).isin(txn_ids)])
        selected_rows = cast(list[dict[str, Any]], selected_frame.to_dict(orient="records"))
        next_account = {str(row["from_account"]): str(row["to_account"]) for row in selected_rows}
        cycle_order = None
        for start in members:
            path = []
            seen = set()
            current = start
            while current in next_account and current not in seen:
                path.append(current)
                seen.add(current)
                current = next_account[current]
            if current == start and len(path) == len(members):
                cycle_order = path
                break
        if cycle_order is None:
            # The rule has still proven a time-bounded cycle; sorted members remain a safe graph fallback.
            cycle_order = members
        add_ring("cycle", members, txn_ids, finding["explanation"], cycle_order=cycle_order)

    # Louvain groups are evaluated on an undirected projection; thresholds are demo heuristics.
    undirected = nx.Graph()
    undirected.add_nodes_from(graph.nodes)
    for source, target, attributes in graph.edges(data=True):
        if source == target:
            continue
        prior = float(undirected.get_edge_data(source, target, {}).get("weight", 0.0))
        undirected.add_edge(source, target, weight=prior + float(attributes.get("weight", 0.0)))
    communities = []
    if undirected.number_of_edges():
        communities = nx.community.louvain_communities(undirected, weight="weight", seed=42)
    cycle_member_sets = {frozenset(ring["accounts"]) for ring in rings if ring["type"] == "cycle"}
    for community in communities:
        members = sorted(str(item) for item in community)
        if len(members) < 3 or frozenset(members) in cycle_member_sets:
            continue
        subgraph = undirected.subgraph(members)
        density = float(nx.density(subgraph))
        if density < 0.35:
            continue
        internal = [edge for edge in edges if edge["from"] in community and edge["to"] in community and edge["from"] != edge["to"]]
        txn_ids = sorted({txn_id for edge in internal for txn_id in edge["transaction_ids"]})
        explanation = f"Dense community of {len(members)} accounts with {density:.0%} undirected link density (minimum 35%)."
        add_ring("community", members, txn_ids, explanation, density=density)

    # The rule-defined inbound cohort already proves both the sender count and configured pass-through behavior.
    for finding in findings:
        if finding.get("rule_id") != "fanin" or finding.get("source") != "rule":
            continue
        members = finding.get("accounts", [])
        txn_ids = finding.get("txn_ids", [])
        hub = max(members, key=lambda account: graph.in_degree(account) if account in graph else 0) if members else None
        add_ring("fan_in", members, txn_ids, finding["explanation"], hub=hub)

    minimum_hub_degree = int(settings["fanin_min_senders"])
    window_ns = pd.Timedelta(minutes=float(settings["fanin_window_minutes"])).value
    for hub in sorted(graph.nodes):
        outgoing = cast(pd.DataFrame, data.loc[(data["from_account"].astype(str) == str(hub)) & (data["to_account"].astype(str) != str(hub))])
        if outgoing.empty:
            continue
        # Stage 2 returns the filtered rows in stable UTC timestamp order.
        outgoing = outgoing.reset_index(drop=True)
        times = outgoing["timestamp"].astype("int64").to_numpy()
        for start in range(len(outgoing)):
            end = int(pd.Series(times).searchsorted(times[start] + window_ns, side="right"))
            cohort = cast(pd.DataFrame, outgoing.iloc[start:end])
            recipients = sorted(cohort["to_account"].astype(str).unique().tolist())
            if len(recipients) < minimum_hub_degree:
                continue
            members = [str(hub), *recipients]
            txn_ids = cohort["txn_id"].astype(str).tolist()
            elapsed = (int(times[end - 1]) - int(times[start])) / 3.6e12 if end > start else 0.0
            explanation = f"One account sent funds to {len(recipients)} distinct accounts within {settings['fanin_window_minutes']} minutes (span {elapsed:.1f}h)."
            add_ring("fan_out", members, txn_ids, explanation, hub=str(hub))
            break

    rings.sort(key=lambda item: (-item["risk_score"], item["id"]))
    for node in graph_result["nodes"]:
        node["ring_ids"] = []
    for edge in edges:
        edge["ring_ids"] = []
        edge["ring_types"] = []
        edge["is_ring"] = False
        edge["is_circular"] = False
    for ring in rings:
        for account in ring["accounts"]:
            if account in graph:
                graph.nodes[account]["ring_ids"].append(ring["id"])
            node = next((item for item in graph_result["nodes"] if item["id"] == account), None)
            if node is not None:
                node["ring_ids"].append(ring["id"])
        for edge in edges:
            if edge["id"] in ring["edge_ids"]:
                edge["ring_ids"].append(ring["id"])
                edge["ring_types"].append(ring["type"])
                edge["is_ring"] = True
                edge["is_circular"] = edge["is_circular"] or ring["type"] == "cycle"
                if graph.has_edge(edge["from"], edge["to"]):
                    graph.edges[edge["from"], edge["to"]]["ring_ids"].append(ring["id"])
                    graph.edges[edge["from"], edge["to"]]["ring_types"].append(ring["type"])
                    graph.edges[edge["from"], edge["to"]]["is_ring"] = True
                    graph.edges[edge["from"], edge["to"]]["is_circular"] = edge["is_circular"]

    ring_findings = [
        {
            "rule_id": f"ring_{ring['type']}",
            "rule_name": ring["type_label"],
            "points": 0,
            "explanation": ring["explanation"],
            "threshold": ring["score_basis"],
            "accounts": ring["accounts"],
            "txn_ids": ring["transaction_ids"],
            "source": "ring",
            "ring_id": ring["id"],
        }
        for ring in rings
    ]
    counts = {kind: sum(1 for ring in rings if ring["type"] == kind) for kind in RING_NAMES}
    return {
        "rings": rings,
        "ring_findings": ring_findings,
        "summary": {"ring_count": int(len(rings)), "counts_by_type": counts},
        "graph_result": graph_result,
    }
