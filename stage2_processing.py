"""Stage 2: clean accepted rows, reconcile every disposition and engineer features."""
from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd

from config import DEFAULT_SETTINGS, MODEL_CONFIG
from stage1_ingestion import DatasetError, GROUND_TRUTH_COLUMN, REQUIRED_COLUMNS

MODEL_FEATURES = list(MODEL_CONFIG["features"])
FEATURE_COLUMNS = [
    "amount_vs_account_avg", "txn_count_1h", "txn_count_24h", "hour_of_day",
    "distinct_counterparties", "seconds_since_prev_txn", "sender_in_degree",
    "sender_out_degree", "device_count", "city_count", "is_new_device",
    "is_new_city", "amount_near_threshold", "is_overnight",
    "rapid_in_out_movement", "is_self_transfer", "time_since_previous_hours",
    "sender_txn_count_1h", "sender_txn_count_24h", "sender_device_count",
    "sender_city_count",
]


def _window_counts(times: pd.Series, window_hours: float) -> np.ndarray:
    nanoseconds = times.astype("int64").to_numpy()
    width = int(window_hours * 3_600_000_000_000)
    left = np.searchsorted(nanoseconds, nanoseconds - width, side="left")
    right = np.searchsorted(nanoseconds, nanoseconds, side="right")
    return (right - left).astype(np.int64)


def _row_record(row: pd.Series, reason: str, detail: str) -> dict[str, Any]:
    source_number = row.get("__source_row_number", 0)
    try:
        source_number_int = int(str(source_number))
    except (TypeError, ValueError, OverflowError):
        source_number_int = 0
    record: dict[str, Any] = {
        "source_row_number": source_number_int,
        "reason": reason,
        "reason_detail": detail,
    }
    for column in REQUIRED_COLUMNS:
        value = row.get(column)
        record[column] = None if value is None or pd.isna(value) else str(value)
    return record


