"""Six explainable transaction rules with explicit numeric evidence; ground truth is never read."""
from __future__ import annotations

from typing import Any, cast

import networkx as nx
import numpy as np
import pandas as pd

from config import RULES


def _ordered_unique(values) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if pd.notna(value)))


def _window_findings(group: pd.DataFrame, duration: pd.Timedelta, min_count: int):
    """Yield stable, non-overlapping qualifying windows in timestamp order."""
    ordered = group.sort_values("timestamp", kind="stable").reset_index(drop=True)
    times = ordered["timestamp"].astype("int64").to_numpy()
    start = 0
    while start < len(ordered):
        end = int(np.searchsorted(times, times[start] + duration.value, side="right"))
        if end - start >= min_count:
            yield ordered.iloc[start:end]
            start = end
        else:
            start += 1


def make_rule_finding(
    rule_id: str,
    points: int,
    explanation: str,
    threshold: str,
    accounts,
    txn_ids,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "rule_name": RULES[rule_id]["title"],
        "points": int(points),
        "explanation": str(explanation),
        "threshold": str(threshold),
        "evidence": evidence or {},
        "accounts": sorted(set(_ordered_unique(accounts))),
        # Preserve transaction event order; identifiers never rank or score activity.
        "txn_ids": _ordered_unique(txn_ids),
        "source": "rule",
    }


def _cycle_transaction_rows(data: pd.DataFrame, cycle: list[str], window: pd.Timedelta) -> list[dict[str, Any]] | None:
    """Choose one real transfer for each directed edge within one rolling timestamp window."""
    edge_rows: list[pd.DataFrame] = []
    for position, source in enumerate(cycle):
        target = cycle[(position + 1) % len(cycle)]
        rows = data.loc[data["from_account"].astype(str).eq(source) & data["to_account"].astype(str).eq(target)]
        if rows.empty:
            return None
        edge_rows.append(rows.sort_values("timestamp", kind="stable").reset_index(drop=True))
    anchors = sorted({pd.Timestamp(stamp) for rows in edge_rows for stamp in rows["timestamp"]})
    for anchor in anchors:
        chosen: list[dict[str, Any]] = []
        end = anchor + window
        for rows in edge_rows:
            valid = rows.loc[(rows["timestamp"] >= anchor) & (rows["timestamp"] <= end)]
            if valid.empty:
                chosen = []
                break
            chosen.append(valid.iloc[0].to_dict())
        if chosen:
            return chosen
    return None


