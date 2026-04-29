/* BurnLens dashboard — Chart.js + plain fetch. No build step. */
'use strict';

const API = window.location.origin + '/api';

// Chart defaults for dark theme
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#232736';
Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
Chart.defaults.font.size = 11;

const PALETTE = [
  '#38bdf8', '#4ade80', '#fb923c', '#f472b6',
  '#a78bfa', '#facc15', '#34d399', '#f87171',
];

// -------------------------------------------------------- chart instances

let timelineChart = null;
let modelChart = null;
let featureChart = null;

// -------------------------------------------------------- helpers

function $(id) { return document.getElementById(id); }

function setText(id, text) {
  const el = $(id);
  if (el) el.textContent = text;
}

function fmtCost(usd) {
  if (usd === null || usd === undefined) return '\u2014';
  if (usd === 0) return '$0.00';
  if (usd < 0.001) return '$' + usd.toFixed(6);
  if (usd < 1) return '$' + usd.toFixed(4);
  return '$' + usd.toFixed(2);
}

function fmtNum(n) {
  if (n === null || n === undefined) return '\u2014';
  return Number(n).toLocaleString();
}

function fmtMs(ms) {
  if (!ms) return '\u2014';
  if (ms < 1000) return ms + 'ms';
  return (ms / 1000).toFixed(1) + 's';
}

function fmtTime(isoStr) {
  if (!isoStr) return '\u2014';
  // Handle ISO strings with timezone offset (+00:00), Z suffix, or naive (no tz info)
  const hasTz = /Z$|[+-]\d{2}:\d{2}$/.test(isoStr);
  const d = new Date(hasTz ? isoStr : isoStr + 'Z');
  if (isNaN(d.getTime())) return '\u2014';
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function currentPeriod() {
  return $('period-select').value || '7d';
}

function makeColors(n) {
  return Array.from({ length: n }, (_, i) => PALETTE[i % PALETTE.length]);
}

async function apiFetch(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(path + ' \u2192 ' + r.status);
  return r.json();
}

function makeTd(text, cls) {
  const el = document.createElement('td');
  el.textContent = text;
  if (cls) el.className = cls;
  return el;
}

// -------------------------------------------------------- KPI cards

async function fetchSummary() {
  const period = currentPeriod();
  const d = await apiFetch('/summary?period=' + period);

  setText('kpi-cost', fmtCost(d.total_cost_usd));
  setText('kpi-cost-sub', period + ' period');

  setText('kpi-requests', fmtNum(d.total_requests));
  setText('kpi-requests-sub', 'across ' + d.models_used + ' model' + (d.models_used !== 1 ? 's' : ''));

  setText('kpi-avg', fmtCost(d.avg_cost_per_request_usd));
  setText('kpi-avg-sub', 'per API call');

  if (d.budget_pct_used !== null && d.budget_pct_used !== undefined) {
    setText('kpi-budget', d.budget_pct_used.toFixed(1) + '%');
    setText('kpi-budget-sub', fmtCost(d.total_cost_usd) + ' of ' + fmtCost(d.budget_limit_usd));

    const wrap = $('budget-bar-wrap');
    const bar = $('budget-bar');
    wrap.style.display = 'block';
    const pct = Math.min(d.budget_pct_used, 100);
    bar.style.width = pct + '%';
    bar.className = 'budget-bar' +
      (d.budget_pct_used >= 90 ? ' danger' : d.budget_pct_used >= 70 ? ' warn' : '');
  } else {
    setText('kpi-budget', 'No limit set');
    setText('kpi-budget-sub', 'Set budget_limit_usd in config');
  }
}

// -------------------------------------------------------- Timeline chart

async function fetchTimeline() {
  const period = currentPeriod();
  const rows = await apiFetch('/costs/timeline?period=' + period + '&granularity=daily');

  const labels = rows.map(function(r) {
    const d = new Date(r.date + 'T00:00:00Z');
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  });
  const costs = rows.map(function(r) { return r.total_cost_usd; });

  const ctx = $('timeline-chart').getContext('2d');
  if (timelineChart) timelineChart.destroy();

  timelineChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        label: 'Daily cost (USD)',
        data: costs,
        borderColor: '#38bdf8',
        backgroundColor: 'rgba(56,189,248,0.08)',
        borderWidth: 2,
        pointRadius: 3,
        pointHoverRadius: 5,
        fill: true,
        tension: 0.3,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: { label: function(ctx) { return fmtCost(ctx.parsed.y); } },
        },
      },
      scales: {
        x: { grid: { color: '#1a1e2a' }, ticks: { maxRotation: 30 } },
        y: {
          grid: { color: '#1a1e2a' },
          ticks: { callback: function(v) { return fmtCost(v); } },
          beginAtZero: true,
        },
      },
    },
  });
}

