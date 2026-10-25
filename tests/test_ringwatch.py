from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient

from config import risk_band
from detect import DatasetError, analyze_transactions, compute_coverage, normalize_transactions
from generate_sample import COLUMNS, generate_transactions
from main import app, _state
from pipeline import run_pipeline
from stage2_processing import process_transactions
from stage3_modeling import score_transactions
from stage4_graph import build_graph
from stage5_rings import detect_rings

client = TestClient(app)


def rows_to_frame(rows):
    return pd.DataFrame(rows, columns=pd.Index(COLUMNS))


def row(txn_id, stamp, source, target, amount, *, city="Mumbai", device="device-a", fraud=0):
    timestamp = pd.Timestamp(stamp)
    timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
    return {
        "txn_id": txn_id, "timestamp": timestamp,
        "from_account": source, "to_account": target, "amount": amount,
        "channel": "UPI", "city": city, "device_id": device, "is_fraud": fraud,
    }


def test_sample_is_deterministic_has_required_order_and_planted_patterns():
    first = generate_transactions()
    second = generate_transactions()
    assert first.equals(second)
    assert list(first.columns) == COLUMNS
    assert len(first) == 3030
    checked_in = pd.read_csv(Path(__file__).resolve().parents[1] / "sample_transactions.csv", parse_dates=["timestamp"])
    pd.testing.assert_frame_equal(first.reset_index(drop=True), checked_in.reset_index(drop=True), check_dtype=False, check_exact=False, rtol=1e-9, atol=1e-9)
    assert int((first.is_fraud == 0).sum()) == 3000
    assert len(set(first.from_account) | set(first.to_account)) == 200
    assert first.is_fraud.sum() == 30
    assert first[first.txn_id.str.startswith("FRAUD-STRUCT")].shape[0] == 5
    cycle = first[first.txn_id.str.startswith("FRAUD-CYCLE")]
    assert len(cycle) == 4
    assert (cycle.timestamp.max() - cycle.timestamp.min()) < pd.Timedelta(hours=24)
    mule_in = first[first.txn_id.str.startswith("FRAUD-MULE-IN")]
    mule_out = first[first.txn_id == "FRAUD-MULE-OUT"].iloc[0]
    assert mule_in.from_account.nunique() == 12
    assert mule_out.amount / mule_in.amount.sum() >= 0.90
    assert (mule_out.timestamp - mule_in.timestamp.min()) < pd.Timedelta(hours=1)
    burst = first[first.txn_id.str.startswith("FRAUD-BURST")]
    assert len(burst) == 8
    assert (burst.timestamp.max() - burst.timestamp.min()) < pd.Timedelta(minutes=10)
    assert set(burst.timestamp.dt.hour) == {3}
    assert burst.device_id.nunique() == 1 and burst.device_id.iloc[0] == "DEV-UNSEEN-X9"


def test_ground_truth_never_changes_model_features_or_scores():
    frame = generate_transactions()
    altered = frame.copy()
    altered["is_fraud"] = 1 - altered["is_fraud"]
    original_result = analyze_transactions(frame)
    altered_result = analyze_transactions(altered)
    assert original_result["accounts"] == altered_result["accounts"]
    assert original_result["findings"] == altered_result["findings"]
    assert [case["id"] for case in original_result["cases"]] == [case["id"] for case in altered_result["cases"]]
    assert original_result["transaction_ml_scores"].equals(altered_result["transaction_ml_scores"])
    unlabeled_result = analyze_transactions(frame.drop(columns=["is_fraud"]))
    assert original_result["accounts"] == unlabeled_result["accounts"]
    assert original_result["findings"] == unlabeled_result["findings"]
    assert original_result["transaction_ml_scores"].equals(unlabeled_result["transaction_ml_scores"])
    assert "is_fraud" not in __import__("detect").REQUIRED_COLUMNS


