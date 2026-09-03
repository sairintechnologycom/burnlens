# Changelog

All notable changes to this project will be documented in this file.

This file documents both the OSS PyPI package (`burnlens`) and the
internal cloud service (`burnlens-cloud`, deployed only). Each entry is
qualified with the package it covers.

## [OSS `burnlens` v1.26.0] — 2026-09-03

### Changed
- **Budget-aware model downgrade is off by default.** Observation must not
  rewrite `model`. `routing.budget_downgrade` now defaults to `false`; YAML
  that already sets `true` is unchanged, as is a cloud `routing_overrides`
  push. There is no `routing.disabled` key — that flag was documented but
  never parsed. Opt in explicitly, or take the 429.

### Added
- **`pricing_class` on every request.** `unpriced` / `calculated` /
  `estimated` (scan) is persisted at insert and classified at read for rows
  written before the column existed. CSV export adds the column and writes
  `unknown` in `cost_usd` for unpriced rows instead of a measured `$0.00`.
- **`pricing_class` syncs to cloud.** The local write-time class is on the
  ingest payload and stored on `request_records`. Cloud Cost Confidence uses
  it when present and infers from source + cost for older rows. Reconciled
  stays a read-time overlay.
- **`burnlens economics` prints local Cost Confidence and Outcome Coverage.**
  Unpriced models are named; untagged vs unattributed spend is split. There
  is no reconciled bucket locally — that still needs a billing key in Cloud.
  Untagged spend points at `burnlens outcome derive`.
- **Local dashboard shows Cost Confidence and Outcome Coverage** from
  `/api/economics`. Total Spend names unpriced requests as `$ unknown`
  rather than a complete `$0.00`. Recent-request rows do the same.
- **Verified savings on the same local surface as spend.** `burnlens economics`,
  `GET /api/economics`, `GET /api/findings/savings`, and the local dashboard
  now show verified / missed / inconclusive / still-verifying using the
  existing `classify_savings` engine. Missed predictions sit in the
  denominator; they are not negative verified savings.
- **`burnlens scan` derives merged-PR outcomes when `gh` is present.** After
  import it runs the same path as `burnlens outcome derive` on the current
  checkout. If `gh` is missing, that is printed as the reason rather than
  skipped. Dry-run does not derive. No new coding-agent scanners.
- **`burnlens economics` points at `burnlens recommend`.** Projected savings
  come from the existing recommender; the command is named rather than
  rebuilt. `--apply` is how the switch is printed.
- **Cloud dashboard is one economics view.** Overview, `/outcomes`,
  `/savings` and `/waste` share a nav; Overview tiles link to those pages.
  The four engines are unchanged.

### Fixed
- **Local dashboard `/waste` and cloud-compat `/waste-alerts` read every
  matching row.** They used to pass the analysis query's old 1000-row cap
  implicitly. `burnlens analyze` was already unbounded; the dashboard now
  matches.
- **`burnlens scan` discloses that history is priced at today's table**,
  not session-date rates, and that Cost Confidence classifies scanned rows
  as estimated. Unpriced imports are described as `$ unknown`, not `$0.00`.
  After import it prints the local-first next step: `economics`, `repos`,
  `outcome derive`.

## [OSS `burnlens` v1.25.0] — 2026-08-24

### Fixed
- **`burnlens analyze` read at most 1000 requests, whatever window you asked
  for.** `--days 365` on a 158k-row database sampled the most recent 1000 rows
  and printed the result as a total: $28.49, where the real figure for that
  window was $3,528.69. Nothing in the output said a cap had been applied. The
  same silent cap bounded the detection scheduler and the weekly report.
  Analysis now reads every matching row; callers that want a recent slice (the
  dashboard panels) ask for one explicitly.
- **`burnlens recommend` could recommend a more expensive model.** A model
  variant was matched onto its family's downgrade target even when the variant
  was already the cheaper one, producing "switch gpt-5.6-luna → gpt-5.6-terra,
  projected saving -$343.99 (-1840.7%)" and summing that negative into the
  headline total. Recommendations that do not save are no longer emitted.
- **`burnlens recommend` was blind to the models most people are running.** Its
  downgrade map held six entries, matched by exact name, and covered none of
  the current Claude or GPT-5.x families — so a database whose largest waste
  was Opus answering short prompts reported "your model usage looks efficient!"
  Keys are now family prefixes matched longest-first, so new releases and dated
  snapshots are covered without an entry each.
- **The overkill rule required a model's *average* output to be short**, so a
  model used for a mix of trivial and heavy work never qualified — even when
  thousands of its individual calls were pure overkill and the waste detector
  flagged every one. Both engines now aggregate over the short-output requests
  themselves.
- **Savings projections ignored cached prompts.** Anthropic reports cache reads
  separately from `input_tokens`, so coding-agent rows carry `input_tokens` of
  ~6 against ~120,000 cached tokens. Projecting from `input_tokens` alone
  priced the suggested model at nearly nothing and claimed savings of 98–99%.
  Projections now go through the same cost engine that prices real requests,
  which already handles both cached-prompt conventions.
- **`burnlens sync --now` reported "No un-synced records to push" in runs that
  pushed outcomes.** Its count covered cost records only.

## [`burnlens-cloud`] — 2026-08-24

### Added
- `GET /api/v1/outcomes/summary` and `/api/v1/outcomes/concentration` accept an
  API key as well as a dashboard session, so the machine that posts outcomes
  can read back the economics it produced without a browser. The key is scoped
  to its own workspace; an invalid key is rejected outright rather than falling
  through to the session path.

### Fixed
- The hosted recommendation engine shares the proxy's rules, and so shared all
  three recommender defects above. Fixed in step with it.

## [OSS `burnlens` v1.24.0] — 2026-08-14

### Added
- **Prompt-segment token counts now sync to the hosted dashboard**, so the
  oversized-tool-schema, low-RAG-efficiency and history-bloat detectors report
  findings there instead of scoring zero. These are integer counts only — how
  many of the already-synced `input_tokens` went to the system prompt, tool
  schemas, retrieved context and conversation history. No prompt text is sent.
  `prompt_user_tokens`, which measures what the human typed, is deliberately
  not synced. Local-only users are unaffected; nothing new leaves a machine
  that has cloud sync switched off.

## [`burnlens-cloud`] — 2026-08-14

### Added
- `request_records` gained the four `prompt_*_tokens` columns, with a migration
  that backfills existing rows to `0`. Historical rows have no segmentation, so
  the detectors stay inert on them rather than inventing a signal.

## [OSS `burnlens` v1.23.2] — 2026-08-14

### Fixed
- **`burnlens sync` printed a traceback on a machine where the proxy had never
  run.** The command prepared the database differently from every other
  command, so against a database with no tables yet it failed with
  `no such table: requests` instead of reporting that there was nothing to
  sync. Affects a fresh install running `sync` before any traffic is recorded.

## [OSS `burnlens` v1.23.1] — 2026-08-14

### Fixed
- **`burnlens sync --now` failed immediately with
  `AttributeError: 'CloudConfig' object has no attribute 'cloud'`.** The command
  handed the sync client only the cloud section of the config when the client
  wants the whole thing, so the manual push has never worked. Background sync
  from the running proxy was unaffected, as was `burnlens sync --status`.

## [OSS `burnlens` v1.23.0] — 2026-08-14

### Fixed
- **Prompt sizes in `burnlens runs` were roughly double for OpenAI, Azure,
  Google and the OpenAI-compatible providers.** Those APIs report the whole
  prompt as one number with the cached share as a *part* of it; Anthropic
  reports the uncached input and the cache reads as two *separate* numbers.
  BurnLens added them together in both cases, so a 12,000-token prompt with
  11,000 cached was shown as 23,000. Costs were never affected. Measured
  against a live request, not inferred.

  The run view now also reports the uncached share rather than the raw column,
  so the three figures add up: prompt = uncached + cached.

