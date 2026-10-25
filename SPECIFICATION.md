# MASTER PROMPT — BUILD RINGWATCH: AI-POWERED FRAUD & TRANSACTION RISK DETECTION PLATFORM

Act as a senior full-stack developer, AI/ML engineer, data visualization specialist, and expert UI/UX designer. Build a complete, functional, polished, hackathon-ready website called **RingWatch**, an AI-powered fraud detection and transaction risk analysis platform.

This is a real working software project, not just a landing page, static design, UI mockup, or frontend prototype. Implement the backend, fraud detection logic, sample dataset generation, interactive frontend, API integration, transaction network visualization, dashboard, settings, and all required interactions.

Follow every requirement in this prompt. Do not omit features, replace complex functionality with decorative mockups, or stop after generating a plan.

## 1. PROJECT VISION AND OBJECTIVE

**Project name:** RingWatch

**Project identifier:** F-01 — Fraud and Transaction Risk

**Tagline:** “We don't just flag transactions, we show the connections, and we respect the investigator's time.”

RingWatch helps investigators identify suspicious financial transactions by analysing transaction patterns, calculating risk scores, grouping related suspicious accounts into cases, and visualizing how money moves between accounts.

The key problem being solved is alert fatigue. Traditional fraud monitoring can generate many separate alerts for transactions that are actually connected to the same fraud ring. RingWatch should group related suspicious transactions into fewer, more useful cases.

The application must have three primary strengths:

1. **Connections, not just alerts:** Reveal circular transfers, suspicious account relationships, and many-to-one money flows through an interactive transaction network graph.
2. **Alert budget:** Allow investigators to choose how many cases they can review per day and calculate how much fraudulent value or overall risk that review budget covers.
3. **Explainable risk scores:** Display understandable reasons for every flagged case instead of showing an unexplained AI score.

The application is intended for a finance hackathon demonstration. It must run locally, work without paid services, use deterministic synthetic data, and remain usable when the demonstration venue has no internet connection.

Do not claim that the system is a production-grade banking fraud prevention service.

## 2. DEVELOPMENT PROCESS

Start by presenting a concise implementation plan, the proposed folder structure, the main components, and the testing strategy. Then proceed automatically to implement the entire application, testing each component before moving to the next. Do not pause for confirmation between steps.

Follow this development order:

1. Establish the project structure, dependencies, configuration, and deterministic sample data generator.
2. Implement CSV ingestion, validation, and the rule-based fraud detection engine.
3. Implement Isolation Forest anomaly detection and combined risk scoring.
4. Implement related-account grouping and case ranking.
5. Build the FastAPI endpoints and test them.
6. Build the frontend shell, homepage, dashboard, and case list.
7. Build the interactive network graph and case detail drawer.
8. Implement the alert budget, coverage chart, threshold settings, and all interactions.
9. Apply the complete Midnight Ops visual design system.
10. Run the tests, fix errors, and provide the completed project with setup and usage instructions.

Do not finish after providing the plan or merely generate code snippets. Deliver the complete project files.

## 3. REQUIRED TECHNOLOGY STACK

### Backend

Use:

- Python
- FastAPI
- pandas
- scikit-learn, including IsolationForest
- NetworkX
- python-multipart for CSV uploads
- Uvicorn

### Frontend

Use:

- HTML
- CSS
- Vanilla JavaScript
- Tailwind CSS for utility styling, with its required assets stored locally
- vis-network for the interactive graph
- Chart.js for the alert-budget coverage chart
- Inline Lucide-style SVG icons

Use the requested lightweight architecture rather than introducing React, Next.js, a separate Node.js application, or unnecessary frameworks.

### Technical restrictions

- No database. Keep application data in memory.
- No paid APIs.
- No external API dependencies.
- No remote service required for fraud scoring.
- No stock photos or decorative stock imagery.
- Vendor frontend libraries locally in the project so the website works offline after installation.
- Prefer locally hosted Inter and JetBrains Mono font files, with suitable system fallbacks.
- Do not require internet access at runtime.
- Include a `requirements.txt`, README, configuration file, sample CSV, tests, and all necessary source files.

The application must start from the project root using:

`uvicorn main:app --reload`

Provide any one-time dependency installation instructions in the README.

## 4. REQUIRED PROJECT STRUCTURE

Use a clean project structure similar to the following:

ringwatch/
- `main.py` — FastAPI application and API endpoints
- `detect.py` — transaction rules, ML scoring, risk calculation, and case grouping
- `config.py` — centralised detection thresholds, rule weights, risk bands, and defaults
- `generate_sample.py` — deterministic synthetic transaction generator
- `sample_transactions.csv` — generated sample dataset
- `requirements.txt` — Python dependencies
- `README.md` — installation, running, testing, features, limitations, and demo instructions
- `tokens.css` — canonical Midnight Ops design tokens
- `static/`
  - `index.html` — single-page application interface
  - `app.js` — application logic and frontend API integration
  - `app.css` — layout, components, and responsive styles
  - `fonts/` — locally hosted font files when available
  - `libs/` — locally hosted frontend libraries