def test_all_six_detection_rules_and_explanations():
    base = pd.Timestamp("2026-04-01T12:00:00Z")
    structuring = rows_to_frame([row(f"s{i}", base + pd.Timedelta(minutes=15 * i), "A", f"T{i}", 48000 + i * 100) for i in range(3)])
    assert "structuring" in {f["rule_id"] for f in analyze_transactions(structuring)["findings"]}

    velocity = rows_to_frame([row(f"v{i}", base + pd.Timedelta(minutes=i), "A", f"T{i}", 500) for i in range(7)])
    assert "velocity" in {f["rule_id"] for f in analyze_transactions(velocity)["findings"]}

    odd_rows = [row(f"o{i}", base + pd.Timedelta(days=i), "A", f"T{i}", 1000) for i in range(12)]
    odd_rows.append(row("odd", pd.Timestamp("2026-04-20T03:12:00Z"), "A", "T-odd", 5000))
    odd_result = analyze_transactions(rows_to_frame(odd_rows))
    assert "odd_hour" in {f["rule_id"] for f in odd_result["findings"]}
    assert any("3:12 AM" in f["explanation"] for f in odd_result["findings"] if f["rule_id"] == "odd_hour")

    new_device = rows_to_frame([
        *[row(f"prior-{i}", base - pd.Timedelta(days=5 - i), "A", f"P{i}", 1000) for i in range(5)],
        row("new", base, "A", "B", 25000, city="New City", device="first-device"),
    ])
    assert "new_signal" in {f["rule_id"] for f in analyze_transactions(new_device)["findings"]}

    cycle_rows = [row("c1", base, "A", "B", 1000), row("c2", base + pd.Timedelta(hours=6), "B", "C", 1000), row("c3", base + pd.Timedelta(hours=12), "C", "A", 1000)]
    assert "circular_flow" in {f["rule_id"] for f in analyze_transactions(rows_to_frame(cycle_rows))["findings"]}

    fanin_rows = [row(f"i{i}", base + pd.Timedelta(minutes=i * 4), f"S{i}", "M", 1000) for i in range(8)]
    fanin_rows.append(row("out", base + pd.Timedelta(minutes=38), "M", "Z", 7000))
    fanin_result = analyze_transactions(rows_to_frame(fanin_rows))
    assert "fanin" in {f["rule_id"] for f in fanin_result["findings"]}
    for finding in fanin_result["findings"]:
        assert finding["rule_id"] and finding["explanation"] and finding["threshold"]
        if finding["source"] == "rule":
            assert finding["points"] > 0
        else:
            assert finding["source"] == "ring" and finding["points"] == 0 and finding["ring_id"]


def test_cycle_edges_outside_window_are_not_flagged():
    start = pd.Timestamp("2026-02-01T00:00:00Z")
    frame = rows_to_frame([
        row("a", start, "A", "B", 1000),
        row("b", start + pd.Timedelta(hours=30), "B", "C", 1000),
        row("c", start + pd.Timedelta(hours=60), "C", "A", 1000),
    ])
    assert "circular_flow" not in {f["rule_id"] for f in analyze_transactions(frame)["findings"]}


def test_isolation_forest_scores_are_finite_and_risk_is_bounded():
    result = analyze_transactions(generate_transactions())
    scores = [item["ml_score"] for item in result["accounts"].values()]
    risks = [item["risk_score"] for item in result["accounts"].values()]
    assert all(pd.notna(score) and 0 <= score <= 100 for score in scores)
    assert all(pd.notna(score) and 0 <= score <= 100 for score in risks)
    assert result["transaction_ml_scores"].between(0, 100).all()


def test_risk_bands_use_the_configured_boundaries():
    assert [risk_band(value) for value in [0, 39, 40, 69, 70, 100]] == ["low", "low", "medium", "medium", "high", "high"]


def test_csv_validation_drops_bad_rows_and_errors_on_missing_columns():
    frame = pd.DataFrame([
        row("good", pd.Timestamp("2026-01-01T00:00:00Z"), "A", "B", 1000),
        {**row("bad-time", pd.Timestamp("2026-01-01T00:00:00Z"), "A", "C", 800), "timestamp": "not a date"},
        {**row("bad-amount", pd.Timestamp("2026-01-01T00:00:00Z"), "A", "D", 900), "amount": -1},
    ])
    normalized, details = normalize_transactions(frame)
    assert len(normalized) == 1
    assert details["dropped_rows"] == 2
    with pytest.raises(DatasetError):
        normalize_transactions(pd.DataFrame({"txn_id": ["x"]}))