- **Anthropic requests that were only partly cached were under-billed.**
  BurnLens subtracted the cache reads from the input tokens before pricing
  them, which is the right rule for OpenAI and the wrong one for Anthropic. A
  request with 5,000 uncached input tokens and 3,000 cache reads was priced as
  2,000 input tokens. Coding-agent traffic hid this — when the whole prompt is
  cached the uncached input is a handful of tokens — but any application that
  caches part of its prompt was quoted low. Costs recorded from now on are
  slightly higher for that traffic, and correct; existing rows are unchanged.

## [OSS `burnlens` v1.22.0] — 2026-08-13

### Added
- **The session id now syncs to burnlens.app, so runs appear in the hosted
  dashboard.** `burnlens runs` has worked locally since v1.21.0, but the
  session id that groups a run stayed on your machine, so the hosted product
  had nothing to group by. It is now sent along with the tags you had already
  opted into.

  A session id is the coding-agent log filename — an opaque identifier. No
  code, no file paths, no prompt content and nothing about you is sent with
  it, and the tags that would name those (`repo`, `branch`, `dev`, `pr`,
  `commit_sha`) still stay on your machine as before. If you do not use cloud
  sync, nothing changes at all.

  `X-BurnLens-Tag-Session` is now accepted as well, so a proxied application
  can name its own runs.

  There is no backfill: runs appear in the hosted dashboard from the point you
  upgrade, not before.

- **`source` is synced too**, so the hosted dashboard can tell coding-agent
  runs apart from proxied application traffic.

## [Cloud `burnlens-cloud`] — 2026-08-14 (deployed only)

### Fixed
- Same prompt-token correction as OSS v1.23.0, in the hosted run view — the
  provider list is duplicated in `burnlens_cloud.models` because the backend
  cannot import the proxy's registry, and `tests/test_prompt_token_semantics.py`
  fails if the two drift.

## [Cloud `burnlens-cloud`] — 2026-08-13 (deployed only)

### Added
- **Run → Step view.** `/dashboard/runs` lists runs by cost or recency and
  drills into the steps inside one, mirroring `burnlens runs`. Token counts
  show the whole prompt with the cached share beside it, for the same reason
  as the CLI.
- `trace_id`, `parent_span_id` and `source` are now persisted on
  `request_records`. They had been arriving from the proxy and being dropped
  after OTEL span export.

## [OSS `burnlens` v1.21.0] — 2026-08-13

### Added
- **`burnlens runs` groups spend into runs and the steps inside them.** Until
  now every figure was per request, which is not how the work is actually
  shaped — a single coding-agent session can be hundreds of requests and tens
  of dollars, and nothing showed you that.

  ```
  burnlens runs                  # runs by cost, or --recent
  burnlens runs 199c4a0a         # the steps inside one run
  ```

  A run is your coding-agent session, taken from the session id already
  recorded by `burnlens scan`, so this works on data you have already
  collected — no new setup and nothing to instrument. For traffic proxied from
  an OpenTelemetry-instrumented application, the W3C trace id is used instead.
  `burnlens economics` reports which of the two your data carries. Requests
  with neither are left out rather than lumped together.

  `GET /api/runs` and `GET /api/runs/{run_id}` return the same data.

  Token counts show the whole prompt with the cached share beside it. Coding
  agents cache nearly the entire prompt, so counting only uncached input would
  show a handful of tokens against a dollar of spend.

  Steps are listed in time order, not nested. Scanned data records no calling
  span, so there is no hierarchy to show for it; where a calling span is
  present it is displayed per step.

  Databases created before recent versions still work — missing columns are
  skipped rather than causing an error.

## [OSS `burnlens` v1.20.0] — 2026-08-13

### Added
- **`burnlens economics` now reports attribution coverage.** BurnLens has been
  recording the trace and calling-span ids from the W3C `traceparent` header
  since v1.18, but nothing displayed them, so there was no way to tell whether
  your traffic carries them at all. The command now says how many requests in
  the window carry a trace, how many name the calling span, and how many
  distinct traces that forms:

  ```
  Attribution coverage — 42 of 1203 request(s) carry a W3C trace (3.5%),
  40 naming the calling span, across 12 distinct trace(s).
  ```

  This is what decides whether spend can be attributed to a run or step rather
  than only to individual requests. Any OpenTelemetry-instrumented client sends
  the header automatically; if none of your traffic does, the command says so
  and nothing else changes. `GET /api/economics` returns the same figures under
  `trace_coverage`.

  A database created before those columns existed is reported as needing a
  migration — start the proxy once — rather than shown as a zero, which would
  look identical to genuinely having no traces.

## [OSS `burnlens` v1.19.0] — 2026-08-12

### Fixed
- **Tool calls are now counted on streaming responses.** The `tool_calls`
  figure was read from a complete response body, which a streaming response
  never produces — each call arrives split across many small events. Every
  streaming request therefore recorded zero tool calls, however many it made.
  Since agents almost always stream, the number was wrong for exactly the
  traffic it exists to describe, and anything built on it would have looked
  credible while being wrong.

  Streaming requests now report a real count for OpenAI-compatible providers
  (including Azure, Groq, Together, Mistral, xAI and DeepSeek), Anthropic and
  Google. Parallel tool calls count once each, not once per fragment.

  Bedrock streams a binary frame format rather than SSE and still reports
  zero. Non-streaming requests were already correct and are unchanged.

  Historical rows are not backfilled — the counts were never recorded, so
  totals over a window spanning this upgrade will step up at the boundary.

## [OSS `burnlens` v1.18.0] — 2026-08-12

### Added
- **The proxy now keeps the caller's span id.** BurnLens already parsed the
  W3C `traceparent` header for its trace id and discarded the rest; the
  discarded half is the span that made the call — the run or step the LLM
  request belongs to. It is now stored as `parent_span_id` on every request,
  so anyone already running OpenTelemetry can reconstruct run/step structure
  by grouping on `trace_id` and nesting on `parent_span_id`. No endpoint to
  call, no dependency to add, and nothing to instrument: requests without a
  `traceparent` behave exactly as before.

  Only the W3C header carries a span, so the `x-trace-id` / `x-correlation-id`
  / tag fallbacks leave it empty. The spec's all-zero "no parent" sentinel and
  malformed values are stored as empty rather than as a fake parent. Existing
  databases gain the column automatically on next start.

  Nothing surfaces the field yet — this release starts collecting it. A
  trace-grouped view comes only once the data shows traces actually arrive.

### Changed
- Cloud sync now includes `parent_span_id` alongside `trace_id`. Like the
  other correlation ids it is an opaque identifier, never prompt content.

## [OSS `burnlens` v1.17.0] — 2026-08-11

The findings lifecycle reaches the dashboard. v1.16.0 shipped it CLI-only.

### Added
- **The dashboard's waste panel now works the findings, not just displays
  them.** It reads persisted findings rather than recomputing on every load,
  and gained status filter tabs, the subject each finding belongs to, the
  evidence behind it, how many times it has been detected, and per-status
  actions. Resolved findings show their savings verdict inline — including the
  honest ones, so a fix that is too recent to judge says
  `Verifying — N more day(s) of data needed` rather than showing a number it
  cannot justify.

- **Dashboard API routes for the lifecycle:**
  - `GET /api/findings[?status=]` — persisted findings with lifecycle state
  - `POST /api/findings/{fingerprint}/status` — move a finding through it
  - `GET /api/findings/verify` — savings verdicts

  `/api/waste` is unchanged: it recomputes live, has no lifecycle, and other
  callers still use it.

### Security
- **`POST /api/findings/{fingerprint}/status` requires an `X-Requested-With`
  header.** It is the dashboard API's first state-changing route. `server.host`
  defaults to `127.0.0.1`, but it can be set to `0.0.0.0` so agents on other
  machines can reach the proxy — which would expose this endpoint too. A custom
  header cannot be sent cross-origin without a preflight, and the proxy's CORS
  policy only allows the local dashboard origin. Requests without the header
  are rejected with 403 and leave the finding untouched.

## [OSS `burnlens` v1.16.0] — 2026-08-11

Waste detection stops being a snapshot you recompute and becomes a workflow:
find it, act on it, then check whether the money actually moved.

