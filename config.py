"""Centralized, illustrative RingWatch detection and model configuration."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_ROWS = 100_000

# The six features, estimator size and seed are deliberately fixed to keep the demo formula reproducible.
MODEL_CONFIG = {
    "name": "Isolation Forest",
    "features": [
        "amount_vs_account_avg", "txn_count_1h", "txn_count_24h",
        "hour_of_day", "distinct_counterparties", "seconds_since_prev_txn",
    ],
    "n_estimators": 200,
    "random_state": 42,
    "contamination": "auto",
    "ml_weight": 0.4,
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "structuring_threshold": 50_000.0,
    "structuring_min_count": 3,
    "structuring_window_hours": 2.0,
    "structuring_lower_ratio": 0.90,
    "structuring_upper_ratio": 0.99,
    "structuring_points": 45,
    "velocity_min_count": 7,
    "velocity_window_minutes": 10,
    "velocity_points": 30,
    "odd_hour_start": 1,
    "odd_hour_end": 5,
    "odd_hour_multiplier": 3.0,
    "odd_hour_points": 25,
    "new_signal_min_amount": 20_000.0,
    "new_signal_min_prior_transactions": 5,
    "new_signal_points": 20,
    "cycle_min_accounts": 3,
    "cycle_max_accounts": 5,
    "cycle_window_hours": 48.0,
    "cycle_points": 50,
    "fanin_min_senders": 8,
    "fanin_forward_ratio": 0.80,
    "fanin_lookback_hours": 24.0,
    "fanin_window_minutes": 60,
    "fanin_points": 50,
    "flagged_risk_threshold": 40,
    "risk_medium_threshold": 40,
    "risk_high_threshold": 70,
    "model_reason_threshold": 70,
    "alert_budget_default": 20,
}

SETTING_BOUNDS: dict[str, tuple[float, float]] = {
    "structuring_threshold": (1_000, 1_000_000),
    "structuring_min_count": (3, 50),
    "structuring_window_hours": (0.1, 48),
    "structuring_lower_ratio": (0.5, 0.99),
    "structuring_upper_ratio": (0.51, 1.0),
    "structuring_points": (1, 100),
    "velocity_min_count": (2, 100),
    "velocity_window_minutes": (1, 1_440),
    "velocity_points": (1, 100),
    "odd_hour_start": (0, 23),
    "odd_hour_end": (1, 24),
    "odd_hour_multiplier": (1.1, 20),
    "odd_hour_points": (1, 100),
    "new_signal_min_amount": (100, 1_000_000),
    "new_signal_min_prior_transactions": (0, 500),
    "new_signal_points": (1, 100),
    "cycle_min_accounts": (3, 5),
    "cycle_max_accounts": (3, 5),
    "cycle_window_hours": (1, 168),
    "cycle_points": (1, 100),
    "fanin_min_senders": (2, 100),
    "fanin_forward_ratio": (0.1, 1.0),
    "fanin_lookback_hours": (1, 168),
    "fanin_window_minutes": (1, 1_440),
    "fanin_points": (1, 100),
    "flagged_risk_threshold": (1, 99),
    "risk_medium_threshold": (1, 99),
    "risk_high_threshold": (2, 100),
    "model_reason_threshold": (1, 100),
    "alert_budget_default": (1, 100_000),
}

INTEGER_SETTINGS = {
    "structuring_min_count", "structuring_points", "velocity_min_count", "velocity_window_minutes",
    "velocity_points", "odd_hour_start", "odd_hour_end", "odd_hour_points",
    "new_signal_min_prior_transactions", "new_signal_points", "cycle_min_accounts",
    "cycle_max_accounts", "cycle_points", "fanin_min_senders", "fanin_window_minutes",
    "fanin_points", "flagged_risk_threshold", "risk_medium_threshold", "risk_high_threshold",
    "model_reason_threshold", "alert_budget_default",
}

RISK_BANDS = {
    "low": {"min": 0, "max": 39, "label": "Low"},
    "medium": {"min": 40, "max": 69, "label": "Medium"},
    "high": {"min": 70, "max": 100, "label": "High"},
}

RULES: dict[str, dict[str, Any]] = {
    "structuring": {
        "title": "Structuring",
        "description": "Repeated transfers just below an illustrative reporting threshold.",
        "points_key": "structuring_points",
        "threshold_keys": ["structuring_min_count", "structuring_window_hours", "structuring_threshold", "structuring_lower_ratio", "structuring_upper_ratio"],
    },
    "velocity": {
        "title": "Transaction velocity",
        "description": "More than six transfers from one sender in ten minutes by default.",
        "points_key": "velocity_points",
        "threshold_keys": ["velocity_min_count", "velocity_window_minutes"],
    },
    "odd_hour": {
        "title": "Odd-hour transfer",
        "description": "A 1AM–5AM transfer at least three times the sender's average of other transfers by default.",
        "points_key": "odd_hour_points",
        "threshold_keys": ["odd_hour_start", "odd_hour_end", "odd_hour_multiplier"],
    },
    "new_signal": {
        "title": "New device or city",
        "description": "A large first-seen device/city signal after enough prior sender activity.",
        "points_key": "new_signal_points",
        "threshold_keys": ["new_signal_min_amount", "new_signal_min_prior_transactions"],
    },
    "circular_flow": {
        "title": "Circular flow",
        "description": "A directed three-to-five-account cycle whose actual transfers fit the configured time window.",
        "points_key": "cycle_points",
        "threshold_keys": ["cycle_min_accounts", "cycle_max_accounts", "cycle_window_hours"],
    },
    "fanin": {
        "title": "Fan-in with pass-through",
        "description": "Funds from at least eight distinct senders converge and at least 80% is forwarded within one hour by default.",
        "points_key": "fanin_points",
        "threshold_keys": ["fanin_min_senders", "fanin_forward_ratio", "fanin_lookback_hours", "fanin_window_minutes"],
    },
}


def default_settings() -> dict[str, Any]:
    """Return a fresh settings object; demo thresholds are not validated bank thresholds."""
    return deepcopy(DEFAULT_SETTINGS)


def risk_bands(settings: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    values = {**DEFAULT_SETTINGS, **(settings or {})}
    medium = int(values["risk_medium_threshold"])
    high = int(values["risk_high_threshold"])
    return {
        "low": {"min": 0, "max": medium - 1, "label": "Low"},
        "medium": {"min": medium, "max": high - 1, "label": "Medium"},
        "high": {"min": high, "max": 100, "label": "High"},
    }


def risk_band(score: float, settings: dict[str, Any] | None = None) -> str:
    value = max(0.0, min(100.0, float(score)))
    thresholds = {**DEFAULT_SETTINGS, **(settings or {})}
    if value >= float(thresholds["risk_high_threshold"]):
        return "high"
    if value >= float(thresholds["risk_medium_threshold"]):
        return "medium"
    return "low"


def validate_settings(candidate: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate and normalize a partial settings update, raising ValueError on invalid input."""
    unknown = sorted(set(candidate) - set(SETTING_BOUNDS))
    if unknown:
        raise ValueError(f"Unknown setting(s): {', '.join(unknown)}")
    values = {**default_settings(), **(current or {})}
    for key, value in candidate.items():
        low, high = SETTING_BOUNDS[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= float(value) <= high:
            raise ValueError(f"{key} must be a number between {low:g} and {high:g}.")
        values[key] = int(value) if key in INTEGER_SETTINGS else float(value)
    if values["structuring_lower_ratio"] >= values["structuring_upper_ratio"]:
        raise ValueError("Structuring lower ratio must be less than upper ratio.")
    if values["cycle_min_accounts"] > values["cycle_max_accounts"]:
        raise ValueError("Cycle minimum accounts must not exceed the maximum.")
    if values["odd_hour_start"] >= values["odd_hour_end"]:
        raise ValueError("Odd-hour start must be earlier than odd-hour end.")
    if values["risk_medium_threshold"] >= values["risk_high_threshold"]:
        raise ValueError("Medium-risk threshold must be less than high-risk threshold.")
    return values