def test_case_grouping_and_budget_coverage_with_and_without_ground_truth():
    result = analyze_transactions(generate_transactions())
    ids = [case["id"] for case in result["cases"]]
    assert ids
    assert ids == [case["id"] for case in sorted(result["cases"], key=lambda case: (-case["risk_score"], case["id"]))]
    cycle = next(case for case in result["cases"] if "ACC002" in case["accounts"])
    assert set(["ACC002", "ACC003", "ACC004", "ACC005"]).issubset(cycle["accounts"])
    coverage = compute_coverage(result, 2)
    assert coverage["metric_label"] == "Fraud value caught"
    assert 0 <= coverage["coverage_percent"] <= 100
    assert coverage["reviewed_count"] <= 2

    unlabeled = generate_transactions().drop(columns=["is_fraud"])
    risk_result = analyze_transactions(unlabeled)
    risk_coverage = compute_coverage(risk_result, 5)
    assert risk_coverage["metric_label"].startswith("Risk-score coverage")
    assert risk_coverage["risk_score_coverage_percent"] is not None
    assert risk_coverage["fraudulent_cases_reviewed"] is None


def test_fastapi_sample_upload_cases_graph_case_and_error_paths():
    _state.update({"result": None, "frame": None, "filename": None, "ingestion": None, "settings": __import__("config").default_settings(), "statuses": {}})
    initial_pipeline = client.get("/api/pipeline").json()
    assert initial_pipeline["active"] is False
    assert [stage["status"] for stage in initial_pipeline["stages"]] == ["not_run"] * 6
    sample = client.get("/api/sample")
    assert sample.status_code == 200
    payload = sample.json()
    assert payload["dataset"]["row_count"] == 3030
    assert payload["injected_fraud_rows"] == 30
    assert payload["validation"]["row_accounting_reconciles"] is True
    assert payload["validation"]["rows_received"] == payload["validation"]["rows_rejected"] + payload["validation"]["duplicates_removed"] + payload["validation"]["rows_loaded"]
    assert [stage["status"] for stage in payload["pipeline"]["stages"]] == ["done"] * 6
    pipeline_payload = client.get("/api/pipeline").json()
    assert pipeline_payload["active"] is True and pipeline_payload["validation"]["rows_loaded"] == 3030
    assert len(pipeline_payload["processing"]["transaction_preview"]) <= 15
    assert "risk_score" in pipeline_payload["processing"]["transaction_preview"][0]
    assert "is_fraud" not in pipeline_payload["model"]["features"]
    assert pipeline_payload["model"]["ground_truth_used_for_scoring"] is False
    assert pipeline_payload["graph_stats"]["edge_count"] < 3000
    assert len(pipeline_payload["rings"]) <= pipeline_payload["ring_summary"]["ring_count"]
    assert len(pipeline_payload["model"]["features"]) == 6
    examples = pipeline_payload["model"]["worked_examples"]
    assert len(examples) >= 3 and any(example["capped_at_100"] for example in examples)
    for example in examples:
        assert example["final_risk"] == pytest.approx(min(100, example["rule_points"] + .4 * example["ml_score"]), abs=.06)
    assert all(stage["handoff_text"] and stage["input_count"] is not None and stage["output_count"] is not None for stage in pipeline_payload["stages"])
    assert [stage["name"] for stage in pipeline_payload["stages"]] == ["Transaction ingestion", "Data processing", "Machine learning", "Graph construction", "Ring detection", "Investigation dashboard"]
    assert all("is_fraud" not in transaction for case in payload["cases"] for transaction in case["transactions"])
    case_id = payload["cases"][0]["id"]
    non_csv = client.post("/api/upload", files={"file": ("not-transactions.txt", b"not a csv", "text/plain")})
    assert non_csv.status_code == 400
    empty_upload = client.post("/api/upload", files={"file": ("empty.csv", b"", "text/csv")})
    assert empty_upload.status_code == 400
    assert client.get("/api/status").json()["dataset"]["filename"] == "sample_transactions.csv"

    cases = client.get("/api/cases?budget=5")
    assert cases.status_code == 200 and len(cases.json()["reviewed_cases"]) <= 5
    assert [point["budget"] for point in cases.json()["coverage"]["coverage_curve"]] == list(range(1, cases.json()["coverage"]["total_cases"] + 1))
    graph_response = client.get("/api/graph")
    graph = graph_response.json()
    assert graph_response.status_code == 200 and len(graph["nodes"]) == 200
    assert len(graph["edges"]) == graph["stats"]["edge_count"] < 3000
    assert sum(edge["transaction_count"] for edge in graph["edges"]) == 3030
    assert all("transactions" not in edge and "transaction_ids" not in edge for edge in graph["edges"])
    assert all("risk_score" in edge and "ring_ids" in edge for edge in graph["edges"])
    assert graph["stats"]["component_count"] >= 1 and "directed_density" in graph["stats"]
    unlinked_account = next(node["id"] for node in graph["nodes"] if node["case_id"] is None)
    unlinked_detail = client.get(f"/api/account/{unlinked_account}")
    assert unlinked_detail.status_code == 200
    assert unlinked_detail.json()["account_id"] == unlinked_account
    assert unlinked_detail.json()["case_id"] is None
    cycle_ring = next(ring for ring in graph["rings"] if ring["type"] == "cycle")
    assert cycle_ring["type_label"] == "Circular flow"
    assert any(edge["is_circular"] and cycle_ring["id"] in edge["ring_ids"] for edge in graph["edges"])
    cycle_case = next(case for case in payload["cases"] if cycle_ring["id"] in case["ring_ids"])
    assert set(cycle_ring["accounts"]).issubset(cycle_case["accounts"])
    case_detail = client.get(f"/api/case/{case_id}")
    assert case_detail.status_code == 200 and case_detail.json()["id"] == case_id
    assert "nodes" in case_detail.json()["graph"] and "edges" in case_detail.json()["graph"]
    account_id = case_detail.json()["accounts"][0]
    account_detail = client.get(f"/api/account/{account_id}")
    assert account_detail.status_code == 200 and account_detail.json()["account_id"] == account_id
    assert all("is_fraud" not in transaction for transaction in account_detail.json()["transactions"])
    transaction_features = client.get("/api/features?kind=transactions&offset=0&limit=10").json()
    account_features = client.get("/api/features?kind=accounts&offset=0&limit=10").json()
    assert transaction_features["total"] == 3030 and "is_fraud" not in transaction_features["columns"]
    assert account_features["total"] == 200 and account_features["rows"]
    assert client.get("/api/features?kind=transactions&sort_by=is_fraud").status_code == 422
    assert client.get("/api/case/unknown").status_code == 404

    status = client.put(f"/api/case/{case_id}/status", json={"status": "confirmed"})
    assert status.status_code == 200 and status.json()["status"] == "Confirmed"
    assert client.get(f"/api/case/{case_id}").json()["status"] == "Confirmed"
    assert client.get("/api/status").json()["summary"]["status_counts"]["Confirmed"] == 1
    other_case_ids = [item["id"] for item in payload["cases"] if item["id"] != case_id][:2]
    for case_id_to_update, requested, displayed in zip(
        other_case_ids, ("false_positive", "escalated"), ("Marked as false positive", "Escalated")
    ):
        posted = client.post(f"/api/case/{case_id_to_update}/status", json={"status": requested})
        assert posted.status_code == 200 and posted.json()["status"] == displayed
    status_counts = client.get("/api/status").json()["summary"]["status_counts"]
    assert status_counts["Confirmed"] == status_counts["Marked as false positive"] == status_counts["Escalated"] == 1

    good_csv = "txn_id,timestamp,from_account,to_account,amount,channel,city,device_id\nu1,2026-01-01T12:00:00Z,A,B,300,UPI,Mumbai,d1\nu2,2026-01-01T12:02:00Z,A,C,350,UPI,Mumbai,d1\n"
    upload = client.post("/api/upload", files={"file": ("mini.csv", good_csv, "text/csv")})
    assert upload.status_code == 200
    assert upload.json()["dataset"]["filename"] == "mini.csv"
    assert not upload.json()["dataset"]["has_ground_truth"]
    assert upload.json()["coverage"]["metric_label"].startswith("Risk-score coverage")
    assert "cycle_min_accounts" in client.get("/api/settings").json()["bounds"]
    assert client.get("/api/cases").status_code == 200
    assert client.get("/api/graph").json()["nodes"]
    assert all("is_fraud" not in row for row in client.get("/api/features?kind=transactions").json()["rows"])
    malformed_csv = "txn_id,timestamp,from_account,to_account,amount,channel,city,device_id\nm1,2026-01-01T12:00:00Z,A,B,300,UPI,Mumbai,d1,EXTRA\nm2,2026-01-01T12:02:00Z,A,C,350,UPI,Mumbai,d1\n"
    malformed = client.post("/api/upload", files={"file": ("malformed.csv", malformed_csv, "text/csv")})
    assert malformed.status_code == 200
    assert malformed.json()["validation"]["malformed_rows_dropped"] == 1
    assert malformed.json()["validation"]["dropped_rows"] == 1
    assert malformed.json()["validation"]["row_accounting_reconciles"] is True
    assert "Rejected 1 row" in malformed.json()["message"]
    rejected_csv = client.get("/api/download/rejected")
    assert rejected_csv.status_code == 200 and "malformed_width" in rejected_csv.text
    processed_csv = client.get("/api/download/processed")
    assert processed_csv.status_code == 200 and "risk_score" in processed_csv.text
    invalid = client.post("/api/upload", files={"file": ("bad.csv", "wrong,header\n1,x\n", "text/csv")})
    assert invalid.status_code == 400
    detail = invalid.json()["detail"]
    assert detail["code"] == "missing_columns"
    assert all(column in detail["message"] for column in COLUMNS[:-1])
    active = client.get("/api/status").json()
    assert active["dataset"]["filename"] == "malformed.csv" and active["dataset"]["row_count"] == 1
    assert client.get("/api/download/sample").status_code == 200
    settings_before_clear = client.get("/api/config").json()["settings"]
    cleared = client.delete("/api/data")
    assert cleared.status_code == 200 and cleared.json()["settings_preserved"] is True
    assert client.get("/api/status").json()["dataset_loaded"] is False
    assert client.get("/api/graph").status_code == 409
    assert client.get("/api/features").status_code == 409
    assert client.get("/api/config").json()["settings"] == settings_before_clear