### Added
- **Waste findings are persisted and have a status lifecycle.** Detection
  previously recomputed everything on every call and wrote nothing down, so a
  finding had no identity between runs — no history, and no way to record that
  something had been fixed. Findings now live in a `waste_findings` table and
  move through `open → acknowledged → resolved`, plus `accepted_risk`.

  A resolved finding that is detected again **reopens**, because a fix that did
  not hold has to come back. `accepted_risk` never reopens — the user already
  decided.

  - `burnlens findings list [--status ...]`
  - `burnlens findings status <fingerprint> <status>`
  - `burnlens analyze --save`
  - findings also sync on the existing hourly detection tick

- **Findings are scoped to a subject** — the tagged `workflow_id` where there is
  one, otherwise the model. Previously each detector returned a single
  workspace-wide aggregate, which meant "mark fixed" would have muted an entire
  category including future offenders, and there would be nothing specific to
  measure a saving against. Both fields already exist on the request record, so
  this needs no new instrumentation.

- **`burnlens economics`** and **`GET /api/economics`** — total spend, detected
  waste, waste rate, error spend, cost per accepted outcome.

  These are a rate plus dimensions, never an additive breakdown. Detector
  estimates overlap heavily: on a window of $12.00 of spend, five detectors
  between them estimated $31.20 as avoidable, because one request can trip
  context bloat, history bloat, oversized tool schemas, low RAG efficiency and
  model overkill at once. Detected waste is therefore an estimate of avoidable
  spend, and the rate clamps at 100% rather than reporting a nonsense figure.

  Error spend counts 4xx/5xx requests. It is deliberately not called
  failed-run cost: the proxy sees individual HTTP requests and cannot tell a
  failed run from a failed request inside a run that went on to succeed.

- **`burnlens findings verify`** — after a finding is resolved, compares the
  subject's **cost per request** before and after the fix and projects the
  monthly saving.

  Per request, not per total: a workflow whose traffic fell to a tenth at an
  unchanged unit cost would otherwise score as a 90% win. Verification also
  refuses to guess — it reports `pending` when a fix is too recent to judge and
  `no_traffic` when nothing has run since, rather than presenting a collapse in
  spend as a 100% saving.

### Changed
- **Detectors no longer emit zero-waste placeholder findings.** Clean traffic
  returns nothing at all instead of eight rows saying "No requests to analyze",
  so an empty findings list means there is nothing to fix. `/api/waste`
  correspondingly returns only detectors that found something.
- **`/api/waste` rows carry a stable `id`** (the finding fingerprint). It was
  previously an `enumerate` index that changed between runs, so nothing could
  reliably address the same finding twice.

## [OSS `burnlens` v1.15.2] — 2026-08-10

### Added
- **`burnlens scan` now warns when a model has no pricing entry.** A missing
  pricing row does not error — it prices at $0.00, so the scan reports a total
  that is simply too low, and nothing on screen says so. That is exactly how
  `claude-opus-5` went unnoticed. Scans now collect every `(provider, model)`
  pair that costed at $0 for lack of a pricing entry and print them once at the
  end of the run, deduplicated across all four scanners.

  The collection point is `calculate_cost` itself, so all scanners (Claude Code,
  Cursor, Codex, Gemini CLI) are covered without per-scanner code.

## [OSS `burnlens` v1.15.1] — 2026-08-10

### Fixed
- **`claude-opus-5` was unpriced, so every request on it cost $0.** An unpriced
  model does not error — it prices at zero and drags down every metric that
  divides by cost. Added at Opus 4.8's rates ($5/M input, $25/M output, cache
  read 0.1x, cache write 1.25x), which is what Anthropic charges for it.

  On a real scan of this repo's Claude Code history, 951 records and 536,207
  tokens that priced $0.00 now price $137.24 — a quarter of that window's spend.
  Anyone who ran `burnlens scan` or proxied traffic on `claude-opus-5` was
  reading a total that was too low; re-scanning re-prices those records.

## [OSS `burnlens` v1.15.0] — 2026-08-10

### Added
- **Per-agent anomaly baselines (economics-graph Phase D).** Every agent is now
  measured against its own history rather than an org-wide average: the hourly
  detection run compares each agent seen in the last hour to a 7-day baseline of
  its own hourly spend and retry rate, built from the `agent_id` tag. Three
  signals, in precedence order — a suspected loop (more than
  `agent_loop_max_requests` calls sharing one `trace_id` inside
  `agent_loop_window_minutes`), a spend deviation past
  `agent_deviation_multiplier` with an `agent_min_spend_usd` floor, and a
  retry-rate deviation. Highest-ranked signal wins, so one runaway burst
  produces one alert naming the cause, not three describing it.

  When the `commit_sha` seen during the burst differs from the one before it,
  the alert says "started after deploy <sha>".

  All five thresholds are `[alerts]` config keys. Alerts ride the existing
  anomaly path — same `fired_alerts` dedup, same Slack and terminal output.

  Not baselined: tool-call counts. `tool_calls` is 0 on the SSE streaming path,
  so a tool-call baseline would silently under-count every streaming agent.

## [Cloud `burnlens-cloud`] — 2026-08-10 (deployed only)

Reconciliation: BurnLens's number, checked against the provider's own bill.

### Added
- **Daily provider reconciliation (economics-graph Phase E).** A workspace owner
  stores a read-only billing key per provider
  (`PUT /settings/reconciliation/{anthropic|openai}`); once a day
  `POST /cron/reconcile` asks that provider what it charged for the previous UTC
  day, sums what BurnLens computed from proxied traffic over the same window,
  and records the drift. `GET /api/v1/reconciliation` serves the dashboard badge
  — "reconciled ✓ −0.4% drift" / "12.1% drift" / "unreconciled".

  Drift over 2% emails the operator alert address. Drift is a diagnosis, not a
  failure: calls that bypassed the proxy, a pricing entry we haven't updated, an
  unpriced model, and rounding all produce it, and BurnLens counting *less* than
  the bill is the normal direction. The dashboard badge says so on hover.

  Two unit systems meet here and only one is dollars: Anthropic's cost report
  returns **minor units** (`"123.45"` USD is $1.23), OpenAI's returns dollars.
  `tests/test_reconciliation.py` pins both — mutating the `/100` fails it.
- Keys are Fernet-encrypted with `OTEL_ENCRYPTION_KEY` and never returned by any
  endpoint. A key the provider rejects is refused at save time rather than
  stored, so the badge can't sit on "unreconciled" with no explanation.
- `.github/workflows/cron-reconcile.yml` runs the job at 06:00 UTC — late enough
  that provider billing has settled the previous day.

## [OSS `burnlens` v1.14.0] — 2026-08-10

Cost per accepted outcome: spend divided by what it produced, not just
attributed. Agent and workflow attribution (Phase A), outcome events
(Phase B), and outcomes derived from merged pull requests (Phase C).

### Added
- **`agent_id` and `workflow_id` tags.** Spend now splits by agent and by
  workflow, not only by model. Set them like any other tag —
  `X-BurnLens-Tag-Agent-Id`, `X-BurnLens-Tag-Workflow-Id` — and read them back
  with `GET /api/costs/by-tag?tag=agent_id`. Both sync to BurnLens Cloud.
- **Tool-call counts per request**, across the OpenAI, Anthropic and Google
  response shapes, so a looping agent shows up as tool-call volume rather than
  only as a larger bill. Non-streaming responses only — SSE fragments each call
  across deltas, so a streaming request reports `0` and any per-agent tool-call
  metric under-counts streaming agents.
- **Outcome events.** `burnlens outcome record --workflow W --status accepted`
  records a business result; `burnlens outcome show` reports cost per accepted
  outcome per workflow, with rework and unattributed spend broken out. Also on
  `GET /api/costs/outcomes` and, on Cloud, `POST /v1/outcomes` +
  `GET /api/v1/outcomes/summary`.

  `outcome_id` is yours and is the idempotency key: re-posting one is ignored,
  so at-least-once delivery cannot inflate the count the cost is divided by.
  A repeat can never overwrite a recorded status either — a replayed delivery
  must not flip a newer result back to a stale one.