// -------------------------------------------------------- Model chart

async function fetchModelChart() {
  const period = currentPeriod();
  const rows = await apiFetch('/costs/by-model?period=' + period);

  const labels = rows.map(function(r) { return r.model; });
  const costs = rows.map(function(r) { return r.total_cost_usd; });
  const colors = makeColors(rows.length);
  const horizontal = rows.length > 4;

  const ctx = $('model-chart').getContext('2d');
  if (modelChart) modelChart.destroy();

  modelChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Cost (USD)',
        data: costs,
        backgroundColor: colors,
        borderRadius: 4,
        borderSkipped: false,
      }],
    },
    options: {
      indexAxis: horizontal ? 'y' : 'x',
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              return fmtCost(ctx.parsed[horizontal ? 'x' : 'y']);
            },
          },
        },
      },
      scales: {
        x: horizontal
          ? { grid: { color: '#1a1e2a' }, ticks: { callback: function(v) { return fmtCost(v); } } }
          : { grid: { color: '#1a1e2a' }, ticks: { color: '#94a3b8' } },
        y: horizontal
          ? { grid: { color: '#1a1e2a' }, ticks: { color: '#94a3b8' } }
          : { grid: { color: '#1a1e2a' }, ticks: { callback: function(v) { return fmtCost(v); } } },
      },
    },
  });
}

// -------------------------------------------------------- Feature chart

async function fetchFeatureChart() {
  const period = currentPeriod();
  const rows = await apiFetch('/costs/by-tag?tag=feature&period=' + period);

  const tagged = rows.filter(function(r) { return r.tag !== '(untagged)'; });
  const display = tagged.length > 0 ? tagged : rows;

  const labels = display.map(function(r) { return r.tag; });
  const costs = display.map(function(r) { return r.total_cost_usd; });
  const colors = makeColors(display.length);

  const ctx = $('feature-chart').getContext('2d');
  if (featureChart) featureChart.destroy();

  if (display.length === 0) {
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    ctx.fillStyle = '#64748b';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('No feature tags yet.', ctx.canvas.width / 2, 70);
    ctx.fillText('Add X-BurnLens-Tag-Feature header to requests.', ctx.canvas.width / 2, 90);
    return;
  }

  featureChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: labels,
      datasets: [{
        data: costs,
        backgroundColor: colors,
        borderColor: '#13161f',
        borderWidth: 2,
        hoverOffset: 6,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: {
          position: 'right',
          labels: { boxWidth: 10, padding: 12, font: { size: 11 } },
        },
        tooltip: {
          callbacks: {
            label: function(ctx) { return ' ' + ctx.label + ': ' + fmtCost(ctx.parsed); },
          },
        },
      },
    },
  });
}

// -------------------------------------------------------- Waste panel