def detect_rules(data: pd.DataFrame, settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate structuring, velocity, odd-hour, new-context, cycle and fan-in rules."""
    findings: list[dict[str, Any]] = []

    # A. Structuring: at least the configured number of transfers in the inclusive ratio band.
    limit = float(settings["structuring_threshold"])
    lower = limit * float(settings["structuring_lower_ratio"])
    upper = limit * float(settings["structuring_upper_ratio"])
    near = data.loc[data["amount"].between(lower, upper, inclusive="both")]
    for account, group in near.groupby("from_account", sort=False):
        duration = cast(pd.Timedelta, pd.Timedelta(hours=float(settings["structuring_window_hours"])))
        windows = _window_findings(group, duration, int(settings["structuring_min_count"]))
        for window in windows:
            amounts = window["amount"].astype(float)
            count = int(len(window))
            findings.append(make_rule_finding(
                "structuring", settings["structuring_points"],
                f"{count} transfers from {account} totalled {float(amounts.sum()):,.2f}; each was between {float(amounts.min()):,.2f} and {float(amounts.max()):,.2f}, just below ₹{limit:,.0f}.",
                f"≥{int(settings['structuring_min_count'])} transfers in ≤{float(settings['structuring_window_hours']):g}h; amount ₹{lower:,.0f}–₹{upper:,.0f}",
                [account, *window["to_account"].tolist()], window["txn_id"].tolist(),
                {"transaction_count": count, "amount_min": float(amounts.min()), "amount_max": float(amounts.max()), "amount_total": float(amounts.sum()), "threshold": limit, "window_hours": float(settings["structuring_window_hours"])},
            ))

    # B. Velocity: seven by default is strictly more than six in a rolling ten minutes.
    for account, group in data.groupby("from_account", sort=False):
        duration = cast(pd.Timedelta, pd.Timedelta(minutes=int(settings["velocity_window_minutes"])))
        for window in _window_findings(group, duration, int(settings["velocity_min_count"])):
            count = int(len(window))
            span_minutes = (window["timestamp"].max() - window["timestamp"].min()).total_seconds() / 60.0
            findings.append(make_rule_finding(
                "velocity", settings["velocity_points"],
                f"{count} transfers from {account} occurred in {span_minutes:.1f} minutes.",
                f">{int(settings['velocity_min_count']) - 1} transfers within {int(settings['velocity_window_minutes'])} minutes",
                [account, *window["to_account"].tolist()], window["txn_id"].tolist(),
                {"transaction_count": count, "observed_window_minutes": span_minutes, "minimum_count": int(settings["velocity_min_count"]), "window_minutes": int(settings["velocity_window_minutes"])},
            ))

    # C. Odd hour: compare each event to the mean of the sender's other transfers, excluding itself.
    totals = data.groupby("from_account", sort=False)["amount"].agg(["sum", "count"])
    hours = data["timestamp"].dt.hour
    overnight = data.loc[hours.ge(int(settings["odd_hour_start"])) & hours.lt(int(settings["odd_hour_end"]))]
    multiplier = float(settings["odd_hour_multiplier"])
    for row in overnight.to_dict(orient="records"):
        stats = totals.loc[str(row["from_account"])]
        other_count = int(stats["count"]) - 1
        if other_count < 1:
            continue
        other_average = (float(stats["sum"]) - float(row["amount"])) / other_count
        amount = float(row["amount"])
        if other_average > 0 and amount >= multiplier * other_average:
            stamp = cast(pd.Timestamp, pd.Timestamp(row["timestamp"]))
            ratio = amount / other_average
            clock = stamp.strftime("%I:%M %p").lstrip("0")
            findings.append(make_rule_finding(
                "odd_hour", settings["odd_hour_points"],
                f"At {clock} UTC, {row['from_account']} sent ₹{amount:,.2f}—{ratio:.1f}× its ₹{other_average:,.2f} average across {other_count} other transfers.",
                f"UTC hour {int(settings['odd_hour_start'])}:00–{int(settings['odd_hour_end'])}:00; amount ≥{multiplier:g}× mean of other sender transfers",
                [row["from_account"], row["to_account"]], [row["txn_id"]],
                {"amount": amount, "other_transfer_average": other_average, "other_transfer_count": other_count, "observed_multiple": ratio, "required_multiple": multiplier, "hour_utc": int(stamp.hour)},
            ))

    # D. New device or city only after a configured amount of prior sender activity.
    minimum_prior = int(settings["new_signal_min_prior_transactions"])
    minimum_amount = float(settings["new_signal_min_amount"])
    for account, group in data.groupby("from_account", sort=False):
        group = group.sort_values("timestamp", kind="stable")
        for row in group.to_dict(orient="records"):
            amount = float(row["amount"])
            prior_count = int(row.get("account_prior_transaction_count", 0))
            is_new_device = bool(row.get("is_new_device", False))
            is_new_city = bool(row.get("is_new_city", False))
            if amount < minimum_amount or prior_count < minimum_prior or not (is_new_device or is_new_city):
                continue
            new_context = []
            if is_new_device:
                new_context.append(f"device {row['device_id']}")
            if is_new_city:
                new_context.append(f"city {row['city']}")
            finding_context = " and ".join(new_context)
            findings.append(make_rule_finding(
                "new_signal", settings["new_signal_points"],
                f"₹{amount:,.2f} was sent using first-seen {finding_context} after {prior_count} earlier sender transfers.",
                f"amount ≥₹{minimum_amount:,.0f}; at least {minimum_prior} prior sender transfers; new device or city",
                [account, row["to_account"]], [row["txn_id"]],
                {"amount": amount, "minimum_amount": minimum_amount, "prior_transaction_count": prior_count, "minimum_prior_transactions": minimum_prior, "new_device": is_new_device, "new_city": is_new_city},
            ))

    # E. Circular flow: every directed edge has a real transaction and all chosen events fit 48h by default.
    min_accounts = int(settings["cycle_min_accounts"])
    max_accounts = int(settings["cycle_max_accounts"])
    cycle_window = cast(pd.Timedelta, pd.Timedelta(hours=float(settings["cycle_window_hours"])))
    graph = nx.DiGraph()
    edge_transactions: dict[tuple[str, str], int] = {}
    for row in data[["from_account", "to_account"]].itertuples(index=False, name=None):
        source, target = str(row[0]), str(row[1])
        if source != target:
            graph.add_edge(source, target)
            edge_transactions[(source, target)] = edge_transactions.get((source, target), 0) + 1
    if graph.number_of_nodes() <= 5_000:
        try:
            cycles = nx.simple_cycles(graph, length_bound=max_accounts)
            for cycle_values in cycles:
                cycle = [str(account) for account in cycle_values]
                if not min_accounts <= len(cycle) <= max_accounts:
                    continue
                chosen = _cycle_transaction_rows(data, cycle, cycle_window)
                if not chosen:
                    continue
                txn_ids = [str(item["txn_id"]) for item in chosen]
                accounts = [str(item) for item in cycle]
                span_hours = (max(pd.Timestamp(item["timestamp"]) for item in chosen) - min(pd.Timestamp(item["timestamp"]) for item in chosen)).total_seconds() / 3600.0
                total_amount = sum(float(item["amount"]) for item in chosen)
                findings.append(make_rule_finding(
                    "circular_flow", settings["cycle_points"],
                    f"₹{total_amount:,.2f} moved around a directed {len(cycle)}-account cycle over {span_hours:.1f} hours: {' → '.join(accounts)} → {accounts[0]}.",
                    f"directed cycle of {min_accounts}–{max_accounts} accounts; observed span ≤{float(settings['cycle_window_hours']):g}h",
                    accounts, txn_ids,
                    {"cycle_length": len(cycle), "cycle_order": accounts, "observed_span_hours": span_hours, "window_hours": float(settings["cycle_window_hours"]), "amount_total": total_amount},
                ))
        except nx.NetworkXError:
            # A graph with too many candidate paths remains available to Stage 5 for reporting.
            pass

    # F. Fan-in: incoming transfers in a rolling lookback, then ≥80% forwarded within one hour after the last inflow.
    lookback = cast(pd.Timedelta, pd.Timedelta(hours=float(settings["fanin_lookback_hours"])))
    forward_window = cast(pd.Timedelta, pd.Timedelta(minutes=int(settings["fanin_window_minutes"])))
    minimum_senders = int(settings["fanin_min_senders"])
    ratio_required = float(settings["fanin_forward_ratio"])
    outgoing_groups = {str(account): group.sort_values("timestamp", kind="stable") for account, group in data.groupby("from_account", sort=False)}
    for receiver, incoming_group in data.groupby("to_account", sort=False):
        incoming = incoming_group.loc[incoming_group["from_account"].astype(str).ne(str(receiver))].sort_values("timestamp", kind="stable").reset_index(drop=True)
        if len(incoming) < minimum_senders:
            continue
        incoming_ns = incoming["timestamp"].astype("int64").to_numpy()
        emitted = False
        for start in range(len(incoming)):
            start_time = pd.Timestamp(incoming.iloc[start]["timestamp"])
            end_position = int(np.searchsorted(incoming_ns, start_time.value + lookback.value, side="right"))
            cohort = incoming.iloc[start:end_position]
            sender_count = int(cohort["from_account"].astype(str).nunique())
            if sender_count < minimum_senders:
                continue
            last_inflow = pd.Timestamp(cohort["timestamp"].max())
            outflow_group = outgoing_groups.get(str(receiver))
            if outflow_group is None:
                continue
            forwarded = outflow_group.loc[outflow_group["timestamp"].between(last_inflow, last_inflow + forward_window, inclusive="both")]
            received_amount = float(cohort["amount"].sum())
            forwarded_amount = float(forwarded["amount"].sum())
            observed_ratio = forwarded_amount / received_amount if received_amount > 0 else 0.0
            if observed_ratio < ratio_required:
                continue
            txn_ids = _ordered_unique([*cohort["txn_id"].tolist(), *forwarded["txn_id"].tolist()])
            elapsed = (last_inflow - start_time).total_seconds() / 3600.0
            findings.append(make_rule_finding(
                "fanin", settings["fanin_points"],
                f"{sender_count} senders transferred ₹{received_amount:,.2f} to {receiver} across {elapsed:.1f}h; ₹{forwarded_amount:,.2f} ({observed_ratio:.1%}) was forwarded within {int(settings['fanin_window_minutes'])} minutes after the last inflow.",
                f"≥{minimum_senders} distinct senders within {float(settings['fanin_lookback_hours']):g}h; ≥{ratio_required:.0%} forwarded within {int(settings['fanin_window_minutes'])}m",
                [receiver, *cohort["from_account"].tolist(), *forwarded["to_account"].tolist()], txn_ids,
                {"sender_count": sender_count, "received_amount": received_amount, "forwarded_amount": forwarded_amount, "forwarded_ratio": observed_ratio, "lookback_hours": float(settings["fanin_lookback_hours"]), "forward_window_minutes": int(settings["fanin_window_minutes"])},
            ))
            emitted = True
            break
        if emitted:
            continue
    return findings
