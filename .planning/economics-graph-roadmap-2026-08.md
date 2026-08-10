# BurnLens Economics Graph — Roadmap 2026-08

**Status**: Approved direction, ready for implementation.
**Origin**: Strategy review 2026-08-09 of external "Technology Economics Intelligence" recommendation doc, cross-checked against the actual codebase.
**Executor**: Hand each phase to an implementation agent as an independent unit. Phases are ordered by dependency; A must land before B, B before C. D and E are independent of C and can run in parallel after A.

---

## 1. Strategic frame (context for every phase)

The external doc proposed 7 phases starting from "build trustworthy cost ingestion" and "CSV upload of OpenAI usage". **Most of that already exists.** BurnLens is already a live multi-provider AI cost proxy with:

- Event identity: `event_id`, provider `request_id` extraction from headers and stream chunks, dedup contract (`tests/test_phase1_event_contract.py`)
- Request-level attribution tags: `team, feature, app_id, env, repo, branch, commit_sha, workspace_id, org_id, trace_id, customer, key_label, service, dev, pr` (`_ALLOWED_TAGS`, `burnlens/proxy/interceptor.py:~173`)
- Git context capture (`burnlens/git_context.py`), virtual keys, budgets, forecast, detection module (`burnlens/detection/`), alert engine, cloud sync + ClickHouse
- Agent-log scanners for Claude Code, Cursor, Codex, Gemini CLI (`burnlens/scan/`)

**The wedge**: real-time AI + agent cost intelligence with cost-per-accepted-outcome. The proxy sits in the request path — it sees agent loops, retries, and tool fan-out live, which no cloud-bill tool can.

**Positioning line**:
> BurnLens: real-time AI and agent cost intelligence — every model call attributed to an agent, workflow, and business outcome, anomalies caught in the request path, numbers that match the provider's bill.

### Explicit non-goals (cut from the external doc — do NOT build)

| Cut | Why |
|---|---|
| Cloud bill / resource ingestion (AWS CUR etc.) | Crowded market (Finout, CloudHealth, Kubecost); contradicts the wedge |
| GPU utilization / idle-cause analysis | Different product; needs host agents + DCGM |
| Commitment/reservation risk module | Enterprise procurement sale, wrong stage |
| SaaS seat + labor cost tracking | Defer until customers ask |
| SecOps–FinOps module | Don't build as module; "spend spike + new destination" alert falls out of Phase D data later |
| Niyam integration | Product doesn't exist; shared vocabulary in schema is free, integration work is not |
| Generic AI chatbot, marketplace, automated remediation | Distractions |

---

## 2. Graph engineering approach

Model the economics domain as a property graph built incrementally. Every phase adds nodes or edges; no phase rebuilds what exists.

```text
NODES                          EDGES
Workspace                      Workspace  ─owns→      App / Agent / Workflow
App (tag: app_id)              Agent      ─belongs_to→ App
Agent (NEW tag: agent_id)      Request    ─attributed_to→ Agent, Workflow, Team, Customer, Env
Workflow (NEW tag: workflow_id)Request    ─costs→      cost_usd (exists today)
Request/CostEvent (exists)     Outcome    ─consumes→   Requests (join on workflow_id + window)
Outcome (NEW)                  Anomaly    ─flags→      Agent (baseline deviation)
Anomaly (exists, extend)       Reconciliation ─verifies→ provider-level cost sums
```

Physical storage stays what it is: SQLite `requests` table (OSS proxy) + Postgres/ClickHouse (cloud). "Graph" = consistent identity keys + join semantics, NOT a graph database. Do not introduce a graph DB.

Existing identity spine (do not change): `event_id` / `request_id` / `trace_id` / `workspace_id`. All new nodes hang off this spine.

---

## 3. Phases

### Phase A — Agent & workflow identity edges (small; do first)

**Goal**: every request attributable to an agent and a workflow; retry and tool-call signals captured.

