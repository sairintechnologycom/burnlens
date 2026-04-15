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

  function buildQueryString() {
    const params = new URLSearchParams({
      sort_by: currentSortBy,
      sort_dir: currentSortDir,
      limit: PAGE_SIZE,
      offset: currentOffset,
    });
    return params.toString();
  }

  async function fetchAssets() {
    const resp = await fetch('/api/v1/assets?' + buildQueryString());
    if (!resp.ok) return;
    const data = await resp.json();
    renderTable(data.assets);
    renderPagination(data.total, data.offset, data.limit);
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

  document.addEventListener('DOMContentLoaded', fetchAssets);
})();