- `tests/`
  - tests for CSV validation, detection rules, risk calculation, case grouping, and API functionality

You may add small supporting modules where genuinely necessary, but preserve the simplicity of the requested architecture.

## 5. SYNTHETIC TRANSACTION DATA

Build `generate_sample.py` to create approximately **3,000 normal and suspicious transactions involving around 200 accounts**, using a fixed random seed so the same dataset and core fraud patterns appear every time.

The generated CSV must contain these required columns, in this order:

`txn_id, timestamp, from_account, to_account, amount, channel, city, device_id`

Add an `is_fraud` column containing 0 or 1 for evaluation purposes only.

Inject the following four fraud patterns into the sample dataset.

### Pattern A: Structuring

Generate five transfers from one account, each between ₹47,000 and ₹49,500, within two hours. These transfers should demonstrate the attempt to avoid a ₹50,000 illustrative transaction threshold.

### Pattern B: Circular money flow

Generate a circular transfer chain:

A → B → C → D → A

Use approximately equal amounts and timestamps within a 24-hour period.

The detection engine should also support identifying qualifying cycles of three to five accounts within the configured 48-hour window.

### Pattern C: Mule-account fan-in and pass-through

Generate transfers from 12 distinct sender accounts into one receiving account. That receiving account should forward at least 90% of the incoming amount within one hour.

### Pattern D: Burst at unusual hours

Generate eight transactions within ten minutes at approximately 3 AM, associated with a new city or device.

Surround the injected patterns with realistic synthetic normal activity, including varied transaction amounts, timestamps, channels, cities, devices, and counterparties.

Ensure relationships and timestamps are internally consistent.

**Important:** `is_fraud` is ground truth for evaluating the synthetic demonstration, not a model feature. Never pass it into the Isolation Forest or use it to calculate transaction risk scores.

The application must display accurate runtime statistics rather than blindly hardcoding sample counts, fraud detection rates, or dashboard KPI values.

## 6. CSV UPLOAD AND VALIDATION

The user must be able to upload a CSV using a file picker or drag-and-drop.

Required columns:

`txn_id, timestamp, from_account, to_account, amount, channel, city, device_id`

When a file is uploaded:

1. Validate the file type and required columns.
2. Parse timestamps consistently.
3. Validate transaction amounts and required values.
4. Handle malformed rows and invalid timestamps gracefully.
5. Show a helpful error message if the data cannot be read.
6. Display the dataset filename and number of loaded rows.
7. Run detection on valid uploaded data.
8. Update dashboard KPIs, ranked cases, graph, chart, and case drawer together.

An uploaded dataset may not contain `is_fraud`. Support both cases.

If the ground-truth column exists, use it only to calculate evaluation metrics. If it does not exist, calculate the share of total model risk score covered by the selected alert budget and clearly label the metric.

Never fabricate fraud-detection accuracy or claim that unknown transactions are confirmed fraud.

Use a user-friendly error message for invalid files:

“We couldn't read this file. Make sure it has these columns: txn_id, timestamp, from_account, to_account, amount, channel, city, device_id.”

Include loading indicators, empty states, upload errors, and success notifications.

## 7. FRAUD DETECTION ENGINE

Implement the actual fraud detection logic in `detect.py`.

All thresholds and configurable rule-point weights must be centralised in `config.py`. Do not scatter unexplained constants throughout the application.

Implement the following six detection rules.

### Rule 1: Structuring

Trigger when an account makes three or more transfers within two hours, with each transfer between 90% and 99% of the illustrative ₹50,000 threshold.

Example reason:

“5 transfers just under ₹50,000 in 2 hours.”

### Rule 2: Transaction velocity

Trigger when one account performs more than six transactions within ten minutes.

Example reason:

“8 transactions in 10 minutes.”

### Rule 3: Odd-hour transactions

Flag transactions between 1 AM and 5 AM when the amount is at least three times the account's average transaction amount.

Example reason:

“Large transfer at 3:12 AM.”

### Rule 4: New device or city

Flag a sufficiently large transaction when its device or city is being seen for the first time for that account, according to the configured threshold.

Example reason:

“First transfer from a new device.”

### Rule 5: Circular flow

Detect directed cycles containing three to five accounts within a 48-hour transaction window.

Use NetworkX cycle detection, including `nx.simple_cycles(G, length_bound=5)` where appropriate. Apply timestamp-window validation to ensure that detected relationships satisfy the configured time limit.

Do not treat every graph cycle as fraud automatically. Use the configured rule points and other available evidence to calculate risk.

Example reason:

“Money returned to its source through 3 accounts.”

### Rule 6: Fan-in with pass-through

Trigger when at least eight distinct sender accounts send funds to one account and at least 80% of the incoming value is sent out within one hour.

