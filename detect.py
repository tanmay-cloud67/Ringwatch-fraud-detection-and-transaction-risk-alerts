"""Backward-compatible facade over RingWatch's six explicit analysis stages."""
from __future__ import annotations

from typing import Any

import pandas as pd

from pipeline import compute_coverage, run_pipeline
from stage1_ingestion import DatasetError, GROUND_TRUTH_COLUMN, REQUIRED_COLUMNS, ingest_frame
from stage2_processing import process_transactions


def normalize_transactions(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Preserve the legacy normalization import while returning Stage 2's validation report."""
    raw, ingestion = ingest_frame(frame)
    processed = process_transactions(raw, ingestion=ingestion)
    return processed["data"], processed["validation"]


def analyze_transactions(frame: pd.DataFrame, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Preserve the legacy analysis entry point; execution now flows through all six stages."""
    return run_pipeline(frame, settings)


__all__ = [
    "DatasetError", "GROUND_TRUTH_COLUMN", "REQUIRED_COLUMNS", "analyze_transactions",
    "compute_coverage", "normalize_transactions",
]