- **`burnlens outcome derive` — cost per merged PR with nothing to integrate.**
  Reads closed pull requests through the `gh` CLI and turns them into outcomes:
  merged is accepted, closed-unmerged is rejected, still-open is skipped rather
  than guessed at. Outcome ids are deterministic, so re-running only adds newly
  closed PRs and it is safe on a schedule. All four coding-agent scanners now
  tag sessions with a workflow, so scanned agent spend joins the same query.

  Attribution is per repository, not per PR: session logs record which repo a
  session ran in, not which branch. With several PRs in flight, total repo
  spend over merged PRs is the honest reading of what one merged PR costs.
- **`get_retry_stats()`** derives retries at query time — a call following a
  failure in the same trace, same model, inside a window — so the heuristic can
  be tuned without a migration or a backfill.

### Fixed
- **Multi-word tag headers only matched the underscore spelling.**
  `X-BurnLens-Tag-App-Id` was silently ignored; only `X-BurnLens-Tag-App_Id`
  worked. Since nginx drops headers containing underscores unless
  `underscores_in_headers` is on, every multi-word tag (`app_id`, `key_label`,
  `commit_sha`, `org_id`) was effectively undeliverable behind it. Hyphens now
  normalise to underscores, so both spellings work.

### Notes
- **How the cost is divided.** A request is charged to the first outcome of its
  workflow at-or-after it, within a window (24h by default, `--window` to
  change). Spend with no outcome after it is reported as *unattributed* rather
  than dropped or spread around.

  `Per accepted` divides **total** workflow spend by accepted outcomes, not only
  the spend that landed on successes — failed attempts cost real money, and
  charging them to the successes is what one working result costs. It is empty,
  never `$0`, when nothing has been accepted yet.
- A model missing from the pricing tables still contributes `$0`, which
  understates any cost-per-outcome figure. Check `burnlens pricing` if a number
  looks low.

## [OSS `burnlens` v1.13.0] — 2026-08-08

### Fixed
- **Unpriced models no longer defeat budget enforcement.** A model absent from
  the pricing data costs `$0`, so its spend never advanced a counter and any
  cap over it silently enforced nothing. Worse, `check_and_reserve` returned
  *allowed* outright on a `$0` estimate, so an unpriced model bypassed every
  `budget_policies` entry without consulting one. Such a request is now
  rejected with `403 unpriced_model_blocked` — but **only where a budget
  actually attaches to it**: a registered key with a daily cap, a tagged
  customer with a budget, a virtual key with a team budget, or a matching
  budget policy. Uncapped traffic on a new model is unaffected.

  403 rather than 429 is deliberate: nothing was exceeded and retrying will
  not help. The gateway is refusing because it cannot enforce.

### Added
- `block_unpriced_models` (default `true`). Set `false` to prefer availability
  over enforcement when a provider ships a model before BurnLens ships its
  price; that model's spend is then recorded as `$0` and does not count against
  any cap — the old behaviour, now opt-in and explicit rather than silent.
- `is_model_priced(provider, model)` and `resolve_pricing(provider, model)` in
  `burnlens.cost.calculator`. `calculate_cost` returns `0.0` both for a
  genuinely free request and for a model it cannot price; callers that must
  distinguish the two now have a way to. Both go through `resolve_pricing`, so
  a model can never be priced by one and unknown to the other.
- `docs/BUDGET_ENFORCEMENT.md` — budget enforcement semantics: concurrency,
  reserved vs finalized cost, streaming overrun, retries, reset timezone,
  fail-open behaviour, and cache interaction, each citing the implementing
  function.

## [OSS `burnlens` v1.12.0] — 2026-07-23

### Added
- **Tiered long-context pricing.** Pricing entries may now carry a `tiered`
  list — `[{"over": N, ...rate overrides}]` — that switches the WHOLE request
  to a higher per-token rate once the prompt exceeds N input tokens (a rate
  switch, not marginal brackets — matching how Google bills). Applied in
  `calculate_cost` after the pricing lookup; `over` is exclusive. Verified
  against ai.google.dev/pricing 2026-07-23: `gemini-2.5-pro` >200k input now
  bills $2.50/$15 (was flat $1.25/$10) and `gemini-3.1-pro-preview` >200k bills
  $4/$18 (was flat $2/$12). Long-context Gemini Pro requests were previously
  under-costed.
- Not applied to Anthropic/Bedrock: per the official pricing page, current
  Claude models (Opus 4.6+, Sonnet 4.6, Sonnet 5, Fable 5) include the full 1M
  context window at standard pricing — the old Sonnet 4/4.5 1M-context premium
  was retired 2026-04-30, so there is no Claude long-context tier to model.

## [OSS `burnlens` v1.11.0] — 2026-07-21

### Added
- **xAI (Grok) and DeepSeek providers.** Both speak the OpenAI wire format,
  so they're config-only `OpenAICompatibleProvider` routes: `/proxy/xai` →
  `api.x.ai` and `/proxy/deepseek` → `api.deepseek.com` (override with
  `XAI_BASE_URL` / `DEEPSEEK_BASE_URL`). Pricing verified against the
  official pages 2026-07-20: `grok-4.5` $2/$6; `deepseek-v4-flash`
  $0.14/$0.28, `deepseek-v4-pro` $0.435/$0.87, plus `deepseek-chat` /
  `deepseek-reasoner` aliases.
- **Anthropic price fills.** `claude-opus-4` / `claude-opus-4-1` ($15/$75)
  and `claude-sonnet-4` / `claude-3-7-sonnet` ($3/$15) were missing from
  `anthropic.json`, so direct-Anthropic traffic on those older models had
  been costing $0. Longest-prefix matching resolves the dated API ids
  without shadowing the newer `-4-5`/`-4-8` keys.

## [OSS `burnlens` v1.10.1] — 2026-07-19

### Fixed
- **Cloud sync actually forwards OTEL correlation IDs now.** v1.9.2 added
  `trace_id`/`event_id`/`request_id` to the sync payload but not to the
  privacy allowlist, so the sanitize step stripped them before the wire. A
  new test asserts every payload field survives the allowlist.

### Added
- **Cache savings sync to BurnLens Cloud.** `cache_hit` and `cache_saved_usd`
  are now part of the sync payload, powering the new "Cache saved" stat on
  the SaaS dashboard (cloud + frontend deployed separately).

## [OSS `burnlens` v1.10.0] — 2026-07-19

### Added
- **Virtual keys — the proxy is now a key-issuing gateway.** `burnlens vkey
  issue/list/revoke` mints `bl-sk-` tokens bound to a team, a provider, and an
  operator env var holding the real upstream key. The proxy resolves the token
  (SHA-256 stored, raw shown once), enforces an optional per-key model
  allowlist and per-team monthly budget, and swaps in the real key before
  forwarding. Enforcement is fail-closed (401/403/429/503) and a key issued
  for one provider is rejected with `403 provider_mismatch` on any other
  provider's path, so an upstream secret can never be sent to the wrong
  provider.

## [OSS `burnlens` v1.9.3] — 2026-07-19

### Added
- **Automatic upstream retry on transient provider failures.** The proxy now
  retries `429`/`503` responses and connection-level errors with exponential
  backoff on both the streaming and non-streaming paths (`retry:` config,
  enabled by default, `max_retries=2`). Defaults are billing-safe — only
  statuses where the provider rejected the request without processing it are
  retried, so a retry can never double-bill. `502`/`504` are opt-in. Read
  timeouts are never retried. Cross-provider failover is not included.

## [OSS `burnlens` v1.9.2] — 2026-07-19

### Fixed
- **Cloud sync now forwards correlation IDs for OTEL export.** The proxy's
  cloud-sync payload now includes `trace_id`, `event_id`, and `request_id`
  (IDs only — never prompt content) so the cloud OTEL exporter can build spans
  that join the client's distributed trace instead of getting random IDs.
  Pairs with the `burnlens-cloud` exporter fix (deployed).

## [OSS `burnlens` v1.9.1] — 2026-07-19

### Changed
- **Semantic cache no longer caches sampled requests.** Requests with an
  explicit `temperature > 0` are neither served from nor written to the
  response cache, so sampled (non-deterministic) outputs stay varied. Requests
  that omit `temperature` (relying on the provider default) are unaffected.

