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
let _filterSearch = '';

let _searchDebounceTimer = null;

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

function fmtRelativeTime(isoStr) {
  if (!isoStr) return '\u2014';
  const hasTz = /Z$|[+-]\d{2}:\d{2}$/.test(isoStr);
  const d = new Date(hasTz ? isoStr : isoStr + 'Z');
  if (isNaN(d.getTime())) return '\u2014';
  const diffMs = Date.now() - d.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return 'just now';
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return diffMin + ' minute' + (diffMin === 1 ? '' : 's') + ' ago';
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return diffHr + ' hour' + (diffHr === 1 ? '' : 's') + ' ago';
  return fmtDate(isoStr);
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
  if (_filterSearch) params.set('search', _filterSearch);
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

// -------------------------------------------------------- shadow panel

async function fetchShadowAssets() {
  var panel = $('shadow-panel');
  if (!panel) return;

  var data;
  try {
    data = await apiFetch('/assets?status=shadow&limit=100');
  } catch (err) {
    console.error('fetchShadowAssets failed:', err);
    panel.replaceChildren(makeEmptyStateDiv('Error loading shadow assets.'));
    return;
  }

  var items = data.items || [];
  var countBadge = $('shadow-panel-count');
  if (countBadge) countBadge.textContent = String(items.length);

  if (!items.length) {
    panel.innerHTML = '<div class="shadow-empty"><span class="shadow-empty-icon">&#10003;</span> No shadow AI detected</div>';
    return;
  }

  panel.replaceChildren();
  items.forEach(function(asset) {
    var card = document.createElement('div');
    card.className = 'shadow-card';
    card.setAttribute('data-asset-id', String(asset.id));

    var modelEl = document.createElement('div');
    modelEl.className = 'model-name';
    modelEl.textContent = asset.model_name || '\u2014';

    var metaEl = document.createElement('div');
    metaEl.className = 'shadow-meta';

    var providerSpan = document.createElement('span');
    providerSpan.className = 'shadow-provider';
    providerSpan.textContent = asset.provider || '';

    var riskBadge = document.createElement('span');
    riskBadge.className = 'risk-badge risk-' + (asset.risk_tier || 'unknown');
    riskBadge.textContent = asset.risk_tier || 'unknown';

    var endpointSpan = document.createElement('div');
    endpointSpan.className = 'shadow-endpoint';
    endpointSpan.textContent = asset.endpoint_url || '';

    var seenSpan = document.createElement('div');
    seenSpan.className = 'shadow-seen';
    seenSpan.textContent = 'First seen: ' + fmtDate(asset.first_seen_at);

    metaEl.appendChild(providerSpan);
    metaEl.appendChild(riskBadge);

    var actionsEl = document.createElement('div');
    actionsEl.className = 'shadow-actions';

    var approveBtn = document.createElement('button');
    approveBtn.className = 'btn-approve';
    approveBtn.setAttribute('data-asset-id', String(asset.id));
    approveBtn.textContent = 'Approve';

    var assignBtn = document.createElement('button');
    assignBtn.className = 'btn-assign';
    assignBtn.setAttribute('data-asset-id', String(asset.id));
    assignBtn.textContent = 'Assign Team';

    var msgEl = document.createElement('div');
    msgEl.className = 'shadow-msg';

    actionsEl.appendChild(approveBtn);
    actionsEl.appendChild(assignBtn);
    actionsEl.appendChild(msgEl);

    card.appendChild(modelEl);
    card.appendChild(metaEl);
    card.appendChild(endpointSpan);
    card.appendChild(seenSpan);
    card.appendChild(actionsEl);

    panel.appendChild(card);
  });
}

async function handleApprove(assetId) {
  var card = document.querySelector('.shadow-card[data-asset-id="' + assetId + '"]');
  var msgEl = card ? card.querySelector('.shadow-msg') : null;

  try {
    var resp = await fetch(API_V1 + '/assets/' + assetId + '/approve', { method: 'POST' });
    if (resp.status === 409) {
      if (msgEl) msgEl.textContent = 'Already approved';
      return;
    }
    if (!resp.ok) {
      if (msgEl) msgEl.textContent = 'Error: ' + resp.status;
      return;
    }
    // Success: fade out and remove the card
    if (card) {
      card.classList.add('fade-out');
      setTimeout(function() {
        if (card.parentNode) card.parentNode.removeChild(card);
        // Update count badge
        var panel = $('shadow-panel');
        var remaining = panel ? panel.querySelectorAll('.shadow-card').length : 0;
        var countBadge = $('shadow-panel-count');
        if (countBadge) countBadge.textContent = String(remaining);
        if (remaining === 0) {
          panel.innerHTML = '<div class="shadow-empty"><span class="shadow-empty-icon">&#10003;</span> No shadow AI detected</div>';
        }
      }, 300);
    }
    // Refresh summary and asset table
    fetchAssetSummary();
    fetchAssets();
  } catch (err) {
    if (msgEl) msgEl.textContent = 'Request failed';
  }
}

function handleAssignTeam(assetId) {
  var card = document.querySelector('.shadow-card[data-asset-id="' + assetId + '"]');
  if (!card) return;

  var actionsEl = card.querySelector('.shadow-actions');
  var assignBtn = card.querySelector('.btn-assign');
  var msgEl = card.querySelector('.shadow-msg');

  // Replace button with inline input
  var inputEl = document.createElement('input');
  inputEl.type = 'text';
  inputEl.className = 'inline-input';
  inputEl.placeholder = 'Team name';

  var saveBtn = document.createElement('button');
  saveBtn.className = 'btn-save-team';
  saveBtn.textContent = 'Save';

  assignBtn.replaceWith(inputEl);

  var existingSave = actionsEl.querySelector('.btn-save-team');
  if (!existingSave) actionsEl.insertBefore(saveBtn, msgEl);

  saveBtn.addEventListener('click', async function() {
    var teamName = inputEl.value.trim();
    if (!teamName) {
      if (msgEl) msgEl.textContent = 'Enter a team name';
      return;
    }

    try {
      var resp = await fetch(API_V1 + '/assets/' + assetId, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ owner_team: teamName }),
      });

      if (!resp.ok) {
        if (msgEl) msgEl.textContent = 'Error: ' + resp.status;
        return;
      }

      // Update card to show team
      inputEl.replaceWith(assignBtn);
      saveBtn.remove();
      if (msgEl) {
        msgEl.textContent = 'Team: ' + teamName;
        msgEl.className = 'shadow-msg shadow-msg-ok';
      }
    } catch (err) {
      if (msgEl) msgEl.textContent = 'Request failed';
    }
  });
}

