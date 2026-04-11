/* BurnLens discovery dashboard — vanilla JS + Chart.js. No build step. */
'use strict';

const API_V1 = window.location.origin + '/api/v1';
// Consumes: api/v1/assets/summary, api/v1/assets (asset inventory endpoints)

// Chart defaults for dark theme
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#232736';
Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
Chart.defaults.font.size = 11;

const PALETTE = [
  '#38bdf8', '#4ade80', '#fb923c', '#f472b6',
  '#a78bfa', '#facc15', '#34d399', '#f87171',
];

// -------------------------------------------------------- state

let providerChart = null;
let _assetSort = { col: 'last_active_at', asc: false };
let _assetData = [];
let _assetTotal = 0;
let _assetOffset = 0;
const _assetLimit = 25;

let _filterProvider = '';
let _filterStatus = '';
let _filterRisk = '';
let _filterTeam = '';
let _filterDateSince = '';

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

function fmtDate(isoStr) {
  if (!isoStr) return '\u2014';
  const hasTz = /Z$|[+-]\d{2}:\d{2}$/.test(isoStr);
  const d = new Date(hasTz ? isoStr : isoStr + 'Z');
  if (isNaN(d.getTime())) return '\u2014';
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

function makeColors(n) {
  return Array.from({ length: n }, function(_, i) { return PALETTE[i % PALETTE.length]; });
}

async function apiFetch(path) {
  const r = await fetch(API_V1 + path);
  if (!r.ok) throw new Error(path + ' \u2192 ' + r.status);
  return r.json();
}

function makeEmptyStateCell(colSpan, message) {
  var tr = document.createElement('tr');
  var td = document.createElement('td');
  td.colSpan = colSpan;
  td.className = 'empty-state-hint';
  td.textContent = message;
  tr.appendChild(td);
  return tr;
}

function makeEmptyStateDiv(message) {
  var div = document.createElement('div');
  div.className = 'empty-state';
  div.textContent = message;
  return div;
}

// -------------------------------------------------------- summary cards + provider chart

async function fetchAssetSummary() {
  let summary;
  try {
    summary = await apiFetch('/assets/summary');
  } catch (err) {
    console.error('fetchAssetSummary failed:', err);
    setText('kpi-total-assets', 'Error');
    return null;
  }

  // KPI: Total Assets
  setText('kpi-total-assets', fmtNum(summary.total));
  setText('kpi-total-assets-sub', 'AI models detected');

  // KPI: Active This Month (approved + active)
  const byStatus = summary.by_status || {};
  const activeCount = (byStatus.active || 0) + (byStatus.approved || 0);
  setText('kpi-active-month', fmtNum(activeCount));
  setText('kpi-active-month-sub', 'approved + active');

  // KPI: Shadow Detected
  const shadowCount = byStatus.shadow || 0;
  setText('kpi-shadow', fmtNum(shadowCount));
  setText('kpi-shadow-sub', shadowCount === 1 ? '1 asset needs review' : shadowCount + ' assets need review');

  // KPI: Unassigned (use by_risk_tier.unclassified as proxy for "needs attention")
  const byRisk = summary.by_risk_tier || {};
  const unclassifiedCount = (byRisk.unclassified || 0);
  setText('kpi-unassigned', fmtNum(unclassifiedCount));
  setText('kpi-unassigned-sub', 'unclassified risk tier');

  // Populate filter dropdowns from summary data
  populateFilterDropdown('filter-provider', Object.keys(summary.by_provider || {}));
  populateFilterDropdown('filter-status', Object.keys(byStatus));
  populateFilterDropdown('filter-risk', Object.keys(byRisk));

  // Render provider donut chart
  renderProviderChart(summary);

  // New this week panel
  await renderNewThisWeek(summary);

  return summary;
}

function populateFilterDropdown(selectId, values) {
  var sel = $(selectId);
  if (!sel) return;
  // Remove all options beyond the first placeholder
  while (sel.options.length > 1) sel.remove(1);
  values.forEach(function(v) {
    if (!v) return;
    var opt = document.createElement('option');
    opt.value = v;
    opt.textContent = v.charAt(0).toUpperCase() + v.slice(1);
    sel.appendChild(opt);
  });
}

function renderProviderChart(summary) {
  var byProvider = summary.by_provider || {};
  var labels = Object.keys(byProvider);
  var data = Object.values(byProvider);
  var colors = makeColors(labels.length);

  var canvas = $('provider-chart');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');
  if (providerChart) providerChart.destroy();

  if (!labels.length) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#64748b';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('No assets detected yet.', canvas.width / 2, 80);
    return;
  }

  providerChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: labels,
      datasets: [{
        data: data,
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
            label: function(ctx) { return ' ' + ctx.label + ': ' + fmtNum(ctx.parsed) + ' assets'; },
          },
        },
      },
    },
  });
}

// -------------------------------------------------------- new this week

