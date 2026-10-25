You are updating my EXISTING project "RingWatch" (live at https://ringwatch-ezeykhtk.manus.space). Do NOT rebuild from scratch and do NOT break features that already work. First audit the current project against this spec, list what is missing or wrong, then fix everything, then test, then give me an evidence-based report. Never mark anything "pass" unless you actually ran it.

=== 1. PURPOSE ===
RingWatch is a fraud and transaction-risk website for a finance hackathon (problem F-01). It shows CONNECTIONS between accounts, not just alerts. The user uploads a transaction CSV or clicks "Load sample data". RingWatch scores every transaction, groups suspicious ones into cases (one fraud ring = one alert, not twenty), draws accounts as a network graph, and explains every alert in plain English. An "alert budget" slider sets how many cases the investigator can review per day and shows how much fraud value that budget catches.
Three differentiators: (1) Connections, not just alerts; (2) Alert budget; (3) Explainability a non-technical person can read.
RingWatch supports investigators. It never blocks transactions or makes final decisions.

=== 2. STACK AND CONSTRAINTS ===
- Preferred: Python FastAPI + pandas + scikit-learn IsolationForest + networkx, with a single-page frontend (vanilla JS, Tailwind, vis-network, Chart.js). If the project currently runs on another runtime (e.g. Node/TypeScript) and switching would break deployment, KEEP it and port faithfully: implement a seeded Isolation Forest natively (random_state/seed 42, 200 trees, documented), and state in the README exactly which parts differ from the Python design and why.
- No database, no paid or external APIs. All state is held IN MEMORY only (per session/server), is lost on restart/redeploy, and the UI says so honestly. Add a "Clear data" button.
- All JS/CSS libraries must be bundled locally (no CDN dependency) so the demo works if Wi-Fi fails.
- All thresholds live in ONE config module/file (config.py or config.ts) and are editable from the UI Settings panel.
- Deterministic: fixed random seed 42 everywhere (sample generation and Isolation Forest).

=== 3. WORKFLOW (the 6 pipeline stages; the UI Pipeline view must show these exactly) ===
1) Transaction ingestion  2) Data processing  3) Machine learning  4) Graph construction  5) Ring detection  6) Investigation dashboard
Each stage shows a status (Not run / Running / Done / Failed), duration, input count -> output count, and proof of hand-off, e.g. "Stage 2 received 2,987 rows from Stage 1". Each stage must literally consume the previous stage's output (no recomputing from the raw file in later stages). A failure in a stage shows the error and stops the later stages.

=== 4. DATA FORMAT AND INGESTION ===
Required columns (exact names): txn_id, timestamp, from_account, to_account, amount, channel, city, device_id. Optional: is_fraud (0/1) used ONLY for evaluation, never as a model input, rule input, feature or sort key.
Validation:
- File-level rejection (HTTP 400 + clear on-screen message, previous dataset left untouched): missing required column(s) -> message lists exactly which columns are missing; empty file; unparseable file; non-CSV; over size limit (20 MB / 100,000 rows).
- Row-level rejection (row dropped, counted by reason, rejected rows downloadable as CSV): missing/blank required value, unparseable timestamp, amount not a positive number, from_account == to_account.
- Duplicate policy: exact duplicate rows (all 8 columns equal) -> keep first, drop the rest, count as "duplicates removed". Same txn_id but different content -> keep first, reject later ones with reason "conflicting txn_id". Show this policy as text in the UI.
- Show a Data Quality panel with: raw rows, rejected rows (with reason breakdown), duplicates removed, processed rows, and the check raw = rejected + duplicates + processed (show a green tick or a red warning).
Parse timestamps to a consistent timezone and sort by time.

=== 5. SAMPLE DATA (button "Load sample data" + "Download sample_transactions.csv") ===
Generate deterministically (seed 42): ~3,000 normal transactions across 200 accounts (realistic amounts, channels, cities, devices; each account mostly uses 1-2 devices and 1-2 cities), then inject four fraud patterns, all with is_fraud=1:
(1) Structuring: one account sends 5 transfers of Rs 47,000-49,500 within 2 hours.
(2) Circular ring: A->B->C->D->A with near-equal amounts within 24 hours.
(3) Mule fan-in: 12 accounts send money to one account, which forwards ~90% of it within 1 hour.
(4) Odd-hours burst: 8 transactions within 10 minutes at about 3 AM from a new city/device.
Show how many fraud transactions were injected. Include the generator in the repo (generate_sample) and keep the output identical on every run.

=== 6. DATA PROCESSING (Stage 2) ===
Produce and display (paginated, sortable, with "Download processed CSV"):
Transaction features: txn_id, timestamp, from/to, amount, amount_vs_account_avg, txn_count_1h, txn_count_24h, hour_of_day, distinct_counterparties, seconds_since_prev_txn, rule_points, matched_rules, ml_score, final_risk, reasons.
Account features: account_id, txn_count, in_degree, out_degree, total_in, total_out, avg_amount, distinct_counterparties, first_seen, last_seen, max_risk, case_id.
The previews on the Dashboard must show real rows after processing.