// Shadow panel event delegation
var shadowPanelEl = $('shadow-panel');
if (shadowPanelEl) {
  shadowPanelEl.addEventListener('click', function(e) {
    var target = e.target;
    if (target.classList.contains('btn-approve')) {
      handleApprove(target.getAttribute('data-asset-id'));
    } else if (target.classList.contains('btn-assign')) {
      handleAssignTeam(target.getAttribute('data-asset-id'));
    }
  });
}

// -------------------------------------------------------- discovery timeline

var EVENT_TYPE_CONFIG = {
  new_asset_detected: { color: '#38bdf8', icon: '\u25cf', label: 'New Asset Detected' },
  model_changed:      { color: '#fb923c', icon: '\u21c4', label: 'Model Changed' },
  provider_changed:   { color: '#a78bfa', icon: '\u21c4', label: 'Provider Changed' },
  asset_inactive:     { color: '#64748b', icon: '\u25cb', label: 'Asset Inactive' },
  key_rotated:        { color: '#f87171', icon: '\u27f3', label: 'Key Rotated' },
};

function getEventConfig(eventType) {
  return EVENT_TYPE_CONFIG[eventType] || { color: '#94a3b8', icon: '\u25cf', label: eventType };
}

function buildDetailsText(details) {
  if (!details) return '';
  var parts = [];
  if (details.model_name) parts.push('Model: ' + details.model_name);
  if (details.provider) parts.push('Provider: ' + details.provider);
  if (details.old_status && details.new_status) {
    parts.push(details.old_status + ' \u2192 ' + details.new_status);
  } else if (details.change) {
    parts.push(details.change);
  }
  if (!parts.length) {
    // Generic: show first 2 key-value pairs
    var keys = Object.keys(details).slice(0, 2);
    keys.forEach(function(k) { parts.push(k + ': ' + details[k]); });
  }
  return parts.join(' \u00b7 ');
}

