# RingWatch specification update plan

## Objective and constraints

Update the existing RingWatch website in place against `SPECIFICATION_UPDATE.md`; do not rebuild from scratch or break functions that already pass. Keep the Python/FastAPI + pandas + scikit-learn IsolationForest + NetworkX backend and the vanilla JS/local-asset SPA. Keep all state in process memory, no database, paid APIs, or runtime CDN/library dependencies. Preserve current route names as aliases while adding the exact required API paths. Use random seed 42 for the generator, Isolation Forest, and stochastic graph operations. Keep the current responsive Midnight Ops brand and local preview/runtime architecture.

The approved sample interpretation is 3,000 deterministic normal transactions plus the injected transactions (currently 30 planted fraud rows), across 200 accounts; expected output is about 3,030 rows. The truth label remains evaluation-only. The supplied specification names `https://ringwatch-ezeykhtk.manus.space`, but this task is bound to a newly initialized WebDev project (`wdp_c2c2821eee2d6b710e19ef0e`) with a separate repository, no deployment/domain attached, and no supported attach operation. Keep that live URL unchanged; finish and checkpoint this project, and do not publish it to a different public URL unless the user explicitly chooses that target or connects the original project.

## Implementation architecture

Keep the existing explicit six-stage sequence and make its data contracts stricter:

1. **Transaction ingestion (`stage1_ingestion.py`)** accepts sample frames or CSV bytes, checks exact required headers, 20 MB and 100,000-row file limits, parses CSV structure, and preserves raw row identity. File-level validation errors carry human-readable reasons and must occur before active in-memory state is replaced.
2. **Data processing (`stage2_processing.py`)** rejects rows with missing/blank required values, invalid UTC timestamps, nonpositive amounts, self-transfers, or conflicting repeated transaction IDs. It drops later exact duplicate rows based on all eight required columns and reports duplicates separately from rejected rows. It emits accepted sorted transactions, row-level rejection records/reason counts, a reconcilable quality summary, and full transaction/account feature frames. Optional `is_fraud` is carried solely for evaluation.
3. **Machine learning (`stage3_modeling.py`)** uses exactly the six requested numerical transaction features and a 200-tree Isolation Forest with `random_state=42`; the six rules, their points, and their thresholds remain centralized in `config.py`. Scores are dataset-relative 0–100, and `final_risk=min(100, rule_points + 0.4*ml_score)`. A transaction is flagged at the configured 40 cutoff. Neither labels nor IDs enter rules/features/model sorting.
4. **Graph construction (`stage4_graph.py`)** creates a directed account graph with one aggregated edge per ordered pair and the specified counts, total amount, first/last times, and max risk. It also reports node, edge, and ring counts.
5. **Ring detection (`stage5_rings.py`)** retains timestamp-valid simple cycles of 3–5 within 48 hours and fan-in with at least eight distinct senders and the 80%-within-one-hour forwarding condition. Keep dense-community results only because Louvain is actually implemented and tested; clearly label that heuristic. Ring inventory rows carry evidence and navigate to their linked case/graph highlight.
6. **Investigation dashboard (`stage6_investigation.py`)** builds weakly connected components from flagged-transaction edges; each component is one case. Case score is the highest account risk in that case and case value is the sum of flagged transaction amounts. It retains case status and computes exact budget metrics with or without ground truth.

`pipeline.py` passes each previous stage's output directly into the next, recording status, elapsed time, input/output counts, hand-off proof, and error. A failure stops subsequent stages and leaves the previous active dataset untouched. `main.py` keeps existing routes and adds `/api/status`, `/api/features`, `/api/config` GET/PUT, processed/rejected/sample CSV downloads, and a clear-data operation with consistent JSON and no-data behavior.

## Frontend and documentation

Keep `/` as the single page route. The visible pipeline rail and Pipeline screen show the six exact stage names, Not run/Running/Done/Failed status, duration, row/object counts, preceding hand-off, and error details. Dashboard gains the complete data-quality reconciliation, actual sortable/paginated transaction/account previews, exports, ML worked example, flagged-transaction-to-case summary, graph metrics, rings, status counters, and synchronized budget/cases/coverage chart. Cases show per-transaction rule/ML/weighted/cap breakdown; Network keeps full directed aggregate data, ring highlighting, case/account details and table alternative. Settings keeps thresholds editable from the one config module, adds a documented API reference and in-app README, and separates Assumptions from other Settings anchors. Add Clear data; disclose that data is memory-only/lost at restart and that anomaly scores are not fraud probabilities. Rename the visible `Present` control to an explicit presentation-mode label without removing the keyboard shortcut.