Build:
1. Add `agent_id`, `workflow_id` to `_ALLOWED_TAGS` in `burnlens/proxy/interceptor.py`. Flows via existing `X-BurnLens-Tag-*` headers and env fallback — the mechanism already exists, this is a set-membership change plus column plumbing.
2. Add `tag_agent_id` / `tag_workflow_id` columns to the SQLite `requests` migration chain (`burnlens/storage/database.py` — follow the existing `ALTER TABLE requests ADD COLUMN` pattern) and to the cloud sync payload (`burnlens/cloud/sync.py` `_row_to_payload`), cloud models (`burnlens_cloud/models.py` — extend the `_lift_flat_tags` re-nesting list), and ClickHouse schema.
3. Count `tool_calls` per request: parse the response body for tool-use blocks (Anthropic `tool_use` content blocks, OpenAI `tool_calls` array). New int column on `requests`. Best-effort — 0 when unparseable.
4. Retry detection: same `trace_id` + same model + request within N seconds of a failed request = retry. Store `is_retry` flag or derive at query time — prefer derive-at-query-time first (no schema change), promote to column only if query cost hurts.
5. Extend `CostByTag` dashboards/API: cost by agent, cost by workflow.

**Standing-guard requirement**: extend `tests/test_provider_hooks_wired.py` pattern — a test that fails if a new tag is added to `_ALLOWED_TAGS` but not to the storage columns, sync payload, and cloud re-nesting list. This closes the known "abstraction built, wire-up missed" failure family (7 prior instances).

Exit criteria:
- Request through proxy with `X-BurnLens-Tag-Agent-Id: refund-agent` lands in SQLite, syncs to cloud, appears in cost-by-agent view.
- Tool-call count captured for Anthropic + OpenAI response shapes (test with recorded fixtures).
- Guard test red if plumbing incomplete.

### Phase B — Outcome nodes + cost per accepted outcome (the differentiator)

**Goal**: `cost_event → workflow → accepted_outcome` join works end to end.

Build:
1. New table `outcomes` (cloud Postgres, mirrored to ClickHouse): `outcome_id, workspace_id, workflow_id, status (accepted|rejected|failed), business_value NUMERIC NULL, currency, event_time, source (api|derived), metadata JSONB`. Idempotent on `(workspace_id, outcome_id)` — same ON CONFLICT discipline as ingest.
2. `POST /api/outcomes` in `burnlens_cloud` — authenticated with existing API-key auth, validated, workspace-scoped. Batch accepted.
3. Cost allocation: cost of an outcome = sum of request `cost_usd` where `workflow_id` matches, within an allocation window (default: since previous outcome for that workflow, cap 24h; window configurable per workflow later — do NOT build config UI now).
4. Metric endpoints + dashboard view: cost per accepted outcome, failure/rework cost (spend attributed to rejected/failed outcomes), trend over time, comparison by model within the same workflow.
5. OSS proxy CLI: `burnlens outcome record --workflow refund_review --status accepted` for local/dev use, writing to a local `outcomes` table and syncing like requests do.

Exit criteria:
- Synthetic E2E: N proxied requests tagged `workflow_id=support_ticket` + M outcome posts → dashboard shows cost per accepted resolution matching hand-computed number.
- Duplicate outcome post does not double-count.
- Zero-outcome workflow shows "unattributed spend", not a divide-by-zero.

### Phase C — Derived outcomes (adoption cliff killer)

**Goal**: cost-per-outcome without customer instrumentation, for the audience BurnLens already serves — coding agents.

The classic failure of unit-economics products: customers never instrument outcome events. BurnLens can derive them:

Build:
1. Coding-agent outcome deriver: scan module (`burnlens/scan/`) + git context already identify sessions and repos. Derive `outcome = PR merged` via `gh` CLI or GitHub API when repo/pr tags are present; `status=accepted` on merge, `rejected` on close-without-merge. Emit into the Phase B outcomes table with `source=derived`.
2. Map scanned agent-session cost (Claude Code / Cursor / Codex / Gemini CLI scanners) to the same workflow join so "cost per merged PR" works for scan data, not just proxied traffic.
3. One derived-outcome dashboard: cost per merged PR by repo / branch / dev.

Exit criteria: on the BurnLens repo itself, dashboard shows real cost-per-merged-PR from actual usage. Dogfood number in README/marketing.

### Phase D — Agent anomaly baselines (runs parallel to B/C after A)

**STATUS: BUILT 2026-08-10** — `AnomalyDetector.check_agent()` + `check_active_agents()` in `burnlens/detection/anomaly.py`, called from `run_detection` in `scheduler.py`; five `[alerts]` config keys; `tests/test_agent_anomaly_baselines.py`. Proxy-only, so it ships on the next `v*` tag, not on a deploy. Deviations from the spec below: (a) **no tool-call baseline** — `tool_calls` is 0 on the SSE streaming path, so it would silently under-count every streaming agent; (b) the retry-rate deviation reports as an `anomaly_events` `cost_spike` row with `details['signal'] = 'retry_rate'`, because that table's `CHECK(event_type IN ('cost_spike','runaway_loop'))` predates the signal and widening it means a table rebuild; (c) signals are ranked loop > spend > retry and only the top one fires, which is what makes "exactly one alert" hold when a burst trips all three.