async function fetchTimeline() {
  var panel = $('timeline-panel');
  if (!panel) return;

  var data;
  try {
    data = await apiFetch('/discovery/events?limit=30');
  } catch (err) {
    console.error('fetchTimeline failed:', err);
    panel.replaceChildren(makeEmptyStateDiv('Error loading timeline.'));
    return;
  }

  var items = (data.items || []);

  if (!items.length) {
    panel.replaceChildren(makeEmptyStateDiv('No discovery events yet.'));
    return;
  }

  panel.replaceChildren();
  items.forEach(function(event) {
    var cfg = getEventConfig(event.event_type);

    var eventEl = document.createElement('div');
    eventEl.className = 'timeline-event';

    var iconEl = document.createElement('div');
    iconEl.className = 'event-icon';
    iconEl.style.color = cfg.color;
    iconEl.textContent = cfg.icon;

    var bodyEl = document.createElement('div');
    bodyEl.className = 'event-body';

    var typeEl = document.createElement('div');
    typeEl.className = 'event-type-label';
    typeEl.style.color = cfg.color;
    typeEl.textContent = cfg.label;

    var detailsEl = document.createElement('div');
    detailsEl.className = 'event-details';
    detailsEl.textContent = buildDetailsText(event.details);

    var timeEl = document.createElement('div');
    timeEl.className = 'event-time';
    timeEl.textContent = fmtRelativeTime(event.detected_at);

    bodyEl.appendChild(typeEl);
    if (detailsEl.textContent) bodyEl.appendChild(detailsEl);
    bodyEl.appendChild(timeEl);

    eventEl.appendChild(iconEl);
    eventEl.appendChild(bodyEl);
    panel.appendChild(eventEl);
  });
}

// -------------------------------------------------------- global search

function handleSearch() {
  var input = $('global-search');
  if (!input) return;

  input.addEventListener('input', function() {
    clearTimeout(_searchDebounceTimer);
    _searchDebounceTimer = setTimeout(function() {
      _filterSearch = input.value.trim();
      _assetOffset = 0;
      fetchAssets();
    }, 300);
  });
}

// Initialize search listener
handleSearch();

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

// -------------------------------------------------------- saved views (localStorage)

var SAVED_VIEWS_KEY = 'burnlens_saved_views';

/**
 * Get all saved views from localStorage.
 * Returns an array of { name, filters } objects.
 */
function getSavedViews() {
  try {
    var raw = localStorage.getItem(SAVED_VIEWS_KEY);
    if (!raw) return [];
    var parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    return [];
  }
}

/**
 * Persist the given views array to localStorage.
 */
function persistSavedViews(views) {
  try {
    localStorage.setItem(SAVED_VIEWS_KEY, JSON.stringify(views));
  } catch (e) {
    console.error('Failed to persist saved views:', e);
  }
}

/**
 * Read current values from all filter UI elements.
 * Returns a filters object matching the saved-view schema.
 */
function getCurrentFilters() {
  return {
    provider: ($('filter-provider') || {}).value || '',
    status: ($('filter-status') || {}).value || '',
    risk_tier: ($('filter-risk') || {}).value || '',
    owner_team: ($('filter-team') || {}).value || '',
    date_since: ($('filter-date-since') || {}).value || '',
    search: ($('global-search') || {}).value || '',
  };
}

/**
 * Rebuild the #saved-views-select options from localStorage.
 */
function renderSavedViewsDropdown() {
  var sel = $('saved-views-select');
  if (!sel) return;
  // Keep currently selected value if any
  var current = sel.value;
  while (sel.options.length > 1) sel.remove(1);
  var views = getSavedViews();
  views.forEach(function(view) {
    var opt = document.createElement('option');
    opt.value = view.name;
    opt.textContent = view.name;
    sel.appendChild(opt);
  });
  // Restore selection if still present
  if (current) sel.value = current;
}

/**
 * Save the current filter state under the given name.
 * Overwrites an existing view with the same name.
 */
function saveView(name) {
  var errorEl = $('save-view-error');
  if (!name) {
    if (errorEl) errorEl.textContent = 'Enter a view name.';
    return;
  }
  if (errorEl) errorEl.textContent = '';

  var views = getSavedViews();
  var filters = getCurrentFilters();
  var existingIdx = views.findIndex(function(v) { return v.name === name; });
  if (existingIdx >= 0) {
    views[existingIdx].filters = filters;
  } else {
    views.push({ name: name, filters: filters });
  }
  persistSavedViews(views);
  renderSavedViewsDropdown();

  // Select the just-saved view in the dropdown
  var sel = $('saved-views-select');
  if (sel) sel.value = name;

  // Show delete button since a view is now selected
  var deleteBtn = $('delete-view-btn');
  if (deleteBtn) deleteBtn.style.display = '';

  // Hide the save form and clear input
  var form = $('save-view-form');
  if (form) form.style.display = 'none';
  var input = $('view-name-input');
  if (input) input.value = '';
}