async function fetchWaste() {
  const findings = await apiFetch('/waste');
  const panel = $('waste-panel');
  panel.replaceChildren();

  const active = findings.filter(function(f) {
    return f.severity !== 'low' || f.affected_count > 0;
  });
  const display = active.length ? active : findings;

  if (!display.length) {
    const msg = document.createElement('div');
    msg.className = 'empty-state';
    msg.textContent = 'No waste detected.';
    panel.appendChild(msg);
    return;
  }

  for (const f of display) {
    const item = document.createElement('div');
    item.className = 'waste-item severity-' + f.severity;

    const titleRow = document.createElement('div');
    titleRow.className = 'waste-title';

    const titleText = document.createTextNode(f.title + ' ');
    titleRow.appendChild(titleText);

    const badge = document.createElement('span');
    badge.className = 'waste-badge ' + f.severity;
    badge.textContent = f.severity;
    titleRow.appendChild(badge);

    const desc = document.createElement('div');
    desc.className = 'waste-desc';
    desc.textContent = f.description;

    item.appendChild(titleRow);
    item.appendChild(desc);

    if (f.estimated_waste_usd > 0) {
      const savings = document.createElement('div');
      savings.className = 'waste-savings';
      savings.textContent = '~' + fmtCost(f.estimated_waste_usd) + ' estimated waste';
      item.appendChild(savings);
    }

    panel.appendChild(item);
  }
}

// -------------------------------------------------------- Recommendations

async function fetchRecommendations() {
  const recs = await apiFetch('/recommendations');
  var panel = $('recommendations-panel');
  panel.replaceChildren();

  if (!recs.length) {
    var empty = document.createElement('div');
    empty.className = 'empty-state-ok';
    var check = document.createElement('span');
    check.className = 'check';
    check.textContent = '\u2705';
    empty.appendChild(check);
    empty.appendChild(document.createTextNode('Your model usage looks efficient'));
    panel.appendChild(empty);
    return;
  }

  for (var i = 0; i < recs.length; i++) {
    var r = recs[i];
    var item = document.createElement('div');
    item.className = 'rec-item confidence-' + r.confidence;

    var titleRow = document.createElement('div');
    titleRow.className = 'rec-title';

    var titleText;
    if (r.suggested_model === 'prompt-caching') {
      titleText = 'Enable prompt caching for ' + r.feature_tag;
    } else {
      titleText = 'Switch ' + r.feature_tag + ' from ' + r.current_model + ' \u2192 ' + r.suggested_model;
    }
    titleRow.appendChild(document.createTextNode(titleText + ' '));

    var badge = document.createElement('span');
    badge.className = 'rec-badge ' + r.confidence;
    badge.textContent = r.confidence.toUpperCase();
    titleRow.appendChild(badge);

    var saving = document.createElement('div');
    saving.className = 'rec-saving';
    saving.textContent = 'Projected saving: ' + fmtCost(r.projected_saving) + '/month (' + r.saving_pct.toFixed(1) + '%)';

    var detail = document.createElement('div');
    detail.className = 'rec-detail';
    detail.textContent = 'Based on ' + fmtNum(r.request_count) + ' requests averaging ' + Math.round(r.avg_output_tokens) + ' output tokens';

    item.appendChild(titleRow);
    item.appendChild(saving);
    item.appendChild(detail);
    panel.appendChild(item);
  }
}

// -------------------------------------------------------- Customers

var _customersData = [];
var _customerSort = { col: 'total_cost', asc: false };