async function renderNewThisWeek(summary) {
  var list = $('new-this-week-list');
  if (!list) return;

  var newCount = summary.new_this_week || 0;
  setText('new-this-week-count', newCount + ' detected');

  if (newCount === 0) {
    list.replaceChildren(makeEmptyStateDiv('No new assets this week.'));
    return;
  }

  var sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
  var dateSince = sevenDaysAgo.toISOString().split('T')[0];

  var data;
  try {
    data = await apiFetch('/assets?date_since=' + dateSince + '&limit=5');
  } catch (err) {
    list.replaceChildren(makeEmptyStateDiv('Could not load new assets.'));
    return;
  }

  if (!data.items || !data.items.length) {
    list.replaceChildren(makeEmptyStateDiv('No new assets this week.'));
    return;
  }

  list.replaceChildren();
  data.items.forEach(function(asset) {
    var item = document.createElement('div');
    item.className = 'new-week-item';

    var modelName = document.createElement('div');
    modelName.className = 'new-week-model';
    modelName.textContent = asset.model_name || '\u2014';

    var meta = document.createElement('div');
    meta.className = 'new-week-meta';

    var providerSpan = document.createElement('span');
    providerSpan.textContent = asset.provider || '';

    var badge = document.createElement('span');
    badge.className = 'status-badge status-' + (asset.status || 'unknown');
    badge.textContent = asset.status || 'unknown';

    var dateSpan = document.createElement('span');
    dateSpan.className = 'new-week-date';
    dateSpan.textContent = fmtDate(asset.first_seen_at);

    meta.appendChild(providerSpan);
    meta.appendChild(badge);
    meta.appendChild(dateSpan);

    item.appendChild(modelName);
    item.appendChild(meta);
    list.appendChild(item);
  });
}

// -------------------------------------------------------- asset table

async function fetchAssets() {
  var params = new URLSearchParams();
  if (_filterProvider) params.set('provider', _filterProvider);
  if (_filterStatus) params.set('status', _filterStatus);
  if (_filterRisk) params.set('risk_tier', _filterRisk);
  if (_filterTeam) params.set('owner_team', _filterTeam);
  if (_filterDateSince) params.set('date_since', _filterDateSince);
  params.set('limit', String(_assetLimit));
  params.set('offset', String(_assetOffset));

  var queryString = params.toString();
  var path = '/assets' + (queryString ? '?' + queryString : '');

  var data;
  try {
    data = await apiFetch(path);
  } catch (err) {
    console.error('fetchAssets failed:', err);
    var tbody = $('asset-table-body');
    if (tbody) {
      tbody.replaceChildren(makeEmptyStateCell(8, 'Error loading assets.'));
    }
    return;
  }

  _assetData = data.items || [];
  _assetTotal = data.total || 0;

  // Sort client-side
  sortAssetData();

  // Render table
  renderAssetTable();

  // Update pagination
  updatePagination();

  // Update monthly spend KPI from visible page
  var totalSpend = _assetData.reduce(function(sum, a) {
    return sum + (a.monthly_spend_usd || 0);
  }, 0);
  setText('kpi-monthly-spend', fmtCost(totalSpend));
  setText('kpi-monthly-spend-sub', 'page total (visible assets)');

  // Update asset count note
  setText('asset-count-note', fmtNum(_assetTotal) + ' total');

  // Populate team filter from loaded data
  populateTeamFilter(_assetData);
}

function populateTeamFilter(items) {
  var teams = new Set();
  items.forEach(function(a) { if (a.owner_team) teams.add(a.owner_team); });
  var sel = $('filter-team');
  if (!sel) return;
  var current = sel.value;
  while (sel.options.length > 1) sel.remove(1);
  Array.from(teams).sort().forEach(function(t) {
    var opt = document.createElement('option');
    opt.value = t;
    opt.textContent = t;
    sel.appendChild(opt);
  });
  if (current) sel.value = current;
}

function sortAssetData() {
  var col = _assetSort.col;
  var asc = _assetSort.asc;
  _assetData = _assetData.slice().sort(function(a, b) {
    var va = a[col], vb = b[col];
    if (va === null || va === undefined) va = '';
    if (vb === null || vb === undefined) vb = '';
    if (typeof va === 'string') va = va.toLowerCase();
    if (typeof vb === 'string') vb = vb.toLowerCase();
    if (va < vb) return asc ? -1 : 1;
    if (va > vb) return asc ? 1 : -1;
    return 0;
  });
}