All JS/CSS libraries remain local. Test browser requests for third-party assets and document any unavoidable non-app platform asset. Update README with the current stack, config, all API paths and curl examples, scoring/rule definitions, limitations, and three-minute demo. Create `ACCEPTANCE_REPORT.md` only after evidence collection; every A–P result must say Pass/Fail/Not verified based on checks actually run.

## Delivery and deployment

Implement in small, testable increments: ingestion/data quality; generator/feature outputs; rules/scoring/cases; graph/rings/budget; pipeline observability/API/UI/docs. Run focused tests alongside each increment, then the full backend suite, curl-level contracts, and browser checks for the UI paths. Checkpoint this new workspace on its canonical `main`. The specified existing URL is not attached to this project, so do not issue a publish request or claim same-URL deployment; that remains blocked until the original project is connected or the user chooses a different target. Never claim an unrun browser, offline, restart, or deployment check passed.

## Project structure

```text
ringwatch/
├── main.py                      # FastAPI routes, aliases, in-memory state
├── pipeline.py                  # Ordered stage execution and instrumentation
├── stage1_ingestion.py           # CSV/file validation, raw rows and rejections
├── stage2_processing.py          # Cleaning, duplicate policy and feature tables
├── rule_engine.py                # Six configured rules and evidence reasons
├── stage3_modeling.py            # Seeded Isolation Forest and score decomposition
├── stage4_graph.py               # Directed aggregate graph and metrics
├── stage5_rings.py               # Cycles, Louvain communities, fan-in rings
├── stage6_investigation.py       # Flagged components, cases, budgets and metrics
├── config.py                     # All configurable thresholds, weights and bands
├── generate_sample.py            # Seeded normal baseline plus planted patterns
├── sample_transactions.csv
├── tests/                        # Unit/API acceptance-boundary coverage
├── static/index.html             # Existing SPA screens plus required controls
├── static/app.js                 # API state, renderers and interactions
├── static/app.css                # Responsive Midnight Ops components
├── static/libs/                  # Offline Chart.js, vis-network, Tailwind
├── README.md / plan.md / TODO.md
├── SPECIFICATION_UPDATE.md / ACCEPTANCE_REPORT.md
└── Dockerfile                    # Existing production container
```

## Design: Midnight Ops (preserved)

Reuse the user's existing Midnight Ops design system and exact tokens in `tokens.css`; no new brand, imagery, runtime dependency, or color palette is proposed.

- **Design movement:** Calm, high-trust financial-security operations UI.
- **Core principles:** Evidence before decoration; consistent and labelled risk; investigator time is scarce; explain every rule-driven decision.
- **Color philosophy:** Deep navy establishes focus, cyan marks interaction and navigation, muted text preserves hierarchy, and green/amber/red retain stable low/medium/high semantics.
- **Layout paradigm:** Persistent investigator shell with compact left navigation and a wide, responsive evidence workspace; graph remains dominant on Network and detailed stage evidence is organized in Pipeline.
- **Signature elements:** Cyan ring-mark with a red gap-side point; score rings; restrained red dashed circular-flow edges.
- **Interaction philosophy:** Every visible control has a clear, testable effect; cases remain reachable outside the selected alert budget; graph/table offer equivalent access.
- **Animation:** Use specified restrained transitions, respect reduced motion, and avoid continuous decoration or long camera transitions.
- **Typography:** Inter for interface copy and JetBrains Mono for IDs, scores, timestamps, and financial figures, with existing local/system fallbacks.
- **Brand essence:** A practical investigator workspace that turns disconnected alerts into explainable connected cases; calm, precise, accountable.
- **Brand voice:** Short, plain-English, measured. “See the rings behind the alerts.” “Review the connections. Decide what happens next.”
- **Wordmark and logo:** RingWatch in Inter 700 beside the existing 24px cyan broken-ring SVG with a small red dot; reuse the mark for favicon.
- **Signature brand color:** `--accent` cyan `#22D3EE`.