function renderCustomersTable() {
  var tbody = $('customers-body');
  tbody.replaceChildren();

  if (!_customersData.length) {
    var tr = document.createElement('tr');
    var td = document.createElement('td');
    td.colSpan = 8;
    td.className = 'empty-state-hint';
    var hintText = document.createTextNode('Tag requests with ');
    var code = document.createElement('code');
    code.textContent = 'X-BurnLens-Tag-Customer';
    td.appendChild(hintText);
    td.appendChild(code);
    td.appendChild(document.createTextNode(' header'));
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  var sorted = _customersData.slice().sort(function(a, b) {
    var va = a[_customerSort.col], vb = b[_customerSort.col];
    if (va === null || va === undefined) va = -Infinity;
    if (vb === null || vb === undefined) vb = -Infinity;
    if (typeof va === 'string') { va = va.toLowerCase(); vb = (vb || '').toLowerCase(); }
    if (va < vb) return _customerSort.asc ? -1 : 1;
    if (va > vb) return _customerSort.asc ? 1 : -1;
    return 0;
  });

  for (var i = 0; i < sorted.length; i++) {
    var r = sorted[i];
    var tr = document.createElement('tr');

    if (r.status === 'EXCEEDED') tr.className = 'row-exceeded';

    tr.appendChild(makeTd(r.customer));
    tr.appendChild(makeTd(fmtNum(r.request_count)));
    tr.appendChild(makeTd(fmtNum(r.input_tokens)));
    tr.appendChild(makeTd(fmtNum(r.output_tokens)));
    tr.appendChild(makeTd(fmtCost(r.total_cost), 'td-cost'));
    tr.appendChild(makeTd(r.budget !== null ? fmtCost(r.budget) : '\u2014'));
    tr.appendChild(makeTd(r.pct_used !== null ? r.pct_used.toFixed(1) + '%' : '\u2014'));

    var statusTd = document.createElement('td');
    var badge = document.createElement('span');
    badge.className = 'status-badge status-' + r.status.toLowerCase();
    badge.textContent = r.status;
    statusTd.appendChild(badge);
    tr.appendChild(statusTd);

    tbody.appendChild(tr);
  }
}

function updateSortIndicators() {
  var ths = document.querySelectorAll('#customers-table th.sortable');
  for (var i = 0; i < ths.length; i++) {
    ths[i].classList.remove('active-sort', 'asc', 'desc');
    if (ths[i].getAttribute('data-col') === _customerSort.col) {
      ths[i].classList.add('active-sort', _customerSort.asc ? 'asc' : 'desc');
    }
  }
}

async function fetchCustomers() {
  _customersData = await apiFetch('/customers');
  renderCustomersTable();
}

// -------------------------------------------------------- Team Budgets

async function fetchTeamBudgets() {
  const rows = await apiFetch('/team-budgets');
  var panel = $('team-budgets-panel');
  panel.replaceChildren();

  if (!rows.length) {
    var hint = document.createElement('div');
    hint.className = 'empty-state-hint';
    var text = document.createTextNode('Add ');
    var code = document.createElement('code');
    code.textContent = 'budgets.teams';
    hint.appendChild(text);
    hint.appendChild(code);
    hint.appendChild(document.createTextNode(' to burnlens.yaml'));
    panel.appendChild(hint);
    return;
  }

  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    var row = document.createElement('div');
    row.className = 'team-row';

    var name = document.createElement('div');
    name.className = 'team-name';
    name.textContent = r.team;

    var barWrap = document.createElement('div');
    barWrap.className = 'team-bar-wrap';
    var bar = document.createElement('div');
    var pct = Math.min(r.pct_used, 100);
    bar.style.width = pct + '%';
    var barClass = 'team-bar';
    if (r.pct_used >= 100) barClass += ' critical';
    else if (r.pct_used >= 80) barClass += ' warning';
    else barClass += ' ok';
    bar.className = barClass;
    barWrap.appendChild(bar);

    var spend = document.createElement('div');
    spend.className = 'team-spend';
    spend.textContent = fmtCost(r.spent) + ' / ' + fmtCost(r.limit);

    var statusDiv = document.createElement('div');
    statusDiv.className = 'team-status';
    var badge = document.createElement('span');
    badge.className = 'status-badge status-' + r.status.toLowerCase();
    badge.textContent = r.status;
    statusDiv.appendChild(badge);

    row.appendChild(name);
    row.appendChild(barWrap);
    row.appendChild(spend);
    row.appendChild(statusDiv);
    panel.appendChild(row);
  }
}

// -------------------------------------------------------- API keys today (CODE-2)