Example reason:

“12 accounts funnelled money into one account that forwarded it.”

### Explainability

Each applicable rule must return:

- The rule identifier.
- The points contributed to the risk score.
- A readable explanation.
- The relevant transactions and accounts.
- The configured threshold used.

Choose sensible, configurable default rule-point weights where the brief does not specify them. Document those defaults as illustrative rather than validated banking thresholds.

Make sure the detection engine produces stable, reproducible results for the fixed sample dataset.

## 8. ISOLATION FOREST AND RISK SCORING

Implement an actual scikit-learn Isolation Forest to identify unusual transactions or account activity.

Use these features:

- Transaction amount compared with the account's average.
- Number of transactions in the last hour.
- Number of transactions in the last 24 hours.
- Hour of the day.
- Number of distinct counterparties.
- Time since the account's previous transaction.

Handle insufficient data, missing values, scaling, and accounts with limited activity gracefully.

Convert the model's anomaly score into a consistently interpreted 0–100 scale.

Combine rule-based and ML scores using the specified formula:

`final_risk = min(100, rule_points + 0.4 * ml_score)`

Keep the rule-point totals and ML scores visible in the internal case data so the reasoning can be inspected.

Every score must have relevant human-readable reasons attached. Do not invent explanations for ML-only anomalies; clearly distinguish rule-based reasons from unusual-behaviour findings.

### Risk categories

Define the risk bands once in the central configuration:

- **Low:** 0–39
- **Medium:** 40–69
- **High:** 70–100

Use the same thresholds consistently across score rings, case cards, graph nodes, chart indicators where applicable, and badges.

Always accompany risk colours with a visible text label, numeric score, and appropriate icon. Colour must never be the sole indicator of risk.

## 9. CASE GROUPING AND RANKING

Group related flagged accounts and suspicious transactions into cases so that connected activity can be reviewed as a single investigation.

Use connected components or an equivalent NetworkX-based grouping approach for the flagged account relationships.

Each case must include:

- A unique case identifier.
- A readable case title.
- A risk band and numeric risk score.
- The relevant accounts and transactions.
- The total transaction amount associated with the case.
- The applicable detection rules.
- Plain-English explanations.
- Relevant transaction timestamps.
- Case status.

Use the highest applicable account risk as the case score.

Sort cases in descending order by risk score.

The number of cases displayed for review must respond to the alert-budget setting. Cases outside the current review budget must remain accessible but visually de-emphasised.

Avoid treating every suspicious transaction as a separate case when it belongs to the same connected fraud pattern.

## 10. BACKEND API ENDPOINTS

Implement and test these exact endpoints:

### `GET /api/sample`

Load the built-in deterministic sample dataset, run detection, and return the processed summary.

### `POST /api/upload`

Accept a CSV upload, validate it, run detection, and return the processed results.

### `GET /api/cases?budget=N`

Return cases ranked by risk, limited to the selected review budget, together with relevant coverage metrics.

### `GET /api/graph`

Return graph nodes representing accounts and edges representing transfers, including required risk values, amounts, direction, and related case information.

### `GET /api/case/{id}`

Return the selected case's details, score, risk band, explanations, relevant accounts, transactions, and status.

Design consistent JSON response structures, handle invalid input and unknown case IDs correctly, and use meaningful HTTP status codes.

The frontend must consume these real API endpoints. Do not populate the interface exclusively with hardcoded sample objects.

Because the project does not use a database, an uploaded or sampled dataset and its case-status changes may be kept in memory during the session.

## 11. WEBSITE PAGES AND NAVIGATION

Build a cohesive application with the following screens:

1. Home
2. Dashboard
3. Network
4. Cases
5. Settings and assumptions

Create a shared application shell containing a left sidebar, top bar, and responsive main content area.

### Logo and branding

Use the name **RingWatch** with the supplied ring-mark concept.

Create a 24px inline SVG mark: a cyan circle outline with a small gap and a red dot beside the gap. Use the same mark as the favicon.

Use Inter 700 for the wordmark.

The brand should feel like a professional financial security operations tool, not a gaming dashboard, generic admin template, crypto landing page, or cyberpunk advertisement.

### Sidebar

At desktop width, use a 240px sidebar with:

- RingWatch logo.
- Dashboard.
- Network.
- Cases.
- Settings.

Use 44px-high navigation items and 20px icons.

The active item must have an accent-coloured left bar, accent text, and a subtly tinted background.

At widths between 1024px and 1279px, shrink the sidebar to 72px and show icons with accessible tooltips.

Below 768px, convert the sidebar into a bottom navigation bar.

### Top bar

Use a 64px top bar.

On the left, show the active dataset filename and row count in JetBrains Mono.

On the right, show:

- Presentation mode toggle.
- “Load sample data” secondary button.
- “Upload CSV” primary button.

Provide working interactions for all controls.

