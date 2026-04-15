/* Discovery dashboard — server-side sorted asset table with pagination. */
(function () {
  'use strict';

  let currentSortBy = 'first_seen_at';
  let currentSortDir = 'desc';
  let currentOffset = 0;
  const PAGE_SIZE = 50;

  const SORTABLE_COLUMNS = {
    provider: 'Provider',
    model_name: 'Model',
    owner_team: 'Owner',
    status: 'Status',
    risk_tier: 'Risk',
    first_seen_at: 'First Seen',
    last_active_at: 'Last Active',
    monthly_spend_usd: 'Monthly Spend',
    monthly_requests: 'Requests',
  };

  function clearElement(el) {
    while (el.firstChild) {
      el.removeChild(el.firstChild);
    }
  }

  let currentStatus = null;
  let currentProvider = null;
  let currentRiskTier = null;
  let currentSearch = null;

  function buildFilterParams() {
    const params = new URLSearchParams();
    if (currentStatus) params.set('status', currentStatus);
    if (currentProvider) params.set('provider', currentProvider);
    if (currentRiskTier) params.set('risk_tier', currentRiskTier);
    if (currentSearch) params.set('search', currentSearch);
    return params;
  }

  function buildQueryString() {
    const params = buildFilterParams();
    params.set('sort_by', currentSortBy);
    params.set('sort_dir', currentSortDir);
    params.set('limit', PAGE_SIZE);
    params.set('offset', currentOffset);
    return params.toString();
  }

  async function fetchAssets() {
    const resp = await fetch('/api/v1/assets?' + buildQueryString());
    if (!resp.ok) return;
    const data = await resp.json();
    renderTable(data.assets);
    renderPagination(data.total, data.offset, data.limit);
  }

  async function fetchSummary() {
    const params = buildFilterParams();
    const resp = await fetch('/api/v1/assets/summary?' + params.toString());
    if (!resp.ok) return;
    const data = await resp.json();
    renderKpiCards(data);
  }

  function formatUsd(value) {
    return '$' + Number(value).toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function renderKpiCards(summary) {
    var cards = [
      { id: 'kpi-total-assets', value: summary.total_assets, label: 'Total Assets' },
      { id: 'kpi-monthly-spend', value: formatUsd(summary.monthly_spend_usd_total), label: 'Monthly Spend' },
      { id: 'kpi-shadow-assets', value: summary.shadow_assets, label: 'Shadow Assets' },
      { id: 'kpi-new-this-week', value: summary.new_this_week, label: 'New This Week' },
    ];
    for (var i = 0; i < cards.length; i++) {
      var el = document.getElementById(cards[i].id);
      if (el) el.textContent = String(cards[i].value);
    }
  }

  function sortIndicator(col) {
    if (col !== currentSortBy) return '';
    return currentSortDir === 'asc' ? ' \u25B2' : ' \u25BC';
  }

  function renderTable(assets) {
    const thead = document.getElementById('asset-thead');
    const tbody = document.getElementById('asset-tbody');
    if (!thead || !tbody) return;

    clearElement(thead);
    const tr = document.createElement('tr');
    for (const [col, label] of Object.entries(SORTABLE_COLUMNS)) {
      const th = document.createElement('th');
      th.textContent = label + sortIndicator(col);
      th.style.cursor = 'pointer';
      th.addEventListener('click', function () {
        if (currentSortBy === col) {
          currentSortDir = currentSortDir === 'desc' ? 'asc' : 'desc';
        } else {
          currentSortBy = col;
          currentSortDir = 'desc';
        }
        currentOffset = 0;
        fetchAssets();
      });
      tr.appendChild(th);
    }
    thead.appendChild(tr);

    clearElement(tbody);
    for (const asset of assets) {
      const row = document.createElement('tr');
      for (const col of Object.keys(SORTABLE_COLUMNS)) {
        const td = document.createElement('td');
        td.textContent = asset[col] != null ? String(asset[col]) : '';
        row.appendChild(td);
      }
      tbody.appendChild(row);
    }
  }

  function renderPagination(total, offset, limit) {
    const el = document.getElementById('asset-pagination');
    if (!el) return;

    const page = Math.floor(offset / limit) + 1;
    const pages = Math.ceil(total / limit);

    clearElement(el);

    if (page > 1) {
      const prev = document.createElement('button');
      prev.textContent = 'Prev';
      prev.addEventListener('click', function () {
        currentOffset = Math.max(0, currentOffset - PAGE_SIZE);
        fetchAssets();
      });
      el.appendChild(prev);
    }

    const span = document.createElement('span');
    span.textContent = ' Page ' + page + ' of ' + pages + ' (' + total + ' assets) ';
    el.appendChild(span);

    if (page < pages) {
      const next = document.createElement('button');
      next.textContent = 'Next';
      next.addEventListener('click', function () {
        currentOffset = currentOffset + PAGE_SIZE;
        fetchAssets();
      });
      el.appendChild(next);
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    fetchAssets();
    fetchSummary();
  });
})();