### Added
- **Cache-savings visibility.** `/api/summary` now returns `cache_saved_usd`
  and `cache_hits`, and the local dashboard shows a "Cache Saved" KPI card, so
  the value the response cache already tracked is now surfaced.

## [OSS `burnlens` v1.9.0] — 2026-07-18

### Added
- **AWS Bedrock provider (Claude).** Proxy Anthropic Claude models on Amazon
  Bedrock through BurnLens. Auth is a Bedrock API key forwarded as
  `Authorization: Bearer` (SigV4 is unsupported by design — the proxy replaces
  the `host` header when forwarding, which invalidates any forwarded signature).
  The per-region endpoint is resolved from `BURNLENS_BEDROCK_REGION` at request
  time. Model is read from the `/model/{modelId}/…` path; the geo prefix
  (`us.`/`eu.`/`apac.`/`global.`) and version suffix are preserved for routing.
- **Bedrock pricing (`bedrock.json`).** Global cross-region inference rates for
  10 modern Claude models (Sonnet 5, Fable 5, Opus 4.8/4.7/4.6/4.5, Sonnet
  4.6/4.5/4, Haiku 4.5), which equal Anthropic first-party pricing — including
  cache tiers and Sonnet 5's 2026-09-01 scheduled price change. All geo
  inference profiles bill at the global rate: `calculate_cost` strips the geo
  prefix before lookup, so a new/unknown geo prefix still prices correctly
  instead of silently costing $0. Per-geo/regional (+~10%) rates are not
  modeled. Bedrock is now the 8th supported provider.

## [OSS `burnlens` v1.8.3] — 2026-07-17

### Fixed
- **The proxy bypassed most of the `Provider` interface.** An audit prompted by
  the v1.8.2 Azure bug found that six of the plugin's hooks were implemented and
  unit-tested but never actually called by `handle_request` — the interceptor
  inlined equivalent logic or re-resolved the provider from the registry by name.
  For the bundled providers the inlined behaviour matched, so there was no live
  mispricing (unlike v1.8.2), but any future provider overriding these hooks
  would have been silently ignored. Now wired to the provider instance in hand:
  - `resolve_upstream_url()` — was `f"{provider.upstream_base}{path}"`.
  - `is_streaming()` — new hook; streaming detection had Google's
    `:streamGenerateContent` hardcoded in a module helper.
  - `should_buffer_chunk()` — the streaming usage gate matched a hardcoded
    `USAGE_EVENT_INDICATORS` tuple; `split_sse_events()` now consults the
    provider, with that tuple as the no-provider fallback.
  - `headers_to_strip()` — unioned onto the `x-burnlens-*` prefix rule (the
    prefix rule stays authoritative, so git-context tags never leak upstream).
  - `extract_usage()` and `extract_usage_from_stream()` — used the provider
    instance instead of re-looking-it-up by name.

  The duplicate module-level `should_buffer_chunk()` in `streaming.py` (never
  called by the proxy) is deleted.

### Tests
- `test_provider_hooks_wired.py` drives `handle_request` with a recording
  provider and asserts each hook is actually reached, plus a meta-test that fails
  if a new `Provider` hook is added without coverage here. Verified to fail when
  a hook is un-wired. This is the class of bug that caused v1.6.1, v1.8.2, and
  this release; the guard exists so it stops recurring.

## [OSS `burnlens` v1.8.2] — 2026-07-17

### Fixed
- **Azure deployments priced at $0 through the proxy.** The interceptor never
  called `Provider.extract_model()` — it used a private helper whose path
  extraction was hardcoded to Google, so `providers/azure.py`'s deployment-name
  mapping was dead code on the proxy path. Azure's dotless `gpt-35-turbo`
  spelling and any deployment mapped via `BURNLENS_AZURE_DEPLOYMENTS` (e.g.
  `prod-gpt4o=gpt-4o`) reached the pricing lookup unmapped and cost **$0.00**
  per request instead of $0.50 and $2.50/MTok respectively. The provider-level
  unit tests passed throughout because they called the provider object directly
  and never routed through the interceptor.

  These two behaviours were previously documented as known ceilings of the Azure
  provider. They were not ceilings — the code to handle them shipped in v1.6.1
  and was simply never wired up.

  The interceptor now calls `provider.extract_model(...)`, so each provider owns
  its own extraction (body, path, or alias map) as the plugin interface always
  intended. `_extract_model` and `_extract_model_from_path` are deleted.
  Regression tests drive `handle_request` end-to-end and assert exact costs.

  Same class of bug as the v1.6.1 `pricing_key` fix: an abstraction existed, the
  interceptor bypassed it, and it worked by accident for the providers where the
  model sits in the request body.

## [OSS `burnlens` v1.8.1] — 2026-07-17

### Added
- **Date-scheduled pricing.** A model entry can carry a `scheduled` list of dated
  rate changes (`{"effective": "YYYY-MM-DD", ...}`); the resolver applies the
  active tier against the current date automatically — no code edit or release
  needed when the date arrives. Used for **Claude Sonnet 5**, which now switches
  from its introductory $2/$10 to the $3/$15 sticker rate on 2026-09-01 on its
  own (previously a manual follow-up that would silently under-report ~33% if
  forgotten). Scans of old logs price at the current tier (the wheel carries one
  live rate anyway).

## [OSS `burnlens` v1.8.0] — 2026-07-17

### Added
- **`burnlens pricing` command.** Shows the bundled model pricing table
  ($/1M tokens) for all providers, or exports it: `--csv` writes CSV to stdout,
  `--output/-o FILE` writes to a file. Backed by a new `cost.pricing.all_pricing()`
  helper so the table and CSV share one source.

## [OSS `burnlens` v1.7.5] — 2026-07-17

### Added
- **Current GA realtime-audio models.** `gpt-realtime-2.1` (text $4/$24, audio
  $32/$64, cached $0.40) and `gpt-realtime-2.1-mini` (text $0.60/$2.40, audio
  $10/$20, cached $0.30), verified against OpenAI's live pricing page. These
  replaced the `*-audio-preview` / `gpt-4o-realtime-preview` entries on OpenAI's
  side and previously matched no pricing entry — i.e. all `gpt-realtime-2.1*`
  traffic was silently tracked at $0. Legacy preview entries are retained for
  historical scan data.

## [OSS `burnlens` v1.7.4] — 2026-07-17

### Fixed
- **Codex scan double-billed reasoning tokens** (same class of bug as v1.7.3, in
  the `codex` scanner). Verified against real `~/.codex` sessions that Codex
  mirrors the OpenAI Responses API — `output_tokens` is *inclusive* of
  `reasoning_output_tokens` (`total_tokens == input + output`). The scanner set
  `output_tokens` to the inclusive value and also billed reasoning separately, so
  every scanned Codex turn with reasoning over-charged. The reader now stores
  `output` disjoint from `reasoning` (`output = output − reasoning`). Verified on
  live sessions (e.g. raw output 237 / reasoning 81 → stored 156 + 81).

## [OSS `burnlens` v1.7.3] — 2026-07-17

### Fixed
- **Reasoning tokens double-billed on OpenAI.** OpenAI reports `completion_tokens`
  *inclusive* of `reasoning_tokens`, but the proxy extractors set
  `output_tokens = completion_tokens` while also billing `reasoning_tokens`
  separately — so reasoning was charged twice (e.g. an o1 call with 200 of 1000
  output tokens as reasoning cost `$0.072` instead of `$0.060`). Extractors now
  keep `output_tokens` disjoint from `reasoning_tokens` (matching the Gemini/Codex
  scanners and the storage schema, where the two sum to the total). Fixed on the
  non-streaming, streaming, and stream-chunk paths.

## [OSS `burnlens` v1.7.2] — 2026-07-17

