"""Stage 3: six explainable transaction rules plus a deterministic anomaly signal."""
from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

from config import DEFAULT_SETTINGS, MODEL_CONFIG, risk_band, risk_bands
from rule_engine import detect_rules

MODEL_FEATURES = list(MODEL_CONFIG["features"])
MODEL_FEATURE_LABELS = {
    "amount_vs_account_avg": "amount compared with sender's own average",
    "txn_count_1h": "sender's transactions in the last hour",
    "txn_count_24h": "sender's transactions in the last 24 hours",
    "hour_of_day": "UTC time of the transfer",
    "distinct_counterparties": "sender's distinct counterparties",
    "seconds_since_prev_txn": "time since the sender's previous transfer",
}
ML_WEIGHT = float(MODEL_CONFIG["ml_weight"])
FLAGGED_RISK_THRESHOLD = float(DEFAULT_SETTINGS["flagged_risk_threshold"])
ML_REASON_THRESHOLD = float(DEFAULT_SETTINGS["model_reason_threshold"])


def _score_distribution(values) -> dict[str, float]:
    array = np.asarray(list(values), dtype=float)
    if not array.size:
        return {"min": 0.0, "median": 0.0, "p90": 0.0, "max": 0.0}
    return {
        "min": round(float(np.min(array)), 1),
        "median": round(float(np.median(array)), 1),
        "p90": round(float(np.quantile(array, 0.90)), 1),
        "max": round(float(np.max(array)), 1),
    }


def _feature_signals(features: pd.DataFrame) -> list[list[dict[str, Any]]]:
    """Return dataset-relative robust feature deviations, not causal IF attributions."""
    matrix = features.astype(float)
    medians = cast(pd.Series, matrix.median(axis=0))
    deviations = (matrix - medians).abs()
    mad = cast(pd.Series, deviations.median(axis=0))
    quartile_scale = cast(pd.Series, (matrix.quantile(.75) - matrix.quantile(.25)) / 1.349)
    scales = mad * 1.4826
    scales = scales.where(scales > 1e-9, quartile_scale.where(quartile_scale > 1e-9, 1.0))
    robust = deviations.divide(scales, axis=1)
    values = matrix.to_numpy(dtype=float)
    med_values = cast(dict[str, float], medians.to_dict())
    robust_values = robust.to_numpy(dtype=float)
    columns = [str(column) for column in matrix.columns]
    output: list[list[dict[str, Any]]] = []
    for row_position in range(len(matrix)):
        row_signals: list[dict[str, Any]] = []
        for feature_position in np.argsort(-robust_values[row_position], kind="stable"):
            index = int(feature_position)
            feature = columns[index]
            deviation = float(robust_values[row_position, index])
            if deviation < 0.5:
                continue
            observed = float(values[row_position, index])
            median = float(med_values[feature])
            label = MODEL_FEATURE_LABELS[feature]
            row_signals.append({
                "feature": feature,
                "label": label,
                "value": round(observed, 3),
                "dataset_median": round(median, 3),
                "robust_deviation": round(deviation, 2),
                "explanation": f"{label.capitalize()} was {observed:,.3g}; the dataset median is {median:,.3g} ({deviation:.1f} robust deviations away).",
            })
            if len(row_signals) == 3:
                break
        output.append(row_signals)
    return output


def _fit_transaction_model(data: pd.DataFrame) -> tuple[pd.Series, list[list[dict[str, Any]]], dict[str, Any]]:
    features = cast(pd.DataFrame, data.loc[:, MODEL_FEATURES].astype(float))
    signals = _feature_signals(features)
    fitted = len(features) >= 12
    if not fitted:
        scores = pd.Series(np.zeros(len(features), dtype=float), index=data.index)
    else:
        matrix = SimpleImputer(strategy="median").fit_transform(features)
        matrix = StandardScaler().fit_transform(matrix)
        model = IsolationForest(
            n_estimators=int(MODEL_CONFIG["n_estimators"]),
            contamination=str(MODEL_CONFIG["contamination"]),
            random_state=int(MODEL_CONFIG["random_state"]),
            n_jobs=1,
        )
        model.fit(matrix)
        raw = -model.decision_function(matrix)
        lower, upper = np.quantile(raw, [0.50, 0.98])
        normalized = np.zeros_like(raw) if upper <= lower else np.clip((raw - lower) / (upper - lower) * 100.0, 0.0, 100.0)
        scores = pd.Series(normalized.astype(float), index=data.index)
    metadata = {
        "name": str(MODEL_CONFIG["name"]),
        "features": MODEL_FEATURES,
        "scored_transactions": int(len(features)),
        "score_distribution": _score_distribution(scores),
        "random_state": int(MODEL_CONFIG["random_state"]),
        "n_estimators": int(MODEL_CONFIG["n_estimators"]),
        "contamination": str(MODEL_CONFIG["contamination"]),
        "model_fitted": fitted,
        "explanation_method": "Feature signals are robust dataset-relative deviations, not causal Isolation Forest feature attributions.",
        "anomaly_score_scaling": "The fitted Isolation Forest raw anomaly score is mapped from its p50–p98 interval to 0–100; higher means more unusual in this dataset, not more likely to be fraud.",
    }
    return scores, signals, metadata


