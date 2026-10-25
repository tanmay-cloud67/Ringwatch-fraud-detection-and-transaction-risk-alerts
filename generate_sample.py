"""Generate deterministic synthetic normal activity and four labelled demo patterns."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pandas as pd

COLUMNS = ["txn_id", "timestamp", "from_account", "to_account", "amount", "channel", "city", "device_id", "is_fraud"]
INJECTED_FRAUD_ROWS = 30
DEFAULT_NORMAL_ROWS = 3_000


def generate_transactions(seed: int = 42, total_rows: int = DEFAULT_NORMAL_ROWS + INJECTED_FRAUD_ROWS, *, normal_rows: int | None = None) -> pd.DataFrame:
    """Return total_rows rows, of which exactly 30 are planted fraud patterns by default.

    Pass normal_rows to request an exact clean baseline; total_rows remains available for
    compatibility with callers that historically requested a final output row count.
    """
    if normal_rows is None:
        normal_rows = int(total_rows) - INJECTED_FRAUD_ROWS
    if normal_rows < 100:
        raise ValueError("normal_rows must be at least 100")
    if int(total_rows) != int(normal_rows) + INJECTED_FRAUD_ROWS and total_rows != DEFAULT_NORMAL_ROWS + INJECTED_FRAUD_ROWS:
        raise ValueError("total_rows must equal normal_rows plus the 30 injected pattern rows")
    rng = np.random.default_rng(seed)
    accounts = [f"ACC{i:03d}" for i in range(1, 201)]
    normal_accounts = [f"ACC{i:03d}" for i in range(29, 201)]
    cities = ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Pune", "Kolkata", "Ahmedabad", "Jaipur", "Kochi"]
    channels = ["UPI", "IMPS", "NEFT", "Card", "Wallet"]
    base = datetime(2026, 9, 1, tzinfo=timezone.utc)
    records: list[dict[str, object]] = []
    account_device = {account: f"DEV-{index:03d}-A" for index, account in enumerate(accounts, start=1)}
    account_city = {account: cities[(index * 7) % len(cities)] for index, account in enumerate(accounts)}

    # Benign histories supply stable sender baselines for the injected odd-hour/new-context patterns.
    history: list[tuple[str, str, datetime, float, str]] = []
    for index in range(5):
        stamp = base + timedelta(days=3 + index * 8, hours=12)
        history.append(("ACC001", f"ACC{101 + index:03d}", stamp, round(float(rng.uniform(2_500, 8_000)), 2), "NEFT"))
    for index in range(30):
        stamp = base + timedelta(days=1 + index * 2, hours=12)
        history.append(("ACC020", "ACC021", stamp, round(float(rng.uniform(450, 1_200)), 2), "UPI"))
    history.append(("ACC006", "ACC019", base + timedelta(days=80, hours=13), 1_000.0, "UPI"))
    for index, (sender, receiver, stamp, amount, channel) in enumerate(history, start=1):
        records.append({
            "txn_id": f"NORMAL-HIST-{index:02d}", "timestamp": stamp,
            "from_account": sender, "to_account": receiver, "amount": amount,
            "channel": channel, "city": account_city[sender], "device_id": account_device[sender], "is_fraud": 0,
        })

    # The clean baseline uses a sparse acyclic account ordering and each sender's usual city/device.
    random_normal_count = int(normal_rows) - len(history)
    for index in range(random_normal_count):
        sender_index = int(rng.integers(0, len(normal_accounts) - 1))
        sender = normal_accounts[sender_index]
        receiver = normal_accounts[int(rng.integers(sender_index + 1, len(normal_accounts)))]
        day = int(rng.integers(0, 90))
        seconds = int(rng.integers(0, 86_400))
        stamp = base + timedelta(days=day, seconds=seconds)
        amount = round(float(np.clip(rng.lognormal(mean=8.35, sigma=0.72), 150, 18_000)), 2)
        records.append({
            "txn_id": f"TXN-{index + 1:05d}", "timestamp": stamp,
            "from_account": sender, "to_account": receiver, "amount": amount,
            "channel": str(rng.choice(channels)), "city": account_city[sender],
            "device_id": account_device[sender], "is_fraud": 0,
        })

    # Pattern A: five transfers just below the configured limit inside two hours.
    struct_sender = "ACC001"
    struct_base = base + timedelta(days=91, hours=13)
    for index, minute in enumerate([0, 17, 39, 66, 101]):
        records.append({
            "txn_id": f"FRAUD-STRUCT-{index + 1}", "timestamp": struct_base + timedelta(minutes=minute),
            "from_account": struct_sender, "to_account": f"ACC{101 + index:03d}",
            "amount": round(float(rng.uniform(47_000, 49_500)), 2), "channel": "NEFT",
            "city": account_city[struct_sender], "device_id": account_device[struct_sender], "is_fraud": 1,
        })

    # Pattern B: a near-equal A→B→C→D→A cycle inside 24 hours.
    cycle_accounts = ["ACC002", "ACC003", "ACC004", "ACC005"]
    cycle_base = base + timedelta(days=92, hours=10)
    for index, source in enumerate(cycle_accounts):
        target = cycle_accounts[(index + 1) % len(cycle_accounts)]
        records.append({
            "txn_id": f"FRAUD-CYCLE-{index + 1}", "timestamp": cycle_base + timedelta(hours=index * 3),
            "from_account": source, "to_account": target, "amount": 11_800.0 + float(index * 25),
            "channel": "IMPS", "city": account_city[source], "device_id": account_device[source], "is_fraud": 1,
        })

    # Pattern C: 12 senders funnel value into one account; 94% is forwarded within one hour.
    mule = "ACC006"
    mule_base = base + timedelta(days=93, hours=14)
    inbound_total = 0.0
    for index in range(12):
        sender = f"ACC{7 + index:03d}"
        amount = 10_000.0 + index * 350
        inbound_total += amount
        records.append({
            "txn_id": f"FRAUD-MULE-IN-{index + 1:02d}", "timestamp": mule_base + timedelta(minutes=index * 2),
            "from_account": sender, "to_account": mule, "amount": amount, "channel": "UPI",
            "city": account_city[sender], "device_id": account_device[sender], "is_fraud": 1,
        })
    records.append({
        "txn_id": "FRAUD-MULE-OUT", "timestamp": mule_base + timedelta(minutes=33),
        "from_account": mule, "to_account": "ACC019", "amount": round(inbound_total * 0.94, 2),
        "channel": "IMPS", "city": account_city[mule], "device_id": account_device[mule], "is_fraud": 1,
    })

    # Pattern D: eight transactions in ten minutes around 3AM from a new city and device.
    burst_sender = "ACC020"
    burst_base = base + timedelta(days=94, hours=3, minutes=12)
    for index in range(8):
        records.append({
            "txn_id": f"FRAUD-BURST-{index + 1}", "timestamp": burst_base + timedelta(minutes=index),
            "from_account": burst_sender, "to_account": f"ACC{21 + index:03d}",
            "amount": round(float(rng.uniform(26_000, 31_000)), 2), "channel": "Wallet",
            "city": "Reykjavik", "device_id": "DEV-UNSEEN-X9", "is_fraud": 1,
        })

    expected_total = int(normal_rows) + INJECTED_FRAUD_ROWS
    data = pd.DataFrame.from_records(records).reindex(columns=pd.Index(COLUMNS))
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    # Stable timestamp sort preserves source order for ties; transaction ID and labels never rank activity.
    data = data.sort_values("timestamp", kind="stable").reset_index(drop=True)
    if len(data) != expected_total:
        raise AssertionError(f"Expected {expected_total} rows; generated {len(data)}")
    if len(set(data["from_account"]) | set(data["to_account"])) != 200:
        raise AssertionError("The generated sample must use all 200 accounts.")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="sample_transactions.csv")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--normal-rows", type=int, default=DEFAULT_NORMAL_ROWS)
    args = parser.parse_args()
    frame = generate_transactions(seed=args.seed, normal_rows=args.normal_rows)
    output = Path(args.output)
    frame.to_csv(output, index=False, date_format="%Y-%m-%dT%H:%M:%SZ")
    injected = int(frame["is_fraud"].eq(1).sum())
    print(f"Wrote {len(frame):,} rows ({len(frame) - injected:,} normal; {injected:,} injected) across {len(set(frame['from_account']) | set(frame['to_account']))} accounts to {output}")


if __name__ == "__main__":
    main()