=== 7. DETECTION RULES (thresholds in config; every rule returns points + a plain-English reason; matched transactions get the points and reason) ===
Default points are config values: structuring 45, velocity 30, odd_hours 25, new_device_city 20, circular_flow 50, fan_in_pass_through 50.
1. Structuring: >=3 transfers from one account within 2 hours, each between 90% and 99% of the Rs 50,000 limit. Reason e.g. "5 transfers just under Rs 50,000 in 2 hours".
2. Velocity: more than 6 transactions in 10 minutes from one account. Reason e.g. "8 transactions in 10 minutes".
3. Odd hours: between 1 AM and 5 AM AND amount >= 3x the account's average (average of that account's other sent transactions). Reason e.g. "Large transfer at 3:12 AM".
4. New device or city: first time this device_id or city is seen for the sending account (only if the account already has >=5 earlier transactions) AND amount above a threshold (default Rs 20,000). Reason e.g. "First transfer from a new device".
5. Circular flow: cycle of length 3 to 5 in the directed account graph (networkx simple_cycles with length_bound=5, or an equivalent bounded DFS), where the cycle's transactions fall within a 48-hour window. Ignore self-loops and 2-cycles. Reason e.g. "Money returned to its source through 3 accounts". Draw these in RED on the graph.
6. Fan-in with pass-through: >=8 distinct senders into one account AND >=80% of the received amount sent out within 1 hour. Reason e.g. "12 accounts funnelled money into one account that forwarded it".
Each reason must be readable by a non-technical person and include the evidence numbers and the threshold used.

=== 8. MACHINE LEARNING AND COMBINED SCORE ===
- Isolation Forest per transaction, features: amount compared with the account's average, transactions in last 1h, transactions in last 24h, hour of day, number of distinct counterparties, time since the account's previous transaction. NEVER use is_fraud, txn_id or labels.
- Scale the anomaly score to 0-100 (higher = more unusual). State clearly in the UI that it is a relative anomaly signal for this dataset, NOT a fraud probability.
- Final score: final_risk = min(100, rule_points + 0.4 * ml_score). Show this formula in the Machine learning stage panel with a live worked example from a real transaction, and in case detail show for each top transaction: rule_points, ml_score, 0.4*ml_score, capped final_risk.
- Flag a transaction when final_risk >= 40 (config). Risk levels (config): High >= 70, Medium 40-69, Low < 40.
- Show the top reasons attached to each score.

=== 9. GRAPH CONSTRUCTION AND RING DETECTION (Stages 4-5) ===
- Build a directed graph: nodes = accounts, edges = aggregated transfers per account pair (count, total amount, first/last time, max risk).
- Show graph metrics: node count, edge count, ring count.
- Ring table columns: Ring ID, Type (Circular / Mule fan-in; add "Dense community" ONLY if you really implement it, otherwise remove that wording everywhere), Accounts, Transfers, Value, Risk, Reason. Each row links to its case and highlights it on the graph.

