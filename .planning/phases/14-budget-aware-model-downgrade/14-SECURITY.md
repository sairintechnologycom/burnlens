---
phase: 14
slug: budget-aware-model-downgrade
status: verified
threats_open: 0
asvs_level: 1
created: 2026-05-06
---

# Phase 14 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| YAML config → Python runtime | `burnlens.yaml` routing block parsed by `config.py` `load_config()` | budget thresholds, bool flags — type-confused YAML values could subvert routing logic |
| SQLite → router cache | `_team_spend_cache` / `_customer_spend_cache` populated from DB queries | spend totals used to make downgrade decisions |
| Request body (bytes) → JSON rewrite | `interceptor.py` parses `body_bytes` to swap `"model"` field before forwarding | user-originated request body; parse failure must not break proxy |
| Dashboard HTML (localhost) → browser DOM | `app.js` renders `routed_model` from SQLite rows into the DOM | model name strings — could carry injected markup if not safely inserted |
| CLI stdout → terminal | `burnlens routing --json` dumps SQLite rows as JSON to stdout | local spend + model names; no network transmission |
| Test process → shared module state | `_team_spend_cache` dict lives in module scope across all test functions | stale entries leak spend state between tests, causing spurious failures |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-14-01-01 | Tampering | RoutingConfig YAML parse | mitigate | `config.py:348-351` — explicit `bool()` + `float()` casts on every routing field; YAML type coercion neutralised | closed |
| T-14-01-02 | Denial of Service | downgrade_threshold_pct | accept | Invalid float causes startup error with clear message — fail-fast at config load is acceptable; see accepted risks | closed |
| T-14-02-01 | Tampering | insert_request routed_model column | accept | `routed_model` set server-side from `RouteDecision` only — never from user-controlled request input; see accepted risks | closed |
| T-14-02-02 | Denial of Service | migrate_add_routing_columns idempotency | mitigate | `database.py:294-301` — `PRAGMA table_info(requests)` check before every `ALTER TABLE`; safe to call at every startup | closed |
| T-14-03-01 | Spoofing | tag_team header used as budget dict key | accept | `X-BurnLens-Tag-*` headers are set by the developer, not end-users; trusted internal integration; see accepted risks | closed |
| T-14-03-02 | Denial of Service | _team_spend_cache grows unbounded | accept | One entry per team name; enterprise deployments have O(10s) teams; memory impact negligible; see accepted risks | closed |
| T-14-03-03 | Elevation of Privilege | Routing error falls back to original model | mitigate | `router.py:91-94` — outer `try/except` in `decide_route()` catches all exceptions; returns pass-through decision (fail-open) | closed |
| T-14-04-01 | Tampering | body_bytes JSON rewrite | mitigate | `interceptor.py:449-455` — `try/except Exception: pass` wraps `json.loads`/`json.dumps`; parse failure leaves `body_bytes` unmodified (fail-open) | closed |
| T-14-04-02 | Information Disclosure | logger.info downgrade log | accept | Log contains model names and budget amounts — no PII, no prompt content; INFO level is operator-visible only; see accepted risks | closed |
| T-14-04-03 | Repudiation | decision stored in RequestRecord | mitigate | `database.py:286-305` migration adds `routed_model`, `downgrade_reason`, `budget_remaining_usd`, `budget_remaining_pct` columns; every request creates an immutable audit record | closed |
| T-14-05-01 | Cross-site Scripting | model name rendered in Routed column | mitigate | `app.js:697-699` — uses `routedBadge.textContent` (not innerHTML); `textContent` never parses HTML — stronger than the planned `escHtml()` approach | closed |
| T-14-05-02 | Information Disclosure | /api/routing-stats exposes downgrade counts | accept | Dashboard is localhost-only (`127.0.0.1:8420`); no auth required by design; counts reveal no sensitive data; see accepted risks | closed |
| T-14-06-01 | Information Disclosure | burnlens routing --json | accept | JSON output goes to stdout on the user's local machine; no network transmission; user has full access to their own SQLite DB; see accepted risks | closed |
| T-14-06-02 | Injection | today_only param in SQL WHERE clause | mitigate | `database.py:926-931` — `date.today().isoformat()` is a computed value (not user input); passed as parameterised `?` placeholder — no injection path | closed |
| T-14-07-01 | Denial of Service | _team_spend_cache leaking between tests | mitigate | `tests/test_router.py:33-39` — `@pytest.fixture(autouse=True) def clear_router_cache()` clears `_team_spend_cache` before and after every test function | closed |

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-14-01 | T-14-01-02 | Invalid YAML float for `downgrade_threshold_pct` causes startup error with a clear message. This is an operator configuration mistake, not a runtime attack. Fail-fast at startup is the correct behaviour — a mis-configured proxy should not silently accept all traffic. | plan author | 2026-05-06 |
| AR-14-02 | T-14-02-01 | `routed_model` is populated entirely from `DOWNGRADE_MAP` server-side logic; the value originates in the proxy's own routing decision, not from the request body or headers. No user-controlled string reaches this column. | plan author | 2026-05-06 |
| AR-14-03 | T-14-03-01 | `X-BurnLens-Tag-*` headers are set by application developers (not end-users) in their SDK call wrappers or environment configs. The tag is used as a dict key for spend lookup — an adversarial tag can only cause the wrong budget bucket to be checked, not escalate privileges or access another team's data. | plan author | 2026-05-06 |
| AR-14-04 | T-14-03-02 | `_team_spend_cache` holds one entry per unique team tag value. Enterprise deployments have O(10s–100s) distinct teams; each entry is a `(float, float)` tuple. Total memory footprint is negligible (< 1 KB for 100 teams). No eviction policy is needed at current scale. | plan author | 2026-05-06 |
| AR-14-05 | T-14-04-02 | The downgrade log line emits: original model name, routed model name, budget remaining in USD, budget remaining as %. None of these are PII or prompt content. The log is at INFO level — visible to the operator running `burnlens start`, not transmitted externally. | plan author | 2026-05-06 |
| AR-14-06 | T-14-05-02 | `/api/routing-stats` is served by the FastAPI app bound to `127.0.0.1` (loopback). It is inaccessible from external networks by design. The endpoint exposes aggregate downgrade counts — no prompt content, no API keys, no personally identifiable information. | plan author | 2026-05-06 |
| AR-14-07 | T-14-06-01 | `burnlens routing --json` writes JSON to stdout on the user's local machine. The user already has full read access to their own SQLite DB. No new exposure path is introduced. | plan author | 2026-05-06 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-05-06 | 15 | 15 | 0 | gsd-security-auditor (automated) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-05-06