/**
 * Restore a saved view by name — set all filters and refetch.
 */
function loadView(name) {
  var views = getSavedViews();
  var view = views.find(function(v) { return v.name === name; });
  if (!view) return;

  var f = view.filters || {};

  var provSel = $('filter-provider');
  var statSel = $('filter-status');
  var riskSel = $('filter-risk');
  var teamSel = $('filter-team');
  var dateSince = $('filter-date-since');
  var searchInput = $('global-search');

  if (provSel) provSel.value = f.provider || '';
  if (statSel) statSel.value = f.status || '';
  if (riskSel) riskSel.value = f.risk_tier || '';
  if (teamSel) teamSel.value = f.owner_team || '';
  if (dateSince) dateSince.value = f.date_since || '';
  if (searchInput) searchInput.value = f.search || '';

  // Sync module-level filter state
  _filterProvider = f.provider || '';
  _filterStatus = f.status || '';
  _filterRisk = f.risk_tier || '';
  _filterTeam = f.owner_team || '';
  _filterDateSince = f.date_since || '';
  _filterSearch = f.search || '';
  _assetOffset = 0;

  fetchAssets();
}

/**
 * Delete a saved view by name, reset UI to defaults.
 */
function deleteView(name) {
  if (!name) return;
  var views = getSavedViews().filter(function(v) { return v.name !== name; });
  persistSavedViews(views);
  renderSavedViewsDropdown();

  // Hide delete button, reset dropdown to default
  var sel = $('saved-views-select');
  if (sel) sel.value = '';
  var deleteBtn = $('delete-view-btn');
  if (deleteBtn) deleteBtn.style.display = 'none';

  // Reset all filters
  _filterProvider = ''; _filterStatus = ''; _filterRisk = '';
  _filterTeam = ''; _filterDateSince = ''; _filterSearch = '';
  _assetOffset = 0;

  var provSel = $('filter-provider');
  var statSel = $('filter-status');
  var riskSel = $('filter-risk');
  var teamSel = $('filter-team');
  var dateSince = $('filter-date-since');
  var searchInput = $('global-search');

  if (provSel) provSel.value = '';
  if (statSel) statSel.value = '';
  if (riskSel) riskSel.value = '';
  if (teamSel) teamSel.value = '';
  if (dateSince) dateSince.value = '';
  if (searchInput) searchInput.value = '';

  fetchAssets();
}

// Wire saved views event listeners once DOM is ready
(function wireViewEvents() {
  var saveBtn = $('save-view-btn');
  var confirmSaveBtn = $('confirm-save-view');
  var cancelSaveBtn = $('cancel-save-view');
  var savedViewsSel = $('saved-views-select');
  var deleteBtn = $('delete-view-btn');
  var form = $('save-view-form');
  var nameInput = $('view-name-input');

  if (saveBtn && form && nameInput) {
    saveBtn.addEventListener('click', function() {
      form.style.display = '';
      nameInput.focus();
    });
  }

  if (confirmSaveBtn && nameInput) {
    confirmSaveBtn.addEventListener('click', function() {
      saveView(nameInput.value.trim());
    });
    // Allow pressing Enter in the name input to save
    nameInput.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') saveView(nameInput.value.trim());
      if (e.key === 'Escape' && form) form.style.display = 'none';
    });
  }

  if (cancelSaveBtn && form) {
    cancelSaveBtn.addEventListener('click', function() {
      form.style.display = 'none';
      var errorEl = $('save-view-error');
      if (errorEl) errorEl.textContent = '';
    });
  }

  if (savedViewsSel && deleteBtn) {
    savedViewsSel.addEventListener('change', function() {
      var val = savedViewsSel.value;
      if (val) {
        deleteBtn.style.display = '';
        loadView(val);
      } else {
        deleteBtn.style.display = 'none';
      }
    });
  }

  if (deleteBtn && savedViewsSel) {
    deleteBtn.addEventListener('click', function() {
      deleteView(savedViewsSel.value);
    });
  }

  // Populate from localStorage on load
  renderSavedViewsDropdown();
}());

// -------------------------------------------------------- initial load + refresh

async function refresh() {
  await fetchAssetSummary();
  await fetchAssets();
  await fetchShadowAssets();
  await fetchTimeline();
}

refresh();
setInterval(refresh, 30000);