async function fetchKeysToday() {
  const rows = await apiFetch('/keys-today');
  const panel = $('keys-today-panel');
  panel.replaceChildren();

  if (rows.length && rows[0].reset_timezone) {
    setText('keys-today-tz', '(' + rows[0].reset_timezone + ')');
  }

  if (!rows.length) {
    var hint = document.createElement('div');
    hint.className = 'empty-state-hint';
    hint.appendChild(document.createTextNode('Register a key with '));
    var code = document.createElement('code');
    code.textContent = 'burnlens key register';
    hint.appendChild(code);
    hint.appendChild(document.createTextNode(' and add a daily cap under '));
    var code2 = document.createElement('code');
    code2.textContent = 'alerts.api_key_budgets';
    hint.appendChild(code2);
    hint.appendChild(document.createTextNode(' in burnlens.yaml.'));
    panel.appendChild(hint);
    return;
  }

  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    var row = document.createElement('div');
    row.className = 'team-row';

    var name = document.createElement('div');
    name.className = 'team-name';
    name.textContent = r.label;

    var barWrap = document.createElement('div');
    barWrap.className = 'team-bar-wrap';
    var bar = document.createElement('div');
    var pct = r.pct_used == null ? 0 : Math.min(r.pct_used, 100);
    bar.style.width = pct + '%';
    var barClass = 'team-bar';
    if (r.status === 'CRITICAL') barClass += ' critical';
    else if (r.status === 'WARNING') barClass += ' warning';
    else barClass += ' ok';
    bar.className = barClass;
    barWrap.appendChild(bar);

    var spend = document.createElement('div');
    spend.className = 'team-spend';
    if (r.daily_cap != null) {
      spend.textContent = fmtCost(r.spent_usd) + ' / ' + fmtCost(r.daily_cap);
    } else {
      spend.textContent = fmtCost(r.spent_usd) + ' / no cap';
    }

    var statusDiv = document.createElement('div');
    statusDiv.className = 'team-status';
    var badge = document.createElement('span');
    badge.className = 'status-badge status-' + r.status.toLowerCase().replace('_', '-');
    badge.textContent = r.status.replace('_', ' ');
    statusDiv.appendChild(badge);

    row.appendChild(name);
    row.appendChild(barWrap);
    row.appendChild(spend);
    row.appendChild(statusDiv);
    panel.appendChild(row);
  }
}

// -------------------------------------------------------- Requests table

// Top PRs panel — module-scoped active filter for click-to-drill-down
let activePRFilter = null;

async function fetchTopPRs() {
  const period = currentPeriod();
  const days = parseInt((period || '7d').replace('d', ''), 10) || 7;
  setText('top-prs-window', `(last ${days} day${days === 1 ? '' : 's'})`);

  const rows = await apiFetch(`/cost-by-pr?days=${days}`);
  const tbody = $('top-prs-body');
  tbody.replaceChildren();

  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 7;
    td.className = 'loading-text';
    td.textContent = 'No PR-tagged traffic yet. Run `burnlens run -- <agent>` from a git repo to populate this.';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  for (const row of rows) {
    const tr = document.createElement('tr');
    tr.style.cursor = 'pointer';
    if (activePRFilter && activePRFilter === row.pr) {
      tr.classList.add('row-active');
    }
    tr.addEventListener('click', () => setPRFilter(row.pr));

    tr.appendChild(makeTd(row.pr || '—'));
    tr.appendChild(makeTd(row.repo || '—', 'td-muted'));
    tr.appendChild(makeTd(row.dev || '—', 'td-muted'));
    tr.appendChild(makeTd(row.branch || '—', 'td-muted'));
    tr.appendChild(makeTd(fmtNum(row.requests || 0)));
    tr.appendChild(makeTd(fmtCost(row.total_cost_usd || 0), 'td-cost'));
    tr.appendChild(makeTd(fmtTime(row.last_seen), 'td-muted'));

    tbody.appendChild(tr);
  }
}

