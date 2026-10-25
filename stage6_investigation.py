"""Stage 6: build investigator-ready cases from weakly connected flagged transfers."""
from __future__ import annotations

import hashlib
from typing import Any, cast

import networkx as nx
import pandas as pd

from config import DEFAULT_SETTINGS, risk_band


def _iso_stamp(value: Any) -> str:
    stamp = cast(pd.Timestamp, pd.Timestamp(value))
    return "" if stamp is pd.NaT else stamp.isoformat()


def _unique_reasons(rows: pd.DataFrame, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows.to_dict(orient="records"):
        for reason in row.get("transaction_reasons", []):
            key = (str(reason.get("rule_id", "")), str(reason.get("explanation", "")))
            if key not in seen:
                seen.add(key)
                output.append(dict(reason))
    for finding in findings:
        key = (str(finding.get("rule_id", "")), str(finding.get("explanation", "")))
        if key not in seen:
            seen.add(key)
            keep = ("rule_id", "rule_name", "points", "explanation", "threshold", "evidence", "source", "ring_id")
            output.append({name: finding[name] for name in keep if name in finding})
    if not output and not rows.empty:
        row = rows.sort_values("risk_score", ascending=False, kind="stable").iloc[0]
        output.append({
            "rule_id": "risk_score_threshold", "rule_name": "Combined risk threshold", "points": 0,
            "explanation": f"Combined risk score {float(row['risk_score']):.1f}/100 meets the configured investigation threshold.",
            "threshold": f"final_risk ≥ {float(DEFAULT_SETTINGS['flagged_risk_threshold']):g}", "source": "score",
        })
    return output


def build_investigations(
    scored: dict[str, Any],
    graph_result: dict[str, Any],
    ring_result: dict[str, Any],
    validation: dict[str, Any],
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Group only flagged transactions; a case score is its highest member-account risk."""
    values = {**DEFAULT_SETTINGS, **(settings or {})}
    data: pd.DataFrame = scored["data"].copy().reset_index(drop=True)
    account_rows: dict[str, dict[str, Any]] = scored["accounts"]
    rings: list[dict[str, Any]] = ring_result["rings"]
    flagged = data.loc[data["is_flagged"]].copy()
    flagged_ids = set(flagged["txn_id"].astype(str))
    findings = list(scored["findings"]) + list(ring_result["ring_findings"])

    case_graph = nx.Graph()
    case_graph.add_nodes_from(set(data["from_account"].astype(str)) | set(data["to_account"].astype(str)))
    for row in flagged[["from_account", "to_account"]].itertuples(index=False, name=None):
        case_graph.add_edge(str(row[0]), str(row[1]))

    cases: list[dict[str, Any]] = []
    transaction_case: dict[str, str] = {}
    for member_set in nx.connected_components(case_graph):
        members = sorted(str(item) for item in member_set)
        member_rows = flagged.loc[flagged["from_account"].astype(str).isin(member_set) & flagged["to_account"].astype(str).isin(member_set)].copy()
        if member_rows.empty:
            continue
        txn_ids = set(member_rows["txn_id"].astype(str))
        relevant_findings = [finding for finding in findings if txn_ids.intersection(str(value) for value in finding.get("txn_ids", []))]
        linked_rings = [ring for ring in rings if txn_ids.intersection(str(value) for value in ring.get("transaction_ids", []))]
        reasons = _unique_reasons(member_rows, relevant_findings)
        top_account = max(members, key=lambda account: float(account_rows.get(account, {}).get("risk_score", 0.0)))
        score = max((float(account_rows.get(account, {}).get("risk_score", 0.0)) for account in members), default=0.0)
        transaction_ids = list(member_rows["txn_id"].astype(str))
        digest_source = "|".join(members) + "|" + "|".join(sorted(transaction_ids))
        digest = hashlib.sha1(digest_source.encode()).hexdigest()[:7].upper()
        case_id = f"RW-{digest}"
        for txn_id in transaction_ids:
            transaction_case[txn_id] = case_id

        timeline = []
        for row in member_rows.sort_values("timestamp", kind="stable").to_dict(orient="records"):
            timeline.append({
                "txn_id": str(row["txn_id"]),
                "timestamp": _iso_stamp(row["timestamp"]),
                "from_account": str(row["from_account"]),
                "to_account": str(row["to_account"]),
                "amount": round(float(row["amount"]), 2),
                "channel": str(row["channel"]),
                "city": str(row["city"]),
                "device_id": str(row["device_id"]),
                "rule_points": int(row["rule_points"]),
                "matched_rules": list(row["matched_rules"]),
                "ml_score": round(float(row["ml_score"]), 2),
                "weighted_ml_score": round(float(row["weighted_ml_score"]), 2),
                "uncapped_score": round(float(row["uncapped_score"]), 2),
                "score_capped": bool(row["score_capped"]),
                "final_risk": round(float(row["final_risk"]), 1),
                "risk_score": round(float(row["risk_score"]), 1),
                "risk_band": str(row["risk_band"]),
                "is_flagged": True,
                "reasons": list(row["transaction_reasons"]),
                "feature_signals": list(row["feature_signals"][:3]),
            })
        top_transactions = sorted(timeline, key=lambda row: (-row["risk_score"], row["timestamp"]))[:3]
        account_details = []
        for account in members:
            detail = dict(account_rows.get(account, {"account_id": account, "risk_score": 0.0, "risk_band": "low", "reasons": []}))
            detail["reasons"] = [dict(reason) for reason in detail.get("reasons", [])]
            account_details.append(detail)

        ring_ids = [ring["id"] for ring in linked_rings]
        case_edges: list[dict[str, Any]] = []
        for (source_value, target_value), pair_rows in member_rows.groupby(["from_account", "to_account"], sort=False):
            source, target = str(source_value), str(target_value)
            ids = set(pair_rows["txn_id"].astype(str))
            edge_id = f"{source}→{target}"
            attached = [ring for ring in linked_rings if ids.intersection(str(value) for value in ring.get("transaction_ids", []))]
            case_edges.append({
                "id": edge_id, "from": source, "to": target,
                "amount": round(float(pair_rows["amount"].sum()), 2),
                "transaction_count": int(len(pair_rows)),
                "risk_score": round(float(pair_rows["risk_score"].max()), 1),
                "risk_band": str(pair_rows.sort_values("risk_score", ascending=False).iloc[0]["risk_band"]),
                "transaction_ids": list(pair_rows["txn_id"].astype(str)),
                "ring_ids": [ring["id"] for ring in attached],
                "ring_types": [ring["type"] for ring in attached],
                "is_ring": bool(attached),
                "is_circular": any(ring["type"] == "cycle" for ring in attached),
            })
        case_nodes = []
        for account in members:
            source_node = next((node for node in graph_result["nodes"] if node["id"] == account), {})
            case_nodes.append({
                "id": account,
                "risk_score": float(source_node.get("risk_score", account_rows.get(account, {}).get("risk_score", 0.0))),
                "risk_band": str(source_node.get("risk_band", "low")),
                "flagged": True,
                "ring_ids": [ring["id"] for ring in linked_rings if account in ring.get("accounts", [])],
            })
        rules_present = sorted({str(reason.get("rule_id")) for reason in reasons})
        case = {
            "id": case_id,
            "title": f"{reasons[0]['rule_name'] if reasons else 'Connected risk activity'} · {len(members)} account{'s' if len(members) != 1 else ''}",
            "risk_score": round(score, 1),
            "risk_band": risk_band(score, values),
            "rule_points": max((int(account_rows.get(account, {}).get("rule_points", 0)) for account in members), default=0),
            "ml_score": round(max((float(account_rows.get(account, {}).get("ml_score", 0.0)) for account in members), default=0.0), 1),
            "accounts": members,
            "account_details": account_details,
            "account_count": len(members),
            "transaction_count": len(timeline),
            "transaction_ids": [row["txn_id"] for row in timeline],
            "amount": round(float(member_rows["amount"].sum()), 2),
            "rules": rules_present,
            "reasons": reasons,
            "transactions": timeline,
            "top_transactions": top_transactions,
            "first_seen": timeline[0]["timestamp"],
            "last_seen": timeline[-1]["timestamp"],
            "status": "Open",
            "ring_ids": ring_ids,
            "rings": linked_rings,
            "graph": {"nodes": case_nodes, "edges": case_edges},
            "top_risk_account": top_account,
        }
        cases.append(case)
    cases.sort(key=lambda case: (-float(case["risk_score"]), str(case["id"])))

    data["case_id"] = data["txn_id"].astype(str).map(lambda transaction_id: transaction_case.get(str(transaction_id)))
    scored["data"]["case_id"] = data["case_id"].to_numpy()
    for node in graph_result["nodes"]:
        node["case_id"] = next((case["id"] for case in cases if node["id"] in case["accounts"]), None)
    for edge in graph_result["edges"]:
        edge["case_id"] = transaction_case.get(next((txn_id for txn_id in edge["transaction_ids"] if txn_id in transaction_case), ""))

    account_features = scored["account_features"].copy()
    account_case_ids = {account: case["id"] for case in cases for account in case["accounts"]}
    account_features["max_risk"] = account_features["account_id"].map(
        lambda account: float(account_rows.get(str(account), {}).get("risk_score", 0.0))
    )
    account_features["case_id"] = account_features["account_id"].map(account_case_ids)

    amount_at_risk = float(flagged["amount"].sum())
    labels = data.loc[data["is_fraud"].isin([0, 1]), "is_fraud"] if "is_fraud" in data else pd.Series(dtype=float)
    has_truth = bool(validation.get("has_ground_truth", False)) and not labels.empty
    fraud_data = data.loc[data["is_fraud"].eq(1)] if has_truth else data.iloc[0:0]
    risk_score_total = sum(float(case["risk_score"]) for case in cases)
    summary = {
        "transactions_analysed": int(len(data)),
        "flagged_transactions": int(len(flagged)),
        "accounts_analysed": int(len(scored["accounts"])),
        "cases_found": int(len(cases)),
        "amount_at_risk": round(amount_at_risk, 2),
        "has_ground_truth": has_truth,
        "fraud_value_total": round(float(fraud_data["amount"].sum()), 2) if has_truth else None,
        "fraudulent_transactions": int(len(fraud_data)) if has_truth else None,
        "risk_score_total": round(risk_score_total, 2),
        "risk_exposure_total": round(risk_score_total, 2),
        "dropped_rows": int(validation.get("rows_rejected", 0) + validation.get("duplicates_removed", 0)),
        "rows_received": int(validation.get("rows_received", len(data))),
        "rows_rejected": int(validation.get("rows_rejected", 0)),
        "duplicates_removed": int(validation.get("duplicates_removed", 0)),
        "status_counts": {status: sum(case["status"] == status for case in cases) for status in ("Open", "Confirmed", "Marked as false positive", "Escalated")},
    }
    graph_result["stats"]["ring_count"] = int(len(rings))
    return {
        "data": data,
        "cases": cases,
        "accounts": scored["accounts"],
        "findings": findings,
        "transaction_ml_scores": scored["transaction_ml_scores"],
        "summary": summary,
        "validation": validation,
        "settings": values,
        "graph_result": graph_result,
        "rings": rings,
        "ring_summary": ring_result["summary"],
        "model": scored["model"],
        "account_features": account_features,
    }


def compute_coverage(result: dict[str, Any], budget: int) -> dict[str, Any]:
    """Evaluate actual fraud value/precision when labels exist; otherwise report score-only coverage."""
    cases = result["cases"]
    total_cases = len(cases)
    count = min(max(0, int(budget)), total_cases)
    selected = cases[:count]
    selected_ids = {str(txn_id) for case in selected for txn_id in case["transaction_ids"]}
    summary = result["summary"]
    if summary["has_ground_truth"]:
        data = result["data"]
        labeled_fraud = data.loc[data["is_fraud"].eq(1)]
        labeled_fraud_ids = set(labeled_fraud["txn_id"].astype(str))
        total_value = float(labeled_fraud["amount"].sum())
        covered_value = float(labeled_fraud.loc[labeled_fraud["txn_id"].astype(str).isin(selected_ids), "amount"].sum())
        fraud_cases = sum(bool(labeled_fraud_ids.intersection(str(txn_id) for txn_id in case["transaction_ids"])) for case in selected)
        precision = fraud_cases / count if count else 0.0
        curve = []
        for n in range(1, total_cases + 1):
            prefix = cases[:n]
            ids = {str(txn_id) for case in prefix for txn_id in case["transaction_ids"]}
            covered = float(labeled_fraud.loc[labeled_fraud["txn_id"].astype(str).isin(ids), "amount"].sum())
            curve.append({"budget": n, "coverage_percent": round(covered / total_value * 100, 2) if total_value else 0.0})
        return {
            "metric_label": "Fraud value caught",
            "coverage_percent": round(covered_value / total_value * 100, 1) if total_value else 0.0,
            "covered_value": round(covered_value, 2), "total_value": round(total_value, 2),
            "fraudulent_cases_reviewed": int(fraud_cases),
            "false_alarms": int(count - fraud_cases),
            "precision": round(precision * 100, 1),
            "risk_score_coverage_percent": None,
            "selected_case_ids": [case["id"] for case in selected],
            "reviewed_count": count, "total_cases": total_cases, "coverage_curve": curve,
        }
    total_score = sum(float(case["risk_score"]) for case in cases)
    covered_score = sum(float(case["risk_score"]) for case in selected)
    coverage = covered_score / total_score * 100 if total_score else 0.0
    curve = []
    running = 0.0
    for n, case in enumerate(cases, start=1):
        running += float(case["risk_score"])
        curve.append({"budget": n, "coverage_percent": round(running / total_score * 100, 2) if total_score else 0.0})
    return {
        "metric_label": "Risk-score coverage (not confirmed fraud)",
        "coverage_percent": round(coverage, 1), "covered_value": None, "total_value": None,
        "fraudulent_cases_reviewed": None, "false_alarms": None, "precision": None,
        "risk_score_coverage_percent": round(coverage, 1),
        "selected_case_ids": [case["id"] for case in selected],
        "reviewed_count": count, "total_cases": total_cases, "coverage_curve": curve,
    }


__all__ = ["build_investigations", "compute_coverage"]