def test_settings_are_validated_and_affect_reruns():
    defaults = client.get("/api/settings").json()["defaults"]
    bounds = client.get("/api/settings").json()["bounds"]
    assert defaults["structuring_threshold"] == 50000
    assert bounds["cycle_max_accounts"] == [3, 5]
    too_long = client.put("/api/settings", json={"settings": {"cycle_max_accounts": 6}})
    assert too_long.status_code == 422
    invalid = client.put("/api/settings", json={"settings": {"cycle_min_accounts": 5, "cycle_max_accounts": 3}})
    assert invalid.status_code == 422
    valid = client.put("/api/settings", json={"settings": {"cycle_points": 44}})
    assert valid.status_code == 200
    assert valid.json()["settings"]["cycle_points"] == 44


def test_stage2_normalizes_deduplicates_and_engineers_features():
    base = pd.Timestamp("2026-05-01T12:00:00Z")
    accepted = row("clean-1", base, " acct-a ", "acct-b", 48000)
    source = rows_to_frame([
        accepted,
        {**accepted, "is_fraud": 1},
        row("clean-1", base + pd.Timedelta(minutes=1), "acct-a", "acct-c", 49000),
        row("self", base + pd.Timedelta(hours=1), "acct-m", "acct-m", 900),
        {**row("invalid", base + pd.Timedelta(hours=2), "acct-a", "acct-d", 800), "amount": "not-a-number"},
        {**row("blank", base + pd.Timedelta(hours=3), "acct-a", "acct-e", 800), "city": " "},
    ])
    processed = process_transactions(source)
    data = processed["data"]
    report = processed["validation"]
    assert report["rows_received"] == 6 and report["rows_loaded"] == 1
    assert report["rows_rejected"] == 4
    assert report["duplicate_rows_dropped"] == 1 and report["invalid_rows_dropped"] == 4
    assert report["rejected_by_reason"]["conflicting_txn_id"] == 1
    assert report["rejected_by_reason"]["self_transfer"] == 1
    assert report["rejected_by_reason"]["missing_required_value"] == 1
    assert report["row_accounting_reconciles"] is True
    assert data.iloc[0]["from_account"] == "ACCT-A"
    assert data.iloc[0]["timestamp"].tz is not None
    assert data.iloc[0]["channel"] == "UPI"
    assert data["txn_id"].tolist() == ["clean-1"]
    assert not data["is_self_transfer"].any()
    assert report["self_transfers_rejected"] == 1
    assert report["self_transfers_flagged"] == 0
    assert {"time_since_previous_hours", "sender_txn_count_1h", "sender_txn_count_24h", "sender_in_degree", "sender_out_degree", "sender_device_count", "sender_city_count", "amount_near_threshold", "rapid_in_out_movement"}.issubset(processed["feature_names"])
    assert "is_fraud" not in processed["feature_names"]
    account_a = processed["account_features"].set_index("account_id").loc["ACCT-A"]
    assert account_a["out_transaction_count"] == 1 and account_a["out_degree"] == 1


