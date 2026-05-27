/* Discovery dashboard.
 *
 * Drives the AI-asset discovery page entirely from the existing backend:
 *   - KPI cards + provider chart + filter options -> GET /api/v1/assets/summary
 *   - team filter list + Unassigned KPI (client-side derived from a wide fetch)
 *                                          ->  GET /api/v1/assets?limit=...
 *   - filterable / sortable / searchable, paginated asset table
 *                                          ->  GET /api/v1/assets
 *   - "New this week" recent-assets panel  ->  GET /api/v1/assets?date_since=...
 *   - Shadow AI Alerts panel               ->  GET /api/v1/assets?status=shadow
 *   - Discovery Timeline panel             ->  GET /api/v1/discovery/events
 *   - per-row approve                      ->  POST /api/v1/assets/{id}/approve
 *   - per-row assign / reassign team       ->  PATCH /api/v1/assets/{id}
 *   - Saved Views                          ->  localStorage (no backend)
 *
 * Every element id / class produced here matches discovery.html and style.css.
 */
(function () {
  'use strict';

  var ASSETS_URL = '/api/v1/assets';
  var SUMMARY_URL = '/api/v1/assets/summary';
  var EVENTS_URL = '/api/v1/discovery/events';
  var PAGE_SIZE = 50;
  // Upper bound for the single wide fetch used to derive the team list and the
  // Unassigned KPI client-side. Matches the assets endpoint's max `limit`.
  var DERIVE_LIMIT = 200;
  var VIEWS_STORAGE_KEY = 'burnlens.discovery.savedViews';

  // Chart.js instance for the provider breakdown; rebuilt on each refresh.
  var providerChart = null;

  // Columns rendered in the asset table — must mirror the static
  // <th class="sortable" data-col="..."> set in discovery.html.
  var COLUMNS = [
    'model_name',
    'provider',
    'owner_team',
    'status',
    'risk_tier',
    'monthly_spend_usd',
    'first_seen_at',
    'last_active_at',
  ];

  var state = {
    sortBy: 'first_seen_at',
    sortDir: 'desc',
    offset: 0,
    provider: '',
    status: '',
    riskTier: '',
    ownerTeam: '',
    dateSince: '',
    search: '',
  };

  // ----------------------------------------------------------------- helpers
  function byId(id) {
    return document.getElementById(id);
  }

  function clearElement(el) {
    while (el && el.firstChild) {
      el.removeChild(el.firstChild);
    }
  }

  function setText(id, value) {
    var el = byId(id);
    if (el) el.textContent = value;
  }

  function formatUsd(value) {
    var n = Number(value) || 0;
    return '$' + n.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function formatDate(iso) {
    if (!iso) return '—';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  }

  function slug(value) {
    return String(value == null ? 'unknown' : value)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'unknown';
  }

  function debounce(fn, ms) {
    var timer = null;
    return function () {
      var args = arguments;
      var self = this;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(self, args); }, ms);
    };
  }

  // ------------------------------------------------------------ query string
  function filterParams() {
    var params = new URLSearchParams();
    if (state.provider) params.set('provider', state.provider);
    if (state.status) params.set('status', state.status);
    if (state.riskTier) params.set('risk_tier', state.riskTier);
    if (state.ownerTeam) params.set('owner_team', state.ownerTeam);
    if (state.dateSince) params.set('date_since', state.dateSince);
    if (state.search) params.set('search', state.search);
    return params;
  }

  function listQuery() {
    var params = filterParams();
    params.set('sort_by', state.sortBy);
    params.set('sort_dir', state.sortDir);
    params.set('limit', String(PAGE_SIZE));
    params.set('offset', String(state.offset));
    return params.toString();
  }

  // --------------------------------------------------- summary: KPIs + filters
  function populateSelect(id, values, selected) {
    var sel = byId(id);
    if (!sel) return;
    // Keep the leading "All ..." placeholder option, replace the rest.
    while (sel.options.length > 1) {
      sel.remove(1);
    }
    values.slice().sort().forEach(function (value) {
      var opt = document.createElement('option');
      opt.value = value;
      opt.textContent = value;
      sel.appendChild(opt);
    });
    sel.value = selected || '';
  }

  async function fetchSummary() {
    var resp;
    try {
      resp = await fetch(SUMMARY_URL);
    } catch (e) {
      return;
    }
    if (!resp.ok) return;
    var data = await resp.json();
    var byStatus = data.by_status || {};
    var activeThisMonth = (byStatus.approved || 0) + (byStatus.active || 0);

    setText('kpi-total-assets', String(data.total != null ? data.total : 0));
    setText('kpi-active-month', String(activeThisMonth));
    setText('kpi-shadow', String(byStatus.shadow || 0));
    // kpi-monthly-spend is the current page total, set by renderTable().

    populateSelect('filter-provider', Object.keys(data.by_provider || {}), state.provider);
    populateSelect('filter-status', Object.keys(byStatus), state.status);
    populateSelect('filter-risk', Object.keys(data.by_risk_tier || {}), state.riskTier);

    renderProviderChart(data.by_provider || {});
  }

  // --------------------------------------------------------- provider chart
  var CHART_COLORS = [
    '#38bdf8', '#a78bfa', '#fb923c', '#4ade80', '#facc15',
    '#f87171', '#34d399', '#f472b6', '#60a5fa', '#c084fc',
  ];

  function renderProviderChart(byProvider) {
    var canvas = byId('provider-chart');
    if (!canvas || typeof Chart === 'undefined') return;

    var labels = Object.keys(byProvider);
    var values = labels.map(function (k) { return byProvider[k]; });

    if (providerChart) {
      providerChart.destroy();
      providerChart = null;
    }
    if (labels.length === 0) return;

    providerChart = new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          backgroundColor: labels.map(function (_, i) {
            return CHART_COLORS[i % CHART_COLORS.length];
          }),
          borderWidth: 0,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'right',
            labels: { color: '#cbd5e1', boxWidth: 12, padding: 12 },
          },
        },
      },
    });
  }

  // ------------------------------------------------------------- asset table
  function applyHeaderIndicators() {
    var headers = document.querySelectorAll('#asset-table th.sortable');
    for (var i = 0; i < headers.length; i++) {
      var th = headers[i];
      th.classList.remove('active-sort', 'asc', 'desc');
      if (th.getAttribute('data-col') === state.sortBy) {
        th.classList.add('active-sort', state.sortDir);
      }
    }
  }

  function badge(kind, value) {
    var span = document.createElement('span');
    span.className = kind + '-badge ' + kind + '-' + slug(value);
    span.textContent = value == null ? '—' : String(value);
    return span;
  }

  function renderActions(asset, td) {
    clearElement(td);
    var wrap = document.createElement('div');
    wrap.className = 'shadow-actions';

    if (asset.status !== 'approved') {
      var approve = document.createElement('button');
      approve.className = 'btn-approve';
      approve.textContent = 'Approve';
      approve.addEventListener('click', function () { approveAsset(asset.id); });
      wrap.appendChild(approve);
    }

    var assign = document.createElement('button');
    assign.className = 'btn-assign';
    assign.textContent = asset.owner_team ? 'Reassign' : 'Assign Team';
    assign.addEventListener('click', function () { startAssign(asset, td); });
    wrap.appendChild(assign);

    td.appendChild(wrap);
  }

  function startAssign(asset, td) {
    clearElement(td);
    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'inline-input';
    input.placeholder = 'Team name';
    input.value = asset.owner_team || '';

    var save = document.createElement('button');
    save.className = 'btn-save-team';
    save.textContent = 'Save';

    function commit() {
      var name = input.value.trim();
      if (name) {
        assignTeam(asset.id, name);
      } else {
        renderActions(asset, td);
      }
    }

    save.addEventListener('click', commit);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') commit();
      if (e.key === 'Escape') renderActions(asset, td);
    });

    td.appendChild(input);
    td.appendChild(save);
    input.focus();
  }

  function renderTable(items) {
    var tbody = byId('asset-table-body');
    if (!tbody) return;
    clearElement(tbody);

    var pageSpend = 0;

    if (!items || items.length === 0) {
      var emptyRow = document.createElement('tr');
      var emptyCell = document.createElement('td');
      emptyCell.colSpan = COLUMNS.length + 1;
      emptyCell.className = 'loading-text';
      emptyCell.textContent = 'No assets match the current filters.';
      emptyRow.appendChild(emptyCell);
      tbody.appendChild(emptyRow);
      setText('kpi-monthly-spend', formatUsd(0));
      return;
    }

    items.forEach(function (asset) {
      pageSpend += Number(asset.monthly_spend_usd) || 0;
      var row = document.createElement('tr');

      COLUMNS.forEach(function (col) {
        var cell = document.createElement('td');
        if (col === 'status') {
          cell.appendChild(badge('status', asset.status));
        } else if (col === 'risk_tier') {
          cell.appendChild(badge('risk', asset.risk_tier));
        } else if (col === 'monthly_spend_usd') {
          cell.textContent = formatUsd(asset.monthly_spend_usd);
        } else if (col === 'first_seen_at' || col === 'last_active_at') {
          cell.textContent = formatDate(asset[col]);
        } else {
          var v = asset[col];
          cell.textContent = v != null && v !== '' ? String(v) : '—';
        }
        row.appendChild(cell);
      });

      var actionCell = document.createElement('td');
      renderActions(asset, actionCell);
      row.appendChild(actionCell);

      tbody.appendChild(row);
    });

    setText('kpi-monthly-spend', formatUsd(pageSpend));
  }

  function renderPagination(total, offset, limit) {
    var page = Math.floor(offset / limit) + 1;
    var pages = Math.max(1, Math.ceil(total / limit));

    setText('pagination-info', 'Page ' + page + ' of ' + pages + ' · ' + total + ' assets');
    setText('asset-count-note', total + ' total');

    var prev = byId('btn-prev');
    var next = byId('btn-next');
    if (prev) prev.disabled = page <= 1;
    if (next) next.disabled = page >= pages;
  }

  async function fetchAssets() {
    var resp;
    try {
      resp = await fetch(ASSETS_URL + '?' + listQuery());
    } catch (e) {
      return;
    }
    if (!resp.ok) return;
    var data = await resp.json();
    renderTable(data.items);
    renderPagination(data.total || 0, data.offset || 0, data.limit || PAGE_SIZE);
    applyHeaderIndicators();
  }

  // ---------------------------------------------------- "new this week" panel
  function sevenDaysAgoIso() {
    var d = new Date();
    d.setDate(d.getDate() - 7);
    return d.toISOString().slice(0, 10);
  }

  async function fetchNewThisWeek() {
    var list = byId('new-this-week-list');
    if (!list) return;

    var params = new URLSearchParams();
    params.set('date_since', sevenDaysAgoIso());
    params.set('sort_by', 'first_seen_at');
    params.set('sort_dir', 'desc');
    params.set('limit', '10');

    var resp;
    try {
      resp = await fetch(ASSETS_URL + '?' + params.toString());
    } catch (e) {
      return;
    }
    if (!resp.ok) return;

    var data = await resp.json();
    var items = data.items || [];
    setText('new-this-week-count', items.length ? items.length + ' new' : 'None');

    clearElement(list);
    if (items.length === 0) {
      var empty = document.createElement('div');
      empty.className = 'loading-text';
      empty.textContent = 'No new assets in the last 7 days.';
      list.appendChild(empty);
      return;
    }

    items.forEach(function (asset) {
      var item = document.createElement('div');
      item.className = 'new-week-item';

      var model = document.createElement('div');
      model.className = 'new-week-model';
      model.textContent = asset.model_name || '(unknown model)';

      var meta = document.createElement('div');
      meta.className = 'new-week-meta';

      var provider = document.createElement('span');
      provider.textContent = asset.provider || '—';

      var when = document.createElement('span');
      when.className = 'new-week-date';
      when.textContent = formatDate(asset.first_seen_at);

      meta.appendChild(provider);
      meta.appendChild(when);
      item.appendChild(model);
      item.appendChild(meta);
      list.appendChild(item);
    });
  }

  // --------------------------------------------- team filter + unassigned KPI
  // The summary endpoint has no team breakdown, so derive the distinct team
  // list and the unassigned count client-side from a single wide fetch.
  // Capped at DERIVE_LIMIT — fine for a local single-developer proxy.
  async function fetchTeamsAndUnassigned() {
    var params = new URLSearchParams();
    params.set('limit', String(DERIVE_LIMIT));
    params.set('offset', '0');

    var resp;
    try {
      resp = await fetch(ASSETS_URL + '?' + params.toString());
    } catch (e) {
      return;
    }
    if (!resp.ok) return;

    var data = await resp.json();
    var items = data.items || [];
    var teams = {};
    var unassigned = 0;
    items.forEach(function (asset) {
      var team = asset.owner_team;
      if (team) {
        teams[team] = true;
      } else {
        unassigned += 1;
      }
    });

    populateSelect('filter-team', Object.keys(teams), state.ownerTeam);
    setText('kpi-unassigned', String(unassigned));
  }

  // --------------------------------------------------- shadow AI alerts panel
  function fillShadowActions(asset, container) {
    clearElement(container);

    var approve = document.createElement('button');
    approve.className = 'btn-approve';
    approve.textContent = 'Approve';
    approve.addEventListener('click', function () { approveAsset(asset.id); });
    container.appendChild(approve);

    var assign = document.createElement('button');
    assign.className = 'btn-assign';
    assign.textContent = asset.owner_team ? 'Reassign' : 'Assign Team';
    assign.addEventListener('click', function () {
      clearElement(container);
      var input = document.createElement('input');
      input.type = 'text';
      input.className = 'inline-input';
      input.placeholder = 'Team name';
      input.value = asset.owner_team || '';

      var save = document.createElement('button');
      save.className = 'btn-save-team';
      save.textContent = 'Save';

      function commit() {
        var name = input.value.trim();
        if (name) assignTeam(asset.id, name);
        else fillShadowActions(asset, container);
      }
      save.addEventListener('click', commit);
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') commit();
        if (e.key === 'Escape') fillShadowActions(asset, container);
      });

      container.appendChild(input);
      container.appendChild(save);
      input.focus();
    });
    container.appendChild(assign);
  }

  function renderShadowCard(asset) {
    var card = document.createElement('div');
    card.className = 'shadow-card';

    var model = document.createElement('div');
    model.className = 'model-name';
    model.textContent = asset.model_name || '(unknown model)';
    card.appendChild(model);

    var meta = document.createElement('div');
    meta.className = 'shadow-meta';
    var provider = document.createElement('span');
    provider.className = 'shadow-provider';
    provider.textContent = asset.provider || '—';
    meta.appendChild(provider);
    meta.appendChild(badge('risk', asset.risk_tier));
    card.appendChild(meta);

    if (asset.endpoint_url) {
      var endpoint = document.createElement('div');
      endpoint.className = 'shadow-endpoint';
      endpoint.textContent = asset.endpoint_url;
      card.appendChild(endpoint);
    }

    var seen = document.createElement('div');
    seen.className = 'shadow-seen';
    seen.textContent = 'First seen ' + formatDate(asset.first_seen_at);
    card.appendChild(seen);

    var actions = document.createElement('div');
    actions.className = 'shadow-actions';
    fillShadowActions(asset, actions);
    card.appendChild(actions);

    return card;
  }

  async function fetchShadowAssets() {
    var panel = byId('shadow-panel');
    if (!panel) return;

    var params = new URLSearchParams();
    params.set('status', 'shadow');
    params.set('sort_by', 'monthly_spend_usd');
    params.set('sort_dir', 'desc');
    params.set('limit', '50');

    var resp;
    try {
      resp = await fetch(ASSETS_URL + '?' + params.toString());
    } catch (e) {
      return;
    }
    if (!resp.ok) return;

    var data = await resp.json();
    var items = data.items || [];
    setText('shadow-panel-count', String(data.total != null ? data.total : items.length));

    clearElement(panel);
    if (items.length === 0) {
      var empty = document.createElement('div');
      empty.className = 'loading-text';
      var emptyIcon = document.createElement('span');
      emptyIcon.className = 'shadow-empty-icon';
      emptyIcon.textContent = '✓';
      empty.appendChild(emptyIcon);
      empty.appendChild(document.createTextNode('No shadow AI detected — every asset is reviewed.'));
      panel.appendChild(empty);
      return;
    }
    items.forEach(function (asset) {
      panel.appendChild(renderShadowCard(asset));
    });
  }

  // --------------------------------------------------- discovery timeline panel
  var EVENT_ICONS = {
    new_asset_detected: '🔍',
    discovered: '🔍',
    first_seen: '🔍',
    approved: '✅',
    status_changed: '🔄',
    team_assigned: '👥',
    risk_changed: '⚠️',
    spend_spike: '📈',
    deprecated: '🗑️',
  };

  function eventTitle(type) {
    return String(type || 'event').replace(/_/g, ' ').replace(/\b\w/g, function (c) {
      return c.toUpperCase();
    });
  }

  function eventDetailText(details) {
    if (!details || typeof details !== 'object') return '';
    return Object.keys(details).map(function (k) {
      return k + ': ' + details[k];
    }).join(' · ');
  }

  async function fetchTimeline() {
    var panel = byId('timeline-panel');
    if (!panel) return;

    var resp;
    try {
      resp = await fetch(EVENTS_URL + '?limit=50');
    } catch (e) {
      return;
    }
    if (!resp.ok) return;

    var data = await resp.json();
    var items = data.items || [];

    clearElement(panel);
    if (items.length === 0) {
      var empty = document.createElement('div');
      empty.className = 'loading-text';
      empty.textContent = 'No discovery events yet.';
      panel.appendChild(empty);
      return;
    }

    items.forEach(function (event) {
      var row = document.createElement('div');
      row.className = 'timeline-event';

      var icon = document.createElement('div');
      icon.className = 'event-icon';
      icon.textContent = EVENT_ICONS[event.event_type] || '•';
      row.appendChild(icon);

      var body = document.createElement('div');
      body.className = 'event-body';

      var label = document.createElement('div');
      label.className = 'event-type-label';
      label.textContent = eventTitle(event.event_type);
      body.appendChild(label);

      var detailText = eventDetailText(event.details);
      if (detailText) {
        var details = document.createElement('div');
        details.className = 'event-details';
        details.textContent = detailText;
        body.appendChild(details);
      }

      var time = document.createElement('div');
      time.className = 'event-time';
      time.textContent = formatDate(event.detected_at);
      body.appendChild(time);

      row.appendChild(body);
      panel.appendChild(row);
    });
  }

  // ----------------------------------------------------------------- mutations
  async function approveAsset(id) {
    try {
      await fetch(ASSETS_URL + '/' + id + '/approve', { method: 'POST' });
    } catch (e) {
      return;
    }
    await refreshAll();
  }

  async function assignTeam(id, team) {
    try {
      await fetch(ASSETS_URL + '/' + id, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ owner_team: team }),
      });
    } catch (e) {
      return;
    }
    await refreshAll();
  }

  function refreshAll() {
    return Promise.all([
      fetchSummary(),
      fetchAssets(),
      fetchNewThisWeek(),
      fetchTeamsAndUnassigned(),
      fetchShadowAssets(),
      fetchTimeline(),
    ]);
  }

  // --------------------------------------------------------------- saved views
  // Filter presets persisted in localStorage (no backend). A view is a snapshot
  // of every filter/sort field in `state`.
  var VIEW_FIELDS = [
    'provider', 'status', 'riskTier', 'ownerTeam', 'dateSince', 'search',
    'sortBy', 'sortDir',
  ];

  function loadViews() {
    try {
      var raw = window.localStorage.getItem(VIEWS_STORAGE_KEY);
      var parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (e) {
      return {};
    }
  }

  function storeViews(views) {
    try {
      window.localStorage.setItem(VIEWS_STORAGE_KEY, JSON.stringify(views));
    } catch (e) {
      // Storage unavailable / full — saved views silently degrade.
    }
  }

  function populateViewsSelect(selectedName) {
    var sel = byId('saved-views-select');
    if (!sel) return;
    var views = loadViews();
    while (sel.options.length > 1) {
      sel.remove(1);
    }
    Object.keys(views).sort().forEach(function (name) {
      var opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      sel.appendChild(opt);
    });
    sel.value = selectedName || '';
    var del = byId('delete-view-btn');
    if (del) del.style.display = sel.value ? '' : 'none';
  }

  function syncControlsFromState() {
    var map = {
      'filter-provider': state.provider,
      'filter-status': state.status,
      'filter-risk': state.riskTier,
      'filter-team': state.ownerTeam,
      'filter-date-since': state.dateSince,
    };
    Object.keys(map).forEach(function (id) {
      var el = byId(id);
      if (el) el.value = map[id] || '';
    });
    var search = byId('global-search');
    if (search) search.value = state.search || '';
  }

  function applyView(name) {
    var views = loadViews();
    var view = views[name];
    if (!view) return;
    VIEW_FIELDS.forEach(function (field) {
      if (view[field] !== undefined) state[field] = view[field];
    });
    state.offset = 0;
    syncControlsFromState();
    fetchAssets();
    var del = byId('delete-view-btn');
    if (del) del.style.display = 'none';
    if (del && name) del.style.display = '';
  }

  function saveCurrentView(name) {
    var views = loadViews();
    var snapshot = {};
    VIEW_FIELDS.forEach(function (field) { snapshot[field] = state[field]; });
    views[name] = snapshot;
    storeViews(views);
    populateViewsSelect(name);
  }

  function deleteView(name) {
    if (!name) return;
    var views = loadViews();
    delete views[name];
    storeViews(views);
    populateViewsSelect('');
  }

  function wireSavedViews() {
    populateViewsSelect('');

    var sel = byId('saved-views-select');
    if (sel) {
      sel.addEventListener('change', function () {
        if (sel.value) {
          applyView(sel.value);
        } else {
          var del = byId('delete-view-btn');
          if (del) del.style.display = 'none';
        }
      });
    }

    var form = byId('save-view-form');
    var nameInput = byId('view-name-input');
    var errorEl = byId('save-view-error');

    function showError(msg) {
      if (errorEl) errorEl.textContent = msg || '';
    }

    var saveBtn = byId('save-view-btn');
    if (saveBtn && form) {
      saveBtn.addEventListener('click', function () {
        form.style.display = '';
        showError('');
        if (nameInput) {
          nameInput.value = '';
          nameInput.focus();
        }
      });
    }

    function commitSave() {
      var name = nameInput ? nameInput.value.trim() : '';
      if (!name) {
        showError('Name required');
        return;
      }
      saveCurrentView(name);
      if (form) form.style.display = 'none';
      showError('');
    }

    var confirmBtn = byId('confirm-save-view');
    if (confirmBtn) confirmBtn.addEventListener('click', commitSave);
    if (nameInput) {
      nameInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') commitSave();
        if (e.key === 'Escape' && form) form.style.display = 'none';
      });
    }

    var cancelBtn = byId('cancel-save-view');
    if (cancelBtn && form) {
      cancelBtn.addEventListener('click', function () {
        form.style.display = 'none';
        showError('');
      });
    }

    var deleteBtn = byId('delete-view-btn');
    if (deleteBtn && sel) {
      deleteBtn.addEventListener('click', function () {
        deleteView(sel.value);
      });
    }
  }

  // ------------------------------------------------------------------- wiring
  function wireControls() {
    var headers = document.querySelectorAll('#asset-table th.sortable');
    for (var i = 0; i < headers.length; i++) {
      (function (th) {
        th.addEventListener('click', function () {
          var col = th.getAttribute('data-col');
          if (!col) return;
          if (state.sortBy === col) {
            state.sortDir = state.sortDir === 'desc' ? 'asc' : 'desc';
          } else {
            state.sortBy = col;
            state.sortDir = 'desc';
          }
          state.offset = 0;
          fetchAssets();
        });
      })(headers[i]);
    }

    function onFilterChange(id, key) {
      var el = byId(id);
      if (!el) return;
      el.addEventListener('change', function () {
        state[key] = el.value;
        state.offset = 0;
        fetchAssets();
      });
    }
    onFilterChange('filter-provider', 'provider');
    onFilterChange('filter-status', 'status');
    onFilterChange('filter-risk', 'riskTier');
    onFilterChange('filter-team', 'ownerTeam');
    onFilterChange('filter-date-since', 'dateSince');

    var search = byId('global-search');
    if (search) {
      search.addEventListener('input', debounce(function () {
        state.search = search.value.trim();
        state.offset = 0;
        fetchAssets();
      }, 300));
    }

    var prev = byId('btn-prev');
    if (prev) {
      prev.addEventListener('click', function () {
        state.offset = Math.max(0, state.offset - PAGE_SIZE);
        fetchAssets();
      });
    }
    var next = byId('btn-next');
    if (next) {
      next.addEventListener('click', function () {
        state.offset = state.offset + PAGE_SIZE;
        fetchAssets();
      });
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    wireControls();
    wireSavedViews();
    refreshAll();

    // Honor the header "auto-refreshes every 30s" indicator. Skip while the
    // user is mid-edit (inline team input or the save-view form open) so we
    // never clobber in-progress input.
    setInterval(function () {
      if (document.querySelector('.inline-input')) return;
      var form = byId('save-view-form');
      if (form && form.style.display !== 'none') return;
      refreshAll();
    }, 30000);
  });
})();