### Added
- **Non-token billing.** The cost calculator now prices multiple line items per
  request beyond plain text tokens:
  - **Audio-modality tokens** are repriced at a dedicated `audio_input_per_million`
    / `audio_output_per_million` rate instead of the text rate (they're a subset of
    the reported input/output tokens). Wired end-to-end through the OpenAI
    extractor and both streaming paths; added `gpt-4o-audio-preview`,
    `gpt-4o-mini-audio-preview`, and `gpt-4o-realtime-preview` with audio rates.
    Fixes ~16× under-reporting of audio traffic on those models.
  - **Flat per-unit fees** via an optional `unit_prices` map on any model entry
    (USD-per-unit) paired with `TokenUsage.units` — e.g. per web-search / tool
    call, per image, per audio-second. Prices any non-token line item a caller
    populates. Models with no audio/unit rates are unchanged (audio falls back to
    the text rate; no `units` → no extra cost).

## [OSS `burnlens` v1.7.1] — 2026-07-17

### Added
- **Current text/chat model pricing.** Added OpenAI GPT-5.4 through GPT-5.6,
  Gemini 3.5 Flash, Claude Mythos 5, Mistral Medium 3.5 and Small 4, and the
  current Together chat catalog.

### Fixed
- **Provider aliases and rates.** Refreshed Mistral `-latest` aliases, Groq
  GPT-OSS 20B, and Together Llama 3.3 70B pricing against provider catalogs.

## [OSS `burnlens` v1.7.0] — 2026-07-17

### Added
- **Current model pricing.** Added GPT-5.2, Gemini 3.1 Flash-Lite, Groq Qwen,
  Mistral Large 3, and Together GPT-OSS pricing; Sonnet 5 uses its $2/$10
  introductory rate through August 31, 2026.

### Changed
- **Recommendations and downgrade routing** now use the bundled pricing tables
  and current model targets, preventing recommendations to retired Claude 3 Haiku.

## [OSS `burnlens` v1.6.2] — 2026-07-14

### Added
- **Azure OpenAI deployment mapping.** Resolve custom/arbitrary Azure deployment names
  to OpenAI models for accurate pricing using the `BURNLENS_AZURE_DEPLOYMENTS` environment
  variable (e.g. `prod-gpt4o=gpt-4o,cheap=gpt-4o-mini`).
- **Azure OpenAI aliases.** Automatically map Azure's dotless `gpt-35-turbo` deployment name family
  to canonical `gpt-3.5-turbo` pricing keys in `openai.json`.

## [OSS `burnlens` v1.6.1] — 2026-07-14

### Fixed
- **Azure requests no longer cost $0.** Pricing lookups (`get_model_pricing`,
  `get_pricing_version`) received `provider.name`, but pricing files are keyed
  by `pricing_key`. For the six providers where those match it worked by
  accident; Azure (name `azure`, pricing_key `openai`) had no `azure.json`, so
  every Azure request/record cost $0. The pricing layer now resolves
  name→pricing_key via the provider registry, with pass-through for scan
  providers (`cursor`, etc.) that aren't registered.

## [OSS `burnlens` v1.6.0] — 2026-07-14

### Added
- **Azure OpenAI proxy provider (beta).** Azure serves the OpenAI models
  over the same chat-completions wire format, so it reuses the OpenAI
  parser via `/proxy/azure`. Point the `AzureOpenAI` client's
  `azure_endpoint` at the proxy path (`burnlens start` exports
  `AZURE_OPENAI_ENDPOINT`) and set `BURNLENS_AZURE_ENDPOINT` to your real
  resource URL (`https://<resource>.openai.azure.com`). The request's
  deployment name is used as the model; pricing reuses `openai.json`, so
  a deployment named after its model (e.g. `gpt-4o`) resolves cost —
  arbitrarily-named deployments price at $0 until a name→model map lands.

## [OSS `burnlens` v1.5.0] — 2026-07-14

### Added
- **Groq, Together, and Mistral proxy providers (beta).** All three speak
  the OpenAI wire format, so they reuse the OpenAI parser with their own
  proxy paths (`/proxy/groq`, `/proxy/together`, `/proxy/mistral`),
  upstream URLs, and pricing tables. `burnlens start` now also exports
  `GROQ_BASE_URL`; Together and Mistral clients point their `base_url`
  at the proxy path.

## [OSS `burnlens` v1.4.3] — 2026-07-14

### Fixed
- **Anthropic pricing corrected.** All Claude Opus 4.x entries carried
  Claude-3-Opus-era rates ($15/$75 per MTok) instead of the actual
  $5/$25 — Opus 4.x requests were over-costed 3×. Claude Haiku 4.5
  corrected from $0.80/$4 to $1/$5.
- **Missing models no longer cost $0.** Added `claude-fable-5`,
  `claude-opus-4-8`, `claude-sonnet-5`, the gpt-5 family
  (`gpt-5` / `gpt-5-mini` / `gpt-5-nano`), the gpt-4.1 family, and
  `o3-pro`. Previously these resolved to no pricing entry and every
  request/scan record for them showed $0.
- `o3` updated to its post-cut $2/$8 rates; `gemini-2.5-flash` corrected
  to $0.30/$2.50; added `gemini-2.5-flash-lite`.

### Changed
- README and landing-page roadmap wording no longer references
  long-obsolete "v0.2 / v0.3" milestones.

## [OSS `burnlens` v1.4.2] — 2026-07-13

### Fixed
- **Cloud sync never reached the backend.** The default (and documented)
  ingest endpoint was `https://api.burnlens.app/api/v1/ingest` — a path
  that has never existed on the backend, so every sync batch 404'd
  (silently, by fail-open design). The default is now the real route
  (`/v1/ingest`), and `push_batch` rewrites the stale `/api/v1/ingest`
  suffix from existing user configs.
- Sync requests now send `X-Requested-With`, so they pass backends
  running the CSRF middleware without the machine-endpoint exemption.

### Cloud (`burnlens-cloud`, deployed only)
- **CSRF middleware no longer blocks machine-to-machine endpoints.**
  The hardening middleware 403'd any POST without `X-Requested-With`,
  which broke `/v1/ingest` (OSS sync), `/cron/evaluate-alerts` (the
  hourly GitHub Actions cron failed with 403 for days), and would have
  broken `/billing/webhook` (Paddle). Those paths carry their own
  credential and are never cookie-authenticated, so CSRF does not apply.
- **`api_keys.paused_at` schema drift repaired.** Production tables
  created before `paused_at` joined the CREATE statement lacked the
  column, making every API-key lookup raise `UndefinedColumnError` —
  ingest returned 500 for all keys. Startup migration now adds the
  column idempotently.

## [OSS `burnlens` v1.4.1] — 2026-07-13

### Changed
- **Accurate provider claims on PyPI.** The published package description
  said Azure OpenAI, AWS Bedrock, and Groq appear "in one unified view";
  those providers are on the roadmap, not shipped. The description now
  matches the provider support table: OpenAI, Anthropic, and Google are
  the supported providers today.
- **Added `CONTRIBUTING.md`** (the README already linked to it) covering
  dev setup, the fail-open / streaming-passthrough ground rules, and the
  provider plugin guide.
- Repo hygiene: internal planning and handoff documents are no longer
  tracked in the public repository.

## [OSS `burnlens` v1.4.0] — 2026-05-27

### Added
- **Saved Views on the discovery dashboard.** Name and persist a set of
  filters (provider, status, risk, team, date, search, sort) to `localStorage`,
  then reload or delete them from the toolbar.

### Fixed
- **The discovery dashboard (`/ui/discovery`) shipped five panels that never
  rendered.** The HTML/CSS for the Provider Breakdown chart, Shadow AI Alerts,
  the Discovery Timeline, the team filter, and the Unassigned KPI were present,
  but `discovery.js` drove none of them — they sat on "Loading…" or blank
  indefinitely. All are now wired to existing endpoints: the provider doughnut
  from `/api/v1/assets/summary`, shadow cards from
  `/api/v1/assets?status=shadow` (with per-card approve / assign-team), the
  timeline from `/api/v1/discovery/events`, and the team list + Unassigned count
  derived client-side from the asset list. A guarded 30s auto-refresh honors the
  header's refresh indicator without clobbering in-progress edits. (No backend
  change, so the frontend↔API contract snapshot is unaffected.)