function setPRFilter(pr) {
  activePRFilter = activePRFilter === pr ? null : pr;
  fetchTopPRs();
  fetchRequests();
}

async function fetchRequests() {
  const params = new URLSearchParams({ limit: '50' });
  if (activePRFilter) params.set('pr', activePRFilter);
  const rows = await apiFetch(`/requests?${params.toString()}`);
  const tbody = $('requests-body');
  tbody.replaceChildren();

  const filterNote = activePRFilter ? ` (filtered to PR ${activePRFilter} — click row again to clear)` : '';
  setText('requests-count', (rows.length ? rows.length + ' recent' : '') + filterNote);

  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 8;
    td.className = 'loading-text';
    td.textContent = 'No requests yet. Route API calls through the proxy to see them here.';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  for (const row of rows) {
    const tr = document.createElement('tr');
    const feature = (row.tags && row.tags.feature) ? row.tags.feature : null;

    tr.appendChild(makeTd(fmtTime(row.timestamp), 'td-muted'));
    tr.appendChild(makeTd(row.provider || '\u2014', 'td-muted'));
    tr.appendChild(makeTd(row.model || '\u2014', 'td-model'));

    // Feature tag cell — text only, styled via class
    const tagTd = document.createElement('td');
    if (feature) {
      const span = document.createElement('span');
      span.className = 'td-tag';
      span.textContent = feature;
      tagTd.appendChild(span);
    } else {
      tagTd.textContent = '\u2014';
      tagTd.className = 'td-muted';
    }
    tr.appendChild(tagTd);

    tr.appendChild(makeTd(fmtNum(row.input_tokens || 0)));
    tr.appendChild(makeTd(fmtNum(row.output_tokens || 0)));
    tr.appendChild(makeTd(fmtCost(row.cost_usd || 0), 'td-cost'));
    tr.appendChild(makeTd(fmtMs(row.duration_ms), 'td-muted'));

    tbody.appendChild(tr);
  }
}

// -------------------------------------------------------- Refresh loop

async function refresh() {
  await Promise.allSettled([
    fetchSummary(),
    fetchTimeline(),
    fetchModelChart(),
    fetchFeatureChart(),
    fetchWaste(),
    fetchRecommendations(),
    fetchCustomers(),
    fetchTeamBudgets(),
    fetchKeysToday(),
    fetchTopPRs(),
    fetchRequests(),
  ]);
}

// Period selector triggers immediate refresh
$('period-select').addEventListener('change', function() {
  if (timelineChart) { timelineChart.destroy(); timelineChart = null; }
  if (modelChart) { modelChart.destroy(); modelChart = null; }
  if (featureChart) { featureChart.destroy(); featureChart = null; }
  refresh();
});

// -------------------------------------------------------- Tab switching

document.querySelectorAll('.tab-btn').forEach(function(btn) {
  btn.addEventListener('click', function() {
    document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
    document.querySelectorAll('.tab-pane').forEach(function(p) { p.classList.remove('active'); });
    btn.classList.add('active');
    var pane = $('tab-' + btn.getAttribute('data-tab'));
    if (pane) pane.classList.add('active');
  });
});

// -------------------------------------------------------- Customer sort

document.querySelectorAll('#customers-table th.sortable').forEach(function(th) {
  th.addEventListener('click', function() {
    var col = th.getAttribute('data-col');
    if (_customerSort.col === col) {
      _customerSort.asc = !_customerSort.asc;
    } else {
      _customerSort.col = col;
      _customerSort.asc = (col === 'customer');  // alpha asc, numbers desc
    }
    updateSortIndicators();
    renderCustomersTable();
  });
});

// -------------------------------------------------------- Export CSV

$('export-btn').addEventListener('click', function() {
  var period = currentPeriod();
  window.location.href = API + '/export?period=' + period;
});

// Initial load + auto-refresh every 10s
refresh();
setInterval(refresh, 10000);