function renderAssetTable() {
  var tbody = $('asset-table-body');
  if (!tbody) return;
  tbody.replaceChildren();

  if (!_assetData.length) {
    tbody.appendChild(makeEmptyStateCell(8, 'No assets found matching current filters.'));
    updateSortIndicators();
    return;
  }

  _assetData.forEach(function(asset) {
    var tr = document.createElement('tr');

    // Model
    var tdModel = document.createElement('td');
    tdModel.className = 'td-model';
    tdModel.textContent = asset.model_name || '\u2014';
    tr.appendChild(tdModel);

    // Provider
    var tdProvider = document.createElement('td');
    tdProvider.className = 'td-muted';
    tdProvider.textContent = asset.provider || '\u2014';
    tr.appendChild(tdProvider);

    // Team
    var tdTeam = document.createElement('td');
    tdTeam.textContent = asset.owner_team || '\u2014';
    if (!asset.owner_team) tdTeam.className = 'td-muted';
    tr.appendChild(tdTeam);

    // Status badge
    var tdStatus = document.createElement('td');
    var statusBadge = document.createElement('span');
    statusBadge.className = 'status-badge status-' + (asset.status || 'unknown');
    statusBadge.textContent = asset.status || 'unknown';
    tdStatus.appendChild(statusBadge);
    tr.appendChild(tdStatus);

    // Risk tier badge
    var tdRisk = document.createElement('td');
    var riskBadge = document.createElement('span');
    riskBadge.className = 'risk-badge risk-' + (asset.risk_tier || 'unknown');
    riskBadge.textContent = asset.risk_tier || 'unknown';
    tdRisk.appendChild(riskBadge);
    tr.appendChild(tdRisk);

    // Spend
    var tdSpend = document.createElement('td');
    tdSpend.className = 'td-cost';
    tdSpend.textContent = fmtCost(asset.monthly_spend_usd);
    tr.appendChild(tdSpend);

    // First seen
    var tdFirst = document.createElement('td');
    tdFirst.className = 'td-muted';
    tdFirst.textContent = fmtDate(asset.first_seen_at);
    tr.appendChild(tdFirst);

    // Last active
    var tdLast = document.createElement('td');
    tdLast.className = 'td-muted';
    tdLast.textContent = fmtDate(asset.last_active_at);
    tr.appendChild(tdLast);

    tbody.appendChild(tr);
  });

  updateSortIndicators();
}

function updateSortIndicators() {
  var ths = document.querySelectorAll('#asset-table th.sortable');
  ths.forEach(function(th) {
    th.classList.remove('active-sort', 'asc', 'desc');
    if (th.getAttribute('data-col') === _assetSort.col) {
      th.classList.add('active-sort', _assetSort.asc ? 'asc' : 'desc');
    }
  });
}

function updatePagination() {
  var btnPrev = $('btn-prev');
  var btnNext = $('btn-next');
  var info = $('pagination-info');

  var start = _assetTotal === 0 ? 0 : _assetOffset + 1;
  var end = Math.min(_assetOffset + _assetData.length, _assetTotal);
  if (info) info.textContent = 'Showing ' + start + '\u2013' + end + ' of ' + fmtNum(_assetTotal);

  if (btnPrev) btnPrev.disabled = _assetOffset === 0;
  if (btnNext) btnNext.disabled = (_assetOffset + _assetLimit) >= _assetTotal;
}

// -------------------------------------------------------- sort click handlers

document.querySelectorAll('#asset-table th.sortable').forEach(function(th) {
  th.addEventListener('click', function() {
    var col = th.getAttribute('data-col');
    if (_assetSort.col === col) {
      _assetSort.asc = !_assetSort.asc;
    } else {
      _assetSort.col = col;
      _assetSort.asc = (col === 'model_name' || col === 'provider' || col === 'owner_team');
    }
    sortAssetData();
    renderAssetTable();
  });
});

// -------------------------------------------------------- filter change handlers

function onFilterChange() {
  _filterProvider = ($('filter-provider') || {}).value || '';
  _filterStatus = ($('filter-status') || {}).value || '';
  _filterRisk = ($('filter-risk') || {}).value || '';
  _filterTeam = ($('filter-team') || {}).value || '';
  _filterDateSince = ($('filter-date-since') || {}).value || '';
  _assetOffset = 0;
  fetchAssets();
}

['filter-provider', 'filter-status', 'filter-risk', 'filter-team'].forEach(function(id) {
  var el = $(id);
  if (el) el.addEventListener('change', onFilterChange);
});

var dateSinceInput = $('filter-date-since');
if (dateSinceInput) {
  dateSinceInput.addEventListener('change', onFilterChange);
}

// -------------------------------------------------------- pagination handlers

var btnPrev = $('btn-prev');
var btnNext = $('btn-next');

if (btnPrev) {
  btnPrev.addEventListener('click', function() {
    _assetOffset = Math.max(0, _assetOffset - _assetLimit);
    fetchAssets();
  });
}

if (btnNext) {
  btnNext.addEventListener('click', function() {
    _assetOffset = _assetOffset + _assetLimit;
    fetchAssets();
  });
}

// -------------------------------------------------------- tab switching

document.querySelectorAll('.tab-btn').forEach(function(btn) {
  btn.addEventListener('click', function() {
    document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
    document.querySelectorAll('.tab-pane').forEach(function(p) { p.classList.remove('active'); });
    btn.classList.add('active');
    var pane = $('tab-' + btn.getAttribute('data-tab'));
    if (pane) pane.classList.add('active');
  });
});

// -------------------------------------------------------- initial load + refresh

async function refresh() {
  await fetchAssetSummary();
  await fetchAssets();
}

refresh();
setInterval(refresh, 30000);