## [OSS `burnlens` v1.3.1] — 2026-05-27

### Fixed
- **`/ui/discovery` returned 404 on FastAPI 0.115.x.** The route's
  `-> FileResponse` return annotation (a string under
  `from __future__ import annotations`) was resolved against module globals,
  but `FileResponse` was only imported locally inside `get_app()`. On the pinned
  FastAPI 0.115.0, `get_type_hints()` raised `NameError`, which the surrounding
  `try/except` swallowed — silently dropping the discovery UI route and its
  static mount. Now imported at module level. (Surfaced by running the test
  suite under prod-pinned deps; masked locally by a newer FastAPI.)
- **Asset API responses dropped the `tags` field.** `_asset_to_dict` omitted
  `tags`, so the persisted per-asset tags never reached the list / get / patch /
  discovery endpoints. Now serialized.
- **Spend-spike alert fired at exactly 200% of the 30-day average.** The guard
  used `< 2.0`, but the intent (and docstring) is to fire only *above* 200%.
  Changed to `<= 2.0` so exactly 200% no longer alerts.

## [Frontend `burnlens.app`] — 2026-05-26

### Fixed
- **Every authenticated page crashed for any workspace that had usage data**
  (found by `/investigate` on 2026-05-26). The dashboard read `total_cost` /
  `api_calls` / `cost` / `latency_ms`, but the cloud API serializes
  `total_cost_usd` / `request_count` / `cost_usd` / `duration_ms` (and `tags`
  as an object). The wrong field names resolved to `undefined`, and the
  unguarded `.toFixed()` / `.toLocaleString()` calls threw a `TypeError`.
  Because the throw happened in `RightPanel` (shared dashboard chrome), it took
  down `/dashboard`, `/api-keys`, and every Shell-wrapped page — but only for
  workspaces with data, so empty QA accounts never surfaced it. Aligned all six
  consumers (RightPanel, Overview, By model, By feature, By customer, By team)
  to the real API field names and added `?? 0` guards so malformed data
  degrades to `$0` instead of a white screen.

## [Cloud `burnlens-cloud` v1.2.1] — 2026-05-25

### Fixed
- **Cloud ingest accepted nothing the OSS proxy sent — the product's core data
  path was 100% broken** (found by live QA on 2026-05-25). Three stacked bugs
  meant every sync batch from the `burnlens` package was silently dropped:
  - **Wire-format mismatch (was HTTP 422).** The OSS proxy sends the API key in
    the `X-API-Key` header and posts `{"records":[...]}`, but `/v1/ingest`
    required `api_key` inside the JSON body. `ingest()` now reads the key from
    the `X-API-Key` header or the body (body wins), and 401s only when neither is
    present. `IngestRequest.api_key` is now optional. This recovers every
    already-installed proxy (1.0–1.3) in place, no client upgrade required.
  - **JSONB encoding 500 on every non-empty batch.** asyncpg has no built-in
    encoder for Python `dict` ↔ `JSONB`, so the bulk insert of `tags` raised and
    failed the whole batch. The connection pool now registers a `jsonb` codec
    (`json.dumps`/`json.loads`) via `init=`.
  - **Attribution tags silently dropped.** The proxy flattens tags to
    `tag_feature` / `tag_team` / `tag_customer` at the top level; Pydantic
    discarded them, erasing per-feature/team/customer cost attribution. A
    `model_validator` re-nests the flat keys into `tags` (an explicit `tags`
    object still wins).

### Tests
- `tests/test_ingest_wire_format.py`: 8 regression tests pinning the exact OSS
  proxy wire shape (header auth, body auth, 401-not-422, flat-tag lifting,
  explicit-tags-win, JSONB codec wiring).
- Updated `tests/test_cloud_sync.py`, `tests/test_cloud_sync_e2e.py` to assert
  the current wire format (API key in `X-API-Key` header; `status_code` is
  intentional operational metadata, `request_path` remains stripped for privacy).
- Fixed a stale `tests/test_keys.py` CLI test that hung the suite on an empty
  hidden-prompt under the test runner.

## [PyPI `burnlens` 1.3.0] — 2026-05-25

### Fixed
- **Google model downgrade now rewrites the URL path** (ROUTE-08). When
  `decide_route()` selects a downgrade model for a Google Generative Language API
  request, the outbound request URL path is rewritten to reflect the downgrade
  model name (in addition to the existing body-field rewrite from v1.2). Closes
  the known v1.2 limitation where Google requests still hit the original-model
  endpoint despite body rewriting. OpenAI and Anthropic are unaffected — their
  model identifier already lives in the body, not the URL.

### Added
- **`Provider.rewrite_path_for_routing()` hook** — polymorphic, opt-in path
  rewriter on the Provider plugin base class. Default is a no-op; the Google
  provider implements it. Future providers can add path rewriting without core
  changes.
- **`DOWNGRADE_MAP` suffix normalization** — Google model keys like
  `models/gemini-1.5-flash` are normalized to suffix form so URL-path matching
  is single-source-of-truth.

## [OSS `burnlens` — bugfix] — 2026-05-04

### Fixed
- **Asset API routing** — `/api/v1/assets` router was double-prefixed (absolute paths
  in router + prefix on include), causing all asset endpoints to return 404. Fixed by
  using relative paths; added missing `GET /{id}`, `PATCH /{id}`, and
  `POST /{id}/approve` endpoints, renamed `"assets"` response key to `"items"` to
  match the API contract, and wired `date_since` filter through to the query layer.
- **date_since validation** — `GET /api/v1/assets?date_since=` now rejects non-ISO
  date strings with a 422 rather than silently returning wrong results.

---

## [PyPI `burnlens` 1.1.0] — 2026-05-03

### Added
- **Offline session scanners** — four new `burnlens scan <provider>` commands import
  coding-agent session costs from disk without replaying any traffic. Re-runs are
  idempotent (partial unique index on `source` + `request_id`). Scanned rows appear
  alongside live-proxy traffic in the dashboard, `burnlens top`, and exports.
  - `burnlens scan claude` — reads Claude Code JSONL session files from
    `~/.claude/projects/` and attributes cost by project, session, and model.
  - `burnlens scan cursor` — reads the Cursor IDE SQLite bubble database from
    `~/.cursor/` and maps composer/chat turns to cost records.
  - `burnlens scan codex` — reads OpenAI Codex JSONL session files from
    `~/.codex/sessions/` (703 sessions, 88k events in testing).
  - `burnlens scan gemini` — reads Gemini CLI JSON/JSONL chat files from
    `~/.gemini/tmp/<project>/chats/` (64 sessions, 5806 turns in testing).
- **Pricing: gpt-5-codex** — `$1.25 / $10.00` per million in/out tokens.
- **Pricing: gemini-3-flash-preview** — `$0.50 / $3.00` per million in/out tokens.
- **Pricing: gemini-3.1-pro-preview** — `$2.00 / $12.00` per million in/out tokens.

---

## [Cloud `burnlens-cloud` v1.2.0] — 2026-05-02

### Added
- **Phase 11 — Auth Essentials**: Full email-verified auth flow for the cloud dashboard.
  - `auth_tokens` table for password-reset and email-verification tokens; `email_verified_at`
    column on `users` tracks first confirmation.
  - 4 new auth endpoints: `POST /auth/reset-password`, `POST /auth/reset-password/confirm`,
    `POST /auth/verify-email`, `POST /auth/resend-verification`.
  - `email_verified` claim in every JWT; login and signup responses surface the flag.
  - Rate-limit rules for reset-password (3/900s) and resend-verification (3/900s).
  - 6 transactional email templates (welcome, verify-email, reset-password, password-changed,
    invitation, payment-receipt) wired to SendGrid via a typed `TEMPLATE_REGISTRY`.
  - `send_invitation_email` migrated from inline HTML to the file-based template system.
- **Phase 11 — Frontend Auth Pages**: Zero-JavaScript-dependency auth UX shipped into the Next.js app.
  - `/verify-email` page — calls the backend on mount, sets `emailVerified` in localStorage on success.
  - `/reset-password` page — token-based password reset form with full validation.
  - Forgot-password flow integrated into `/setup` tab switcher.
  - `emailVerified` surfaced in `useAuth` + `AuthSession` for downstream gating.
  - `BillingStatusBanner` shows a persistent email-verification nudge with a "Resend" button
    for users who have not confirmed their address.
