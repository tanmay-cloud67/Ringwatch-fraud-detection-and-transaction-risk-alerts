"""Stage 1: parse transaction inputs and validate the source schema."""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

import pandas as pd

from config import MAX_UPLOAD_BYTES, MAX_UPLOAD_ROWS

REQUIRED_COLUMNS = ["txn_id", "timestamp", "from_account", "to_account", "amount", "channel", "city", "device_id"]
GROUND_TRUTH_COLUMN = "is_fraud"


class DatasetError(ValueError):
    """A user-correctable dataset error with structured stage/rejection context."""

    def __init__(self, message: str, *, code: str = "invalid_dataset", stage: str = "ingestion", rejected_rows: list[dict[str, Any]] | None = None, validation: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.rejected_rows = rejected_rows or []
        self.validation = validation or {}


def _clean_headers(columns) -> list[str]:
    return [str(column).strip().lower() for column in columns]


def _check_schema(columns: list[str]) -> None:
    if not columns or any(not name for name in columns):
        raise DatasetError("CSV headers must be present and non-empty.", code="missing_header")
    if len(columns) != len(set(columns)):
        raise DatasetError("CSV column names must be unique after trimming and case normalization.", code="duplicate_header")
    missing = [column for column in REQUIRED_COLUMNS if column not in columns]
    if missing:
        raise DatasetError("Missing required columns: " + ", ".join(missing), code="missing_columns")


def ingest_frame(frame: pd.DataFrame, source: str = "transactions.csv") -> tuple[pd.DataFrame, dict[str, Any]]:
    """Validate an in-memory frame and preserve source-row order."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise DatasetError("CSV is empty or contains no transaction rows.", code="empty_csv")
    if len(frame) > MAX_UPLOAD_ROWS:
        raise DatasetError(f"CSV exceeds the {MAX_UPLOAD_ROWS:,}-row limit.", code="row_limit")
    data = frame.copy()
    data.columns = _clean_headers(data.columns)
    _check_schema(list(data.columns))
    data["__source_row_number"] = range(2, len(data) + 2)
    rows = len(data)
    report = {
        "source": Path(str(source)).name or "transactions.csv",
        "rows_received": rows,
        "rows_before_processing": rows,
        "malformed_rows": 0,
        "rejected_rows": [],
        "columns_received": list(data.columns),
        "required_columns_present": True,
    }
    return data.reset_index(drop=True), report


def ingest_csv_bytes(raw: bytes, filename: str = "transactions.csv") -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse CSV bytes without hiding wrong-width rows or exceeding demo limits."""
    if len(raw) > MAX_UPLOAD_BYTES:
        raise DatasetError("CSV exceeds the 20 MB file-size limit.", code="file_too_large")
    if not raw:
        raise DatasetError("CSV file is empty.", code="empty_csv")
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader)
    except (UnicodeDecodeError, csv.Error, StopIteration) as exc:
        raise DatasetError("CSV is empty or could not be parsed as UTF-8 CSV.", code="unparseable_csv") from exc
    columns = _clean_headers(header)
    _check_schema(columns)

    rows: list[list[str]] = []
    rejected: list[dict[str, Any]] = []
    received = 0
    try:
        for record in reader:
            received += 1
            if received > MAX_UPLOAD_ROWS:
                raise DatasetError(f"CSV exceeds the {MAX_UPLOAD_ROWS:,}-row limit.", code="row_limit", rejected_rows=rejected)
            if len(record) != len(columns):
                rejected.append({
                    "source_row_number": int(reader.line_num),
                    "reason": "malformed_width",
                    "reason_detail": f"Expected {len(columns)} fields but found {len(record)}.",
                    "raw_row": " | ".join(str(value) for value in record),
                })
                continue
            rows.append(record)
    except csv.Error as exc:
        raise DatasetError("CSV contains malformed quoting or an unparseable row.", code="unparseable_csv", rejected_rows=rejected) from exc
    if received == 0:
        raise DatasetError("CSV contains headers but no transaction rows.", code="empty_csv")
    if rows:
        data = pd.DataFrame.from_records(rows)
        data.columns = pd.Index(columns)
    else:
        data = pd.DataFrame({column: pd.Series(dtype="string") for column in columns})
    if "__source_row_number" not in data:
        # The record index is only trace metadata; it is never a model feature or sort key.
        data["__source_row_number"] = [i + 2 for i in range(len(data))]
    report = {
        "source": Path(str(filename)).name or "transactions.csv",
        "rows_received": received,
        "rows_before_processing": len(rows),
        "malformed_rows": len(rejected),
        "rejected_rows": rejected,
        "columns_received": columns,
        "required_columns_present": True,
    }
    return data.reset_index(drop=True), report