def test_stage4_aggregates_each_directed_pair_once_with_time_and_risk():
    start = pd.Timestamp("2026-05-02T10:00:00Z")
    result = run_pipeline(rows_to_frame([
        row("ab-1", start, "A", "B", 100),
        row("ab-2", start + pd.Timedelta(minutes=3), "A", "B", 200),
        row("ba-1", start + pd.Timedelta(minutes=6), "B", "A", 50),
    ]))
    edges = result["graph_result"]["edges"]
    assert len(edges) == 2
    forward = next(edge for edge in edges if edge["from"] == "A")
    reverse = next(edge for edge in edges if edge["from"] == "B")
    assert forward["to"] == "B" and forward["transaction_count"] == 2
    assert forward["weight"] == forward["total_amount"] == 300
    assert forward["first_timestamp"].endswith("10:00:00+00:00")
    assert forward["last_timestamp"].endswith("10:03:00+00:00")
    assert 0 <= forward["risk_score"] <= 100 and 0 <= forward["mean_transaction_risk_score"] <= 100
    assert reverse["transaction_count"] == 1
    assert result["graph_result"]["stats"]["node_count"] == 2
    assert result["graph_result"]["stats"]["component_count"] == 1
    assert result["graph_result"]["stats"]["directed_density"] == 1.0


