(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const INR = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
  const INT = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
  const state = {
    page: 'home', dataset: null, summary: null, cases: [], budget: 20,
    coverage: null, chart: null, graph: null, graphNodes: [], graphEdges: [], graphRings: [],
    graphNodeById: new Map(), graphEdgeById: new Map(),
    visNodes: null, visEdges: null, graphLoaded: false, graphStable: false, maxEdgeAmount: 1, caseDetail: null,
    selectedCaseId: null, drawerMode: null, focusedAccounts: null, tableMode: false, networkTablePage: 0, settings: null, settingBounds: null,
    pipelineReport: null, pipelineDetail: null, graphStats: null,
    featureKind: 'transactions', featureOffset: 0, featureLimit: 20, featureTotal: 0,
    featureSortBy: null, featureSortDirection: 'asc', featureRows: [],
    settingsDefaults: null, uploadBusy: false, uploadOpener: null, drawerOpener: null, firstKpiLoad: true,
  };
  let budgetTimer = null;
  let budgetRequestId = 0;
  let pendingZoomSteps = 0;
  let zoomFrame = null;
  const NETWORK_TABLE_PAGE_SIZE = 50;

  const icon = (id) => `<svg class="icon" aria-hidden="true"><use href="#i-${id}"></use></svg>`;
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const formatMoney = (value) => INR.format(Number(value || 0));
  const formatCompactMoney = (value) => {
    const amount = Number(value || 0);
    if (Math.abs(amount) < 100000) return formatMoney(amount);
    return `₹${new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 }).format(amount)}`;
  };
  const riskLabel = (risk) => risk === 'medium' ? 'Medium' : risk.charAt(0).toUpperCase() + risk.slice(1);
  const riskColor = (band) => ({ low: 'var(--risk-low)', medium: 'var(--risk-med)', high: 'var(--risk-high)' }[band] || 'var(--text-muted)');
  const bandIcon = (band) => band === 'high' ? 'alert' : band === 'medium' ? 'info' : 'check';
  const riskPill = (band, score) => `<span class="risk-pill ${escapeHtml(band)}">${icon(bandIcon(band))}${escapeHtml(riskLabel(band))} <span class="mono">${Math.round(score)}</span></span>`;

  async function api(path, options = {}) {
    const response = await fetch(path, options);
    const contentType = response.headers.get('content-type') || '';
    const payload = contentType.includes('application/json') ? await response.json() : {};
    if (!response.ok) {
      const detail = payload.detail;
      const message = typeof detail === 'string' ? detail : detail?.message || payload.message || 'The request could not be completed.';
      throw new Error(message);
    }
    return payload;
  }

  function setPage(page) {
    if (!$$(`[data-page="${page}"]`).length) page = 'home';
    state.page = page;
    $$('[data-page]').forEach((view) => { view.hidden = view.dataset.page !== page; });
    $$('.nav-item[data-nav]').forEach((item) => item.classList.toggle('active', item.dataset.nav === page));
    if (page === 'network') ensureGraph().catch((error) => toast(error.message, true));
    if (page === 'settings') loadSettings().catch((error) => toast(error.message, true));
    if (page === 'cases') renderFullCases();
    if (page === 'dashboard') updateDashboard();
    if (page === 'pipeline') loadPipelineDetails().catch((error) => toast(error.message, true));
    window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }

  const landingStages = [
    ['Transaction ingestion', 'Read the CSV and validate its schema.'],
    ['Data processing', 'Clean rows and engineer time, account and flow features.'],
    ['Machine learning', 'Combine configurable rules with Isolation Forest signals.'],
    ['Graph construction', 'Aggregate directed transfers between account pairs.'],
    ['Ring detection', 'Surface cycles, dense communities and fan patterns.'],
    ['Investigation dashboard', 'Rank connected cases and show their evidence.'],
  ];

  function renderLandingStages() {
    const container = $('.how-section .steps');
    if (!container) return;
    container.innerHTML = landingStages.map(([name, description], index) => `${index ? '<span class="step-line" aria-hidden="true"></span>' : ''}<div class="step"><span class="step-dot">${String(index + 1).padStart(2, '0')}</span><div><b>${escapeHtml(name)}</b><small>${escapeHtml(description)}</small></div></div>`).join('');
  }

  function renderPipelineProgress(report = state.pipelineReport) {
    const attempt = report?.latest_attempt?.status === 'failed' ? report.latest_attempt : report;
    const stages = attempt?.stages || [];
    const byId = new Map(stages.map((stage) => [stage.id, stage]));
    let done = 0;
    let failed = null;
    let running = null;
    $$('[data-progress-stage]').forEach((element) => {
      const stage = byId.get(element.dataset.progressStage);
      const status = stage?.status || 'not_run';
      const complete = status === 'done';
      if (complete) done += 1;
      if (status === 'failed') failed = stage;
      if (status === 'running') running = stage;
      element.classList.toggle('done', complete);
      element.classList.toggle('failed', status === 'failed');
      element.classList.toggle('running', status === 'running');
      const statusLabel = $('.pipeline-progress-state', element);
      if (statusLabel) statusLabel.textContent = ({ not_run: 'Not run', running: 'Running', done: 'Done', failed: 'Failed' })[stage?.status || 'not_run'];
    });
    const total = attempt?.status === 'failed' ? `Failed at ${failed?.name || attempt.failed_stage || 'pipeline'}` : running ? `Running · ${running.name}` : done === 6 ? '6 of 6 done' : done ? `${done} of 6 done` : 'Not run';
    if ($('#pipelineRunState')) $('#pipelineRunState').textContent = total;
    if ($('#pipelinePageState')) $('#pipelinePageState').textContent = total;
  }

  function metricTile(label, value, hint = '') {
    return `<article class="card pipeline-metric-tile"><span>${escapeHtml(label)}</span><strong class="mono">${escapeHtml(value)}</strong><small>${escapeHtml(hint)}</small></article>`;
  }

  function safeDateRange(value) {
    return value?.start && value?.end ? `${String(value.start).replace('T', ' ').slice(0, 16)} — ${String(value.end).replace('T', ' ').slice(0, 16)} UTC` : '—';
  }

  function pipelineCell(key, value) {
    if (value === null || value === undefined || value === '') return '—';
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (key === 'amount' || key.startsWith('total_') || key.startsWith('average_') || key.startsWith('maximum_')) return formatMoney(value);
    if (key === 'amount_vs_account_avg') return `${Number(value).toFixed(2)}×`;
    if (key === 'timestamp' || key.endsWith('_timestamp')) return escapeHtml(String(value).replace('T', ' ').replace('Z', ' UTC').slice(0, 22));
    if (typeof value === 'number') return Number.isInteger(value) ? INT.format(value) : Number(value).toFixed(2);
    return escapeHtml(String(value));
  }

  function renderPreviewTable(headId, bodyId, rows, columns) {
    const head = $(`#${headId}`);
    const body = $(`#${bodyId}`);
    head.innerHTML = `<tr>${columns.map(([key, label]) => `<th${['amount','total_outgoing_amount','total_incoming_amount'].includes(key) ? ' class="num-cell"' : ''}>${escapeHtml(label)}</th>`).join('')}</tr>`;
    body.innerHTML = rows.length ? rows.map((row) => `<tr>${columns.map(([key]) => `<td${['amount','total_outgoing_amount','total_incoming_amount'].includes(key) ? ' class="num-cell"' : ''}>${pipelineCell(key, row[key])}</td>`).join('')}</tr>`).join('') : '<tr><td colspan="20">No preview rows.</td></tr>';
  }

  function stageSummaryMarkup(stage) {
    const summary = stage.summary || {};
    const labels = {
      rows_received: 'Rows received', rows_before_processing: 'Rows parsed', malformed_rows: 'Malformed rows', source: 'Source',
      rows_loaded: 'Rows retained', rows_rejected: 'Rows rejected', duplicates_removed: 'Duplicates removed', duplicate_rows_removed: 'Duplicates removed', unique_accounts: 'Unique accounts',
      self_transfers_flagged: 'Self transfers flagged', model_name: 'Model', features_count: 'Model features', scored_transactions: 'Transactions scored',
      rules_fired: 'Rules fired', node_count: 'Graph nodes', edge_count: 'Aggregated links', weakly_connected_components: 'Weak components',
      directed_density: 'Directed density', ring_count: 'Detected rings', case_count: 'Investigation cases', account_count: 'Accounts reviewed',
      flagged_transactions: 'Flagged transactions', cases_found: 'Cases found', accounts_analysed: 'Accounts analysed',
      transactions_analysed: 'Transactions analysed',
    };
    const items = [];
    Object.entries(summary).forEach(([key, value]) => {
      if (key === 'date_range') { items.push(['Date range', safeDateRange(value)]); return; }
      if (key === 'score_distribution' || value === null || value === undefined) return;
      if (!(key in labels)) return;
      items.push([labels[key], Array.isArray(value) ? value.join(', ') || 'None' : typeof value === 'number' ? String(value) : String(value)]);
    });
    return items.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join('') || '<span class="muted">No stage summary available.</span>';
  }

  function renderPipelineDetails(report) {
    state.pipelineDetail = report;
    state.pipelineReport = report;
    renderPipelineProgress(report);
    const active = Boolean(report?.active && (report?.processing || report?.status === 'failed'));
    $('#pipelineEmpty').hidden = active;
    $('#pipelineContent').hidden = !active;
    const latestAttempt = report?.latest_attempt?.status === 'failed' ? report.latest_attempt : report?.status === 'failed' ? report : null;
    const failedStage = latestAttempt?.stages?.find((stage) => stage.status === 'failed');
    const latestError = latestAttempt?.error?.message || failedStage?.error?.message || 'The pipeline stopped before the remaining stages could run.';
    $('#pipelineLatestAttempt').hidden = !latestAttempt;
    $('#pipelineLatestAttempt').innerHTML = latestAttempt
      ? `<strong>Latest attempt failed at ${escapeHtml(failedStage?.name || latestAttempt.failed_stage || 'the pipeline')}.</strong> ${report?.processing ? 'The previous active dataset is unchanged.' : 'No new active dataset was committed.'} ${escapeHtml(latestError)}`
      : '';
    if (!active) return;
    const processing = report.processing || {};
    const validation = processing.validation || report.validation || {};
    const summary = report.summary || {};
    const dateRange = safeDateRange(validation.date_range);
    $('#pipelineOverview').innerHTML = [
      metricTile('ROWS LOADED', INT.format(validation.rows_loaded || 0), `${INT.format(validation.rows_received || 0)} received · ${INT.format(validation.rows_rejected || 0)} rejected`),
      metricTile('UNIQUE ACCOUNTS', INT.format(validation.unique_accounts || 0), dateRange),
      metricTile('AGGREGATED LINKS', INT.format(report.graph_stats?.edge_count || 0), `${INT.format(report.graph_stats?.component_count || 0)} weak components · density ${Number(report.graph_stats?.directed_density || 0).toFixed(3)}`),
      metricTile('CASES & RINGS', `${INT.format(summary.cases_found || 0)} / ${INT.format(report.ring_summary?.ring_count || 0)}`, `${escapeHtml(report.filename || 'Dataset')} · ${INT.format(summary.transactions_analysed || 0)} valid transactions`),
    ].join('');
    $('#pipelineStageDetails').innerHTML = (report.stages || []).map((stage, index) => {
      const stateLabel = stage.label || ({ not_run: 'Not run', running: 'Running', done: 'Done', failed: 'Failed' })[stage.status] || 'Not run';
      const handoff = stage.handoff_text || (stage.input_count !== null && stage.output_count !== null ? `${INT.format(stage.input_count)} input → ${INT.format(stage.output_count)} output` : 'No hand-off recorded.');
      const error = stage.error?.message ? `<p class="pipeline-stage-error">${escapeHtml(stage.error.message)}</p>` : '';
      return `<article class="pipeline-stage-card ${escapeHtml(stage.status || 'not_run')}"><div class="pipeline-stage-card-head"><span class="pipeline-progress-number mono">${String(index + 1).padStart(2, '0')}</span><div><h3>${escapeHtml(stage.name)}</h3><span class="pipeline-stage-badge ${escapeHtml(stage.status || 'not_run')}">${escapeHtml(stateLabel)}</span></div><span class="pipeline-duration mono">${stage.duration_ms === null || stage.duration_ms === undefined ? '—' : `${Number(stage.duration_ms).toFixed(1)} ms`}</span></div><p class="pipeline-handoff">${escapeHtml(handoff)}</p>${error}<div class="pipeline-stage-card-metrics">${stageSummaryMarkup(stage)}</div></article>`;
    }).join('');
    const model = report.model || {};
    const distribution = model.score_distribution || {};
    const workedExamples = (model.worked_examples || []).map((example) => `<div class="worked-example"><b class="mono">${escapeHtml(example.txn_id)}</b><span>${INT.format(example.rule_points)} rule + 0.4 × ${Number(example.ml_score).toFixed(2)} = ${Number(example.weighted_ml_score).toFixed(2)} ML</span><strong class="mono">${Number(example.final_risk).toFixed(1)} final risk${example.capped_at_100 ? ' · capped at 100' : ''}</strong></div>`).join('');
    const modelFacts = [
      ['Estimator', `${model.name || 'Isolation Forest'} · ${model.model_fitted === false ? 'not fitted (fewer than 12 rows)' : `${model.n_estimators || 200} trees`}`],
      ['Feature count', String(model.features?.length || 0)],
      ['Scored rows', INT.format(model.scored_transactions || 0)],
      ['Contamination', String(model.contamination || 'auto')],
      ['Random seed', String(model.random_state ?? 42)],
      ['Ground truth in scoring', model.ground_truth_used_for_scoring === false ? 'No' : 'No labels used'],
      ['Rule + model formula', model.scoring_formula || 'min(100, rule_points + ml_weight × ml_score)'],
      ['Score scaling', model.anomaly_score_scaling || 'Dataset-relative score, scaled 0–100'],
      ['Transaction ML score · min / median / p90 / max', [distribution.min, distribution.median, distribution.p90, distribution.max].map((value) => Number(value || 0).toFixed(1)).join(' / ')],
    ];
    $('#pipelineModelDetails').innerHTML = `<dl class="pipeline-facts">${modelFacts.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join('')}</dl><p class="pipeline-caveat">${escapeHtml(model.explanation_method || report.score_methodology || 'Feature signals are dataset-relative deviations, not causal model attributions or fraud probabilities.')}</p><h3 class="pipeline-example-title">Worked examples from actual scored transactions</h3>${workedExamples || '<p class="pipeline-caveat">No worked transaction examples are available.</p>'}`;
    $('#pipelineFeatureNames').innerHTML = (model.features || []).map((feature) => `<span class="pipeline-feature-chip mono">${escapeHtml(feature.replaceAll('_', ' '))}</span>`).join('');
    const graphStats = report.graph_stats || {};
    const graphFacts = [
      ['Nodes', graphStats.node_count], ['Aggregated directed links', graphStats.edge_count],
      ['Weakly connected components', graphStats.component_count], ['Directed density', Number(graphStats.directed_density || 0).toFixed(3)],
      ['Self-loop links', graphStats.self_loop_edge_count],
    ];
    $('#pipelineGraphStats').innerHTML = graphFacts.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong class="mono">${escapeHtml(value ?? 0)}</strong></div>`).join('');
    const typeCounts = report.ring_summary?.counts_by_type || {};
    const typeNames = { cycle: 'Cycle', community: 'Dense community', fan_in: 'Fan-in', fan_out: 'Fan-out' };
    $('#pipelineRingCount').textContent = INT.format(report.ring_summary?.ring_count || 0);
    $('#pipelineRingSummary').innerHTML = Object.entries(typeNames).map(([key, label]) => `<span class="pipeline-ring-count">${escapeHtml(label)} <strong class="mono">${INT.format(typeCounts[key] || 0)}</strong></span>`).join('');
    const transactionColumns = [
      ['txn_id','TXN ID'], ['timestamp','UTC TIME'], ['from_account','FROM'], ['to_account','TO'], ['amount','AMOUNT'],
      ['amount_vs_account_avg','AMOUNT / AVG'], ['txn_count_1h','TXNS / 1H'], ['txn_count_24h','TXNS / 24H'],
      ['sender_in_degree','IN DEGREE'], ['sender_out_degree','OUT DEGREE'], ['seconds_since_prev_txn','SECONDS SINCE PREVIOUS'],
      ['is_overnight','OVERNIGHT'], ['amount_near_threshold','NEAR THRESHOLD'], ['rapid_in_out_movement','RAPID IN/OUT'],
      ['is_new_device','NEW DEVICE'], ['is_new_city','NEW CITY'], ['ml_score','ML SCORE'], ['risk_score','RISK'], ['risk_band','BAND'],
    ];
    const transactionRows = processing.transaction_preview || [];
    $('#transactionPreviewCaption').textContent = `Showing ${INT.format(transactionRows.length)} of ${INT.format(validation.rows_loaded || 0)} processed transactions with engineered features.`;
    renderPreviewTable('transactionPreviewHead', 'transactionPreviewBody', transactionRows, transactionColumns);
    const accountColumns = [
      ['account_id','ACCOUNT'], ['out_transaction_count','OUT TXNS'], ['in_transaction_count','IN TXNS'], ['transaction_count','TOTAL TXNS'],
      ['total_outgoing_amount','OUTGOING VALUE'], ['total_incoming_amount','INCOMING VALUE'], ['in_degree','IN DEGREE'], ['out_degree','OUT DEGREE'],
      ['device_count','DEVICES'], ['city_count','CITIES'], ['overnight_count','OVERNIGHT'], ['rapid_in_out_count','RAPID IN/OUT'],
    ];
    renderPreviewTable('accountPreviewHead', 'accountPreviewBody', processing.account_feature_preview || [], accountColumns);
    const rings = report.rings || [];
    const ringCase = new Map((report.cases || []).flatMap((caseItem) => (caseItem.ring_ids || []).map((id) => [id, caseItem.id])));
    $('#detectedRingsBody').innerHTML = rings.length ? rings.map((ring) => `<tr class="ring-table-row" tabindex="0" role="button" data-ring-id="${escapeHtml(ring.id)}" data-case-id="${escapeHtml(ringCase.get(ring.id) || '')}" aria-label="Focus ring ${escapeHtml(ring.id)} in Network"><td class="mono">${escapeHtml(ring.id)}</td><td>${escapeHtml(ring.type_label)}</td><td>${escapeHtml((ring.accounts || []).slice(0, 8).join(', '))}${ring.accounts?.length > 8 ? ` +${ring.accounts.length - 8}` : ''}</td><td class="num-cell">${INT.format(ring.transaction_count || 0)}</td><td class="num-cell">${formatMoney(ring.total_value || 0)}</td><td>${riskPill(ring.risk_band, ring.risk_score)}</td><td>${escapeHtml(ring.explanation || '')}</td></tr>`).join('') : '<tr><td colspan="7">No rings meet the disclosed detection thresholds.</td></tr>';
    $$('[data-ring-id]', $('#detectedRingsBody')).forEach((row) => {
      const focus = () => focusRing(row.dataset.ringId, row.dataset.caseId || null);
      row.addEventListener('click', focus);
      row.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); focus(); } });
    });
  }

  async function loadPipelineDetails() {
    const report = await api('/api/pipeline');
    renderPipelineDetails(report);
  }

  function toast(message, error = false) {
    const region = $('#toastRegion');
    const element = document.createElement('div');
    element.className = `toast${error ? ' error' : ''}`;
    element.innerHTML = `${icon(error ? 'alert' : 'check')}<span>${escapeHtml(message)}</span>`;
    region.appendChild(element);
    window.setTimeout(() => element.remove(), 3600);
  }

  function animateNumber(element, end, formatter, animate = true) {
    if (!element) return;
    const target = Number(end || 0);
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!animate || reduce) { element.textContent = formatter(target); return; }
    const start = performance.now();
    const duration = 800;
    const frame = (time) => {
      const progress = Math.min(1, (time - start) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      element.textContent = formatter(target * eased);
      if (progress < 1) requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }

  function ringMarkup(score, band, large = false) {
    const size = large ? 64 : 44;
    const radius = large ? 28 : 18;
    const circumference = large ? 175.93 : 113.1;
    const offset = circumference * (1 - Math.max(0, Math.min(100, Number(score))) / 100);
    return `<svg class="score-ring${large ? ' large' : ''}" viewBox="0 0 ${size} ${size}" role="img" aria-label="${riskLabel(band)} risk score ${Math.round(score)} out of 100"><circle class="ring-track" cx="${size / 2}" cy="${size / 2}" r="${radius}"></circle><circle class="ring-value" cx="${size / 2}" cy="${size / 2}" r="${radius}" stroke="${riskColor(band)}" stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"></circle><text x="${size / 2}" y="${size / 2}">${Math.round(score)}</text></svg>`;
  }

  function caseCard(caseItem, index, compact = false) {
    const outside = index >= state.budget;
    const reasons = (caseItem.reasons || []).filter((item) => item.source !== 'model');
    const visibleReasons = reasons.slice(0, 3);
    const extra = Math.max(0, reasons.length - visibleReasons.length);
    const chips = visibleReasons.map((reason) => `<span class="reason-chip" title="${escapeHtml(reason.explanation)}">${escapeHtml(reason.rule_name)}</span>`).join('');
    return `<button class="case-card${outside ? ' outside-budget' : ''}" data-case-id="${escapeHtml(caseItem.id)}" aria-label="Open case ${escapeHtml(caseItem.title)}, ${riskLabel(caseItem.risk_band)} risk ${Math.round(caseItem.risk_score)}${outside ? ', outside review budget' : ''}">
      ${ringMarkup(caseItem.risk_score, caseItem.risk_band)}
      <span class="case-main"><span class="case-title-line"><span class="case-title">${escapeHtml(caseItem.title)}</span><span class="case-id">${escapeHtml(caseItem.id)}</span></span>
      <span class="case-meta"><span>${INT.format(caseItem.account_count)} account${caseItem.account_count === 1 ? '' : 's'}</span><span>·</span><span class="mono">${formatCompactMoney(caseItem.amount)}</span>${caseItem.status && caseItem.status !== 'Open' ? `<span>·</span><span>${escapeHtml(caseItem.status)}</span>` : ''}</span>
      ${chips || extra ? `<span class="reason-chips">${chips}${extra ? `<span class="reason-more">+${extra} more</span>` : ''}</span>` : ''}</span>
      <span class="case-side">${riskPill(caseItem.risk_band, caseItem.risk_score)}<span class="case-amount">${compact ? '' : formatCompactMoney(caseItem.amount)}</span></span>
    </button>`;
  }

  function caseBudgetItems() {
    const list = $('#dashboardCaseList');
    if (!state.cases.length) {
      list.innerHTML = `<div class="list-empty">No cases to show yet. Load sample data or upload a CSV to begin.</div>`;
      return;
    }
    list.innerHTML = state.cases.map((item, index) => caseCard(item, index, true)).join('');
    $$('.case-card', list).forEach((button) => button.addEventListener('click', () => openCase(button.dataset.caseId)));
  }

  function renderFullCases() {
    const list = $('#fullCaseList');
    const summary = $('#fullCaseSummary');
    if (!state.summary) {
      summary.textContent = 'No dataset loaded';
      list.innerHTML = `<div class="list-empty">No cases to show yet. Load sample data or upload a CSV to begin.</div>`;
      return;
    }
    const query = ($('#caseSearch')?.value || '').toLowerCase().trim();
    const filtered = state.cases.filter((item) => `${item.id} ${item.title} ${item.accounts.join(' ')} ${item.reasons.map((reason) => reason.rule_name).join(' ')}`.toLowerCase().includes(query));
    summary.textContent = `${filtered.length} case${filtered.length === 1 ? '' : 's'} · ${state.budget} case${state.budget === 1 ? '' : 's'} in review budget`;
    list.innerHTML = filtered.length ? filtered.map((item) => caseCard(item, state.cases.indexOf(item))).join('') : `<div class="list-empty">No cases match this search.</div>`;
    $$('.case-card', list).forEach((button) => button.addEventListener('click', () => openCase(button.dataset.caseId)));
  }

  function renderQuality(payload = {}) {
    const validation = payload.validation || {};
    const summary = payload.summary || {};
    const raw = Number(validation.rows_received ?? payload.dataset?.rows_received ?? 0);
    const parsed = Number(validation.rows_before_processing ?? raw);
    const accepted = Number(validation.rows_loaded ?? summary.transactions_analysed ?? 0);
    const rejected = Number(validation.rows_rejected ?? summary.rows_rejected ?? 0);
    const duplicates = Number(validation.duplicates_removed ?? summary.duplicates_removed ?? 0);
    const reconciles = validation.row_accounting_reconciles ?? (raw === rejected + duplicates + accepted);
    $('#qualityReceived').textContent = INT.format(raw);
    $('#qualityParsed').textContent = INT.format(parsed);
    $('#qualityAccepted').textContent = INT.format(accepted);
    $('#qualityRejected').textContent = INT.format(rejected);
    $('#qualityDuplicates').textContent = INT.format(duplicates);
    const indicator = $('#qualityReconciled');
    indicator.classList.toggle('good', Boolean(reconciles));
    indicator.classList.toggle('bad', !reconciles);
    indicator.textContent = reconciles
      ? `✓ ${INT.format(raw)} = ${INT.format(rejected)} rejected + ${INT.format(duplicates)} duplicates + ${INT.format(accepted)} processed`
      : `Warning · ${INT.format(raw)} ≠ ${INT.format(rejected)} + ${INT.format(duplicates)} + ${INT.format(accepted)}`;
    const reasonNames = {
      malformed_width: 'Malformed row width', missing_required_value: 'Blank required value', invalid_timestamp: 'Invalid timestamp',
      invalid_amount: 'Non-numeric amount', non_positive_amount: 'Non-positive amount', self_transfer: 'Self-transfer',
      conflicting_txn_id: 'Conflicting transaction ID',
    };
    const reasons = validation.rejected_by_reason || {};
    const entries = Object.entries(reasons).filter(([, count]) => Number(count) > 0);
    $('#qualityReasons').innerHTML = entries.length
      ? entries.map(([reason, count]) => `<span class="quality-reason" title="${escapeHtml(reason)}">${escapeHtml(reasonNames[reason] || reason.replaceAll('_', ' '))}<strong>${INT.format(count)}</strong></span>`).join('')
      : '<span class="muted">No row rejections.</span>';
  }

  const featureColumns = {
    transactions: [
      ['txn_id', 'Transaction'], ['timestamp', 'UTC time'], ['from_account', 'From'], ['to_account', 'To'], ['amount', 'Amount'],
      ['amount_vs_account_avg', 'Amount / avg'], ['txn_count_1h', 'Txns / 1h'], ['txn_count_24h', 'Txns / 24h'],
      ['hour_of_day', 'Hour UTC'], ['distinct_counterparties', 'Counterparties'], ['seconds_since_prev_txn', 'Seconds since prior'],
      ['rule_points', 'Rule pts'], ['matched_rules', 'Matched rules'], ['ml_score', 'ML score'], ['weighted_ml_score', 'Weighted ML'],
      ['final_risk', 'Final risk'], ['risk_band', 'Risk band'], ['transaction_reasons', 'Plain-English reasons'],
    ],
    accounts: [
      ['account_id', 'Account'], ['transaction_count', 'Txns'], ['in_degree', 'In degree'], ['out_degree', 'Out degree'],
      ['total_incoming_amount', 'Total in'], ['total_outgoing_amount', 'Total out'], ['average_outgoing_amount', 'Avg sent'],
      ['distinct_counterparties', 'Counterparties'], ['first_seen', 'First seen UTC'], ['last_seen', 'Last seen UTC'],
      ['max_risk', 'Max risk'], ['case_id', 'Case'],
    ],
  };

  function featureCell(key, value, row) {
    if (value === null || value === undefined || value === '') return '—';
    if (key === 'amount' || key.startsWith('total_') || key.startsWith('average_')) return formatMoney(value);
    if (key === 'amount_vs_account_avg') return `${Number(value).toFixed(2)}×`;
    if (key === 'timestamp' || key.endsWith('_seen')) return escapeHtml(String(value).replace('T', ' ').replace('Z', ' UTC').slice(0, 22));
    if (key === 'matched_rules') return escapeHtml(Array.isArray(value) ? (value.length ? value.join(', ') : 'None') : String(value));
    if (key === 'transaction_reasons') {
      const explanations = Array.isArray(value) ? value.map((reason) => reason.explanation).filter(Boolean) : [];
      return escapeHtml(explanations.length ? explanations.join(' · ') : 'No rule-based reason.');
    }
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (typeof value === 'number') return Number.isInteger(value) ? INT.format(value) : value.toFixed(2);
    return escapeHtml(String(value));
  }

  function renderFeatureRows() {
    const columns = featureColumns[state.featureKind] || featureColumns.transactions;
    const head = $('#featureTableHead');
    const body = $('#featureTableBody');
    head.innerHTML = `<tr>${columns.map(([key, label]) => {
      const sortable = !['matched_rules', 'transaction_reasons'].includes(key);
      const direction = state.featureSortBy === key ? (state.featureSortDirection === 'asc' ? ' ↑' : ' ↓') : '';
      return `<th${['amount','total_incoming_amount','total_outgoing_amount','average_outgoing_amount'].includes(key) ? ' class="num-cell"' : ''}>${sortable ? `<button class="feature-sort-button" type="button" data-sort-feature="${key}" aria-label="Sort by ${escapeHtml(label)}">${escapeHtml(label)}${direction}</button>` : escapeHtml(label)}</th>`;
    }).join('')}</tr>`;
    body.innerHTML = state.featureRows.length ? state.featureRows.map((row) => `<tr>${columns.map(([key]) => `<td${['amount','total_incoming_amount','total_outgoing_amount','average_outgoing_amount'].includes(key) ? ' class="num-cell"' : ''}>${featureCell(key, row[key], row)}</td>`).join('')}</tr>`).join('') : `<tr><td colspan="${columns.length}">${state.summary ? 'No feature rows available.' : 'Load a dataset to browse features.'}</td></tr>`;
    const from = state.featureTotal ? state.featureOffset + 1 : 0;
    const to = Math.min(state.featureOffset + state.featureRows.length, state.featureTotal);
    $('#featurePageSummary').textContent = state.featureTotal ? `Rows ${INT.format(from)}–${INT.format(to)} of ${INT.format(state.featureTotal)} ${state.featureKind}` : 'No rows';
    $('#featurePreviewSummary').textContent = state.featureKind === 'transactions'
      ? 'Actual scored transaction rows; the six model inputs and score components are inspectable.'
      : 'Actual account aggregates with incoming/outgoing volume, activity span, maximum risk, and linked case.';
    $('#featurePrev').disabled = state.featureOffset <= 0;
    $('#featureNext').disabled = state.featureOffset + state.featureLimit >= state.featureTotal;
    $('#transactionFeaturesTab').setAttribute('aria-pressed', String(state.featureKind === 'transactions'));
    $('#accountFeaturesTab').setAttribute('aria-pressed', String(state.featureKind === 'accounts'));
    $$('[data-sort-feature]', head).forEach((button) => button.addEventListener('click', () => {
      const key = button.dataset.sortFeature;
      state.featureSortDirection = state.featureSortBy === key && state.featureSortDirection === 'asc' ? 'desc' : 'asc';
      state.featureSortBy = key;
      state.featureOffset = 0;
      loadFeatureRows();
    }));
  }

  async function loadFeatureRows() {
    if (!state.summary) { state.featureRows = []; state.featureTotal = 0; renderFeatureRows(); return; }
    const query = new URLSearchParams({ kind: state.featureKind, offset: String(state.featureOffset), limit: String(state.featureLimit), direction: state.featureSortDirection });
    if (state.featureSortBy) query.set('sort_by', state.featureSortBy);
    try {
      const result = await api(`/api/features?${query.toString()}`);
      state.featureRows = result.rows || [];
      state.featureTotal = Number(result.total || 0);
      renderFeatureRows();
    } catch (error) {
      $('#featureTableBody').innerHTML = `<tr><td colspan="20">${escapeHtml(error.message)}</td></tr>`;
      $('#featurePageSummary').textContent = 'Feature preview unavailable';
    }
  }

  function computeCoverageAt(budget) {
    const selected = state.cases.slice(0, budget);
    if (!state.summary) return { percent: 0, amount: 0, fraudulentCases: 0 };
    if (state.summary.has_ground_truth) {
      const point = state.coverage?.coverage_curve?.find((entry) => Number(entry.budget) === Math.min(budget, state.cases.length));
      return { percent: Number(point?.coverage_percent || 0), amount: 0, fraudulentCases: null, precision: null };
    }
    const total = Number(state.summary.risk_score_total ?? state.summary.risk_exposure_total ?? 0);
    const covered = selected.reduce((sum, item) => sum + Number(item.risk_score || 0), 0);
    return { percent: total ? covered / total * 100 : 0, amount: covered, fraudulentCases: null, precision: null };
  }

  function setSliderFill() {
    const slider = $('#budgetSlider');
    if (!slider) return;
    const pct = ((Number(slider.value) - Number(slider.min)) / (Number(slider.max) - Number(slider.min))) * 100;
    slider.style.setProperty('--range-fill', `${pct}%`);
  }

  function updateCoverageAndChart() {
    if (!state.summary) return;
    const coverageCurve = state.coverage?.coverage_curve || [];
    const computed = computeCoverageAt(state.budget);
    const backendCoverage = state.coverage && state.coverage.reviewed_count === Math.min(state.budget, state.cases.length) ? state.coverage : null;
    const coverage = backendCoverage ? {
      ...computed,
      percent: backendCoverage.coverage_percent,
      amount: state.summary.has_ground_truth ? backendCoverage.covered_value : computed.amount,
      fraudulentCases: backendCoverage.fraudulent_cases_reviewed,
      precision: backendCoverage.precision,
      coverage_curve: backendCoverage.coverage_curve || coverageCurve,
    } : { ...computed, coverage_curve: coverageCurve };
    state.coverage = coverage;
    const pct = Math.round(coverage.percent * 10) / 10;
    const sentence = state.summary.has_ground_truth
      ? `Review ${state.budget} cases per day and catch about ${pct}% of fraud value.`
      : `Review ${state.budget} cases per day and cover about ${pct}% of model risk score.`;
    $('#budgetSentence').textContent = sentence;
    $('#coverageValue').textContent = `${pct}%`;
    $('#chartCurrentValue').textContent = `${pct}%`;
    $('#coverageLabel').textContent = state.summary.has_ground_truth ? 'FRAUD VALUE COVERED' : 'MODEL RISK COVERED';
    $('#coverageFootnote').textContent = state.summary.has_ground_truth
      ? backendCoverage ? `${formatMoney(coverage.amount)} of ${formatMoney(backendCoverage.total_value ?? state.summary.fraud_value_total)} · ${coverage.fraudulentCases ?? 0} reviewed cases with fraud · ${Math.round(coverage.precision || 0)}% precision` : 'Refreshing exact fraud value and precision for this budget…'
      : 'Risk-score coverage, not confirmed fraud';
    const coverageLabel = state.summary.has_ground_truth ? 'Fraud value caught' : 'Risk-score coverage';
    $('#chartLegendCoverage').textContent = coverageLabel;
    $('#chartCaption').textContent = state.summary.has_ground_truth ? 'Synthetic fraud value covered by reviewed cases.' : 'Model risk-score coverage; no ground-truth labels available.';
    caseBudgetItems();
    $('#caseCountSummary').textContent = `Showing top ${Math.min(state.budget, state.cases.length)} of ${state.cases.length} cases.`;
    renderFullCases();
    updateChart();
  }

  function chartData() {
    const labels = [];
    const points = [];
    const random = [];
    const maxCases = Math.max(1, state.cases.length);
    for (let amount = 1; amount <= maxCases; amount += 1) {
      const reviewed = Math.min(amount, state.cases.length);
      labels.push(String(amount));
      points.push(Number(computeCoverageAt(reviewed).percent.toFixed(1)));
      random.push(state.cases.length ? Math.min(100, reviewed / state.cases.length * 100) : 0);
    }
    return { labels, points, random };
  }

  function createChart() {
    const canvas = $('#coverageChart');
    if (!canvas || !window.Chart || !state.summary) return;
    if (state.chart) { state.chart.destroy(); state.chart = null; }
    const { labels, points, random } = chartData();
    const ctx = canvas.getContext('2d');
    const gradient = ctx.createLinearGradient(0, 0, 0, canvas.clientHeight || 270);
    gradient.addColorStop(0, 'rgba(34,211,238,.22)');
    gradient.addColorStop(1, 'rgba(34,211,238,0)');
    const selectedIdx = Math.max(0, Math.min(labels.length - 1, state.budget - 1));
    state.chart = new Chart(ctx, {
      type: 'line',
      data: { labels, datasets: [
        { label: state.summary.has_ground_truth ? 'Fraud value caught' : 'Risk-score coverage', data: points, borderColor: '#22D3EE', backgroundColor: gradient, fill: true, tension: .34, borderWidth: 2, pointRadius: labels.map((_, index) => index === selectedIdx ? 5 : 1.5), pointHoverRadius: 5, pointBackgroundColor: labels.map((_, index) => index === selectedIdx ? '#22D3EE' : '#8FA1BF'), pointBorderColor: '#0B1220' },
        { label: 'Random review', data: random, borderColor: '#8FA1BF', borderDash: [5, 5], borderWidth: 1, pointRadius: 0, fill: false, tension: 0 },
      ] },
      options: { responsive: true, maintainAspectRatio: false, animation: { duration: 450 }, interaction: { intersect: false, mode: 'index' }, plugins: { legend: { display: false }, tooltip: { backgroundColor: '#16223A', borderColor: '#2B3A5C', borderWidth: 1, padding: 10, titleColor: '#E6EDF7', bodyColor: '#E6EDF7', titleFont: { family: 'JetBrains Mono, monospace', size: 12 }, bodyFont: { family: 'JetBrains Mono, monospace', size: 12 }, callbacks: { label: (item) => `${item.dataset.label}: ${item.parsed.y.toFixed(1)}%` } } }, scales: { x: { title: { display: false }, grid: { display: false }, ticks: { color: '#8FA1BF', maxTicksLimit: 6, font: { family: 'JetBrains Mono, monospace', size: 12 } } }, y: { min: 0, max: 100, ticks: { stepSize: 25, color: '#8FA1BF', callback: (value) => `${value}%`, font: { family: 'JetBrains Mono, monospace', size: 12 } }, grid: { color: 'rgba(43,58,92,.48)', drawBorder: false }, border: { display: false } } } },
    });
  }

  function updateChart() {
    if (!state.summary) return;
    if (!state.chart) { createChart(); return; }
    const { labels, points, random } = chartData();
    const selectedIdx = Math.max(0, Math.min(labels.length - 1, state.budget - 1));
    state.chart.data.labels = labels;
    state.chart.data.datasets[0].data = points;
    state.chart.data.datasets[1].data = random;
    state.chart.data.datasets[0].pointRadius = labels.map((_, index) => index === selectedIdx ? 5 : 1.5);
    state.chart.data.datasets[0].pointBackgroundColor = labels.map((_, index) => index === selectedIdx ? '#22D3EE' : '#8FA1BF');
    state.chart.update();
  }

  function updateDashboard() {
    const loaded = Boolean(state.summary);
    $('#dashboardEmpty').hidden = loaded;
    $('#dashboardContent').hidden = !loaded;
    $('#clearDataBtn').hidden = !loaded;
    $('#dashboardDataState').textContent = loaded ? `${INT.format(state.summary.transactions_analysed)} rows processed` : 'Waiting for data';
    if (!loaded) return;
    animateNumber($('#kpiTransactions'), state.summary.transactions_analysed, (value) => INT.format(value), state.firstKpiLoad);
    animateNumber($('#kpiFlagged'), state.summary.flagged_transactions, (value) => INT.format(value), state.firstKpiLoad);
    animateNumber($('#kpiCases'), state.summary.cases_found, (value) => INT.format(value), state.firstKpiLoad);
    animateNumber($('#kpiAmount'), state.summary.amount_at_risk, (value) => formatMoney(value), state.firstKpiLoad);
    $('#flaggedCaseSummary').textContent = `${INT.format(state.summary.flagged_transactions || 0)} flagged transactions → ${INT.format(state.summary.cases_found || 0)} cases`;
    const counts = state.summary.status_counts || {};
    $('#statusOpen').textContent = INT.format(counts.Open || 0);
    $('#statusConfirmed').textContent = INT.format(counts.Confirmed || 0);
    $('#statusFalsePositive').textContent = INT.format(counts['Marked as false positive'] || 0);
    $('#statusEscalated').textContent = INT.format(counts.Escalated || 0);
    renderQuality({ validation: state.dataset?.validation || {}, summary: state.summary });
    state.firstKpiLoad = false;
    state.budget = Math.max(1, Math.min(state.budget, state.cases.length || 1));
    $('#budgetSlider').min = '1';
    $('#budgetSlider').max = String(Math.max(1, state.cases.length));
    $('#budgetMaxTick').textContent = INT.format(state.cases.length);
    $('#budgetNumber').textContent = String(state.budget);
    $('#budgetSlider').value = String(state.budget);
    setSliderFill();
    updateCoverageAndChart();
    loadFeatureRows();
  }

  function setDataset(payload) {
    if (!state.summary) state.budget = Number(state.settings?.alert_budget_default || 20);
    state.dataset = { ...(payload.dataset || {}), validation: payload.validation || payload.dataset?.validation || {} };
    state.summary = payload.summary;
    state.cases = payload.cases || [];
    state.coverage = payload.coverage || null;
    state.featureOffset = 0;
    state.pipelineReport = payload.pipeline || null;
    state.pipelineDetail = null;
    renderPipelineProgress(state.pipelineReport);
    if (!$('#caseDrawer').hidden) closeDrawer();
    $('#datasetName').textContent = payload.dataset?.filename || 'Dataset loaded';
    $('#datasetName').title = payload.dataset?.filename || '';
    $('#datasetRows').textContent = `${INT.format(payload.dataset?.row_count || 0)} rows`;
    state.graphLoaded = false;
    state.graphNodes = [];
    state.graphEdges = [];
    state.graphRings = [];
    if (state.graph) { state.graph.destroy(); state.graph = null; state.visNodes = null; state.visEdges = null; }
    updateDashboard();
    setBudget(state.budget);
    if (state.page === 'network') ensureGraph().catch((error) => toast(error.message, true));
    if (state.page === 'cases') renderFullCases();
  }

  async function clearData() {
    if (!state.summary || !window.confirm('Clear the active in-memory dataset, cases, statuses, and pipeline results? Detection settings will be preserved.')) return;
    try {
      const payload = await api('/api/data', { method: 'DELETE' });
      state.dataset = null;
      state.summary = null;
      state.cases = [];
      state.coverage = null;
      state.pipelineReport = payload.pipeline || null;
      state.pipelineDetail = null;
      state.featureRows = [];
      state.featureTotal = 0;
      state.featureOffset = 0;
      state.budget = 1;
      state.graphLoaded = false;
      state.graphNodes = [];
      state.graphEdges = [];
      state.graphRings = [];
      if (state.graph) { state.graph.destroy(); state.graph = null; state.visNodes = null; state.visEdges = null; }
      if (state.chart) { state.chart.destroy(); state.chart = null; }
      $('#datasetName').textContent = 'No dataset loaded';
      $('#datasetName').title = '';
      $('#datasetRows').textContent = '— rows';
      $('#budgetSlider').min = '1';
      $('#budgetSlider').max = '1';
      $('#budgetSlider').value = '1';
      $('#budgetMaxTick').textContent = '0';
      $('#budgetNumber').textContent = '1';
      $('#budgetSentence').textContent = 'Load a dataset to calculate coverage.';
      $('#coverageValue').textContent = '—';
      $('#coverageFootnote').textContent = 'Calculated from the active dataset';
      renderPipelineProgress(state.pipelineReport);
      renderFullCases();
      renderFeatureRows();
      updateDashboard();
      setPage('home');
      toast(payload.message || 'Dataset and investigation results cleared. Settings were preserved.');
    } catch (error) { toast(error.message, true); }
  }

  async function loadSample() {
    const buttons = $$('[data-action="sample"],#loadSampleBtn');
    buttons.forEach((button) => { button.disabled = true; button.dataset.previousText = button.textContent.trim(); });
    try {
      const payload = await api(`/api/sample?budget=${state.budget}`);
      setDataset(payload);
      setPage('dashboard');
      toast(payload.message || 'Sample data loaded.');
    } catch (error) { toast(error.message, true); }
    finally { buttons.forEach((button) => { button.disabled = false; }); }
  }

  function openUpload() {
    state.uploadOpener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    $('#uploadOverlay').hidden = false;
    $('#uploadFeedback').textContent = '';
    $('#uploadFeedback').className = 'upload-feedback';
    window.setTimeout(() => $('#chooseFile').focus(), 0);
  }

  function closeUpload() {
    if (state.uploadBusy) return;
    $('#uploadOverlay').hidden = true;
    $('#csvInput').value = '';
    const opener = state.uploadOpener;
    state.uploadOpener = null;
    if (opener?.isConnected) opener.focus({ preventScroll: true });
  }

  async function uploadFile(file) {
    if (!file) return;
    const feedback = $('#uploadFeedback');
    if (file.size > 20 * 1024 * 1024) {
      feedback.textContent = 'CSV exceeds the 20 MB file-size limit. The current dataset has not been changed.';
      feedback.className = 'upload-feedback error';
      return;
    }
    if (!file.name.toLowerCase().endsWith('.csv')) {
      feedback.textContent = 'Please choose a .csv file. The current dataset has not been changed.';
      feedback.className = 'upload-feedback error';
      return;
    }
    state.uploadBusy = true;
    feedback.textContent = 'Validating and analysing transactions…';
    feedback.className = 'upload-feedback';
    $('#chooseFile').disabled = true;
    try {
      const form = new FormData();
      form.append('file', file, file.name);
      const payload = await api(`/api/upload?budget=${state.budget}`, { method: 'POST', body: form });
      feedback.textContent = payload.message;
      feedback.className = 'upload-feedback success';
      setDataset(payload);
      setPage('dashboard');
      toast(payload.message || 'CSV uploaded and analysed.');
      window.setTimeout(closeUpload, 500);
    } catch (error) {
      feedback.textContent = error.message;
      feedback.className = 'upload-feedback error';
    } finally {
      state.uploadBusy = false;
      $('#chooseFile').disabled = false;
    }
  }

  function setBudget(value) {
    state.budget = Math.max(1, Math.min(Math.max(1, state.cases.length), Number(value) || 1));
    $('#budgetNumber').textContent = String(state.budget);
    $('#budgetSlider').value = String(state.budget);
    setSliderFill();
    if (!state.summary) return;
    updateCoverageAndChart();
    const requestId = ++budgetRequestId;
    window.clearTimeout(budgetTimer);
    budgetTimer = window.setTimeout(async () => {
      try {
        const payload = await api(`/api/cases?budget=${state.budget}`);
        if (requestId !== budgetRequestId) return;
        state.cases = payload.cases || [];
        state.coverage = payload.coverage || null;
        updateCoverageAndChart();
      } catch (error) {
        if (requestId === budgetRequestId) toast(error.message, true);
      }
    }, 110);
  }

  async function openCase(caseId, { focusNetwork = true } = {}) {
    const fallback = state.cases.find((item) => item.id === caseId);
    if (!fallback) return;
    if ($('#caseDrawer').hidden) state.drawerOpener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    try { state.caseDetail = await api(`/api/case/${encodeURIComponent(caseId)}`); }
    catch { state.caseDetail = fallback; }
    state.drawerMode = 'case';
    state.selectedCaseId = caseId;
    renderDrawer(state.caseDetail);
    $('#drawerBackdrop').hidden = false;
    $('#caseDrawer').hidden = false;
    $('#closeDrawer').focus();
    if (focusNetwork && state.page === 'network') ensureGraph().then(() => focusCase(caseId, false)).catch(() => {});
  }

  async function openAccount(accountId) {
    if ($('#caseDrawer').hidden) state.drawerOpener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    try {
      state.caseDetail = await api(`/api/account/${encodeURIComponent(accountId)}`);
      state.drawerMode = 'account';
      state.selectedCaseId = null;
      renderDrawer(state.caseDetail);
      $('#drawerBackdrop').hidden = false;
      $('#caseDrawer').hidden = false;
      $('#closeDrawer').focus();
    } catch (error) { toast(error.message, true); }
  }

  function closeDrawer() {
    $('#caseDrawer').hidden = true;
    $('#drawerBackdrop').hidden = true;
    state.selectedCaseId = null;
    state.caseDetail = null;
    state.drawerMode = null;
    if (state.focusedAccounts) clearGraphFocus();
    const opener = state.drawerOpener;
    state.drawerOpener = null;
    if (opener?.isConnected) opener.focus({ preventScroll: true });
    else if (state.page === 'network') $('#networkCanvas')?.focus({ preventScroll: true });
  }

  function trapDialogFocus(event, dialog) {
    if (!dialog) return;
    const focusable = $$('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])', dialog)
      .filter((element) => !element.hidden && element.getClientRects().length > 0);
    if (!focusable.length) { event.preventDefault(); return; }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
      event.preventDefault(); first.focus();
    }
  }

  function caseGraphMarkup(graph) {
    const nodes = (graph?.nodes || []).slice(0, 32);
    const accounts = new Set(nodes.map((node) => node.id));
    const edges = (graph?.edges || []).filter((edge) => accounts.has(edge.from) && accounts.has(edge.to)).slice(0, 80);
    if (!nodes.length || !edges.length) return '<p class="drawer-empty">No account-transfer graph is available for this case.</p>';
    const positions = new Map(nodes.map((node, index) => {
      const angle = -Math.PI / 2 + (Math.PI * 2 * index / nodes.length);
      return [node.id, { x: 240 + Math.cos(angle) * 205, y: 138 + Math.sin(angle) * 96 }];
    }));
    const edgeMarkup = edges.map((edge) => {
      const from = positions.get(edge.from); const to = positions.get(edge.to);
      if (!from || !to) return '';
      const ring = Boolean(edge.is_ring);
      const width = Math.max(1, Math.min(4, 1 + Math.log10(Number(edge.amount || 0) + 1) / 2));
      const color = ring ? 'var(--risk-ring)' : riskColor(edge.risk_band);
      const title = `${edge.from} to ${edge.to}; ${edge.transaction_count} transfers; ${formatMoney(edge.amount)} total${ring ? '; detected ring link' : ''}`;
      return `<line x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" stroke="${color}" stroke-width="${width}" opacity="${ring ? '.95' : '.48'}"${ring ? ' stroke-dasharray="5 4" marker-end="url(#caseRingArrow)"' : ' marker-end="url(#caseArrow)"'}><title>${escapeHtml(title)}</title></line>`;
    }).join('');
    const nodeMarkup = nodes.map((node) => {
      const point = positions.get(node.id);
      return `<g><circle cx="${point.x}" cy="${point.y}" r="7" fill="${riskColor(node.risk_band)}" stroke="var(--surface)" stroke-width="2"><title>${escapeHtml(node.id)} · ${riskLabel(node.risk_band)} risk ${Math.round(node.risk_score)}</title></circle><text x="${point.x}" y="${point.y - 12}" text-anchor="middle">${escapeHtml(node.id)}</text></g>`;
    }).join('');
    return `<div class="case-mini-graph"><svg viewBox="0 0 480 280" role="img" aria-label="Case transfer graph: ${nodes.length} accounts and ${edges.length} aggregated directed links"><title>Directed account-transfer graph</title><defs><marker id="caseArrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="var(--border-strong)"/></marker><marker id="caseRingArrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="var(--risk-ring)"/></marker></defs><g class="case-mini-edges">${edgeMarkup}</g><g class="case-mini-nodes">${nodeMarkup}</g></svg></div>${graph.nodes?.length > nodes.length || graph.edges?.length > edges.length ? `<p class="drawer-empty">Showing ${nodes.length} of ${graph.nodes?.length || 0} accounts and ${edges.length} of ${graph.edges?.length || 0} transfer links.</p>` : ''}`;
  }

  function renderDrawer(item) {
    const accountView = state.drawerMode === 'account';
    $('#drawerCaseId').textContent = accountView ? `ACCOUNT ${item.account_id || item.id}` : `CASE ${item.id}`;
    $('#drawerTitle').textContent = item.title || (accountView ? `Account ${item.id}` : 'Case');
    $('#caseDrawer').setAttribute('aria-label', accountView ? 'Account details' : 'Case details');
    $('#closeDrawer').setAttribute('aria-label', accountView ? 'Close account details' : 'Close case details');
    $('.drawer-action-buttons').hidden = accountView;
    const status = item.status || 'Open';
    $('#drawerStatus').innerHTML = accountView
      ? `<span class="drawer-status-pill">${item.case_id ? `Linked case ${escapeHtml(item.case_id)} · ${escapeHtml(status)}` : 'No linked case'}</span>`
      : status === 'Open' ? '' : `<span class="drawer-status-pill">${escapeHtml(status)}</span>`;
    const reasons = item.reasons?.length ? item.reasons : [{ rule_name: 'Unusual behaviour', explanation: 'The model observed activity that differs from the rest of this dataset.', source: 'model', threshold: '' }];
    const transactions = item.transactions || [];
    const recent = accountView ? transactions.slice(-80).reverse() : transactions.slice(-80).reverse();
    const reasonMarkup = reasons.map((reason) => `<article class="drawer-reason"><span class="reason-icon">${icon(reason.source === 'model' ? 'spark' : reason.rule_id === 'circular_flow' ? 'network' : 'alert')}</span><div><p>${escapeHtml(reason.explanation)}</p><small>${escapeHtml(reason.rule_name || 'Risk evidence')}${reason.points ? ` · <span class="mono">+${reason.points} pts</span>` : ''}${reason.threshold ? ` · ${escapeHtml(reason.threshold)}` : ''}</small></div></article>`).join('');
    const timelineMarkup = recent.length ? recent.map((txn) => {
      const time = new Date(txn.timestamp).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }) + ' UTC';
      const rulePoints = Number(txn.rule_points || 0);
      const mlScore = Number(txn.ml_score || 0);
      const weightedMl = Number(txn.weighted_ml_score ?? (0.4 * mlScore));
      const finalRisk = Number(txn.final_risk ?? txn.risk_score ?? Math.min(100, rulePoints + weightedMl));
      const capped = Boolean(txn.score_capped || txn.capped_at_100 || Number(txn.uncapped_score || 0) >= 100);
      const transactionReasons = txn.reasons || txn.transaction_reasons || [];
      const explanation = transactionReasons.map((reason) => reason.explanation).filter(Boolean).slice(0, 1).join(' ');
      const scoreLine = `Rule ${rulePoints} + 0.4 × ML ${mlScore.toFixed(1)} = ${weightedMl.toFixed(1)} → ${finalRisk.toFixed(1)} final risk${capped ? ' · capped at 100' : ''}`;
      return `<div class="timeline-item${txn.is_flagged ? ' flagged' : ''}"><span class="timeline-time">${escapeHtml(time)}</span><div class="timeline-flow"><span class="mono">${escapeHtml(txn.from_account)}</span> → <span class="mono">${escapeHtml(txn.to_account)}</span></div><strong class="timeline-amount">${formatMoney(txn.amount)}</strong><span class="timeline-score mono">${escapeHtml(scoreLine)}</span><span class="timeline-context">${escapeHtml(txn.channel || 'Transfer')} · ${escapeHtml(txn.city || 'City not supplied')}${explanation ? ` · ${escapeHtml(explanation)}` : ''}</span></div>`;
    }).join('') : '<p class="drawer-empty">No associated transactions.</p>';
    const rings = item.rings || [];
    const ringCards = rings.map((ring) => `<article class="drawer-ring-card"><div><strong>${escapeHtml(ring.type_label)} · ${escapeHtml(ring.id)}</strong><span>${INT.format(ring.transaction_count)} transfers · ${formatMoney(ring.total_value)} · ${riskLabel(ring.risk_band)} ${Math.round(ring.risk_score)}</span></div><p>${escapeHtml(ring.explanation || '')}</p></article>`).join('');
    const linkedCase = accountView && item.case_id ? `<button type="button" class="btn btn-secondary drawer-linked-case" data-linked-case="${escapeHtml(item.case_id)}">Open linked case ${escapeHtml(item.case_id)}</button>` : '';
    const graphSection = accountView
      ? `<section class="drawer-section"><h3>Account activity</h3><p class="drawer-empty">Risk is the highest participating transaction risk score. This account has ${INT.format(item.transaction_count || 0)} related transactions; the latest ${Math.min(100, item.transaction_count || 0)} are listed below.</p>${linkedCase}</section>`
      : `<section class="drawer-section"><h3>Account transfer graph</h3>${caseGraphMarkup(item.graph)}</section>`;
    const accountHeading = accountView ? 'Account' : 'Accounts in this case';
    const truncatedNote = item.transaction_rows_truncated || transactions.length > 80 ? `<p class="drawer-empty">Showing the latest ${Math.min(80, transactions.length)} of ${INT.format(item.transaction_count || transactions.length)} associated transactions.</p>` : '';
    $('#drawerBody').innerHTML = `<div class="drawer-risk-summary">${ringMarkup(item.risk_score, item.risk_band, true)}<div class="drawer-risk-details"><span>Risk score · ${riskLabel(item.risk_band)}</span><strong>${Number(item.risk_score || 0).toFixed(1)} / 100</strong><small>${formatMoney(item.amount)} associated value</small></div></div><section class="drawer-section"><h3>${accountView ? 'Account risk reasons' : 'Why this was flagged'}</h3><div class="drawer-reasons">${reasonMarkup}</div></section>${graphSection}${ringCards ? `<section class="drawer-section"><h3>Detected rings · ${rings.length}</h3><div class="drawer-ring-list">${ringCards}</div></section>` : ''}<section class="drawer-section"><h3>Transaction timeline <span class="muted">· ${INT.format(item.transaction_count || transactions.length)}</span></h3><div class="timeline">${timelineMarkup}</div>${truncatedNote}</section><section class="drawer-section"><h3>${accountHeading}</h3><p class="account-tags">${(item.accounts || []).map((account) => `<span class="account-tag mono">${escapeHtml(account)}</span>`).join('')}</p><p class="drawer-model-meta mono">Rule points ${item.rule_points ?? '—'} · ML score ${Number(item.ml_score || 0).toFixed(1)}</p></section>`;
    $$('[data-linked-case]', $('#drawerBody')).forEach((button) => button.addEventListener('click', () => openCase(button.dataset.linkedCase)));
  }

  async function changeCaseStatus(status) {
    if (!state.caseDetail) return;
    try {
      const result = await api(`/api/case/${encodeURIComponent(state.caseDetail.id)}/status`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) });
      state.caseDetail.status = result.status;
      if (state.summary) state.summary.status_counts = result.status_counts;
      const item = state.cases.find((entry) => entry.id === result.id);
      if (item) item.status = result.status;
      const counts = result.status_counts || {};
      $('#statusOpen').textContent = INT.format(counts.Open || 0);
      $('#statusConfirmed').textContent = INT.format(counts.Confirmed || 0);
      $('#statusFalsePositive').textContent = INT.format(counts['Marked as false positive'] || 0);
      $('#statusEscalated').textContent = INT.format(counts.Escalated || 0);
      renderDrawer(state.caseDetail);
      caseBudgetItems();
      renderFullCases();
      toast(`Case ${result.id}: ${result.status.toLowerCase()}.`);
    } catch (error) { toast(error.message, true); }
  }

  async function ensureGraph() {
    if (!state.summary) {
      $('#graphEmpty').hidden = false;
      return;
    }
    if (state.graphLoaded && state.graph) return;
    const payload = await api('/api/graph');
    state.graphNodes = payload.nodes || [];
    state.graphEdges = payload.edges || [];
    state.graphNodeById = new Map(state.graphNodes.map((node) => [node.id, node]));
    state.graphEdgeById = new Map(state.graphEdges.map((edge) => [edge.id, edge]));
    state.networkTablePage = 0;
    state.graphRings = payload.rings || [];
    state.graphStats = payload.stats || null;
    state.maxEdgeAmount = Math.max(1, ...state.graphEdges.map((edge) => Number(edge.amount || 0)));
    state.graphLoaded = true;
    $('#graphEmpty').hidden = state.graphNodes.length > 0;
    $('#graphCounts').textContent = `${INT.format(state.graphNodes.length)} accounts · ${INT.format(state.graphEdges.length)} aggregated links`;
    $('.graph-legend').innerHTML = `<b>RISK LEVEL</b><span><i class="risk-dot low"></i>Low</span><span><i class="risk-dot med"></i>Medium</span><span><i class="risk-dot high"></i>High</span><hr><span><i class="legend-dash"></i>Detected ring links</span><small>Node size = transaction volume<br>Edge width = total transfer value<br>Arrow direction = money movement</small>`;
    $('.graph-access-note').innerHTML = `${icon('info')}<span>One directed link aggregates all transfers between an account pair. Risk is a review signal; use Table view for keyboard-accessible detail.</span>`;
    drawGraph();
    renderNetworkTable();
  }

  function cssHex(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function hexRgba(color, opacity) {
    const match = color.match(/^#([0-9a-f]{6})$/i);
    if (!match) return `rgba(143,161,191,${opacity})`;
    const num = parseInt(match[1], 16);
    return `rgba(${(num >> 16) & 255},${(num >> 8) & 255},${num & 255},${opacity})`;
  }

  function prepareNode(node, opacity = 1) {
    const palette = node.flagged
      ? ({ low: cssHex('--risk-low', '#22C55E'), medium: cssHex('--risk-med', '#F59E0B'), high: cssHex('--risk-high', '#EF4444') }[node.risk_band])
      : '#45536B';
    const volume = Number(node.transaction_volume || 0);
    const size = Math.max(8, Math.min(34, 8 + Math.log1p(volume) * 5.1));
    const color = hexRgba(palette || '#45536B', node.flagged ? opacity : Math.min(.3, opacity * .3));
    const labelColor = node.flagged ? hexRgba('#E6EDF7', opacity) : 'rgba(230,237,247,0)';
    return {
      id: node.id, label: node.flagged ? node.id : '', title: '', shape: 'dot', size,
      color: { background: color, border: node.flagged ? hexRgba('#E6EDF7', opacity) : 'rgba(69,83,107,.15)', highlight: { background: color, border: '#E6EDF7' }, hover: { background: color, border: '#E6EDF7' } },
      borderWidth: node.flagged ? 2 : 0, borderWidthSelected: 2,
      font: { color: labelColor, face: 'Inter, system-ui, sans-serif', size: 12, strokeWidth: 0, vadjust: -2 },
      shadow: node.flagged ? { enabled: opacity > .25, color: hexRgba(palette || '#EF4444', .32 * opacity), size: 11, x: 0, y: 0 } : false,
      risk_score: node.risk_score, risk_band: node.risk_band, flagged: node.flagged,
      transaction_volume: node.transaction_volume, top_reason: node.top_reason, case_id: node.case_id,
    };
  }

  function prepareEdge(edge) {
    const ring = Boolean(edge.is_ring);
    const stroke = ring ? cssHex('--risk-ring', '#FF3B5C') : ({
      low: cssHex('--risk-low', '#22C55E'), medium: cssHex('--risk-med', '#F59E0B'), high: cssHex('--risk-high', '#EF4444'),
    }[edge.risk_band] || cssHex('--border-strong', '#2B3A5C'));
    return {
      id: edge.id, from: edge.from, to: edge.to,
      width: Math.max(1, Math.min(6, 1 + 5 * Math.sqrt(Number(edge.amount || 0) / state.maxEdgeAmount))),
      arrows: { to: { enabled: true, scaleFactor: .45 } },
      color: { color: stroke, opacity: ring ? 1 : .58, highlight: stroke, hover: stroke },
      dashes: ring, smooth: { enabled: false },
      title: '', amount: edge.amount, transaction_count: edge.transaction_count,
      first_timestamp: edge.first_timestamp, last_timestamp: edge.last_timestamp,
      risk_score: edge.risk_score, risk_band: edge.risk_band, ring_ids: edge.ring_ids,
      ring_types: edge.ring_types, is_ring: ring, case_id: edge.case_id,
    };
  }

  function drawGraph() {
    const container = $('#networkCanvas');
    if (!container || !window.vis || !state.graphNodes.length) return;
    if (zoomFrame !== null) cancelAnimationFrame(zoomFrame);
    zoomFrame = null;
    pendingZoomSteps = 0;
    if (state.graph) { state.graph.destroy(); state.graph = null; }
    const nodes = state.graphNodes.map((node) => prepareNode(node));
    const edges = state.graphEdges.map(prepareEdge);
    state.visNodes = new window.vis.DataSet(nodes);
    state.visEdges = new window.vis.DataSet(edges);
    state.graphStable = false;
    state.graph = new window.vis.Network(container, { nodes: state.visNodes, edges: state.visEdges }, {
      autoResize: true,
      interaction: { hover: true, hoverConnectedEdges: false, selectConnectedEdges: false, tooltipDelay: 160, navigationButtons: false, keyboard: { enabled: true, bindToWindow: false }, multiselect: false, hideEdgesOnDrag: true, hideEdgesOnZoom: true, hideNodesOnDrag: false },
      nodes: { chosen: { node: (values) => { values.borderColor = '#E6EDF7'; values.borderWidth = 2; } }, scaling: { min: 8, max: 34 }, font: { face: 'Inter, sans-serif', size: 12 } },
      edges: { selectionWidth: 8, hoverWidth: 2, smooth: { enabled: false } },
      physics: { enabled: true, solver: 'forceAtlas2Based', forceAtlas2Based: { gravitationalConstant: -46, centralGravity: .012, springLength: 116, springConstant: .075, damping: .55, avoidOverlap: .7 }, stabilization: { enabled: true, iterations: 80, updateInterval: 25 }, adaptiveTimestep: true },
    });
    const graph = state.graph;
    graph.once('stabilizationIterationsDone', () => {
      if (state.graph !== graph || state.graphStable) return;
      freezeGraphLayout(graph);
      graph.fit({ animation: false });
    });
    state.graph.on('click', (event) => {
      const ringEdge = (event.edges || [])
        .map((edgeId) => state.graphEdgeById.get(edgeId))
        .find((edge) => edge?.ring_ids?.length);
      if (ringEdge) {
        const ringId = ringEdge.ring_ids[0];
        const linkedCase = state.cases.find((item) => (item.ring_ids || []).includes(ringId));
        void focusRing(ringId, linkedCase?.id || ringEdge.case_id || null)
          .catch((error) => toast(`Could not open ring ${ringId}: ${error.message}`, true));
      } else if (event.nodes?.length) {
        const node = state.graphNodeById.get(event.nodes[0]);
        if (node) openAccount(node.id);
      } else if (event.edges?.length) {
        const edge = state.graphEdgeById.get(event.edges[0]);
        if (edge?.case_id) openCase(edge.case_id);
        else if (edge) toast(`${edge.from} → ${edge.to}: ${INT.format(edge.transaction_count)} transfers, ${formatMoney(edge.amount)} total.`);
      } else {
        clearGraphFocus();
        closeDrawer();
      }
    });
    state.graph.on('hoverNode', (event) => showGraphTooltip(event));
    state.graph.on('blurNode', () => { $('#graphTooltip').hidden = true; });
    state.graph.on('hoverEdge', (event) => showEdgeTooltip(event));
    state.graph.on('blurEdge', () => { $('#graphTooltip').hidden = true; });
    applyGraphFilters({ refreshTable: true });
  }

  function freezeGraphLayout(graph = state.graph) {
    if (!graph || state.graphStable) return false;
    state.graphStable = true;
    graph.setOptions({ physics: { enabled: false } });
    return true;
  }

  function fitGraphToView() {
    const graph = state.graph;
    if (!graph) return;
    freezeGraphLayout(graph);
    graph.fit({ animation: false });
  }

  function zoomGraph(direction) {
    const graph = state.graph;
    const requestedSteps = Math.sign(Number(direction));
    if (!graph || !requestedSteps) return;
    pendingZoomSteps = Math.max(-8, Math.min(8, pendingZoomSteps + requestedSteps));
    if (zoomFrame !== null) return;
    zoomFrame = requestAnimationFrame(() => {
      zoomFrame = null;
      const steps = pendingZoomSteps;
      pendingZoomSteps = 0;
      const currentGraph = state.graph;
      if (!currentGraph || !steps) return;
      freezeGraphLayout(currentGraph);
      const currentScale = currentGraph.getScale();
      const position = currentGraph.getViewPosition();
      if (!Number.isFinite(currentScale) || currentScale <= 0
        || !position || !Number.isFinite(position.x) || !Number.isFinite(position.y)) return;
      const targetScale = Math.min(4, Math.max(.025, currentScale * Math.pow(1.25, steps)));
      if (Math.abs(targetScale - currentScale) < 0.0001) return;
      currentGraph.moveTo({
        position,
        scale: targetScale,
        animation: { duration: 160, easingFunction: 'easeInOutQuad' },
      });
    });
  }

  function showGraphTooltip(event) {
    const node = state.graphNodeById.get(event.node);
    if (!node) return;
    const tip = $('#graphTooltip');
    const rings = node.ring_ids || [];
    tip.innerHTML = `<b>${escapeHtml(node.id)} · ${riskLabel(node.risk_band)} ${Math.round(node.risk_score)}</b><span>${escapeHtml(node.top_reason || 'No rule-based reason.')}</span><span>${INT.format(node.transaction_volume)} transactions · ${node.case_id ? escapeHtml(node.case_id) : 'No case'}</span><span>${rings.length ? `Ring ${escapeHtml(rings.join(', '))}` : 'No detected ring'}</span>`;
    tip.hidden = false;
  }

  function showEdgeTooltip(event) {
    const edge = state.graphEdgeById.get(event.edge);
    if (!edge) return;
    const ringNames = (edge.ring_types || []).map((type) => ({ cycle: 'cycle', community: 'dense community', fan_in: 'fan-in', fan_out: 'fan-out' }[type] || type));
    const tip = $('#graphTooltip');
    tip.innerHTML = `<b>${escapeHtml(edge.from)} → ${escapeHtml(edge.to)}</b><span>${INT.format(edge.transaction_count)} transfers · ${formatMoney(edge.amount)} total</span><span>${riskLabel(edge.risk_band)} edge risk ${Math.round(edge.risk_score)} · last activity ${escapeHtml(String(edge.last_timestamp || '').replace('T', ' ').slice(0, 16))} UTC</span><span>${ringNames.length ? `Ring: ${escapeHtml(ringNames.join(', '))} · ${escapeHtml((edge.ring_ids || []).join(', '))} · click to focus` : edge.case_id ? `Case ${escapeHtml(edge.case_id)} · click to open` : 'No detected ring or linked case'}</span>`;
    tip.hidden = false;
  }

  function applyGraphFilters({ refreshTable = false, skipEdgeUpdate = false } = {}) {
    if (!state.graph || !state.visNodes || !state.visEdges) return;
    const query = ($('#accountSearch').value || '').trim().toLowerCase();
    const flaggedOnly = $('#flaggedOnly').checked;
    const minRisk = Number($('#minRisk').value || 0);
    const filtersActive = Boolean(query) || flaggedOnly || minRisk > 0;
    $('#minRiskValue').textContent = String(minRisk);
    const visibleIds = new Set();
    const focus = state.focusedAccounts ? new Set(state.focusedAccounts) : null;
    const nodes = state.graphNodes.map((node) => {
      const searchMatch = !query || node.id.toLowerCase().includes(query);
      const incidentEdgeRisk = state.graphEdges.reduce((maximum, edge) => edge.from === node.id || edge.to === node.id ? Math.max(maximum, Number(edge.risk_score || 0)) : maximum, 0);
      const riskMatch = Math.max(Number(node.risk_score || 0), incidentEdgeRisk) >= minRisk;
      const filterMatch = searchMatch && riskMatch && (!flaggedOnly || node.flagged);
      const visible = filterMatch || Boolean(focus?.has(node.id));
      if (visible) visibleIds.add(node.id);
      const opacity = focus ? (focus.has(node.id) ? 1 : .12) : 1;
      return { ...prepareNode(node, opacity), hidden: !visible };
    });
    state.visNodes.update(nodes);
    if (!skipEdgeUpdate || filtersActive) {
      const edges = state.graphEdges.map((edge) => ({ ...prepareEdge(edge), hidden: !(visibleIds.has(edge.from) && visibleIds.has(edge.to)) }));
      state.visEdges.update(edges);
    }
    const visibleEdgeCount = filtersActive
      ? state.graphEdges.filter((edge) => visibleIds.has(edge.from) && visibleIds.has(edge.to)).length
      : state.graphEdges.length;
    $('#graphCounts').textContent = `${INT.format(visibleIds.size)} / ${INT.format(state.graphNodes.length)} accounts · ${INT.format(visibleEdgeCount)} aggregated links`;
    if (refreshTable && state.tableMode) renderNetworkTable();
  }

  function focusCase(caseId, showDrawer = true) {
    const item = state.cases.find((entry) => entry.id === caseId);
    if (!item || !state.graph) return;
    freezeGraphLayout(state.graph);
    state.focusedAccounts = item.accounts;
    applyGraphFilters({ skipEdgeUpdate: true });
    state.graph.selectNodes(item.accounts, false);
    state.graph.fit({ nodes: item.accounts, animation: false });
    if (showDrawer) openCase(caseId);
  }

  async function focusRing(ringId, caseId = null) {
    setPage('network');
    await ensureGraph();
    if (caseId) await openCase(caseId, { focusNetwork: false });
    const ring = state.graphRings.find((item) => item.id === ringId);
    const ringEdges = state.graphEdges.filter((edge) => (edge.ring_ids || []).includes(ringId));
    const accounts = ring?.accounts || [...new Set(ringEdges.flatMap((edge) => [edge.from, edge.to]))];
    if (!accounts.length || !state.graph) { toast(`Ring ${ringId} is not present in the active graph.`, true); return; }
    freezeGraphLayout(state.graph);
    state.focusedAccounts = accounts;
    applyGraphFilters({ skipEdgeUpdate: true });
    state.graph.selectNodes(accounts, false);
    state.graph.fit({ nodes: accounts, animation: false });
  }

  function clearGraphFocus() {
    state.focusedAccounts = null;
    if (state.graph) {
      freezeGraphLayout(state.graph);
      state.graph.unselectAll();
      applyGraphFilters({ skipEdgeUpdate: true });
      state.graph.fit({ animation: false });
    }
  }

  function renderNetworkTable() {
    const body = $('#networkTableBody');
    if (!body) return;
    const pageStatus = $('#networkTablePageStatus');
    const previousButton = $('#networkTablePrev');
    const nextButton = $('#networkTableNext');
    if (!state.graphNodes.length) {
      body.innerHTML = '<tr><td colspan="7">Load a dataset to explore transfer links.</td></tr>';
      if (pageStatus) pageStatus.textContent = 'No transfer links';
      if (previousButton) previousButton.disabled = true;
      if (nextButton) nextButton.disabled = true;
      return;
    }
    $('#networkTableWrap thead').innerHTML = '<tr><th>TRANSFER LINK</th><th>FROM</th><th>TO</th><th class="num-cell">TXNS</th><th class="num-cell">TOTAL AMOUNT</th><th>LINK RISK</th><th>CASE / RING</th></tr>';
    const query = ($('#accountSearch')?.value || '').trim().toLowerCase();
    const flaggedOnly = Boolean($('#flaggedOnly')?.checked);
    const minRisk = Number($('#minRisk')?.value || 0);
    const nodes = new Map(state.graphNodes.map((node) => [node.id, node]));
    const edges = state.graphEdges.filter((edge) => {
      const from = nodes.get(edge.from); const to = nodes.get(edge.to);
      const searchMatch = !query || edge.from.toLowerCase().includes(query) || edge.to.toLowerCase().includes(query);
      const riskMatch = Math.max(Number(edge.risk_score || 0), Number(from?.risk_score || 0), Number(to?.risk_score || 0)) >= minRisk;
      return searchMatch && riskMatch && (!flaggedOnly || from?.flagged || to?.flagged);
    });
    const pageCount = Math.max(1, Math.ceil(edges.length / NETWORK_TABLE_PAGE_SIZE));
    state.networkTablePage = Math.max(0, Math.min(state.networkTablePage, pageCount - 1));
    const start = state.networkTablePage * NETWORK_TABLE_PAGE_SIZE;
    const pageEdges = edges.slice(start, start + NETWORK_TABLE_PAGE_SIZE);
    const ringToCase = new Map(state.cases.flatMap((item) => (item.ring_ids || []).map((ringId) => [ringId, item.id])));
    const ringsById = new Map(state.graphRings.map((ring) => [ring.id, ring]));
    body.innerHTML = pageEdges.length ? pageEdges.map((edge) => {
      const from = nodes.get(edge.from); const to = nodes.get(edge.to);
      const caseItem = edge.case_id ? state.cases.find((item) => item.id === edge.case_id) : null;
      const ringTypes = (edge.ring_types || []).map((type) => ({ cycle: 'Cycle', community: 'Community', fan_in: 'Fan-in', fan_out: 'Fan-out' }[type] || type));
      const description = caseItem?.reasons?.[0]?.explanation || ringTypes.join(', ') || from?.top_reason || to?.top_reason || 'No rule-based finding.';
      const caseMarkup = edge.case_id ? `<button type="button" class="table-case-button" data-case-id="${escapeHtml(edge.case_id)}">${escapeHtml(edge.case_id)} · ${escapeHtml(description)}</button>` : escapeHtml(description);
      const ringMarkup = (edge.ring_ids || []).map((ringId, index) => {
        const ring = ringsById.get(ringId);
        const label = ring?.type_label || ringTypes[index] || 'Detected ring';
        const linkedCaseId = ringToCase.get(ringId) || edge.case_id || '';
        const action = linkedCaseId ? `open case ${linkedCaseId} and focus this ring` : 'focus this ring';
        return `<button type="button" class="table-case-button table-ring-link" data-network-ring-id="${escapeHtml(ringId)}" data-ring-case-id="${escapeHtml(linkedCaseId)}" aria-label="${escapeHtml(label)} ${escapeHtml(ringId)}: ${action}" title="${escapeHtml(label)} · ${escapeHtml(ringId)} — ${action}">${escapeHtml(label)} · ${escapeHtml(ringId)}</button>`;
      }).join('');
      return `<tr><td class="mono">${escapeHtml(edge.id)}</td><td class="mono">${escapeHtml(edge.from)}</td><td class="mono">${escapeHtml(edge.to)}</td><td class="num-cell">${INT.format(edge.transaction_count || 0)}</td><td class="num-cell">${formatMoney(edge.amount)}</td><td>${riskPill(edge.risk_band, edge.risk_score)}${edge.is_ring ? '<span class="edge-ring-label">Ring link</span>' : ''}</td><td>${caseMarkup}${ringMarkup}</td></tr>`;
    }).join('') : '<tr><td colspan="7">No transfer links match these filters.</td></tr>';
    if (pageStatus) {
      pageStatus.textContent = edges.length
        ? `Rows ${INT.format(start + 1)}–${INT.format(Math.min(start + pageEdges.length, edges.length))} of ${INT.format(edges.length)} transfer links`
        : 'No matching transfer links';
    }
    if (previousButton) previousButton.disabled = !edges.length || state.networkTablePage === 0;
    if (nextButton) nextButton.disabled = !edges.length || state.networkTablePage >= pageCount - 1;
    const tableScroll = $('.table-scroll', $('#networkTableWrap'));
    if (tableScroll) tableScroll.scrollTop = 0;
    $$('[data-case-id]', body).forEach((button) => button.addEventListener('click', () => openCase(button.dataset.caseId)));
    $$('[data-network-ring-id]', body).forEach((button) => button.addEventListener('click', () => {
      const ringId = button.dataset.networkRingId;
      void focusRing(ringId, button.dataset.ringCaseId || null)
        .catch((error) => toast(`Could not open ring ${ringId}: ${error.message}`, true));
    }));
  }

  async function loadSettings() {
    const payload = await api('/api/settings');
    state.settings = payload.settings;
    state.settingsDefaults = payload.defaults;
    state.settingBounds = payload.bounds || {};
    renderSettings(payload);
  }

  const settingLabels = {
    structuring_threshold: 'Illustrative transaction threshold (₹)', structuring_min_count: 'Minimum transfers', structuring_window_hours: 'Window (hours)', structuring_lower_ratio: 'Lower threshold ratio', structuring_upper_ratio: 'Upper threshold ratio', structuring_points: 'Rule points',
    velocity_min_count: 'Transactions required to trigger', velocity_window_minutes: 'Window (minutes)', velocity_points: 'Rule points',
    odd_hour_start: 'Overnight start hour (UTC)', odd_hour_end: 'Overnight end hour (UTC)', odd_hour_multiplier: 'Multiple of sender average', odd_hour_points: 'Rule points',
    new_signal_min_amount: 'Minimum transfer amount (₹)', new_signal_min_prior_transactions: 'Minimum prior sender transactions', new_signal_points: 'Rule points',
    cycle_min_accounts: 'Minimum accounts in cycle', cycle_max_accounts: 'Maximum accounts in cycle', cycle_window_hours: 'Maximum time window (hours)', cycle_points: 'Rule points',
    fanin_min_senders: 'Distinct sender minimum', fanin_forward_ratio: 'Forwarded share required', fanin_lookback_hours: 'Incoming activity lookback (hours)', fanin_window_minutes: 'Pass-through window (minutes)', fanin_points: 'Rule points',
    flagged_risk_threshold: 'Flag transaction at risk score ≥', risk_medium_threshold: 'Medium risk starts at', risk_high_threshold: 'High risk starts at',
    model_reason_threshold: 'Show anomaly explanation at', alert_budget_default: 'Default daily review budget (cases)',
  };
  const rulesUi = [
    ['structuring', 'Structuring', 'Repeated transfers within a configured share of the illustrative threshold.', ['structuring_threshold','structuring_min_count','structuring_window_hours','structuring_lower_ratio','structuring_upper_ratio','structuring_points']],
    ['velocity', 'Transaction velocity', 'More than the configured transfer count inside a short interval.', ['velocity_min_count','velocity_window_minutes','velocity_points']],
    ['odd_hour', 'Odd-hour activity', 'Large transfers from 1AM through 5AM relative to the sender’s average.', ['odd_hour_start','odd_hour_end','odd_hour_multiplier','odd_hour_points']],
    ['new_signal', 'New device or city', 'A large transfer from a device or city not previously seen after the required prior sender activity.', ['new_signal_min_amount','new_signal_min_prior_transactions','new_signal_points']],
    ['circular_flow', 'Circular flow', 'Directed money cycles are checked against actual timestamps.', ['cycle_min_accounts','cycle_max_accounts','cycle_window_hours','cycle_points']],
    ['fanin', 'Fan-in with pass-through', 'Many distinct senders fund an account within a lookback window; forwarded value must arrive within the configured pass-through interval.', ['fanin_min_senders','fanin_forward_ratio','fanin_lookback_hours','fanin_window_minutes','fanin_points']],
  ];

  function renderSettings(payload = {}) {
    if (!state.settings) return;
    if (payload.bounds) state.settingBounds = payload.bounds;
    const fieldMarkup = (key) => {
      const value = state.settings[key];
      const [minimum, maximum] = state.settingBounds?.[key] || [1, ''];
      const step = key.includes('ratio') ? '.01' : (key.includes('hours') || key.includes('multiplier')) ? '.1' : '1';
      return `<div class="setting-field"><label for="setting-${key}">${escapeHtml(settingLabels[key] || key)}</label><input id="setting-${key}" data-setting="${key}" type="number" step="${step}" min="${escapeHtml(minimum)}" max="${escapeHtml(maximum)}" value="${escapeHtml(value)}"></div>`;
    };
    const cards = rulesUi.map(([id, title, description, keys]) => `<article class="card rule-card"><div class="rule-card-head"><h3 class="rule-title">${escapeHtml(title)}</h3><span class="rule-id">${escapeHtml(id.toUpperCase())}</span></div><p class="rule-description">${escapeHtml(description)}</p>${keys.map(fieldMarkup).join('')}</article>`).join('');
    const riskKeys = ['flagged_risk_threshold','risk_medium_threshold','risk_high_threshold','model_reason_threshold','alert_budget_default'];
    $('#settingsCards').innerHTML = `${cards}<article class="card rule-card"><div class="rule-card-head"><h3 class="rule-title">Risk scoring &amp; review</h3><span class="rule-id">THRESHOLDS</span></div><p class="rule-description">Final risk = min(100, rule_points + 0.4 × ml_score). The 0.4 model coefficient, six model inputs, estimator size and random seed are fixed by the demo specification.</p>${riskKeys.map(fieldMarkup).join('')}</article>`;
    $('#settingsState').textContent = 'Illustrative defaults';
    $$('[data-setting]').forEach((input) => input.addEventListener('input', () => { $('#settingsState').textContent = 'Unsaved changes'; }));
  }

  async function saveSettings(andRun = true) {
    const inputs = $$('[data-setting]');
    const values = {};
    for (const input of inputs) {
      if (!input.reportValidity()) { input.focus(); return; }
      const parsed = Number(input.value);
      if (!Number.isFinite(parsed)) { input.focus(); toast(`Enter a valid number for ${settingLabels[input.dataset.setting] || input.dataset.setting}.`, true); return; }
      values[input.dataset.setting] = parsed;
    }
    try {
      const saved = await api('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ settings: values }) });
      state.settings = saved.settings;
      if (andRun && state.summary) {
        const result = await api(`/api/detect?budget=${state.budget}`, { method: 'POST' });
        setDataset(result);
        if (state.page === 'settings') renderSettings({});
        toast('Detection rerun with the updated thresholds.');
      } else {
        renderSettings({});
        toast('Settings saved. Load data or rerun detection to apply them.');
      }
    } catch (error) { toast(error.message, true); }
  }

  async function resetSettings() {
    try {
      const payload = await api('/api/settings');
      const saved = await api('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ settings: payload.defaults }) });
      state.settings = saved.settings;
      renderSettings({});
      if (state.summary) {
        const result = await api(`/api/detect?budget=${state.budget}`, { method: 'POST' });
        setDataset(result);
        renderSettings({});
      }
      toast('Default detection thresholds restored.');
    } catch (error) { toast(error.message, true); }
  }

  function togglePresentation() {
    document.documentElement.classList.toggle('present');
    const active = document.documentElement.classList.contains('present');
    $('#presentBtn').setAttribute('aria-pressed', String(active));
    toast(active ? 'Presentation mode on.' : 'Presentation mode off.');
  }

  // Static navigation and controls: register once to avoid stale listeners when views change.
  $$('[data-nav]').forEach((element) => element.addEventListener('click', (event) => {
    event.preventDefault();
    setPage(element.dataset.nav);
  }));
  $$('[data-action="sample"],#loadSampleBtn').forEach((element) => element.addEventListener('click', loadSample));
  $$('[data-action="upload"],#uploadBtn').forEach((element) => element.addEventListener('click', openUpload));
  $('#presentBtn').addEventListener('click', togglePresentation);
  $('#clearDataBtn').addEventListener('click', clearData);
  $('#transactionFeaturesTab').addEventListener('click', () => { state.featureKind = 'transactions'; state.featureOffset = 0; state.featureSortBy = null; state.featureSortDirection = 'asc'; loadFeatureRows(); });
  $('#accountFeaturesTab').addEventListener('click', () => { state.featureKind = 'accounts'; state.featureOffset = 0; state.featureSortBy = null; state.featureSortDirection = 'asc'; loadFeatureRows(); });
  $('#featurePrev').addEventListener('click', () => { state.featureOffset = Math.max(0, state.featureOffset - state.featureLimit); loadFeatureRows(); });
  $('#featureNext').addEventListener('click', () => { state.featureOffset = Math.min(Math.max(0, state.featureTotal - state.featureLimit), state.featureOffset + state.featureLimit); loadFeatureRows(); });
  $('#budgetSlider').addEventListener('input', (event) => setBudget(event.target.value));
  $('#uploadOverlay').addEventListener('click', (event) => { if (event.target === $('#uploadOverlay')) closeUpload(); });
  $('#closeUpload').addEventListener('click', closeUpload);
  $('#chooseFile').addEventListener('click', (event) => { event.stopPropagation(); $('#csvInput').click(); });
  $('#dropZone').addEventListener('click', (event) => { if (event.target.id !== 'chooseFile') $('#csvInput').click(); });
  $('#dropZone').addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); $('#csvInput').click(); } });
  $('#csvInput').addEventListener('change', (event) => uploadFile(event.target.files?.[0]));
  ['dragenter', 'dragover'].forEach((name) => $('#dropZone').addEventListener(name, (event) => { event.preventDefault(); $('#dropZone').classList.add('dragging'); }));
  ['dragleave', 'drop'].forEach((name) => $('#dropZone').addEventListener(name, (event) => { event.preventDefault(); $('#dropZone').classList.remove('dragging'); }));
  $('#dropZone').addEventListener('drop', (event) => uploadFile(event.dataTransfer?.files?.[0]));
  $('#closeDrawer').addEventListener('click', closeDrawer);
  $('#drawerBackdrop').addEventListener('click', closeDrawer);
  $('#confirmFraud').addEventListener('click', () => changeCaseStatus('confirmed'));
  $('#falsePositive').addEventListener('click', () => changeCaseStatus('false_positive'));
  $('#escalateCase').addEventListener('click', () => changeCaseStatus('escalated'));
  $('#focusInNetwork').addEventListener('click', async () => {
    const accountId = state.drawerMode === 'account' ? state.caseDetail?.account_id : null;
    const caseId = state.drawerMode === 'case' ? state.caseDetail?.id : null;
    closeDrawer();
    setPage('network');
    await ensureGraph();
    if (accountId && state.graph) {
      state.focusedAccounts = [accountId];
      applyGraphFilters({ skipEdgeUpdate: true });
      state.graph.selectNodes([accountId], false);
      state.graph.fit({ nodes: [accountId], animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
    } else if (caseId) focusCase(caseId, true);
  });
  $('#tableViewBtn').addEventListener('click', async () => {
    await ensureGraph();
    state.tableMode = !state.tableMode;
    if (state.tableMode) renderNetworkTable();
    $('#networkTableWrap').hidden = !state.tableMode;
    $('.graph-stage').hidden = state.tableMode;
    $('#tableViewBtn').innerHTML = `${icon(state.tableMode ? 'network' : 'table')}<span>${state.tableMode ? 'Graph view' : 'Table view'}</span>`;
    if (!state.tableMode) window.setTimeout(() => state.graph?.redraw(), 40);
  });
  $('#networkTablePrev').addEventListener('click', () => {
    state.networkTablePage = Math.max(0, state.networkTablePage - 1);
    renderNetworkTable();
  });
  $('#networkTableNext').addEventListener('click', () => {
    state.networkTablePage += 1;
    renderNetworkTable();
  });
  $('#accountSearch').addEventListener('input', () => { state.networkTablePage = 0; applyGraphFilters({ refreshTable: true }); });
  $('#flaggedOnly').addEventListener('change', () => { state.networkTablePage = 0; applyGraphFilters({ refreshTable: true }); });
  $('#minRisk').addEventListener('input', () => { state.networkTablePage = 0; applyGraphFilters({ refreshTable: true }); });
  $('#fitGraph').addEventListener('click', fitGraphToView);
  $('#zoomIn').addEventListener('click', () => zoomGraph(1));
  $('#zoomOut').addEventListener('click', () => zoomGraph(-1));
  $('#caseSearch').addEventListener('input', renderFullCases);
  $('#rerunDetection').addEventListener('click', () => saveSettings(true));
  $('#resetSettings').addEventListener('click', resetSettings);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      if (!$('#caseDrawer').hidden) closeDrawer();
      else if (!$('#uploadOverlay').hidden) closeUpload();
    }
    if (event.key === 'Tab') {
      if (!$('#uploadOverlay').hidden) trapDialogFocus(event, $('#uploadOverlay [role="dialog"]'));
      else if (!$('#caseDrawer').hidden) trapDialogFocus(event, $('#caseDrawer'));
    }
    if (event.key.toLowerCase() === 'p' && !event.ctrlKey && !event.metaKey && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)) togglePresentation();
  });
  window.addEventListener('resize', () => { if (state.chart) state.chart.resize(); if (state.graph) state.graph.redraw(); });

  renderLandingStages();
  renderPipelineProgress();
  // Landing view is the initial route. Navigation state follows the visible destination.
  setPage('home');
  loadSettings().catch(() => { $('#settingsState').textContent = 'Unavailable'; });
})();