## 12. HOME PAGE

Create a polished two-column hero layout on the specified dark background.

The main headline must be:

**“See the rings behind the alerts.”**

Supporting text:

“RingWatch groups suspicious transactions into cases and shows how money moves between accounts.”

Include two clearly visible, 48px-high actions:

- Load sample data.
- Upload CSV.

On the right, create a decorative inline SVG mini-network with approximately 12 nodes, one red dashed ring, and one glowing node. This is the only decorative illustration.

Below the hero, include three feature cards:

- Connections
- Alert budget
- Plain-English reasons

Each card should have a 40px accent-tinted icon circle, clear title, and short explanation.

Add a four-step “How it works” section connected by a subtle line with numbered dots:

1. Upload
2. Score
3. Group
4. Review

Include a footer link to “Assumptions and limitations”.

Keep the homepage visually impressive but restrained. Do not add stock photography or unrequested decorative imagery.

## 13. DASHBOARD

The dashboard is the primary investigator workspace.

### A. KPI cards

Create four KPI cards:

1. Transactions analysed.
2. Cases found.
3. Amount at risk.
4. Fraud value caught at the current budget.

The values must be calculated from the currently loaded dataset and detected cases.

Use a muted uppercase label, large bold number, short contextual hint, and 32px accent-soft icon circle.

Numbers should count up from zero on first load over approximately 800ms, respecting reduced-motion preferences.

Format amounts with Indian currency formatting:

`new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })`

Display amounts in readable form, such as ₹1,84,000.

Use monospace typography and tabular numerals for financial figures.

### B. Alert-budget card

Create a full-width card with a subtle cyan accent glow on its border.

Add an interactive slider with a practical default of 20 cases per day and a range that supports reviewing 5–50 cases.

Show tick labels at 5, 10, 20, and 50.

Display an accessible, live-updating sentence such as:

“Review 20 cases per day and catch about 78% of fraud value.”

The percentage must be calculated from the actual loaded data, never hardcoded merely to match the example.

When `is_fraud` is available, use the ground truth solely to evaluate the share of fraudulent value covered by the selected cases. Also calculate how many reviewed cases contain fraud and a false-alarm/precision metric where meaningful.

Without ground truth, show the percentage of total risk score covered and clearly identify it as risk coverage, not confirmed fraud caught.

### C. Ranked case list

Use seven columns of the 12-column content grid for the ranked case list.

Show a sticky summary such as:

“Showing top 20 of 46 cases.”

Both numbers must come from the current dataset, with the displayed number also responding to the slider.

Each case card must show:

- A 44px circular risk-score ring on the left.
- Case title and identifier.
- Account count.
- Case transaction amount.
- Risk pill on the right.
- Up to three short reason chips, followed by “+2 more” when additional reasons exist.

Use the exact risk thresholds and colours defined in the configuration.

Cases beyond the alert budget should be dimmed to 40% opacity and use a dashed border. They must not disappear from the complete case list or become inaccessible.

The case list must scroll internally, with a maximum height of approximately 60vh.

Clicking a case must open its details and focus the corresponding accounts in the network graph.

### D. Coverage chart

Use the remaining five columns for the alert-budget coverage chart.

Use Chart.js to plot:

- X-axis: Cases reviewed.
- Y-axis: Fraud value caught (%) or clearly labelled risk-score coverage (%) when ground truth is unavailable.
- Vertical scale: 0–100%.

Use a smooth cyan curve and subtle gradient fill, with a highlighted point at the selected budget.

Add a dashed grey diagonal baseline labelled “Random review”.

Use horizontal grid lines only, hide the chart border, and keep the legend hidden unless multiple meaningful series are present.

Style tooltips using the existing dark surfaces, muted border, and monospace numeric values.

Update the existing chart instance when the slider moves, using an animation of approximately 450ms. Do not destroy and recreate the chart on every interaction.

## 14. NETWORK GRAPH — THE SHOWCASE FEATURE

Build a real, responsive, interactive transaction network using vis-network.

The graph must be the largest visual element on the Network page.

It must show accounts as nodes and financial transfers as directed edges.

### Node styling

- Node size reflects transaction volume, bounded between 8px and 34px.
- High-risk nodes use the configured red risk colour.
- Medium-risk nodes use amber.
- Low-risk nodes use green.
- Flagged nodes have a 2px light border and a soft glow in the corresponding risk colour.
- Unflagged nodes use muted grey-blue at approximately 30% opacity and have no glow or visible label.
- Labels appear only on flagged nodes and use short account IDs in 12px Inter.

The graph must remain readable with 200 or more accounts.

### Edge styling

- Normal edges use the existing border-strong colour at approximately 55% opacity.
- Edge thickness reflects transaction amount, ranging from 1px to 6px.
- Directed transfers use arrows.
- Circular-flow edges use the configured `--risk-ring` colour, red dashed strokes, and full opacity.