def test_stage5_fan_in_fan_out_and_louvain_community_rings():
    base = pd.Timestamp("2026-05-03T12:00:00Z")
    fan_rows = [row(f"out-{index}", base + pd.Timedelta(minutes=index), "HUB-OUT", f"R{index}", 1000) for index in range(8)]
    fan_rows.extend(row(f"in-{index}", base + pd.Timedelta(minutes=10 + index), f"S{index}", "HUB-IN", 1000) for index in range(8))
    fan_rows.append(row("fan-forward", base + pd.Timedelta(minutes=25), "HUB-IN", "DEST", 9000))
    fan_result = run_pipeline(rows_to_frame(fan_rows))
    fan_rings = fan_result["rings"]
    fan_types = {ring["type"] for ring in fan_rings}
    assert {"fan_in", "fan_out"}.issubset(fan_types)
    fan_out = next(ring for ring in fan_rings if ring["type"] == "fan_out")
    assert fan_out["hub_account"] == "HUB-OUT" and len(fan_out["accounts"]) == 9
    assert fan_out["cycle_length"] is None and fan_out["risk_score"] <= 100
    assert fan_out["id"].startswith("RW-RING-")
    assert [ring["id"] for ring in fan_rings] == [ring["id"] for ring in run_pipeline(rows_to_frame(fan_rows))["rings"]]

    accounts = [f"C{index}" for index in range(6)]
    clique_rows = [
        row(f"edge-{source}-{target}", base + pd.Timedelta(seconds=index), accounts[source], accounts[target], 1000)
        for index, (source, target) in enumerate((source, target) for source in range(6) for target in range(6) if source != target)
    ]
    processed = process_transactions(rows_to_frame(clique_rows))
    scored = score_transactions(processed)
    graph = build_graph(scored["data"], scored["accounts"], processed["account_features"])
    community_result = detect_rings(graph, scored["data"], scored["accounts"], [], scored["settings"])
    community = next(ring for ring in community_result["rings"] if ring["type"] == "community")
    assert len(community["accounts"]) >= 3 and community["density"] >= 0.35
    assert community["transaction_count"] == 30 and community["total_value"] == 30000
    assert community["score_basis"].startswith("Maximum attached Stage 3")


