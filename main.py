"""FastAPI application for the RingWatch offline fraud-investigation demo."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import os
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import (
    DEFAULT_SETTINGS,
    MODEL_CONFIG,
    RULES,
    SETTING_BOUNDS as CONFIG_BOUNDS,
    default_settings,
    risk_bands,
    validate_settings,
)
from detect import DatasetError, compute_coverage
from generate_sample import generate_transactions
from pipeline import empty_pipeline_report, pipeline_detail, run_pipeline, _json_value
from stage1_ingestion import REQUIRED_COLUMNS, ingest_csv_bytes

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
app = FastAPI(title="RingWatch API", version="1.1.0", description="Synthetic fraud and transaction risk analysis demonstration")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# Bounds are sourced only from config.py; the API converts tuples to JSON arrays.
SETTING_BOUNDS = {key: [low, high] for key, (low, high) in CONFIG_BOUNDS.items()}

_state: dict[str, Any] = {
    "result": None,
    "frame": None,
    "filename": None,
    "ingestion": None,
    "settings": default_settings(),
    "statuses": {},
    "last_attempt": None,
}


class SettingsUpdate(BaseModel):
    settings: dict[str, Any]


class CaseStatusUpdate(BaseModel):
    status: str


def _require_data() -> dict[str, Any]:
    if _state["result"] is None:
        raise HTTPException(status_code=409, detail="No dataset is loaded. Load sample data or upload a CSV first.")
    return _state["result"]


def _apply_statuses(result: dict[str, Any]) -> None:
    for case in result["cases"]:
        if case["id"] in _state["statuses"]:
            case["status"] = _state["statuses"][case["id"]]
    result["summary"]["status_counts"] = {
        status: sum(case["status"] == status for case in result["cases"])
        for status in ("Open", "Confirmed", "Marked as false positive", "Escalated")
    }


def _record_failure(exc: Exception, fallback_stage: str = "ingestion") -> None:
    report = getattr(exc, "pipeline_report", None)
    if not isinstance(report, dict):
        report = empty_pipeline_report()
        report.update({"active": True, "status": "failed", "label": "Failed", "failed_stage": fallback_stage})
        report["error"] = {"code": getattr(exc, "code", "stage_error"), "message": str(exc)}
        stage = next((item for item in report["stages"] if item["id"] == fallback_stage), None)
        if stage:
            stage.update({"status": "failed", "label": "Failed", "error": dict(report["error"])})
    _state["last_attempt"] = _json_value(report)


def _run_detection(
    frame: pd.DataFrame,
    filename: str,
    ingestion: dict[str, Any] | None = None,
    *,
    reset_statuses: bool = False,
) -> dict[str, Any]:
    try:
        result = run_pipeline(frame, _state["settings"], filename, ingestion)
    except Exception as exc:
        _record_failure(exc, getattr(exc, "stage", "ingestion"))
        raise
    # Commit the new active dataset only after the entire pipeline succeeds.
    if reset_statuses:
        _state["statuses"].clear()
    _state["frame"] = frame.copy()
    _state["result"] = result
    _state["filename"] = filename
    _state["ingestion"] = dict(ingestion or result["ingestion"])
    _state["last_attempt"] = result["pipeline"]
    _apply_statuses(result)
    return result


def _summary_payload(result: dict[str, Any], budget: int) -> dict[str, Any]:
    _apply_statuses(result)
    return {
        "dataset": {
            "filename": _state["filename"],
            "row_count": result["summary"]["transactions_analysed"],
            "has_ground_truth": result["summary"]["has_ground_truth"],
            "rows_received": result["validation"]["rows_received"],
            "rows_rejected": result["validation"]["rows_rejected"],
            "duplicates_removed": result["validation"]["duplicates_removed"],
            "date_range": result["validation"]["date_range"],
            "unique_accounts": result["validation"]["unique_accounts"],
        },
        "summary": result["summary"],
        "cases": result["cases"],
        "coverage": compute_coverage(result, budget),
        "settings": _state["settings"],
        "validation": result["validation"],
        "pipeline": result["pipeline"],
    }


def _validate_settings(candidate: dict[str, Any]) -> dict[str, Any]:
    try:
        return validate_settings(candidate, _state["settings"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _csv_response(frame: pd.DataFrame, filename: str) -> Response:
    data = frame.copy()
    for column in data.columns:
        if data[column].dtype == "object":
            data[column] = data[column].map(
                lambda value: __import__("json").dumps(value, ensure_ascii=False, default=str)
                if isinstance(value, (dict, list, tuple)) else value
            )
    content = data.to_csv(index=False, lineterminator="\n")
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "ringwatch"}


@app.get("/manus-routes.json")
def routes_manifest():
    return FileResponse(ROOT / "manus-routes.json", media_type="application/json")


@app.get("/tokens.css")
def token_stylesheet():
    return FileResponse(ROOT / "tokens.css", media_type="text/css")


@app.get("/favicon.svg")
def favicon():
    return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")


@app.get("/sample_transactions.csv")
def sample_csv():
    return FileResponse(ROOT / "sample_transactions.csv", media_type="text/csv", filename="sample_transactions.csv")


@app.get("/README.md")
def readme():
    return FileResponse(ROOT / "README.md", media_type="text/markdown; charset=utf-8")


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html", media_type="text/html")


@app.get("/api/sample")
def api_sample(budget: int = Query(default=20, ge=1)):
    try:
        frame = generate_transactions()
        result = _run_detection(frame, "sample_transactions.csv", reset_statuses=True)
        payload = _summary_payload(result, budget)
        payload["injected_fraud_rows"] = sum(1 for value in frame["is_fraud"].tolist() if value == 1)
        payload["message"] = f"Loaded {payload['dataset']['row_count']:,} deterministic sample transactions ({payload['injected_fraud_rows']} planted fraud-pattern rows)."
        return payload
    except Exception as exc:
        if not _state.get("last_attempt"):
            _record_failure(exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...), budget: int = Query(default=20, ge=1)):
    filename = Path(file.filename or "").name
    if not filename or not filename.lower().endswith(".csv"):
        exc = DatasetError("Please choose a CSV file with a .csv filename.", code="not_csv")
        _record_failure(exc)
        raise HTTPException(status_code=400, detail=str(exc))
    raw = await file.read(20 * 1024 * 1024 + 1)
    if len(raw) > 20 * 1024 * 1024:
        exc = DatasetError("CSV exceeds the 20 MB file-size limit.", code="file_too_large")
        _record_failure(exc)
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        frame, ingestion = ingest_csv_bytes(raw, filename)
        result = _run_detection(frame, filename, ingestion, reset_statuses=True)
    except DatasetError as exc:
        _record_failure(exc, getattr(exc, "stage", "ingestion"))
        detail: dict[str, Any] = {"message": str(exc), "code": exc.code, "stage": exc.stage}
        if exc.validation:
            detail["validation"] = exc.validation
        if exc.rejected_rows:
            detail["rejected_rows"] = exc.rejected_rows
        raise HTTPException(status_code=400, detail=detail) from exc
    except Exception as exc:
        _record_failure(exc, getattr(exc, "stage", "processing"))
        raise HTTPException(status_code=500, detail=f"Transaction analysis failed: {exc}") from exc
    payload = _summary_payload(result, budget)
    skipped = result["validation"]["rows_rejected"]
    payload["message"] = f"Loaded {payload['dataset']['row_count']:,} valid rows from {filename}."
    if skipped:
        payload["message"] += f" Rejected {skipped:,} row(s); see the data-quality report for reasons."
    return payload


@app.get("/api/pipeline")
def api_pipeline():
    """Expose stage status, hand-offs, data quality and bounded real feature previews."""
    if _state["result"] is None:
        return _state["last_attempt"] or empty_pipeline_report()
    detail = pipeline_detail(_state["result"])
    if _state["last_attempt"] and _state["last_attempt"].get("status") == "failed":
        detail["latest_attempt"] = _state["last_attempt"]
    return detail


@app.get("/api/status")
def api_status():
    result = _state["result"]
    if result is not None:
        _apply_statuses(result)
    return {
        "dataset_loaded": result is not None,
        "dataset": ({"filename": _state["filename"], "row_count": result["summary"]["transactions_analysed"]} if result else None),
        "summary": result["summary"] if result else None,
        "pipeline": result["pipeline"] if result else empty_pipeline_report(),
        "last_attempt": _state["last_attempt"],
    }


@app.get("/api/features")
def api_features(
    kind: str = Query(default="transactions", pattern="^(transactions|accounts)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=500),
    sort_by: str | None = None,
    direction: str = Query(default="asc", pattern="^(asc|desc)$"),
):
    result = _require_data()
    frame = result["data"].drop(columns=["is_fraud"], errors="ignore") if kind == "transactions" else result["account_features"]
    if sort_by:
        # Ground-truth labels are deliberately not a sorting key.
        allowed = {str(column) for column in frame.columns if column != "is_fraud"}
        if sort_by not in allowed:
            raise HTTPException(status_code=422, detail=f"Unknown or unavailable feature sort column: {sort_by}.")
        frame = frame.sort_values(sort_by, ascending=direction == "asc", kind="stable", na_position="last")
    total = len(frame)
    selected = frame.iloc[offset : offset + limit]
    rows = [_json_value(row) for row in selected.to_dict(orient="records")]
    return {"kind": kind, "total": total, "offset": offset, "limit": limit, "columns": [str(column) for column in selected.columns], "rows": rows}


@app.get("/api/cases")
def api_cases(budget: int = Query(default=20, ge=1)):
    result = _require_data()
    _apply_statuses(result)
    coverage = compute_coverage(result, budget)
    return _json_value({
        "cases": result["cases"],
        "reviewed_cases": result["cases"][:budget],
        "coverage": coverage,
        "summary": result["summary"],
        "dataset": {"filename": _state["filename"], "row_count": result["summary"]["transactions_analysed"]},
    })


@app.get("/api/graph")
def api_graph():
    result = _require_data()
    _apply_statuses(result)
    case_for_account: dict[str, str] = {}
    for case in result["cases"]:
        for account in case["accounts"]:
            case_for_account.setdefault(account, case["id"])
    graph_result = result["graph_result"]
    nodes = []
    for source_node in graph_result["nodes"]:
        node = dict(source_node)
        node["label"] = node["id"] if node["flagged"] else ""
        node["case_id"] = case_for_account.get(node["id"])
        nodes.append(node)
    edges = []
    for source_edge in graph_result["edges"]:
        edge = {key: value for key, value in source_edge.items() if key not in {"transactions", "transaction_ids"}}
        edge["case_id"] = case_for_account.get(edge["from"]) or case_for_account.get(edge["to"])
        edges.append(edge)
    rings = [{key: ring[key] for key in (
        "id", "type", "type_label", "accounts", "edge_ids", "transaction_count",
        "total_value", "cycle_length", "density", "hub_account", "risk_score", "risk_band", "reasons",
    )} for ring in result["rings"][:100]]
    return _json_value({
        "nodes": nodes,
        "edges": edges,
        "stats": graph_result["stats"],
        "rings": rings,
        "ring_summary": result["ring_summary"],
        "legend": {"low": "Low risk", "medium": "Medium risk", "high": "High risk", "ring": "Detected ring", "node_size": "Transaction volume", "edge_width": "Aggregated transfer value", "direction": "Money movement"},
    })


@app.get("/api/account/{account_id}")
def api_account(account_id: str):
    result = _require_data()
    normalized_id = account_id.strip().upper()
    account = result["accounts"].get(normalized_id)
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account {normalized_id} was not found.")
    frame = result["data"]
    related = frame.loc[frame["from_account"].eq(normalized_id) | frame["to_account"].eq(normalized_id)].sort_values("timestamp", kind="stable")
    transaction_count = int(len(related))
    transaction_columns = [
        "txn_id", "timestamp", "from_account", "to_account", "amount", "channel", "city", "device_id",
        "rule_points", "matched_rules", "ml_score", "weighted_ml_score", "final_risk", "risk_band", "is_flagged", "transaction_reasons",
    ]
    visible = related.loc[:, [column for column in transaction_columns if column in related.columns]].tail(100)
    transactions = _json_value(visible.to_dict(orient="records"))
    case_row = result["account_features"].loc[result["account_features"]["account_id"].eq(normalized_id)]
    case_id = case_row.iloc[0]["case_id"] if not case_row.empty else None
    case = next((item for item in result["cases"] if item["id"] == case_id), None)
    return _json_value({
        "id": normalized_id,
        "account_id": normalized_id,
        "title": f"Account {normalized_id}",
        "risk_score": account["risk_score"],
        "risk_band": account["risk_band"],
        "flagged": account["flagged"],
        "rule_points": account["rule_points"],
        "ml_score": account["ml_score"],
        "transaction_count": transaction_count,
        "amount": float(related["amount"].sum()),
        "reasons": account["reasons"],
        "transactions": transactions,
        "transaction_rows_truncated": transaction_count > len(visible),
        "accounts": [normalized_id],
        "case_id": case_id,
        "status": case.get("status") if case else None,
        "case_risk_score": case.get("risk_score") if case else None,
    })


@app.get("/api/case/{case_id}")
def api_case(case_id: str):
    result = _require_data()
    _apply_statuses(result)
    for case in result["cases"]:
        if case["id"] == case_id:
            return _json_value(case)
    raise HTTPException(status_code=404, detail=f"Case {case_id} was not found.")


@app.put("/api/case/{case_id}/status")
@app.post("/api/case/{case_id}/status")
def api_case_status(case_id: str, update: CaseStatusUpdate):
    allowed = {"confirmed": "Confirmed", "false_positive": "Marked as false positive", "escalated": "Escalated"}
    if update.status not in allowed:
        raise HTTPException(status_code=422, detail="Status must be confirmed, false_positive, or escalated.")
    result = _require_data()
    case = next((item for item in result["cases"] if item["id"] == case_id), None)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} was not found.")
    _state["statuses"][case_id] = allowed[update.status]
    case["status"] = allowed[update.status]
    _apply_statuses(result)
    return {"id": case_id, "status": case["status"], "status_counts": result["summary"]["status_counts"]}


@app.get("/api/settings")
@app.get("/api/config")
def api_get_settings():
    return {
        "settings": _state["settings"], "defaults": DEFAULT_SETTINGS, "bounds": SETTING_BOUNDS,
        "rules": RULES, "risk_bands": risk_bands(_state["settings"]), "model": MODEL_CONFIG,
    }


@app.put("/api/settings")
@app.put("/api/config")
def api_update_settings(update: SettingsUpdate):
    _state["settings"] = _validate_settings(update.settings)
    return {"settings": _state["settings"], "message": "Detection settings saved. Run detection to apply them to the loaded data."}


@app.post("/api/detect")
def api_rerun_detection(budget: int = Query(default=20, ge=1)):
    if _state["frame"] is None:
        raise HTTPException(status_code=409, detail="Load sample data or upload a CSV before rerunning detection.")
    frame = _state["frame"].copy()
    filename = _state["filename"] or "transactions.csv"
    result = _run_detection(frame, filename, _state["ingestion"])
    payload = _summary_payload(result, budget)
    payload["message"] = "Detection rerun using the current settings."
    return payload


@app.get("/api/download/sample")
def download_sample():
    return sample_csv()


@app.get("/api/download/processed")
def download_processed():
    result = _require_data()
    return _csv_response(result["data"], "ringwatch_processed_transactions.csv")


@app.get("/api/download/rejected")
def download_rejected():
    result = _require_data()
    columns = ["source_row_number", "reason", "reason_detail", *REQUIRED_COLUMNS]
    rejected = pd.DataFrame(result.get("rejected_rows", []))
    for column in columns:
        if column not in rejected:
            rejected[column] = pd.Series(dtype="object")
    rejected = rejected.loc[:, columns]
    return _csv_response(rejected, "ringwatch_rejected_rows.csv")


@app.delete("/api/data")
@app.post("/api/clear")
def clear_data():
    _state.update({"result": None, "frame": None, "filename": None, "ingestion": None, "statuses": {}, "last_attempt": None})
    return {"cleared": True, "settings_preserved": True, "pipeline": empty_pipeline_report(), "message": "Dataset, investigation statuses and pipeline results cleared. Settings are unchanged."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "3000")), reload=True)