The graph must make circular money flows visually distinct without flooding the entire screen with red.

### Physics and interaction

Use the `forceAtlas2Based` layout, approximately 150 stabilisation iterations, and then disable physics after stabilisation to keep the graph still during the presentation.

Provide:

- Account hover tooltips displaying account ID, risk score, and top reason.
- Node click handling.
- Case selection and focus.
- Fit-view control.
- Zoom-in control.
- Zoom-out control.
- Table-view control.
- Search by account ID.
- A “Flagged only” toggle.
- A minimum-risk slider.

Use a custom themed tooltip positioned from pointer coordinates. Do not rely on the default browser tooltip.

The floating filter panel should appear at the top left. Put the legend at the bottom left and round graph controls at the bottom right.

### Selecting a case or node

When a case is selected:

1. Fit the graph to the relevant account nodes.
2. Animate the focus over approximately 600ms.
3. Fade unrelated nodes to approximately 12% opacity.
4. Open the right-hand case drawer.
5. Restore the original graph appearance when the canvas background is clicked.

Use a custom legend explaining:

- Green: Low risk.
- Amber: Medium risk.
- Red: High risk.
- Red dashed line: Circular flow.
- Node size: Transaction volume.
- Arrow direction: Money movement.

### Table-view accessibility

Provide a working Table view that displays accounts, transaction links, amounts, risks, and reasons in a readable table.

The table must expose the same important information as the graph. The graph must never be the only way to access case information.

## 15. CASE DETAILS AND INVESTIGATION DRAWER

Clicking a case or flagged node must open a right-hand detail drawer.

At desktop widths, use a drawer approximately 420px wide with the existing glass surface style. On mobile, convert it into a bottom sheet approximately 85% of the viewport height.

The drawer must contain:

### Header

- Case title.
- Case ID where useful.
- Risk pill with icon, label, and score.
- Accessible close button.

### Risk summary

Display a 64px score ring, the label “Risk score”, the numeric risk score, and the case amount.

### “Why this was flagged”

For each detected reason, display:

- An appropriate icon.
- A one-sentence plain-English explanation.
- The corresponding rule name in muted text.

Show the reasons directly instead of hiding important content in hover interactions.

### Transaction timeline

Display a vertical timeline containing the relevant transactions.

Each entry must show:

- Timestamp in monospace.
- Transaction amount in Indian currency formatting.
- Source and destination accounts.
- Channel or other useful context.
- A short description.
- Risk indicators where appropriate.

Use a vertical line in the existing border-strong colour and 10px dots. Flagged transactions use their configured risk colour and a subtle glow.

### Investigation actions

Pin these three buttons at the bottom of the drawer:

- “Confirm fraud” — red outline and red text.
- “False positive” — secondary button.
- “Escalate” — cyan outline.

All buttons must work.

Because the project uses no database, these are demonstration workflow actions that update the case status in application memory.

After a click:

- Update the case's visible status.
- Display a status pill such as “Confirmed”, “Marked as false positive”, or “Escalated”.
- Show a confirmation toast.

Allow the drawer to close using its close button or the Escape key.

## 16. SETTINGS AND ASSUMPTIONS

Build a Settings page with a two-column layout.

### Left column: Detection settings

Show a separate card for each configurable detection rule.

Include:

- Rule title.
- Plain-English description.
- Threshold inputs or sliders.
- Current values in monospace.
- Clear validation and reset behaviour.

Every displayed threshold must correspond to the values used by the backend detection engine.

Provide these buttons:

- “Re-run detection” — apply the selected configuration to the currently loaded dataset and refresh the complete interface.
- “Reset to defaults” — restore the configured defaults.

Ensure changes in the UI actually affect the detection logic; do not create decorative sliders that have no backend effect.

Use clean, understandable controls and provide sensible bounds for numeric inputs.

### Right column: Assumptions and limitations

Create an “Assumptions and limitations” card with an information icon and a 4px cyan left border.

Display these four statements clearly:

1. The sample data is synthetic and the fraud patterns are simplified.
2. Thresholds such as ₹50,000 are examples and can be changed in settings.
3. The model has not been validated on real bank data.
4. RingWatch supports investigators. It does not block transactions or make final decisions.

Keep this section visible, readable, and accessible. Do not bury these limitations in fine print.

## 17. EXACT VISUAL DESIGN SYSTEM — MIDNIGHT OPS

Follow the attached RingWatch style guide precisely.

The design theme is called **Midnight Ops**: a dark, calm, high-trust financial security operations dashboard designed for investigators working under pressure.

The interface must feel professional, information-rich, modern, refined, and suitable for a live hackathon demonstration.

Prioritise evidence over decoration. Risk colours must have consistent meaning. Use plain English. Avoid flashing effects, visual panic, noisy neon styling, unnecessary gradients, excessive glass effects, and constant animation.

### 17.1 Canonical tokens.css

Create `tokens.css` first and use the following exact design tokens:

```css
:root {
  /* Surfaces */
  --bg: #0B1220;
  --surface: #111A2E;
  --surface-2: #16223A;
  --border: #1F2A44;
  --border-strong: #2B3A5C;

  /* Text */
  --text: #E6EDF7;
  --text-muted: #8FA1BF;

  /* Brand */
  --accent: #22D3EE;
  --accent-soft: rgba(34, 211, 238, 0.12);
  --on-accent: #06222B;

  /* Risk: shapes */
  --risk-low: #22C55E;
  --risk-med: #F59E0B;
  --risk-high: #EF4444;
  --risk-ring: #FF3B5C;

  /* Risk: badge text and backgrounds */
  --risk-low-text: #86EFAC;
  --risk-low-bg: rgba(34, 197, 94, 0.14);
  --risk-med-text: #FCD34D;
  --risk-med-bg: rgba(245, 158, 11, 0.14);
  --risk-high-text: #FCA5A5;
  --risk-high-bg: rgba(239, 68, 68, 0.14);

  /* Typography */
  --font-ui: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;

  /* Spacing: 4px grid */
  --s-1: 4px;
  --s-2: 8px;
  --s-3: 12px;
  --s-4: 16px;
  --s-5: 24px;
  --s-6: 32px;
  --s-7: 48px;

  /* Radius */
  --r-sm: 8px;
  --r-md: 12px;
  --r-lg: 16px;
  --r-pill: 999px;

  /* Depth */
  --shadow-card: 0 1px 2px rgba(0, 0, 0, 0.35),
                 0 8px 24px rgba(0, 0, 0, 0.25);
  --glow-accent: 0 0 0 1px rgba(34, 211, 238, 0.35),
                 0 0 24px rgba(34, 211, 238, 0.18);
  --glow-ring: 0 0 16px rgba(255, 59, 92, 0.55);

  /* Motion */
  --ease: cubic-bezier(0.2, 0.8, 0.2, 1);
  --t-fast: 120ms;
  --t-med: 200ms;
  --t-slow: 450ms;
}

html {
  color-scheme: dark;
  font-size: 16px;
}

html.present {
  font-size: 18px;
}

body {
  margin: 0;
  font: 400 0.9375rem/1.6 var(--font-ui);
  color: var(--text);
  background:
    radial-gradient(
      1100px 520px at 8% -10%,
      rgba(34, 211, 238, 0.10),
      transparent 60%
    ),
    var(--bg);
  -webkit-font-smoothing: antialiased;
}

.mono,
.num {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-card);
  padding: 20px;
  transition: border-color var(--t-med) var(--ease);
}

.card:hover {
  border-color: var(--border-strong);
}

.glass {
  background: rgba(17, 26, 46, 0.78);
  backdrop-filter: blur(10px);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation: none !important;
    transition: none !important;
  }
}
```

This is the canonical design token set. All design colours must come from these tokens, and all tokenised spacing, radii, typography, shadows, and transitions must remain consistent. For the additional component and layout dimensions specified in this prompt, preserve the stated dimensions exactly rather than inventing new visual styles.

Do not introduce extra palette colours, fonts, gradients, or decorative effects beyond those explicitly specified.

### 17.2 Typography

Use Inter for normal interface text and JetBrains Mono for IDs, scores, timestamps, transaction amounts, and technical data.

Preferred locally hosted font weights:

- Inter: 400, 500, 600, 700.
- JetBrains Mono: 400, 500.

Use `font-display: swap` for locally hosted fonts where available and appropriate fallbacks if font files cannot be obtained.

Use these typography specifications:

- Home-page hero headline: 2.75rem / 3.25rem, weight 700, letter spacing -0.02em.
- Page title: 1.5rem / 2rem, weight 600.
- Section title: 1.125rem / 1.625rem, weight 600.
- Card title: 0.9375rem / 1.375rem, weight 600.
- Body: 0.9375rem / 1.5rem, weight 400.
- KPI numbers: 2rem / 2.25rem, weight 700.
- Labels and captions: 0.8125rem / 1.125rem, weight 500, muted.
- Data: 0.8125rem / 1.125rem, weight 500, monospace.

Use uppercase KPI labels with 0.04em letter spacing. Keep reason text compact and readable. Do not shrink text below 0.75rem, and use no more than three text sizes inside one card.

### 17.3 Layout and spacing

- Design for a 1366 × 768 laptop and a 1920 × 1080 projector first.
- Page padding: 24px.
- Gap between cards: 16px.
- Card padding: 20px.
- Main content maximum width: 1440px, centred.
- Main content grid: 12 columns with a 16px gap.
- Small button/input radius: 8px.
- Standard card radius: 12px.
- Large panel/dropzone radius: 16px.
- Every card must have a subtle 1px border.
- Hovered cards should brighten their border slightly.
- Selected items should use the cyan accent border and glow.