def test_each_detection_rule_stays_quiet_on_its_near_miss():
    base = pd.Timestamp("2026-08-01T12:00:00Z")
    cases = {
        "structuring": rows_to_frame([row(f"s{i}", base + pd.Timedelta(minutes=20 * i), "A", f"T{i}", 48000) for i in range(2)]),
        "velocity": rows_to_frame([row(f"v{i}", base + pd.Timedelta(minutes=i), "A", f"V{i}", 500) for i in range(6)]),
        "odd_hour": rows_to_frame([
            *[row(f"day-{i}", base + pd.Timedelta(days=i), "A", f"D{i}", 1000) for i in range(12)],
            row("small-odd", pd.Timestamp("2026-08-20T03:12:00Z"), "A", "NIGHT", 2900),
        ]),
        "new_signal": rows_to_frame([
            *[row(f"prior-{i}", base - pd.Timedelta(days=4 - i), "A", f"P{i}", 1000) for i in range(4)],
            row("only-four-priors", base, "A", "NEW", 25000, city="New City", device="new-device"),
        ]),
        "circular_flow": rows_to_frame([
            row("cycle-a", base, "A", "B", 1000),
            row("cycle-b", base + pd.Timedelta(hours=30), "B", "C", 1000),
            row("cycle-c", base + pd.Timedelta(hours=60), "C", "A", 1000),
        ]),
        "fanin": rows_to_frame([
            *[row(f"sender-{i}", base + pd.Timedelta(minutes=i * 4), f"S{i}", "M", 1000) for i in range(7)],
            row("forward", base + pd.Timedelta(minutes=35), "M", "DEST", 7000),
        ]),
    }
    for rule_id, frame in cases.items():
        findings = analyze_transactions(frame)["findings"]
        assert rule_id not in {finding["rule_id"] for finding in findings}, f"{rule_id} fired on a near-miss"


def test_detection_rules_expose_explanations_and_configurable_fixed_model_contract():
    from config import DEFAULT_SETTINGS, MODEL_CONFIG

    assert DEFAULT_SETTINGS["structuring_points"] == 45
    assert DEFAULT_SETTINGS["velocity_points"] == 30
    assert DEFAULT_SETTINGS["odd_hour_points"] == 25
    assert DEFAULT_SETTINGS["new_signal_points"] == 20
    assert DEFAULT_SETTINGS["cycle_points"] == 50
    assert DEFAULT_SETTINGS["fanin_points"] == 50
    assert MODEL_CONFIG["features"] == [
        "amount_vs_account_avg", "txn_count_1h", "txn_count_24h",
        "hour_of_day", "distinct_counterparties", "seconds_since_prev_txn",
    ]
    assert MODEL_CONFIG["n_estimators"] == 200 and MODEL_CONFIG["random_state"] == 42
    assert MODEL_CONFIG["ml_weight"] == .4


def test_stage1_rejects_empty_unparseable_oversized_and_over_row_limit_files():
    from config import MAX_UPLOAD_BYTES, MAX_UPLOAD_ROWS
    from stage1_ingestion import DatasetError, ingest_csv_bytes, ingest_frame

    with pytest.raises(DatasetError) as empty:
        ingest_csv_bytes(b"")
    assert empty.value.code == "empty_csv"
    with pytest.raises(DatasetError) as malformed:
        ingest_csv_bytes(b"\xff\xfe\x00")
    assert malformed.value.code == "unparseable_csv"
    with pytest.raises(DatasetError) as oversized:
        ingest_csv_bytes(b"x" * (MAX_UPLOAD_BYTES + 1))
    assert oversized.value.code == "file_too_large"
    too_many = pd.DataFrame({"txn_id": range(MAX_UPLOAD_ROWS + 1)})
    with pytest.raises(DatasetError) as row_limit:
        ingest_frame(too_many)
    assert row_limit.value.code == "row_limit"


def test_pipeline_failure_marks_exact_stage_and_stops_later_stages(monkeypatch):
    import pipeline

    calls = []

    def fail_processing(frame, settings, ingestion):
        calls.append("processing")
        raise RuntimeError("deliberate Stage 2 failure")

    monkeypatch.setattr(pipeline, "_process_stage", fail_processing)
    with pytest.raises(RuntimeError, match="deliberate Stage 2 failure") as raised:
        pipeline.run_pipeline(rows_to_frame([row("failure", "2026-01-01T12:00:00Z", "A", "B", 500)]))

    report = getattr(raised.value, "pipeline_report")
    assert report["status"] == "failed" and report["failed_stage"] == "processing"
    assert calls == ["processing"]
    assert [stage["status"] for stage in report["stages"]] == ["done", "failed", "not_run", "not_run", "not_run", "not_run"]
    assert report["stages"][1]["error"]["message"] == "deliberate Stage 2 failure"