def process_transactions(
    frame: pd.DataFrame,
    settings: dict[str, Any] | None = None,
    ingestion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return cleaned transactions, account features, row-rejection details and quality metrics."""
    values = {**DEFAULT_SETTINGS, **(settings or {})}
    source_report = ingestion or {
        "source": "transactions.csv", "rows_received": len(frame), "rows_before_processing": len(frame),
        "malformed_rows": 0, "rejected_rows": [], "columns_received": list(frame.columns),
    }
    data = frame.copy().reset_index(drop=True)
    data.columns = [str(column).strip().lower() for column in data.columns]
    if len(data.columns) != len(set(data.columns)):
        raise DatasetError("CSV column names must be unique after trimming and case normalization.", code="duplicate_header")
    missing = [column for column in REQUIRED_COLUMNS if column not in data.columns]
    if missing:
        raise DatasetError("Missing required columns: " + ", ".join(missing), code="missing_columns")
    if "__source_row_number" not in data.columns:
        data["__source_row_number"] = np.arange(2, len(data) + 2, dtype=np.int64)

    rows_received = int(source_report.get("rows_received", len(data)))
    malformed_records = list(source_report.get("rejected_rows", []))
    malformed_count = int(source_report.get("malformed_rows", len(malformed_records)))
    rows_parsed = int(source_report.get("rows_before_processing", len(data)))
    has_truth_column = GROUND_TRUTH_COLUMN in data.columns
    if data.empty:
        validation = {
            "rows_received": rows_received, "rows_before_processing": rows_parsed,
            "rows_loaded": 0, "rows_rejected": malformed_count,
            "duplicates_removed": 0, "invalid_rows_dropped": 0,
            "malformed_rows": malformed_count, "rejected_by_reason": {"malformed_width": malformed_count},
            "unique_accounts": 0, "has_ground_truth": False,
            "ground_truth_column_present": has_truth_column, "labelled_rows": 0,
            "date_range": None, "row_accounting_reconciles": rows_received == malformed_count,
        }
        raise DatasetError(
            "No transaction rows could be parsed. Review the rejected-row report.",
            code="no_valid_rows", stage="processing", rejected_rows=malformed_records, validation=validation,
        )

    timestamps = cast(pd.Series, pd.to_datetime(cast(pd.Series, data.loc[:, "timestamp"]), errors="coerce", utc=True))
    amounts = cast(pd.Series, pd.to_numeric(cast(pd.Series, data.loc[:, "amount"]), errors="coerce"))
    source_ids = cast(pd.Series, data.loc[:, "txn_id"]).astype("string").str.strip()
    senders = cast(pd.Series, data.loc[:, "from_account"]).astype("string").str.strip().str.upper()
    recipients = cast(pd.Series, data.loc[:, "to_account"]).astype("string").str.strip().str.upper()
    signatures: list[tuple[str, ...]] = []
    row_rejections: list[dict[str, Any]] = []
    primary_reasons: list[str | None] = []
    for position in range(len(data)):
        row = data.iloc[position]
        signatures.append(tuple("" if pd.isna(row[column]) else str(row[column]) for column in REQUIRED_COLUMNS))
        required_values = tuple(REQUIRED_COLUMNS)
        blanks = [column for column in required_values if pd.isna(row[column]) or not str(row[column]).strip()]
        reason: str | None = None
        detail = ""
        if blanks:
            reason, detail = "missing_required_value", "Blank required field(s): " + ", ".join(blanks)
        elif pd.isna(timestamps.iloc[position]):
            reason, detail = "invalid_timestamp", "Timestamp could not be parsed as valid UTC time."
        elif pd.isna(amounts.iloc[position]):
            reason, detail = "invalid_amount", "Amount must be numeric."
        elif float(amounts.iloc[position]) <= 0:
            reason, detail = "non_positive_amount", "Amount must be greater than zero."
        elif str(senders.iloc[position]) == str(recipients.iloc[position]):
            reason, detail = "self_transfer", "Transfers from an account to itself are not accepted."
        primary_reasons.append(reason)
        if reason:
            row_rejections.append(_row_record(row, reason, detail))

    # Ground truth is normalized exclusively for evaluation. Invalid labels are excluded from evaluation, not risk scoring.
    if has_truth_column:
        label_series = cast(pd.Series, data.loc[:, GROUND_TRUTH_COLUMN])
        truth = cast(pd.Series, pd.to_numeric(label_series, errors="coerce"))
        raw_labels = label_series.astype("string").str.strip().fillna("")
        invalid_truth_labels = int((raw_labels.ne("") & ~truth.isin(np.asarray([0, 1]))).sum())
        truth = cast(pd.Series, truth.where(truth.isin(np.asarray([0, 1])), np.nan))
    else:
        truth = pd.Series(np.nan, index=data.index, dtype=float)
        invalid_truth_labels = 0

    valid_positions = [position for position, reason in enumerate(primary_reasons) if reason is None]
    candidates = data.iloc[valid_positions].copy().reset_index(drop=True)
    candidates["timestamp"] = timestamps.iloc[valid_positions].to_numpy()
    candidates["amount"] = amounts.iloc[valid_positions].to_numpy(dtype=float)
    candidates["from_account"] = senders.iloc[valid_positions].astype(str).to_numpy()
    candidates["to_account"] = recipients.iloc[valid_positions].astype(str).to_numpy()
    candidates[GROUND_TRUTH_COLUMN] = truth.iloc[valid_positions].to_numpy(dtype=float)
    candidates["txn_id"] = source_ids.iloc[valid_positions].astype(str).to_numpy()
    for column in ("channel", "city", "device_id"):
        candidates[column] = candidates[column].astype("string").str.strip().fillna("").replace("", "Unknown").to_numpy()
    candidates["__raw_signature"] = [signatures[position] for position in valid_positions]

    # Exact duplicates compare all eight required raw fields; optional labels are never part of this decision.
    exact_duplicate_mask = candidates["__raw_signature"].duplicated(keep="first")
    exact_duplicates = candidates.loc[exact_duplicate_mask]
    unique_candidates = candidates.loc[~exact_duplicate_mask].copy()
    seen_ids: set[str] = set()
    conflict_positions: list[int] = []
    for position, txn_id in enumerate(unique_candidates["txn_id"].tolist()):
        if txn_id in seen_ids:
            conflict_positions.append(position)
        else:
            seen_ids.add(txn_id)
    conflicts = unique_candidates.iloc[conflict_positions] if conflict_positions else unique_candidates.iloc[0:0]
    for _, row in conflicts.iterrows():
        row_rejections.append(_row_record(row, "conflicting_txn_id", "Transaction ID was reused with different required-column content."))
    accepted = unique_candidates.drop(unique_candidates.index[conflict_positions]).drop(columns=["__raw_signature"], errors="ignore").reset_index(drop=True)

    rejection_records = malformed_records + row_rejections
    rejected_by_reason: dict[str, int] = {}
    for record in rejection_records:
        reason = str(record.get("reason", "unknown"))
        rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1
    duplicates_removed = int(len(exact_duplicates))
    rejected_count = int(len(rejection_records))
    if rows_received != rejected_count + duplicates_removed + len(accepted):
        validation = {
            "rows_received": rows_received, "rows_before_processing": rows_parsed,
            "rows_loaded": int(len(accepted)), "rows_rejected": rejected_count,
            "duplicates_removed": duplicates_removed, "malformed_rows": malformed_count,
            "rejected_by_reason": rejected_by_reason, "row_accounting_reconciles": False,
        }
        raise DatasetError(
            "Row accounting did not reconcile; no active dataset was changed.",
            code="row_accounting_error", stage="processing", rejected_rows=rejection_records, validation=validation,
        )

    def build_validation(clean: pd.DataFrame) -> dict[str, Any]:
        accounts = set(clean["from_account"].astype(str)) | set(clean["to_account"].astype(str)) if not clean.empty else set()
        date_range = None
        if not clean.empty:
            date_range = {"start": clean["timestamp"].min().isoformat(), "end": clean["timestamp"].max().isoformat()}
        labelled = int(clean[GROUND_TRUTH_COLUMN].notna().sum()) if has_truth_column and GROUND_TRUTH_COLUMN in clean else 0
        return {
            "source": str(source_report.get("source", "transactions.csv")),
            "rows_received": rows_received,
            "rows_before_processing": rows_parsed,
            "rows_loaded": int(len(clean)),
            "rows_rejected": rejected_count,
            "invalid_rows_dropped": int(len(row_rejections)),
            "duplicates_removed": duplicates_removed,
            "duplicate_rows_dropped": duplicates_removed,
            "dropped_rows": rejected_count + duplicates_removed,
            "malformed_rows_dropped": malformed_count,
            "malformed_rows": malformed_count,
            "rejected_by_reason": rejected_by_reason,
            "unique_accounts": int(len(accounts)),
            "ground_truth_column_present": has_truth_column,
            "has_ground_truth": labelled > 0,
            "labelled_rows": labelled,
            "invalid_truth_labels_excluded": invalid_truth_labels,
            "self_transfers_rejected": sum(record.get("reason") == "self_transfer" for record in row_rejections),
            "self_transfers_flagged": int(clean["is_self_transfer"].sum()) if "is_self_transfer" in clean else 0,
            "account_ids_normalized": int((data["from_account"].astype(str).str.strip().str.upper() != data["from_account"].astype(str)).sum() + (data["to_account"].astype(str).str.strip().str.upper() != data["to_account"].astype(str)).sum()),
            "date_range": date_range,
            "row_accounting_reconciles": rows_received == rejected_count + duplicates_removed + len(clean),
        }

    if accepted.empty:
        validation = build_validation(accepted)
        raise DatasetError(
            "No valid transaction rows remain after cleaning. Download the rejected-row report and correct the CSV.",
            code="no_valid_rows", stage="processing", rejected_rows=rejection_records, validation=validation,
        )

    # Stable timestamp-only order preserves source order for timestamp ties; neither transaction IDs nor labels rank data.
    accepted = accepted.sort_values("timestamp", kind="stable").reset_index(drop=True)
    accepted["amount"] = accepted["amount"].astype(float)
    accepted["hour_of_day"] = accepted["timestamp"].dt.hour.astype(int)
    accepted["hour_utc"] = accepted["hour_of_day"]
    accepted["is_overnight"] = accepted["hour_of_day"].lt(int(values["odd_hour_start"])) | accepted["hour_of_day"].ge(int(values["odd_hour_end"]))
    accepted["is_self_transfer"] = accepted["from_account"].eq(accepted["to_account"])

    sender_average = accepted.groupby("from_account", sort=False)["amount"].transform("mean")
    accepted["sender_average_amount"] = sender_average
    accepted["sender_avg_amount"] = sender_average
    accepted["amount_vs_account_avg"] = (accepted["amount"] / sender_average.replace(0, np.nan)).fillna(1.0)
    accepted["amount_to_sender_average"] = accepted["amount_vs_account_avg"]
    lower = float(values["structuring_threshold"]) * float(values["structuring_lower_ratio"])
    upper = float(values["structuring_threshold"]) * float(values["structuring_upper_ratio"])
    accepted["amount_near_threshold"] = accepted["amount"].between(lower, upper, inclusive="both")

    counterparties: dict[str, set[str]] = {}
    for source, target in zip(accepted["from_account"].astype(str), accepted["to_account"].astype(str)):
        counterparties.setdefault(source, set()).add(target)
        counterparties.setdefault(target, set()).add(source)
    accepted["distinct_counterparties"] = accepted["from_account"].map(lambda account: len(counterparties.get(str(account), set()))).astype(int)
    out_degree = accepted.groupby("from_account", sort=False)["to_account"].nunique().to_dict()
    in_degree = accepted.groupby("to_account", sort=False)["from_account"].nunique().to_dict()
    accepted["sender_out_degree"] = accepted["from_account"].map(out_degree).fillna(0).astype(int)
    accepted["sender_in_degree"] = accepted["from_account"].map(in_degree).fillna(0).astype(int)
    accepted["sender_distinct_counterparties"] = accepted["distinct_counterparties"]
    accepted["sender_device_count"] = accepted.groupby("from_account", sort=False)["device_id"].transform("nunique")
    accepted["sender_city_count"] = accepted.groupby("from_account", sort=False)["city"].transform("nunique")

    accepted["txn_count_1h"] = 0
    accepted["txn_count_24h"] = 0
    accepted["seconds_since_prev_txn"] = 604_800.0
    for _, positions_group in accepted.groupby("from_account", sort=False).groups.items():
        positions = np.asarray(list(positions_group), dtype=np.int64)
        sender_times = accepted.loc[positions, "timestamp"].reset_index(drop=True)
        accepted.loc[positions, "txn_count_1h"] = _window_counts(sender_times, 1.0)
        accepted.loc[positions, "txn_count_24h"] = _window_counts(sender_times, 24.0)
        time_ns = sender_times.astype("int64").to_numpy()
        elapsed = np.diff(time_ns, prepend=time_ns[0]) / 1_000_000_000.0
        elapsed[0] = 604_800.0
        accepted.loc[positions, "seconds_since_prev_txn"] = np.clip(elapsed, 0, 604_800)
    accepted["sender_txn_count_1h"] = accepted["txn_count_1h"]
    accepted["sender_txn_count_24h"] = accepted["txn_count_24h"]
    accepted["time_since_previous_hours"] = accepted["seconds_since_prev_txn"] / 3_600.0

    accepted["is_new_device"] = False
    accepted["is_new_city"] = False
    accepted["account_prior_transaction_count"] = 0
    minimum_prior = int(values["new_signal_min_prior_transactions"])
    for _, positions_group in accepted.groupby("from_account", sort=False).groups.items():
        seen_devices: set[str] = set()
        seen_cities: set[str] = set()
        prior_count = 0
        for position in positions_group:
            accepted.at[position, "account_prior_transaction_count"] = prior_count
            device = str(accepted.at[position, "device_id"])
            city = str(accepted.at[position, "city"])
            accepted.at[position, "is_new_device"] = prior_count >= minimum_prior and device not in seen_devices and device != "Unknown"
            accepted.at[position, "is_new_city"] = prior_count >= minimum_prior and city not in seen_cities and city != "Unknown"
            seen_devices.add(device)
            seen_cities.add(city)
            prior_count += 1

    incoming_times: dict[str, np.ndarray] = {}
    for account, group in accepted.groupby("to_account", sort=False):
        incoming_times[str(account)] = group["timestamp"].astype("int64").to_numpy()
    burst_window_ns = int(values["fanin_window_minutes"]) * 60 * 1_000_000_000
    rapid_flags = np.zeros(len(accepted), dtype=bool)
    for position, (account, stamp) in enumerate(zip(accepted["from_account"].astype(str), accepted["timestamp"].astype("int64"))):
        times = incoming_times.get(account, np.asarray([], dtype=np.int64))
        left = int(np.searchsorted(times, int(stamp) - burst_window_ns, side="left"))
        right = int(np.searchsorted(times, int(stamp), side="left"))
        rapid_flags[position] = right > left
    accepted["rapid_in_out_movement"] = rapid_flags

    account_ids = list(dict.fromkeys(accepted["from_account"].astype(str).tolist() + accepted["to_account"].astype(str).tolist()))
    account_rows: list[dict[str, Any]] = []
    for account in account_ids:
        sent = accepted.loc[accepted["from_account"].eq(account)]
        received = accepted.loc[accepted["to_account"].eq(account)]
        related = accepted.loc[accepted["from_account"].eq(account) | accepted["to_account"].eq(account)]
        account_rows.append({
            "account_id": account,
            "out_transaction_count": int(len(sent)),
            "in_transaction_count": int(len(received)),
            "transaction_count": int(len(related)),
            "total_outgoing_amount": float(sent["amount"].sum()),
            "total_incoming_amount": float(received["amount"].sum()),
            "average_outgoing_amount": float(sent["amount"].mean()) if not sent.empty else 0.0,
            "maximum_outgoing_amount": float(sent["amount"].max()) if not sent.empty else 0.0,
            "in_degree": int(related.loc[related["to_account"].eq(account), "from_account"].nunique()),
            "out_degree": int(related.loc[related["from_account"].eq(account), "to_account"].nunique()),
            "distinct_counterparties": int(len(counterparties.get(account, set()))),
            "device_count": int(sent["device_id"].nunique()),
            "city_count": int(sent["city"].nunique()),
            "overnight_count": int(sent["is_overnight"].sum()),
            "rapid_in_out_count": int(sent["rapid_in_out_movement"].sum()),
            "first_seen": related["timestamp"].min().isoformat(),
            "last_seen": related["timestamp"].max().isoformat(),
            "max_risk": 0.0,
            "case_id": None,
        })
    account_features = pd.DataFrame(account_rows)
    validation = build_validation(accepted)

    keep = list(dict.fromkeys(REQUIRED_COLUMNS + ([GROUND_TRUTH_COLUMN] if has_truth_column else []) + FEATURE_COLUMNS + [
        "hour_utc", "sender_average_amount", "sender_avg_amount", "amount_to_sender_average",
        "sender_txn_count_1h", "sender_txn_count_24h", "sender_in_degree", "sender_out_degree",
        "sender_distinct_counterparties", "time_since_previous_hours", "account_prior_transaction_count",
    ]))
    accepted = accepted.loc[:, [column for column in keep if column in accepted.columns]].reset_index(drop=True)
    return {
        "data": accepted,
        "account_features": account_features,
        "validation": validation,
        "rejected_rows": rejection_records,
        "feature_names": FEATURE_COLUMNS.copy(),
        "model_features": MODEL_FEATURES.copy(),
    }