Never use pure black or pure white. Preserve the specified dark-navy and cyan visual identity.

### 17.4 Button styling

Use 40px-high standard buttons, 8px corner radius, 16px horizontal padding, 0.875rem semibold text, 18px icons, and an 8px icon gap. Home-page hero actions are 48px high.

Primary buttons use the accent cyan background and `--on-accent` text.

Secondary buttons use `--surface-2`, `--border-strong`, and `--text`.

Ghost buttons use transparent backgrounds and muted text, with an appropriate hover surface.

Buttons must have visible focus states, clear disabled states, and restrained hover and press animations.

### 17.5 Risk pills and score rings

Risk pills must display an icon, risk-band label, and score. Examples: “Low 24”, “Medium 61”, and “High 87”.

Use the supplied lighter text and tinted-background tokens for risk badges to preserve text contrast.

Use 44px SVG score rings in case cards and 64px rings in the detail drawer.

The ring circumference is approximately 113.1 for the 44px ring. Calculate the foreground arc using:

`score / 100 * 113.1`

Rotate the arc by -90 degrees so the score starts at the top. Colour the arc according to the configured risk band, and animate it drawing in over approximately 600ms when appropriate.

The track must use the existing border-strong colour. Use accessible SVG labels describing the risk score.

### 17.6 Alert-budget slider

Use a 24px-high interactive slider, an 8px track, a 24px thumb, and the supplied accent glow. The filled portion must use the accent colour, with the remaining track using border-strong.

Update the slider fill dynamically using a CSS custom property, and synchronise the slider, live sentence, ranked cases, and chart.

### 17.7 Table styling

- Sticky table headers.
- Muted uppercase column labels.
- Approximately 44px rows.
- Hovered rows use `--surface-2`.
- Numeric cells use JetBrains Mono and are right-aligned.
- No zebra striping.

### 17.8 Motion and animation

Use the supplied easing curve, durations, and restrained motion system.

- Case and card hover: subtle border transition and 1px lift over 200ms.
- Button press: 1px movement over 120ms.
- Page transitions: fade and 8px upward movement over 200ms.
- KPI counting: approximately 800ms.
- Score-ring drawing: approximately 600ms.
- Alert chart updates: approximately 450ms.
- Detail drawer transition: approximately 250ms.
- Graph focus: approximately 600ms.
- Loading skeleton shimmer: approximately 1.2 seconds.

Do not run decorative animations continuously. The optional movement of small dots along circular-flow edges is the only permitted continuous decorative animation, and it must remain subtle.

Respect `prefers-reduced-motion: reduce`.

### 17.9 Presentation mode

Implement a Presentation mode button in the top bar with an appropriate monitor icon.

Clicking it or pressing the `P` key must toggle the `present` class on the HTML element, increasing the root font size to 18px.

Ensure the application remains readable from the back of a room, including labels, case cards, scores, charts, and graph controls.

## 18. ACCESSIBILITY AND USER EXPERIENCE

Follow these requirements throughout the application:

- Maintain at least 4.5:1 text contrast and 3:1 contrast for large text, verifying combinations with a contrast checker.
- Make every control keyboard accessible.
- Provide visible focus indicators.
- Keep the tab order logical.
- Ensure interactive targets are at least 40 × 40px where specified.
- Give icon-only buttons appropriate accessible labels.
- Make score rings accessible using SVG roles and labels.
- Use `aria-live="polite"` for the alert-budget summary.
- Support slider keyboard controls.
- Close the case drawer with Escape.
- Provide the graph's accessible table alternative.
- Never rely on colour alone to communicate risk.
- Respect reduced-motion settings.
- Display readable validation errors, loading states, empty states, and success notifications.

Follow a calm, direct tone. Avoid unnecessary jargon, exaggerated warnings, and excessive exclamation marks.

Use this exact empty-state style of messaging:

“No cases to show yet. Load sample data or upload a CSV to begin.”

## 19. FUNCTIONAL INTEGRATION REQUIREMENTS

Every visible control must perform its advertised action.

Specifically, ensure that:

- Loading sample data calls the real sample-data API and processes the dataset.
- Uploading a CSV calls the real upload API.
- Dashboard numbers change when a different dataset is loaded.
- Risk scores are produced by the detection engine.
- Case grouping reflects actual transaction relationships.
- The budget slider changes the visible case ranking, dims cases outside the budget, and updates the coverage chart and summary sentence.
- The graph shows actual account and transaction relationships returned by the backend.
- Selecting a graph node opens the appropriate case when one is associated with it.
- Selecting a case focuses the corresponding graph nodes.
- Search, flagged-only filtering, and minimum-risk filtering work.
- Fit, zoom, and table-view controls work.
- The timeline displays actual transactions associated with the selected case.
- Investigation actions update the selected case status and show toasts.
- Settings modify the backend detection configuration and rerun detection.
- Reset-to-defaults restores the original threshold configuration.
- Presentation mode works with both the button and the P key.
- The upload experience is functional, including file selection, drag-and-drop, validation, error handling, and success feedback.
- Reloading or changing pages does not leave charts or graph event listeners in a broken state.

