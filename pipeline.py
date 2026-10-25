"""Six-stage execution contract, progress reporting and compact JSON-safe previews."""
from __future__ import annotations

from time import perf_counter
from typing import Any, Callable

import numpy as np
import pandas as pd

from config import DEFAULT_SETTINGS
from stage1_ingestion import DatasetError, ingest_frame
from stage2_processing import process_transactions
from stage3_modeling import score_transactions
from stage4_graph import build_graph
from stage5_rings import detect_rings
from stage6_investigation import build_investigations, compute_coverage as stage6_compute_coverage

STAGE_DEFINITIONS = [
    ("ingestion", "Transaction ingestion"),
    ("processing", "Data processing"),
    ("modeling", "Machine learning"),
    ("graph", "Graph construction"),
    ("rings", "Ring detection"),
    ("investigation", "Investigation dashboard"),
]


def _stage_rows() -> list[dict[str, Any]]:
    return [
        {"id": key, "name": name, "status": "not_run", "label": "Not run", "duration_ms": None,
         "input_count": None, "output_count": None, "handoff_count": 0, "handoff_text": None, "summary": {}, "error": None}
        for key, name in STAGE_DEFINITIONS
    ]


def empty_pipeline_report() -> dict[str, Any]:
    return {"active": False, "status": "not_run", "label": "Not run", "stages": _stage_rows(), "failed_stage": None, "error": None}


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def run_pipeline(
    frame: pd.DataFrame,
    settings: dict[str, Any] | None = None,
    filename: str = "transactions.csv",
    ingestion_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run stages in order and preserve explicit, inspectable hand-offs."""
    values = {**DEFAULT_SETTINGS, **(settings or {})}
    report = {"active": True, "status": "running", "label": "Running", "stages": _stage_rows(), "failed_stage": None, "error": None}
    stage_lookup = {stage["id"]: stage for stage in report["stages"]}
    current_stage = "ingestion"

    def execute(
        stage_id: str,
        input_count: int | None,
        operation: Callable[[], tuple[Any, int, dict[str, Any], str]],
    ) -> tuple[Any, int, dict[str, Any]]:
        """Record one stage's lifecycle and capture failure before stopping later stages."""
        nonlocal current_stage
        current_stage = stage_id
        stage = stage_lookup[stage_id]
        stage.update({"status": "running", "label": "Running", "input_count": input_count})
        started = perf_counter()
        try:
            output, output_count, details, handoff_text = operation()
        except Exception as exc:
            stage["duration_ms"] = round((perf_counter() - started) * 1000, 2)
            stage.update({"status": "failed", "label": "Failed", "error": {"code": getattr(exc, "code", "stage_error"), "message": str(exc)}})
            report.update({"status": "failed", "label": "Failed", "failed_stage": stage_id, "error": dict(stage["error"])})
            try:
                setattr(exc, "pipeline_report", _json_value(report))
            except Exception:
                pass
            raise
        stage.update({
            "duration_ms": round((perf_counter() - started) * 1000, 2),
            "status": "done", "label": "Done", "output_count": int(output_count),
            "handoff_count": int(output_count), "handoff_text": handoff_text,
            "summary": _json_value(details),
        })
        return output, int(output_count), details

    def ingest_operation():
        parsed_frame, inferred = ingest_frame(frame, filename)
        raw_count = int((ingestion_report or {}).get("rows_received", len(frame)))
        parsed_count = int((ingestion_report or {}).get("rows_before_processing", len(parsed_frame)))
        return (
            (parsed_frame, inferred), parsed_count,
            {"rows_received": raw_count, "rows_before_processing": parsed_count, "source": filename,
             "malformed_rows": int((ingestion_report or {}).get("malformed_rows", 0))},
            f"Stage 1 read {raw_count:,} source rows and passed {parsed_count:,} parsed rows to Stage 2.",
        )

    (raw_frame, inferred_ingestion), parsed_count, _ = execute("ingestion", int(len(frame)), ingest_operation)
    ingestion = {**inferred_ingestion, **(ingestion_report or {})}
    ingestion["source"] = str(ingestion.get("source") or filename)
    validation_in = int(ingestion.get("rows_received", len(frame)))
    ingestion_parsed = int(ingestion.get("rows_before_processing", parsed_count))
    stage_lookup["ingestion"]["input_count"] = validation_in
    stage_lookup["ingestion"]["duration_ms"] = round(
        float(stage_lookup["ingestion"]["duration_ms"] or 0.0) + float(ingestion.get("parse_duration_ms", 0.0)), 2
    )
    stage_lookup["ingestion"]["summary"].update({
        "source": ingestion["source"], "rows_received": validation_in,
        "rows_before_processing": ingestion_parsed,
        "malformed_rows": int(ingestion.get("malformed_rows", 0)),
        "required_columns_present": bool(ingestion.get("required_columns_present", True)),
    })
    stage_lookup["ingestion"]["handoff_text"] = f"Stage 1 read {validation_in:,} source rows and passed {ingestion_parsed:,} parsed rows to Stage 2."

    processed, _, _ = execute(
        "processing", len(raw_frame),
        lambda: _process_stage(raw_frame, values, ingestion),
    )
    validation = processed["validation"]
    scored, _, _ = execute(
        "modeling", int(validation["rows_loaded"]),
        lambda: _model_stage(processed, values),
    )
    graph_result, _, _ = execute(
        "graph", len(scored["data"]),
        lambda: _graph_stage(scored, values),
    )
    ring_result, _, _ = execute(
        "rings", int(graph_result["stats"]["edge_count"]),
        lambda: _ring_stage(graph_result, scored, values),
    )
    graph_result = ring_result["graph_result"]
    result, _, _ = execute(
        "investigation", len(ring_result["rings"]),
        lambda: _investigation_stage(scored, graph_result, ring_result, processed["validation"], values),
    )

    result["ingestion"] = ingestion
    result["processing"] = {
        "feature_names": processed["feature_names"],
        "transaction_feature_count": len(processed["feature_names"]),
        "account_feature_count": max(0, len(processed["account_features"].columns) - 1),
        "account_features": result["account_features"],
    }
    result["rejected_rows"] = processed["rejected_rows"]
    report["status"] = "done"
    report["label"] = "Done"
    result["pipeline"] = _json_value(report)
    return result


def _process_stage(raw_frame: pd.DataFrame, settings: dict[str, Any], ingestion: dict[str, Any]):
    processed = process_transactions(raw_frame, settings, ingestion)
    validation = processed["validation"]
    count = int(validation["rows_loaded"])
    details = {
        "rows_loaded": count, "rows_rejected": int(validation["rows_rejected"]),
        "duplicates_removed": int(validation["duplicates_removed"]),
        "unique_accounts": int(validation["unique_accounts"]),
        "date_range": validation["date_range"],
        "row_accounting_reconciles": bool(validation["row_accounting_reconciles"]),
    }
    handoff = f"Stage 2 received {len(raw_frame):,} parsed rows from Stage 1 and passed {count:,} processed rows to Stage 3."
    return processed, count, details, handoff


def _model_stage(processed: dict[str, Any], settings: dict[str, Any]):
    scored = score_transactions(processed, settings)
    model = scored["model"]
    count = len(scored["data"])
    details = {
        "model_name": model["name"], "features": model["features"],
        "n_estimators": model["n_estimators"], "random_state": model["random_state"],
        "scored_transactions": model["scored_transactions"],
        "flagged_transactions": int(scored["data"]["is_flagged"].sum()),
        "score_distribution": model["score_distribution"], "formula": model["scoring_formula"],
    }
    handoff = f"Stage 3 received {count:,} processed rows from Stage 2 and passed {count:,} scored transactions to Stage 4."
    return scored, count, details, handoff


def _graph_stage(scored: dict[str, Any], settings: dict[str, Any]):
    graph_result = build_graph(scored["data"], scored["accounts"], scored["account_features"], settings)
    stats = graph_result["stats"]
    count = int(stats["edge_count"])
    handoff = f"Stage 4 received {len(scored['data']):,} scored transactions from Stage 3 and passed {count:,} aggregated directed links to Stage 5."
    return graph_result, count, dict(stats), handoff


def _ring_stage(graph_result: dict[str, Any], scored: dict[str, Any], settings: dict[str, Any]):
    ring_result = detect_rings(graph_result, scored["data"], scored["accounts"], scored["findings"], settings)
    count = len(ring_result["rings"])
    edges = int(ring_result["graph_result"]["stats"]["edge_count"])
    handoff = f"Stage 5 received {edges:,} directed links from Stage 4 and passed {count:,} ring detections to Stage 6."
    return ring_result, count, dict(ring_result["summary"]), handoff


def _investigation_stage(scored, graph_result, ring_result, validation, settings):
    result = build_investigations(scored, graph_result, ring_result, validation, settings)
    cases = len(result["cases"])
    details = {
        "cases_found": int(result["summary"]["cases_found"]),
        "flagged_transactions": int(result["summary"]["flagged_transactions"]),
        "accounts_analysed": int(result["summary"]["accounts_analysed"]),
    }
    handoff = f"Stage 6 received {len(ring_result['rings']):,} ring detections and {len(scored['data']):,} scored transactions, then grouped them into {cases:,} cases."
    return result, cases, details, handoff


compute_coverage = stage6_compute_coverage


def pipeline_detail(result: dict[str, Any] | None, limit: int = 15) -> dict[str, Any]:
    """Return detailed stage summaries and bounded actual feature/model/graph/ring samples."""
    if not result:
        return empty_pipeline_report()
    data = result["data"]
    transaction_columns = [
        "txn_id", "timestamp", "from_account", "to_account", "amount",
        "amount_vs_account_avg", "txn_count_1h", "txn_count_24h", "hour_of_day",
        "distinct_counterparties", "seconds_since_prev_txn", "sender_in_degree", "sender_out_degree",
        "is_overnight", "amount_near_threshold", "rapid_in_out_movement", "is_new_device", "is_new_city",
        "account_prior_transaction_count", "rule_points", "matched_rules", "ml_score", "weighted_ml_score",
        "uncapped_score", "score_capped", "final_risk", "risk_score", "risk_band", "is_flagged", "case_id",
    ]
    available = [column for column in transaction_columns if column in data.columns]
    row_limit = max(1, min(int(limit), 100))
    transaction_preview = [
        {key: _json_value(value) for key, value in row.items()}
        for row in data[available].head(row_limit).to_dict(orient="records")
    ]
    account_frame = result["account_features"]
    account_preview = [
        {key: _json_value(value) for key, value in row.items()}
        for row in account_frame.head(row_limit).to_dict(orient="records")
    ]
    return _json_value({
        **result["pipeline"],
        "filename": result["validation"]["source"],
        "summary": result["summary"],
        "validation": result["validation"],
        "processing": {
            "transaction_feature_names": result["processing"]["feature_names"],
            "transaction_feature_count": result["processing"]["transaction_feature_count"],
            "account_feature_count": result["processing"]["account_feature_count"],
            "transaction_preview": transaction_preview,
            "account_feature_preview": account_preview,
        },
        "model": result["model"],
        "graph_stats": result["graph_result"]["stats"],
        "ring_summary": result["ring_summary"],
        "rings": result["rings"][:100],
        "cases": [{"id": case["id"], "title": case["title"], "risk_score": case["risk_score"], "status": case["status"], "ring_ids": case["ring_ids"]} for case in result["cases"][:50]],
    })


__all__ = ["STAGE_DEFINITIONS", "compute_coverage", "empty_pipeline_report", "pipeline_detail", "run_pipeline"]
