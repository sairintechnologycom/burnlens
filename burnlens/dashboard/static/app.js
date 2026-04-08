/* BurnLens dashboard — Chart.js + plain fetch */
'use strict';

const API = window.location.origin + '/api';
let modelChart = null;

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function createCell(text) {
  const td = document.createElement('td');
  td.textContent = text;
  return td;
}

function createCostCell(value) {
  const td = document.createElement('td');
  td.textContent = '$' + value.toFixed(5);
  td.className = 'cost';
  return td;
}

async function fetchSummary() {
  const r = await fetch(`${API}/summary`);
  const d = await r.json();
  setText('total-cost', '$' + d.total_cost_usd.toFixed(4));
  setText('total-requests', d.total_requests.toLocaleString());
  setText('models-used', d.models_used);
}

async function fetchModels() {
  const r = await fetch(`${API}/models`);
  const rows = await r.json();

  const labels = rows.map(row => row.model);
  const data = rows.map(row => row.total_cost_usd);
  const colors = rows.map((_, i) => `hsl(${(i * 47) % 360}, 70%, 55%)`);

  const ctx = document.getElementById('model-chart').getContext('2d');
  if (modelChart) modelChart.destroy();
  modelChart = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ label: 'Cost (USD)', data, backgroundColor: colors }] },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#94a3b8' }, grid: { color: '#1e2535' } },
        y: {
          ticks: { color: '#94a3b8', callback: v => '$' + Number(v).toFixed(4) },
          grid: { color: '#1e2535' },
        },
      },
    },
  });
}

async function fetchRequests() {
  const r = await fetch(`${API}/requests?limit=50`);
  const rows = await r.json();
  const tbody = document.getElementById('requests-body');
  tbody.replaceChildren();

  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 7;
    td.textContent = 'No requests yet.';
    td.style.color = '#64748b';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  for (const row of rows) {
    const ts = new Date(row.timestamp + 'Z').toLocaleTimeString();
    const tr = document.createElement('tr');
    tr.appendChild(createCell(ts));
    tr.appendChild(createCell(row.provider));
    tr.appendChild(createCell(row.model));
    tr.appendChild(createCell((row.input_tokens || 0).toLocaleString()));
    tr.appendChild(createCell((row.output_tokens || 0).toLocaleString()));
    tr.appendChild(createCostCell(row.cost_usd || 0));
    tr.appendChild(createCell(row.duration_ms));
    tbody.appendChild(tr);
  }
}

async function refresh() {
  await Promise.all([fetchSummary(), fetchModels(), fetchRequests()]);
}

refresh();
setInterval(refresh, 10000);