**Goal**: "Agent spent 4.8x normal after a change" alert.

Build:
1. Per-`agent_id` rolling baseline (7-day, hourly buckets) of spend, request count, retry rate, tool-call count. Compute in existing detection scheduler (`burnlens/detection/scheduler.py` + `anomaly.py`) — extend, don't fork.
2. Deviation alert (default 3x baseline, min-spend floor to avoid noise on tiny agents) through the existing alert engine → Slack/email paths that already exist.
3. Loop heuristic: >K requests with same `agent_id` + same `trace_id` within M minutes = suspected loop; distinct alert type. Constants tunable via existing config, no UI.
4. Correlate with change: if git `commit_sha` tag changed within the anomaly window, include "after deploy <sha>" in the alert text. Cheap, high perceived intelligence.

Exit criteria: replayed synthetic burst on a tagged agent fires exactly one deduplicated alert (existing `fired_alerts` dedup) naming multiplier and, when present, the commit.

### Phase E — Reconciliation (the trust feature; independent, any time after A)

**STATUS: BUILT 2026-08-10** — `burnlens_cloud/reconciliation.py` (provider cost clients + drift + credential and status endpoints), `reconciliation_credentials` / `reconciliation_runs` tables, `POST /cron/reconcile` + `.github/workflows/cron-reconcile.yml` (06:00 UTC), dashboard badge in `frontend/src/app/dashboard/page.tsx`, `tests/test_reconciliation.py`. Cloud-only — no proxy change, so no PyPI release. Google/Bedrock/Azure have no usable per-day cost API wired, so they simply cannot be reconciled and the badge omits them rather than implying agreement. ⚠️ **Anthropic's cost report returns MINOR UNITS** (`"123.45"` USD = $1.23); OpenAI's returns dollars. Mixing them up is a silent 100x.

**Goal**: BurnLens's number provably matches the provider's bill. Nobody trusts a cost tool until it survives this comparison.

Build:
1. Daily job pulling provider usage/cost APIs where available (OpenAI usage API, Anthropic usage/cost API; skip providers without one) per workspace credential.
2. Compare provider-reported daily cost vs BurnLens-computed sum per provider. Store drift %; alert (existing ops-alert path) when |drift| > threshold (start 2%).
3. Dashboard badge per provider: "Reconciled ✓ 0.3% drift" / "Unreconciled".
4. Known legitimate drift causes documented in the UI copy (non-proxied traffic, pricing lag, rounding) so drift reads as diagnosis, not failure.

**Trust also means ops** (context for executor, mostly done): startup credential inventory + Paddle liveness probe shipped (PR #80); fail-open outage class documented in memory. Any NEW credential added by these phases (GitHub token in C, provider usage-API keys in E) MUST register in `burnlens_cloud/startup_check.py` inventory.

Exit criteria: for a workspace with proxied OpenAI traffic, daily reconciliation row exists and drift computed; forced-mismatch test fires the alert.

---

## 4. Sequencing summary

```text
A (agent/workflow identity)          ~small
├─ B (outcomes + cost-per-outcome)   the differentiator
│   └─ C (derived outcomes)          adoption + dogfood story
├─ D (agent anomaly baselines)       parallel to B/C
└─ E (reconciliation)                parallel; trust
```

Everything in the non-goals table stays cut until A–E pull revenue or explicit customer demand.

## 5. Standing constraints for the implementer

- Never bypass `handle_request` / Provider hooks — `tests/test_provider_hooks_wired.py` is a standing guard; extend it for every new hook.
- All frontend mutations use `apiFetch` (X-Requested-With CSRF); `CORSMiddleware` stays outermost in `main.py`.
- CI gate before merge: never `gh pr checks | tail && gh pr merge` (pipe eats failure exit code). `export GH_TOKEN=$(gh auth token --user sairintechnologycom)` before push/merge.
- Proxy code ships via PyPI (`v*` tag → publish.yml); cloud ships via GH Actions to Railway (git-watcher OFF).
- Local full pytest baseline: ~1174 passed OSS-only (~1577 with cloud deps); 3 OTEL failures pre-exist; async-logging flake family is FIXED — a failure there is real.
- New env vars → `burnlens_cloud/config.py` + `startup_check.py` inventory + Railway.