Keep backend and frontend data models consistent. Avoid duplicate event listeners, stale chart instances, and inconsistent case statuses.

## 20. TESTING AND QUALITY ASSURANCE

Before declaring the project complete, run the application and test it.

### Backend tests

Verify:

- Sample generation produces a deterministic dataset with the correct required columns.
- The dataset contains approximately 3,000 transactions and approximately 200 accounts.
- The four injected fraud patterns exist.
- Ground-truth labels are not used as model features.
- Each of the six rules can detect a suitable test pattern.
- Isolation Forest scoring returns valid values.
- The final risk score is bounded from 0 to 100.
- Risk bands match the configured thresholds.
- Related transactions are grouped into cases correctly.
- Case ranking responds to risk scores.
- Circular-flow timestamps are checked against the configured time window.
- Valid CSV files upload successfully.
- Invalid columns, invalid timestamps, malformed input, and unknown cases are handled gracefully.
- The alert-budget calculations work with and without `is_fraud`.
- All five specified endpoints return valid responses.

### Frontend tests

Verify that:

- The complete application loads without console errors.
- The sample-data button works.
- CSV upload and validation work.
- KPI values update correctly.
- The alert-budget slider changes the sentence, cases, and chart together.
- The graph renders accounts and directional transfers.
- Circular flows are highlighted correctly.
- Graph filters, search, zoom, and fit controls work.
- Case selection opens the drawer.
- All drawer actions work.
- Settings update the underlying thresholds.
- The graph table alternative works.
- Presentation mode works with the button and keyboard.
- The interface works at desktop, tablet, and mobile sizes.
- Keyboard focus, Escape-to-close, and reduced-motion behaviour work.

### Visual QA

Confirm that the interface follows Midnight Ops at:

- 1366 × 768.
- 1920 × 1080.
- Tablet widths from 768px to 1023px.
- Mobile widths below 768px.

Verify that risk colours are consistent across every screen, graph labels remain readable, cases outside the budget are visually dimmed, and the layout does not overflow.

All local libraries, fonts, and essential application assets must be available without external network requests at runtime.

Fix errors that appear during testing rather than simply listing them as known issues.

## 21. README AND DEMONSTRATION FLOW

Write a clear README containing:

- Project overview.
- Main features.
- Technology stack.
- Project folder structure.
- Prerequisites.
- Installation instructions.
- How to run the application.
- API endpoint descriptions.
- Sample CSV format.
- Detection-rule explanations.
- Risk-scoring methodology.
- Test commands.
- Limitations and assumptions.
- A step-by-step hackathon demonstration script.

Keep the development workflow simple, with the application launched from the project root using:

`uvicorn main:app --reload`

The README must explain dependency installation before running the command.

### Suggested three-minute demonstration

1. Open RingWatch and load the built-in sample dataset.
2. Show the number of transactions analysed and the suspicious cases identified.
3. Explain how multiple suspicious transactions are grouped into fewer connected cases.
4. Move the alert-budget slider and show how the detected fraud-value coverage changes.
5. Open the Network page and select the circular transfer ring.
6. Explain the graph connections, risk score, and plain-English detection reasons.
7. Open the case drawer and demonstrate the transaction timeline and investigation actions.
8. Open Settings to show configurable thresholds and finish with the assumptions and limitations.

Keep the graph, alert-budget slider, and explainable case details as the highest-priority demonstration features.

## 22. FINAL DELIVERABLES

When the implementation is complete, provide:

1. The complete RingWatch project source files in the proper folder structure.
2. A functioning FastAPI backend with all specified endpoints.
3. The deterministic sample CSV and generator.
4. The six rule-based detections and Isolation Forest scoring.
5. Connected case grouping and risk ranking.
6. The fully integrated dashboard and interactive network graph.
7. The complete Midnight Ops design system.
8. Working upload, settings, alert-budget, drawer, and presentation-mode interactions.
9. Automated tests and their actual results.
10. A README with installation, run, test, and demonstration instructions.

If your environment supports creating downloadable project files, provide the complete project as a ZIP. Also provide the source files in an accessible project workspace so the code can be inspected and edited.

Do not claim that tests passed unless they were actually run. Clearly report any environment limitation that prevents a particular test or dependency from being verified.

Do not leave the project at the mockup stage. Complete the backend, frontend, styling, data flow, and core functionality.

## FINAL DESIGN AND ENGINEERING PRINCIPLE

Build RingWatch as a polished, trustworthy, interactive fraud-investigation tool where the network graph reveals connections, the alert budget respects investigators' limited time, and every risk score has an understandable explanation.

**The final result must look like Midnight Ops, follow the technical specification, use real computed data, and be ready for a local hackathon demonstration.**