- **Phase 12 — Cloud Alert Engine**: Hourly spend-alert evaluation for non-free workspaces.
  - `alert_rules` and `alert_events` tables with default 80% monthly-cap rule seeded on workspace creation.
  - `alert_engine.py`: evaluates all active rules, dispatches via email and/or Slack, records outcome
    in `alert_events`, and deduplicates within a 24-hour window per rule.
  - SSRF-safe Slack dispatch: validates `hooks.slack.com` hostname via `urlparse` (not `startswith`).
  - `POST /cron/evaluate-alerts`: bearer-auth cron endpoint with HMAC-wrapped constant-time secret
    comparison; fail-open — always returns `{"evaluated": N, "fired": M}`.
  - `PUT /settings/slack-webhook`: owner-only endpoint to configure per-workspace Slack alerts;
    sets `channel = 'both'` when a URL is provided, reverts to `'email'` when cleared.
  - GitHub Actions workflow triggers the cron endpoint hourly from Railway.

### Fixed
- **Frontend**: Removed dead `public/signup.html` and `public/dashboard.html` static auth pages.
- **Frontend**: Mobile hamburger nav with `lp-` CSS-prefixed classes to avoid dashboard collision.
- **Frontend**: Register form disables submit until name/email filled and password ≥ 8 chars.
- **Frontend**: Branded `/not-found` 404 page; `/login` and `/pricing` redirect correctly.
- **Frontend**: OG/Twitter descriptions tightened for solo-use positioning.
- **Cloud**: `/billing/summary` 500 for fresh workspaces — fixed pool-import binding.
- **Cloud**: CORS headers now emitted on unhandled 500s; preflight `max_age` capped at 60s.
- **Security**: HTML-escape all user-supplied variables in `send_welcome_email` and
  `send_payment_receipt_email` (XSS fix — matched existing pattern in `send_invitation_email`).
- **Security**: Slack webhook URL no longer stored in `alert_events.recipient` audit column.
- **bcrypt**: Bumped from 4.1.3 → 5.0.0 to match `uv.lock`.

### Tests
- `tests/test_phase11_auth.py`: 729-line suite covering all 7 new auth endpoints and JWT claims.
- `tests/test_phase12_alerts.py`: 13 tests covering alert engine, cron auth, and Slack SSRF guard.
- `tests/test_cors_preflight.py` and `tests/test_cors_on_500.py`: regression tests for CORS hardening.
- `tests/test_plans_pool_binding.py`: regression test for the billing-summary pool-import fix.
- `frontend/tests/e2e/phase11_auth.spec.ts`: Playwright E2E for signup, login, forgot-password,
  and email-verification flows.

## [Unreleased — PyPI `burnlens`] — milestone 0.2.0

### Added
- **CODE-2**: Per-API-key daily hard cap — stop a leaked or runaway
  API key before it burns the month's budget:
    - New `api_keys` table stores SHA-256-hashed keys with a human label
      and optional `daily_cap_usd`. Keys are never stored in plaintext.
    - `burnlens key register|list|remove` CLI manages labels and caps;
      the proxy interceptor resolves the inbound `Authorization:` key to
      its label and stamps `tag_key_label` on every logged request.
    - TZ-aware daily reset (UTC midnight by default, configurable via
      `api_key_budgets.reset_tz` in `burnlens.yaml`). Per-key spend is
      cached in-process and invalidated on each new log write.
    - 50 % / 80 % / 100 % alerts fire to terminal (and Slack if
      configured) with one alert per key per threshold per day.
    - At 100 %, the proxy returns HTTP 429 with a JSON
      `{"error": "burnlens_daily_cap_exceeded", ...}` body until the
      next reset — fail-closed for spend, fail-open for everything else.
    - New `GET /api/keys-today` endpoint + dashboard panel "API keys
      today" shows today's spend and cap status per key.
    - New `burnlens keys` CLI prints today's per-key roll-up.
    - End-to-end demo: `bash docs/demo_killswitch.sh` registers a key,
      sets a 1-cent cap, makes a real request, and demonstrates the
      kill-switch tripping.

### Tests
- 91 new tests across 8 files cover key store, CLI, label
  interceptor, label migration, daily-cap enforcement, alerts,
  `/api/keys-today` endpoint, and the demo script. Combined with
  CODE-1's 30 tests, the v0.2.0 milestone adds 121 passing tests.

## [PyPI `burnlens` 1.0.1] — 2026-04-28

### Fixed
- **CRITICAL**: 1.0.0 published a broken wheel that omitted
  `burnlens/cost/`, `burnlens/proxy/`, `burnlens/cli.py`, and
  `burnlens/__main__.py` — every install was non-functional and any
  `burnlens` console-script invocation failed with `ModuleNotFoundError`.
  1.0.1 ships the complete OSS package: proxy server, request
  interceptor, SSE streaming handler, cost calculator, pricing data,
  CLI, dashboard static assets, telemetry, and reports.
- **I-1**: Google and Anthropic streaming responses no longer log
  `0 tokens / $0.00`. Root causes addressed: `_is_streaming()` now
  detects Google's `:streamGenerateContent` URL scheme; `accept-encoding`
  is stripped from forwarded requests so SSE bytes aren't gzipped;
  Google `_extract_google_stream` parses both SSE `data: {…}` lines and
  raw NDJSON; SSE buffer is reassembled on `\n\n` boundaries before
  extraction so TCP-fragmented usage events aren't dropped.

### Added
- **I-2**: `burnlens export` CSV command gains `--repo / --dev / --pr`
  filters and matching `repo / dev / pr / branch` columns. Cost cells
  now format as `f"{cost:.8f}"` instead of scientific notation
  (e.g. `0.00005120` instead of `5.12e-05`).
- **CODE-1**: Git-aware auto-tagging — every proxied request can now
  be attributed to a PR / repo / dev / branch with zero manual headers:
    - `burnlens run -- <cmd>` wraps any command, reading
      `read_git_context(cwd)` and exposing `BURNLENS_TAG_REPO/DEV/PR/BRANCH`
      env vars + `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` to the child.
    - The proxy's `_extract_tags` falls back to those env vars
      per-request when the corresponding `X-BurnLens-Tag-*` header is
      absent.
    - Schema migration adds `tag_repo / tag_dev / tag_pr / tag_branch`
      columns + `idx_requests_tag_{repo,dev,pr}` indices to the
      `requests` table (idempotent via `PRAGMA table_info`).
    - New CLI groupers: `burnlens prs --days N --repo X`,
      `burnlens devs`, `burnlens repos` — top-20 cost tables.
    - New JSON endpoint `GET /api/cost-by-pr?days=7&repo=X`.
    - New dashboard panel "Top PRs by cost" with click-to-filter
      Recent Requests via the indexed `tag_pr` column.

### Tests
- 197 OSS tests pass on this release: streaming (39), cost (44),
  storage (44), export (9), git_context (16), cli_wrapper (6),
  proxy_env_fallback (5), and integration suites.

## [burnlens-cloud 1.0.1] — 2026-04-15

### Fixed
- Alert deduplication now persists across restarts (was in-memory only)
- Discovery events archival job added — 90-day retention, runs nightly at 2 AM UTC
- Asset table now sorts server-side — sort is global across all pages, not per-page
- Monthly spend KPI now aggregates all assets, not just the current page
- Google billing API integration — Vertex AI and Gemini assets now detected via billing API

### Tech Debt Resolved
- FIX-01: DB-backed fired_alerts table replaces in-memory sets
- FIX-02: discovery_events_archive table with nightly migration job
- FIX-03: sort_by and sort_dir params on GET /api/v1/assets
- FIX-04: get_total_spend_all_assets() query bypasses pagination for KPI
- FIX-05: GoogleBillingParser implements Cloud Billing v1 REST API

## [1.0.0] — 2026-04-15

- Initial release