def _transaction_example(row: pd.Series) -> dict[str, Any]:
    rule_points = int(row["rule_points"])
    ml_score = float(row["ml_score"])
    weight = float(MODEL_CONFIG["ml_weight"])
    uncapped = rule_points + weight * ml_score
    return {
        "txn_id": str(row["txn_id"]),
        "rule_points": rule_points,
        "ml_score": round(ml_score, 2),
        "ml_weight": weight,
        "weighted_ml_score": round(weight * ml_score, 2),
        "uncapped_score": round(uncapped, 2),
        "final_score": round(min(100.0, uncapped), 1),
        "final_risk": round(min(100.0, uncapped), 1),
        "capped_at_100": uncapped >= 100.0,
        "formula": f"min(100, {rule_points} + {weight:.1f} × {ml_score:.2f}) = {min(100.0, uncapped):.1f}",
        "matched_rules": list(row["matched_rules"]),
        "feature_signals": list(row["feature_signals"][:3]),
    }


def score_transactions(processed: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Attach rule evidence, per-transaction risk, account risk and model metadata."""
    values = {**DEFAULT_SETTINGS, **(settings or {})}
    data = processed["data"].copy().reset_index(drop=True)
    rule_findings = detect_rules(data, values)
    ml_scores, feature_signals, model_meta = _fit_transaction_model(data)
    data["ml_score"] = ml_scores.to_numpy(dtype=float)
    data["feature_signals"] = feature_signals

    per_transaction: dict[str, dict[str, int]] = {}
    reasons_by_transaction: dict[str, list[dict[str, Any]]] = {}
    account_rule_points: dict[str, dict[str, int]] = {}
    account_reasons: dict[str, list[dict[str, Any]]] = {}
    for finding in rule_findings:
        rule_id = str(finding["rule_id"])
        points = int(finding["points"])
        for transaction_id in finding["txn_ids"]:
            rules = per_transaction.setdefault(str(transaction_id), {})
            rules[rule_id] = max(rules.get(rule_id, 0), points)
            reasons_by_transaction.setdefault(str(transaction_id), []).append(finding)
        for account_id in finding["accounts"]:
            rules = account_rule_points.setdefault(str(account_id), {})
            rules[rule_id] = max(rules.get(rule_id, 0), points)
            account_reasons.setdefault(str(account_id), []).append(finding)

    transaction_ids = data["txn_id"].astype(str)
    data["rule_points"] = transaction_ids.map(lambda value: sum(per_transaction.get(value, {}).values())).astype(int)
    data["matched_rules"] = transaction_ids.map(lambda value: sorted(per_transaction.get(value, {}).keys()))
    weight = float(MODEL_CONFIG["ml_weight"])
    flag_threshold = float(values["flagged_risk_threshold"])
    model_reason_threshold = float(values["model_reason_threshold"])
    weighted_ml = weight * data["ml_score"].astype(float)
    data["weighted_ml_score"] = weighted_ml
    uncapped = data["rule_points"].astype(float) + weighted_ml
    data["uncapped_score"] = uncapped
    data["risk_score"] = np.minimum(100.0, uncapped).round(1)
    data["final_risk"] = data["risk_score"]
    data["score_capped"] = uncapped.ge(100.0)
    data["risk_band"] = data["risk_score"].map(lambda score: risk_band(float(score), values))
    data["is_flagged"] = data["risk_score"].ge(flag_threshold)

    model_findings: list[dict[str, Any]] = []
    transaction_reasons: list[list[dict[str, Any]]] = []
    for position, row in data.iterrows():
        transaction_id = str(row["txn_id"])
        explanations: list[dict[str, Any]] = []
        seen_explanations: set[tuple[str, str]] = set()
        for finding in reasons_by_transaction.get(transaction_id, []):
            key = (str(finding["rule_id"]), str(finding["explanation"]))
            if key in seen_explanations:
                continue
            seen_explanations.add(key)
            explanations.append({key: finding[key] for key in ("rule_id", "rule_name", "points", "explanation", "threshold", "evidence", "source")})
        anomaly_score = float(row["ml_score"])
        signals = list(row["feature_signals"])
        if anomaly_score >= model_reason_threshold:
            signal_text = "; ".join(item["explanation"] for item in signals[:2]) or "multiple measured transaction features"
            model_reason = {
                "rule_id": "ml_anomaly", "rule_name": "Unusual behaviour", "points": 0,
                "explanation": f"Isolation Forest anomaly score {anomaly_score:.1f}/100. Leading measured signals: {signal_text} This is not a fraud confirmation.",
                "threshold": f"ML anomaly display threshold: {model_reason_threshold:.0f}/100",
                "evidence": {"ml_score": anomaly_score, "leading_feature_signals": signals[:2]},
                "source": "model",
            }
            explanations.append(model_reason)
            model_findings.append({
                **model_reason,
                "accounts": [str(row["from_account"]), str(row["to_account"])],
                "txn_ids": [transaction_id],
            })
        transaction_reasons.append(explanations)
    data["transaction_reasons"] = transaction_reasons

    # Account risk is the maximum participating transaction risk, with distinct rule points for context.
    all_accounts = sorted(set(data["from_account"].astype(str)) | set(data["to_account"].astype(str)))
    account_rows: dict[str, dict[str, Any]] = {}
    for account_id in all_accounts:
        related = data.loc[data["from_account"].astype(str).eq(account_id) | data["to_account"].astype(str).eq(account_id)]
        max_risk = float(related["risk_score"].max()) if not related.empty else 0.0
        max_ml = float(related["ml_score"].max()) if not related.empty else 0.0
        reasons = []
        seen: set[tuple[str, str]] = set()
        for finding in account_reasons.get(account_id, []):
            key = (str(finding["rule_id"]), str(finding["explanation"]))
            if key in seen:
                continue
            seen.add(key)
            reasons.append({item: finding[item] for item in ("rule_id", "rule_name", "points", "explanation", "threshold", "evidence", "source")})
        account_rows[account_id] = {
            "account_id": account_id,
            "rule_points": sum(account_rule_points.get(account_id, {}).values()),
            "ml_score": round(max_ml, 1),
            "risk_score": round(max_risk, 1),
            "risk_band": risk_band(max_risk, values),
            "flagged": max_risk >= flag_threshold,
            "reasons": reasons,
            "transaction_count": int(len(related)),
            "flagged_transaction_count": int(related["is_flagged"].sum()),
        }

    model_meta.update({
        "score_distribution": _score_distribution(data["ml_score"]),
        "account_score_distribution": _score_distribution([item["ml_score"] for item in account_rows.values()]),
        "transaction_risk_distribution": _score_distribution(data["risk_score"]),
        "features": MODEL_FEATURES,
        "ml_weight": weight,
        "scoring_formula": f"final_risk = min(100, rule_points + {weight:.1f} × ml_score)",
        "flagged_risk_threshold": flag_threshold,
        "model_reason_threshold": model_reason_threshold,
        "risk_bands": risk_bands(values),
        "model_fitted": bool(model_meta["model_fitted"]),
        "rule_count": len(rule_findings),
        "rules_fired": sorted({str(item["rule_id"]) for item in rule_findings}),
        "ground_truth_used_for_scoring": False,
        "feature_signal_method": "Robust dataset-relative deviation from median; descriptive only, not causal model attribution.",
    })
    data.attrs["model_features"] = list(MODEL_FEATURES)

    ranked_examples = data.sort_values(["risk_score", "ml_score"], ascending=False, kind="stable")
    examples = [_transaction_example(row) for _, row in ranked_examples.head(3).iterrows()]
    if len(examples) >= 3 and not any(example["capped_at_100"] for example in examples):
        capped_rows = ranked_examples.loc[ranked_examples["score_capped"]]
        if not capped_rows.empty:
            capped_example = _transaction_example(capped_rows.iloc[0])
            examples[-1] = capped_example
    return {
        "data": data,
        "accounts": account_rows,
        "findings": rule_findings + model_findings,
        "rule_findings": rule_findings,
        "model_findings": model_findings,
        "transaction_ml_scores": pd.Series(data["ml_score"].to_numpy(dtype=float), index=data.index),
        "model": {**model_meta, "worked_examples": examples},
        "settings": values,
        "account_features": processed["account_features"],
        "flagged_transactions": data.loc[data["is_flagged"]].copy(),
    }


__all__ = ["FLAGGED_RISK_THRESHOLD", "ML_REASON_THRESHOLD", "ML_WEIGHT", "MODEL_FEATURES", "score_transactions"]