=== 10. CASES ===
- Group flagged transactions into cases: build an account graph from flagged transactions; each weakly connected component = one case. Case score = highest account risk in the case. Case value = sum of flagged amounts. Each case has: ID, risk level, score, accounts, transactions, value, reasons list, status.
- Show on the dashboard "X flagged transactions -> Y cases" (this is the demo's key moment).
- Case detail screen: timeline of the case's transactions, plain-English reasons, score breakdown, and buttons Confirm fraud / False positive / Escalate. Buttons update the case status on screen immediately, show a status chip, and update a KPI counter (in memory is fine).

=== 11. ALERT BUDGET AND COVERAGE ===
- Slider N = cases the investigator can review per day (1 .. total cases). Cases are sorted by score; the top N are reviewed.
- If is_fraud exists: report (a) fraud value caught % = amount of is_fraud=1 transactions inside the top-N cases / total is_fraud amount; (b) precision = reviewed cases containing at least one fraud transaction / N, and false alarms = N minus that. Chart: x = alerts reviewed, y = % fraud value caught, with a diagonal "random review" baseline. is_fraud is used only here.
- If is_fraud is absent: show "share of total risk score covered" instead (x = alerts reviewed, y = % of total flagged risk score), and label the chart accordingly.
- Slider, ranked case list ("Showing top N of M"), KPIs and chart update together live.

=== 12. NETWORK GRAPH (the showpiece) ===
Node size = transaction volume; node colour = risk; edge thickness = amount; arrows show direction; circular transfers in RED; clicking a node opens a side panel with that account's risk, reasons and transactions; a toggle "Show only flagged accounts"; zoom/pan; legend; click a ring in the table to focus it. Works offline (local vis-network).

=== 13. API (must exist at these exact paths, return JSON, and be documented in the README/Settings page) ===
GET /api/sample  - load built-in sample and run the full pipeline
POST /api/upload - multipart CSV upload, run the pipeline, 400 with clear message for bad files
GET /api/cases?budget=N - ranked cases limited to top N, plus coverage numbers (fraud value caught %, precision or risk-covered %) and the full coverage curve
GET /api/graph - nodes (accounts) and edges (transfers) with risk values and cycle flags
GET /api/case/{id} - case detail with reasons, score breakdown and its transactions
Extra (recommended): GET /api/status (pipeline stage statuses + row counts), GET /api/features (processed transaction/account features), GET /api/config and PUT /api/config (thresholds), POST /api/case/{id}/status. Return a clear 409/empty-state message if no dataset is loaded.

=== 14. SCREENS ===
Home/Dashboard: Load sample data, Upload CSV (drag-and-drop), dataset status (fix or remove the stray "Present" label), KPI cards (transactions analysed, flagged transactions, cases found, amount at risk), alert budget slider, ranked cases, coverage chart, ML panel, graph metrics, feature previews, rings table.
Pipeline: the 6 stages with status and hand-offs. Network: graph. Cases: list + case detail. Settings: (a) editable thresholds with "Apply and re-run" and "Reset to defaults"; (b) a SEPARATE "Assumptions and limitations" section (do not merge it into the same anchor), (c) API reference, (d) in-memory behaviour note.
Plain-English reasons must be visible on every screen where a score appears. Empty states must be friendly, and all errors human-readable. Responsive and polished (dark theme is fine).

=== 15. ASSUMPTIONS AND LIMITATIONS (show in the app, exact points) ===
- The sample data is synthetic and the fraud patterns are simplified.
- Thresholds such as Rs 50,000 are examples and can be changed in settings.
- The model has not been validated on real bank data.
- RingWatch supports investigators. It does not block transactions or make final decisions.
Also state: data is held in memory only and is lost on restart; ML scores are relative anomaly signals, not fraud probabilities.

=== 16. DOCS AND REPO EXTRAS ===
README (also viewable in-app): what it does, stack, one-command local run (uvicorn main:app for Python, or the equivalent for the current stack), folder structure, config reference, API reference with curl examples, how scoring works, the 3-minute demo script (load sample -> flagged txns vs grouped cases -> drag budget slider and show coverage chart -> open graph and click the red ring -> read the plain-English reasons -> finish on assumptions), and any differences from the Python reference design. Include an automated test script (tests/) covering the acceptance tests below.

=== 17. ACCEPTANCE TESTS (run each one for real; I will check your evidence) ===
Data ingestion
 A. Load sample data works (state the row count).
 B. Upload a valid CSV works.
 C. Upload a CSV missing required columns is REJECTED with a message naming the missing columns, and the previous dataset is unchanged.
Data processing
 D. Processed transaction features and account features are inspectable in the UI and via API.
 E. raw = rejected + duplicates + processed holds; show the numbers.
 F. Exact duplicates and repeated txn_ids follow the stated policy (test with a crafted CSV).
Detection and scoring
 G. Each of the 6 rules fires on its own crafted test case AND does not fire on a near-miss case (e.g. 2 transfers instead of 3, 6 transactions instead of 7, cycle outside the 48h window, 7 senders instead of 8).
 H. Isolation Forest runs on the 6 listed features; show a worked example proving final_risk = min(100, rule_points + 0.4*ml_score) for at least 3 transactions including one that hits the cap of 100.
 I. is_fraud is evaluation-only: removing the column does not change any score, case or rule result; only the coverage chart switches to the risk-covered variant. Also prove that changing is_fraud values does not change scores.
Graph and investigation
 J. The injected circular ring appears as a RED cycle in Network and as a Circular row in the rings table; click-through to the case works.
 K. Cases are grouped (one ring = one case), risk levels and plain-English reasons are correct.
 L. Budget slider, coverage chart and Confirm/False positive/Escalate actions work and update the screen.
Backend and reliability
 M. Every endpoint in section 13 returns the right JSON (show curl output for each).
 N. Each pipeline stage consumes the previous stage's output (show the hand-off counts).
 O. In-memory behaviour is disclosed and tested (data is gone after restart/clear; the UI says so), and the synthetic-data limitations are shown in the app.
 P. Everything works with no external network requests (libraries are local).

=== 18. HOW TO WORK ===
1) Audit the current live project against sections 3-16 and give me a short gap list. 2) Show a short plan. 3) Implement fixes in small steps, testing each. 4) Do not change anything that already passes unless needed. 5) Redeploy to the same URL. 6) Final report: a table of tests A-P with Pass/Fail and the actual evidence (numbers, sample outputs, curl results), a list of what changed, and a list of anything you could NOT do or where you deviated from this spec, with the reason. Be honest: if something fails or is approximated, say so rather than claiming success.