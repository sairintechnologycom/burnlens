---
plan: 14-05
status: complete
tasks_completed: 2
commits:
  - ccfc2d1
  - f2fe5c9
---

## What Was Built

`GET /api/routing-stats` dashboard endpoint + Downgrades Today KPI card
+ Routed column in the Recent Requests table. Real savings computed via
_compute_savings() using calculate_cost() on original model vs actual cost.

## Key Files Changed

- `burnlens/dashboard/routes.py` — `/api/routing-stats` endpoint with
  `_compute_savings()` helper using calculate_cost(). PRAGMA guard for
  pre-migration databases.
- `burnlens/dashboard/static/index.html` — Downgrades Today KPI card
  (id=kpi-downgrades + id=kpi-downgrades-sub); Routed column header in
  Recent Requests table; colspan updated 8→9.
- `burnlens/dashboard/static/app.js` — fetchRoutingStats() populates
  KPI card; fetchRequests() renders routed-badge span or dash per row;
  fetchRoutingStats() added to refresh() Promise.allSettled().

## Must-Have Verification

- [x] GET /api/routing-stats returns all 4 fields
- [x] downgrades_today counts WHERE downgrade_reason IS NOT NULL AND DATE = today
- [x] downgrades_this_month counts from first of month
- [x] saved_usd_today computed via _compute_savings(), not hardcoded 0.0
- [x] Dashboard Downgrades Today stat card present
- [x] Recent Requests Routed column with original→routed badge
- [x] Rows without downgrade show "-" in Routed column

## Self-Check: PASSED
