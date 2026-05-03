# BurnLens — Roadmap Claude Code Prompts

---

## IMMEDIATE (0.1.x)

---

### Prompt I-1: Fix Google & Anthropic Token Extraction

```
You are working on BurnLens, an open-source LLM cost proxy.

CONTEXT:
- File: burnlens/cost/calculator.py
- Functions: extract_usage_google(), extract_usage_anthropic()
- Problem: Google and Anthropic streaming responses log 0 tokens / $0.00
- Root cause: streaming response JSON shape differs from non-streaming

TASK:
1. Read burnlens/cost/calculator.py in full
2. Read burnlens/proxy/streaming.py — find extract_usage_from_stream() and should_buffer_chunk()
3. Fix extract_usage_google() to handle:
   - Non-streaming: response["usageMetadata"]["promptTokenCount"] / "candidatesTokenCount"
   - Streaming: accumulated chunks may have usageMetadata at top level
4. Fix extract_usage_anthropic() to handle:
   - Non-streaming: response["usage"]["input_tokens"] / "output_tokens"
   - Streaming: usage lives in the message_delta event: {"type":"message_delta","usage":{"output_tokens":N}}
5. Update extract_usage_from_stream() so it correctly identifies and buffers:
   - OpenAI: chunks where "usage" key exists at top level and choices == []
   - Anthropic: chunks where event type is "message_start" (input_tokens) or "message_delta" (output_tokens)
   - Google: chunks where "usageMetadata" exists
6. Add a test for each fix in tests/test_cost.py under TestUsageExtraction

VERIFICATION:
After fixing, run:
  python -c "
  import anthropic
  client = anthropic.Anthropic()
  r = client.messages.create(model='claude-haiku-4-5-20251001', max_tokens=50, messages=[{'role':'user','content':'Hi'}])
  print(r.usage)
  "
Tokens in and out must be > 0 in the BurnLens dashboard after running this.

Do not change any other logic. Only fix the extraction functions and should_buffer_chunk.
```

---

### Prompt I-2: burnlens export CSV Command

```
You are working on BurnLens, an open-source LLM cost proxy.

CONTEXT:
- CLI entry point: burnlens/cli.py
- Storage: burnlens/storage/database.py
- Existing commands: start, dashboard

TASK:
Add a new CLI command: burnlens export

BEHAVIOUR:
  burnlens export                          # exports last 7 days to burnlens_export.csv
  burnlens export --days 30               # last 30 days
  burnlens export --output ~/costs.csv    # custom output path
  burnlens export --team backend          # filter by tag_team
  burnlens export --feature chat          # filter by tag_feature

CSV COLUMNS (in this order):
  timestamp, provider, model, feature, team, customer,
  tokens_in, tokens_out, reasoning_tokens, cache_read_tokens,
  cache_write_tokens, cost_usd, latency_ms, status_code

IMPLEMENTATION STEPS:
1. Add get_requests_for_export(db_path, days, team, feature) to storage/database.py
2. Add export_to_csv(rows, output_path) to a new file burnlens/export.py
3. Register the export command in cli.py using click
4. Print progress: "Exporting 143 requests to costs.csv... done."
5. Handle empty result gracefully: "No requests found for the given filters."

TESTS:
Add tests/test_export.py:
- test_export_creates_file
- test_export_correct_columns
- test_export_filter_by_team
- test_export_filter_by_days
- test_export_empty_result_no_crash

Do not modify any existing commands or storage functions.
```

---

### Prompt I-3: README Quickstart + Animated GIF Script

```
You are working on BurnLens, an open-source LLM cost proxy.

CONTEXT:
- README.md exists at repo root
- burnlens.app domain is registered
- PyPI package is live at pypi.org/project/burnlens

TASK:
Rewrite README.md to be optimised for first-time visitors from Hacker News and Reddit.

STRUCTURE (in this exact order):

1. HERO — one line: "BurnLens — see exactly what your LLM API calls cost, per feature, team, and customer."

2. INSTALL — 3 lines max:
   pip install burnlens
   burnlens start
   # Dashboard at http://127.0.0.1:8420/ui

3. THE PROBLEM — 3 bullet points with real numbers:
   - "OpenAI bills by model, not by feature. You find out at month end."
   - "Reasoning tokens on o1/o3 can cost 10x more than expected."
   - "One bad deploy can cost $47K before anyone notices."

4. HOW IT WORKS — code block showing the proxy env var pattern + tagging headers

5. WHAT YOU GET — screenshot placeholder [Dashboard Screenshot] + 4 bullet points:
   - Cost timeline (daily spend trend)
   - Cost by model, feature, team, customer
   - Waste alerts: context bloat, duplicate requests, model overkill
   - Recent requests with per-call cost and latency

6. CONFIGURATION — show burnlens.yaml example with budget_limit_usd

7. PROVIDERS — table: OpenAI / Anthropic / Google with supported models

8. CONTRIBUTING — 3 lines pointing to CONTRIBUTING.md

9. LICENSE — MIT

Also create docs/record_demo.sh — a shell script that:
- Starts burnlens in background
- Fires 5 real API calls with different tags via curl
- Prints "Open http://127.0.0.1:8420/ui and take a screenshot"
- Kills burnlens

This script will be used to record the demo GIF for the README.

Do not change any source code. README and docs/record_demo.sh only.
```

---

## SHORT TERM (0.2)

---

### Prompt S-1: Per-Team Budget Limits with Alerts

```
You are working on BurnLens, an open-source LLM cost proxy.

CONTEXT:
- Config: burnlens/config.py — loads burnlens.yaml
- Alerts: burnlens/alerts/engine.py — AlertEngine.check_and_dispatch()
- Storage: burnlens/storage/database.py
- Current budget: single global budget_limit_usd in config

TASK:
Add per-team budget limits that alert when a team exceeds their monthly spend cap.

STEP 1 — Config schema extension:
Add to burnlens.yaml support:
  budgets:
    global: 500.00
    teams:
      backend: 200.00
      research: 100.00
      infra: 50.00

Update burnlens/config.py to parse this structure into:
  config.budgets.global: float
  config.budgets.teams: dict[str, float]

STEP 2 — Storage query:
Add get_spend_by_team_this_month(db_path) -> dict[str, float] to database.py
Returns: {"backend": 47.23, "research": 12.10, ...}

STEP 3 — Alert engine:
Add check_team_budgets(config, db_path) -> list[Alert] to alerts/engine.py
Logic:
  - For each team in config.budgets.teams:
    - Get their spend this month
    - If spend > limit * 0.8: fire WARNING alert
    - If spend > limit: fire CRITICAL alert
  - Alert format: {"team": "backend", "spent": 167.23, "limit": 200.00, "severity": "WARNING"}

STEP 4 — Dashboard:
Add a "Team Budgets" card to the dashboard UI (burnlens/ui/dashboard.html or equivalent)
Show: team name | spent | limit | % used | status badge (OK / WARNING / CRITICAL)

STEP 5 — CLI:
  burnlens budgets          # print team budget status table to terminal
  burnlens budgets --json   # machine-readable output

TESTS:
Add tests/test_budgets.py:
- test_team_budget_warning_at_80_percent
- test_team_budget_critical_at_100_percent
- test_team_budget_ok_below_threshold
- test_global_budget_fallback_when_no_team_config
- test_get_spend_by_team_this_month_correct_math

Do not change interceptor.py or the proxy forwarding logic.
```

---

### Prompt S-2: Weekly Cost Report Email

```
You are working on BurnLens, an open-source LLM cost proxy.

CONTEXT:
- CLI: burnlens/cli.py
- Storage: burnlens/storage/database.py
- Config: burnlens/config.py

TASK:
Add burnlens report command that generates and optionally emails a weekly cost summary.

STEP 1 — Report generation:
Create burnlens/reports/weekly.py with generate_weekly_report(db_path, days=7) -> WeeklyReport

WeeklyReport dataclass:
  period_start: datetime
  period_end: datetime
  total_cost: float
  total_requests: int
  cost_by_model: dict[str, float]
  cost_by_team: dict[str, float]
  cost_by_feature: dict[str, float]
  top_waste_findings: list[str]
  vs_prior_week: float  # percent change

STEP 2 — Text rendering:
generate_text_report(report: WeeklyReport) -> str
Plain text format, readable in email or terminal. Example:

  BurnLens Weekly Report — 1 Apr to 7 Apr 2025
  ─────────────────────────────────────────────
  Total spend:    $23.47  (+12% vs prior week)
  Total requests: 1,847

  By model:
    gpt-4o-mini    $14.20  (60%)
    claude-haiku   $6.10   (26%)
    gemini-flash   $3.17   (14%)

  By team:
    backend        $18.40
    research       $5.07

  Waste alerts:
    - 23 requests used gpt-4o for tasks averaging 8 output tokens
    - 0 duplicate request patterns detected

STEP 3 — CLI command:
  burnlens report                     # print to terminal
  burnlens report --email you@co.com  # send via SMTP
  burnlens report --days 30           # monthly summary

STEP 4 — Email sending:
Use Python stdlib smtplib. Config in burnlens.yaml:
  email:
    smtp_host: smtp.gmail.com
    smtp_port: 587
    smtp_user: you@gmail.com
    smtp_password: your-app-password
    from: BurnLens <you@gmail.com>

If email config missing and --email flag used, print clear error with setup instructions.

STEP 5 — Scheduled reports (optional, only if time allows):
  burnlens report --schedule weekly   # writes a cron entry to run every Monday 9am

TESTS:
Add tests/test_reports.py:
- test_weekly_report_math_correct
- test_vs_prior_week_percent_change
- test_text_report_contains_all_sections
- test_email_config_missing_prints_helpful_error
- test_empty_week_no_crash

Do not add any external email dependencies beyond smtplib.
```

---

## DISK READERS (0.2.x)

---

### Prompt SCAN-1: Claude Code Session Disk Reader

```
You are working on BurnLens, an open-source LLM cost proxy.

CONTEXT:
- BurnLens currently captures data via proxy only (burnlens/proxy/interceptor.py)
- New goal: also read Claude Code session files directly from disk — no proxy required
- Claude Code stores sessions as JSONL at ~/.claude/projects/<sanitized-path>/<session-id>.jsonl
- Each line is a JSON object; assistant entries contain model, usage tokens, and timestamp
- Reusable pieces:
    - burnlens/cost/calculator.py — calculate_cost(provider, model, usage)
    - burnlens/storage/database.py — insert_request(record)
    - burnlens/storage/models.py — RequestRecord dataclass
    - burnlens/cost/pricing_data/anthropic.json — Claude pricing already loaded

This is the foundation for a hybrid data model: proxy captures production app traffic,
scan captures coding-agent sessions. Both land in the same `requests` table.

STEP 0 — Verify Claude Code JSONL schema:
Before writing any code, inspect ONE actual session file on this machine:
  ls ~/.claude/projects/ | head -3
  cat "$(find ~/.claude/projects -name '*.jsonl' | head -1)" | head -20 | jq .
Note the actual structure of:
  - assistant message entries (look for "type": "assistant" or role: "assistant")
  - usage object location (top-level vs nested under message)
  - cache token field names (cache_read_input_tokens vs cacheRead)
  - message id field (used for dedup)
  - timestamp field name
Use the real schema, not assumptions. If schema differs from what's described below,
follow the real schema and document the differences in a code comment.

STEP 1 — Schema migration:
Add `source` TEXT column to the requests table with default 'proxy'.
- Existing rows get source='proxy'
- Scan-imported rows get source='scan_claude' (later: 'scan_cursor', 'scan_codex')

In burnlens/storage/database.py:
- Add migrate_add_source_column(db_path) using the same IF NOT EXISTS pattern as migrate_add_synced_at
- Call migration on burnlens start (alongside existing migrations)

In burnlens/storage/models.py:
- Add `source: str = 'proxy'` to RequestRecord dataclass

STEP 2 — Claude Code reader module:
Create burnlens/scan/__init__.py and burnlens/scan/claude_code.py:

  CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

  @dataclass
  class ClaudeSession:
      session_id: str
      project_path: str       # decoded back from sanitized form
      project_basename: str   # e.g., 'burnlens'
      file_path: Path
      modified_at: datetime

  def discover_sessions(since: datetime | None = None,
                        project_filter: str | None = None) -> list[ClaudeSession]:
      """Walk ~/.claude/projects/, return matching .jsonl files."""

  def decode_project_path(sanitized: str) -> str:
      """Claude Code replaces / with - in project paths. Reverse it.
      Example: '-Users-bhushan-Documents-Projects-burnlens'
            -> '/Users/bhushan/Documents/Projects/burnlens'
      Verify exact encoding rule against real directory names from STEP 0."""

  def parse_session(session: ClaudeSession) -> Iterator[RequestRecord]:
      """Read JSONL line-by-line. Yield one RequestRecord per assistant message
      that has both a model and a usage block.
      Skip: user messages, tool_use entries, tool_result entries, malformed lines.
      Set: provider='anthropic', source='scan_claude', tag_repo=session.project_basename,
           tag_dev=resolve_dev_identity(session.project_path), request_id=message.id"""

  def resolve_dev_identity(project_path: str) -> str:
      """Try in order:
        1. `git -C <project_path> config user.email`
        2. os.environ.get('USER')
        3. 'unknown'
      Cache result per project_path within a single scan run."""

STEP 3 — Cost calculation:
For each parsed assistant message:
- Build TokenUsage(input_tokens=..., output_tokens=...,
                   cache_read_tokens=..., cache_write_tokens=...)
- cost_usd = calculate_cost('anthropic', model, usage)
- Reuse the existing function — DO NOT duplicate pricing logic

STEP 4 — Deduplication:
Scan must be idempotent — running it twice imports each message once.

In burnlens/storage/database.py add:
  CREATE UNIQUE INDEX IF NOT EXISTS idx_scan_dedup
    ON requests(source, request_id)
    WHERE source LIKE 'scan_%' AND request_id IS NOT NULL;

In the scan ingestion path:
- Use INSERT OR IGNORE based on the unique index
- Track skipped count for reporting
- DO NOT use SELECT-then-INSERT — race-prone and slow over thousands of rows

STEP 5 — CLI command:
Register in burnlens/cli.py:

  burnlens scan                          # scan all providers (currently just claude)
  burnlens scan --provider claude        # explicit
  burnlens scan --since 2026-04-01       # sessions modified after date
  burnlens scan --project burnlens       # filter by project basename substring
  burnlens scan --dry-run                # parse but don't insert, print counts

Output using Rich table:
  Scanning Claude Code sessions...
  Found 47 session files across 8 projects.
  Parsed 1,847 assistant messages.
  Inserted 1,602 new records (245 already imported).
  Total cost imported: $23.47

  Top projects by cost:
    burnlens          $12.40   (847 messages)
    cloud-infra       $6.10    (412 messages)
    sheetora          $4.97    (343 messages)

STEP 6 — Dashboard integration:
No new endpoints needed. Scanned data flows into existing aggregations because
it lands in the same `requests` table. Verify:
- /api/cost-by-model shows Claude models from scanned sessions
- /api/cost-timeline includes scanned timestamps
- Recent Requests table shows scanned rows (consider adding a small badge for source='scan_claude')

Optional: in dashboard/static/app.js, render source as a small badge next to the model name
in the Recent Requests table — 'proxy' (cyan) vs 'scan' (amber). One-line change.

TESTS:
Add tests/test_scan_claude.py with fixtures in tests/fixtures/claude_sessions/:
- test_decode_project_path_reverses_sanitization
- test_decode_project_path_handles_dashes_in_real_dirnames
- test_parse_session_extracts_assistant_messages_only
- test_parse_session_skips_user_and_tool_messages
- test_parse_session_extracts_cache_tokens
- test_parse_session_handles_malformed_jsonl_line (skip, no crash)
- test_parse_session_handles_empty_file
- test_parse_session_skips_assistant_messages_without_usage
- test_dedup_unique_index_prevents_duplicates
- test_dry_run_does_not_insert
- test_scan_filters_by_since_date
- test_scan_filters_by_project_substring
- test_resolve_dev_identity_falls_back_to_user_env
- test_empty_claude_dir_no_crash

Create 2-3 sample JSONL fixtures with realistic Claude Code session data (anonymized).

VERIFICATION:
After implementation, on this developer machine:
  burnlens scan --dry-run
Should report non-zero parsed messages if you've used Claude Code recently.

Then:
  burnlens scan
  burnlens start
Open dashboard at http://127.0.0.1:8420/ui — scanned data should appear in:
  - Cost Timeline
  - Cost by Model (Claude Sonnet/Haiku/Opus)
  - Recent Requests with tag_repo populated

Run scan a second time:
  burnlens scan
Should report "0 new records (N already imported)" — proves idempotence.

CRITICAL CONSTRAINTS:
- Do NOT modify proxy/interceptor.py, proxy/server.py, or proxy/streaming.py
- Do NOT modify cost/calculator.py — reuse calculate_cost() as-is
- Do NOT change RequestRecord field names — only add the `source` field
- Read-only access to ~/.claude/projects/ — never write or delete files there
- If a JSONL line is malformed, log a warning at DEBUG level and continue
- No new heavy dependencies — use stdlib json, pathlib, datetime only
- Performance target: 1000+ sessions in under 10 seconds on a developer laptop
- Scan is a one-shot CLI command — no background tasks, no daemon

Test gate: All existing tests must stay green. New tests must pass.
Total test count should be 200+ after this work.
```

---

## MEDIUM TERM (0.3)

---

### Prompt M-1: Per-Customer Cost Attribution + Budget Caps

```
You are working on BurnLens, an open-source LLM cost proxy.

CONTEXT:
- Tagging: X-BurnLens-Tag-Customer header already captured in interceptor.py
- Storage: tag_customer column exists in requests table
- This is BurnLens's most defensible enterprise feature

TASK:
Build per-customer cost tracking with automatic spend caps.

STEP 1 — Storage queries:
Add to database.py:
  get_spend_by_customer_this_month(db_path) -> dict[str, float]
  get_customer_request_count(db_path, customer, days=30) -> int
  get_top_customers_by_cost(db_path, limit=20) -> list[dict]

STEP 2 — Config:
Add to burnlens.yaml:
  customer_budgets:
    acme-corp: 50.00
    beta-user: 10.00
    default: 5.00   # applied to any unrecognised customer

STEP 3 — Budget enforcement in interceptor.py:
Before forwarding any request with X-BurnLens-Tag-Customer header:
  1. Look up customer's spend this month from DB
  2. Compare against their budget in config
  3. If spend >= budget: return HTTP 429 immediately, do not forward
     Response body: {"error": "budget_exceeded", "customer": "acme-corp", "spent": 50.12, "limit": 50.00}
  4. Cache the customer spend lookup for 60 seconds to avoid DB hit on every request

STEP 4 — Dashboard:
Add "Customers" tab to dashboard:
  Table: customer | requests | tokens in | tokens out | total cost | budget | % used | status
  Sortable by cost descending
  Red row highlight when budget exceeded

STEP 5 — CLI:
  burnlens customers                    # table of all customers + spend
  burnlens customers --customer acme    # detail for one customer
  burnlens customers --over-budget      # only customers who exceeded limit

STEP 6 — Alert:
When a customer hits 80% of budget, fire an alert:
  {"customer": "acme-corp", "spent": 40.10, "limit": 50.00, "pct": 80.2, "severity": "WARNING"}

TESTS:
Add tests/test_customers.py:
- test_customer_spend_tracked_correctly
- test_budget_cap_returns_429_when_exceeded
- test_budget_cap_allows_request_when_under_limit
- test_default_budget_applied_to_unknown_customer
- test_spend_cache_reduces_db_calls
- test_customer_alert_fires_at_80_percent

IMPORTANT: The 429 enforcement must happen BEFORE the upstream call.
Do not forward the request if budget is exceeded.
```

---

### Prompt M-2: Model Recommendation Engine

```
You are working on BurnLens, an open-source LLM cost proxy.

CONTEXT:
- BurnLens logs every request with model, tokens_in, tokens_out, cost_usd, tag_feature
- Pricing data: burnlens/cost/calculator.py — PRICING_DATA dict
- This feature turns waste detection into actionable recommendations

TASK:
Build a model recommendation engine that analyses usage patterns and suggests cheaper alternatives.

STEP 1 — Analysis queries:
Add to burnlens/analysis/recommender.py:

  analyse_model_fit(db_path, days=30) -> list[ModelRecommendation]

  ModelRecommendation dataclass:
    current_model: str
    suggested_model: str
    feature_tag: str
    request_count: int
    avg_output_tokens: float
    current_cost: float
    projected_cost: float
    projected_saving: float
    saving_pct: float
    confidence: str  # "high" | "medium" | "low"
    reason: str

STEP 2 — Recommendation rules:
Rule 1 — Model overkill:
  IF model in ["gpt-4o", "claude-3-5-sonnet", "gemini-1.5-pro"]
  AND avg_output_tokens < 200
  AND request_count > 20
  THEN suggest cheaper equivalent:
    gpt-4o → gpt-4o-mini
    claude-3-5-sonnet → claude-3-haiku
    gemini-1.5-pro → gemini-1.5-flash
  confidence = "high" if avg_output_tokens < 50 else "medium"

Rule 2 — Reasoning model for simple tasks:
  IF model in ["o1", "o3", "o1-mini"]
  AND avg_output_tokens < 100
  AND reasoning_tokens > output_tokens * 5
  THEN suggest gpt-4o-mini
  reason = "Reasoning tokens are {N}x output tokens — this task may not need deep reasoning"

Rule 3 — Cache opportunity:
  IF same feature_tag appears > 50 times in 24h
  AND avg_input_tokens > 2000
  THEN suggest enabling prompt caching
  reason = "High-volume feature with large prompts — prompt caching could save ~{N}%"

STEP 3 — Cost projection:
  projected_cost = (request_count * avg_input_tokens / 1_000_000 * suggested_input_price)
                 + (request_count * avg_output_tokens / 1_000_000 * suggested_output_price)
  projected_saving = current_cost - projected_cost
  saving_pct = (projected_saving / current_cost) * 100

STEP 4 — Dashboard:
Add "Recommendations" panel below Waste Alerts:
  Card per recommendation:
    "Switch [feature] from gpt-4o → gpt-4o-mini"
    "Projected saving: $12.40/month (73%)"
    "Based on 847 requests averaging 34 output tokens"
    Confidence badge: HIGH / MEDIUM / LOW

STEP 5 — CLI:
  burnlens recommend              # print all recommendations
  burnlens recommend --apply      # print sed/env commands to make the switch

TESTS:
Add tests/test_recommender.py:
- test_model_overkill_high_confidence_below_50_tokens
- test_model_overkill_medium_confidence_50_to_200_tokens
- test_no_recommendation_for_high_output_models
- test_reasoning_model_flagged_for_simple_tasks
- test_cost_projection_math_correct
- test_saving_pct_correct
- test_empty_db_returns_no_recommendations

Do not modify interceptor.py or any existing analysis detectors.
```

---

## GROWTH (0.4)

---

### Prompt G-1: OpenTelemetry Export

```
You are working on BurnLens, an open-source LLM cost proxy.

CONTEXT:
- Every LLM request is logged as a RequestRecord in burnlens/storage/models.py
- Enterprise users want to pipe cost data into Datadog, Grafana, Honeycomb, etc.
- OpenTelemetry is the standard for this

TASK:
Add OpenTelemetry span export so every proxied request emits an OTEL span.

STEP 1 — Dependencies:
Add to pyproject.toml optional dependencies:
  [project.optional-dependencies]
  otel = [
    "opentelemetry-api>=1.20",
    "opentelemetry-sdk>=1.20",
    "opentelemetry-exporter-otlp-proto-grpc>=1.20",
  ]

STEP 2 — Span creation:
Create burnlens/telemetry/otel.py:

  init_tracer(config) -> None
    Reads from config:
      telemetry:
        otel_endpoint: http://localhost:4317
        service_name: burnlens
        enabled: true

  emit_span(record: RequestRecord) -> None
    Creates a span with these attributes:
      llm.provider: "openai"
      llm.model: "gpt-4o-mini"
      llm.tokens.input: 100
      llm.tokens.output: 50
      llm.tokens.reasoning: 0
      llm.cost.usd: 0.000075
      llm.latency_ms: 320
      burnlens.feature: "chat"
      burnlens.team: "backend"
      burnlens.customer: "acme"
      http.status_code: 200

STEP 3 — Integration:
In burnlens/_log_record() (interceptor.py), after inserting to SQLite:
  if telemetry is enabled:
    emit_span(record)

STEP 4 — Config:
burnlens.yaml:
  telemetry:
    enabled: false
    otel_endpoint: http://localhost:4317
    service_name: burnlens

STEP 5 — CLI:
  burnlens start --otel         # enable otel for this session only
  burnlens check-otel           # verify connection to otel_endpoint

TESTS:
Add tests/test_otel.py:
- test_span_emitted_after_request (mock the OTEL exporter)
- test_span_has_correct_attributes
- test_otel_disabled_by_default_no_spans
- test_otel_failure_does_not_crash_proxy

Do not make otel a required dependency. It must be opt-in via pip install burnlens[otel].
```

---

## MONETISATION (0.5)

---

### Prompt P-1: Cloud-Hosted BurnLens SaaS Foundation

```
You are working on BurnLens, an open-source LLM cost proxy.

CONTEXT:
- BurnLens currently runs 100% locally with SQLite
- Goal: add a cloud sync mode that pushes anonymised cost data to a hosted backend
- This is the foundation for the paid SaaS tier at burnlens.app
- Open source stays fully functional offline. Cloud is additive only.

TASK:
Build the cloud sync infrastructure — client side only. Server side is separate.

STEP 1 — Sync config:
Add to burnlens.yaml:
  cloud:
    enabled: false
    api_key: bl_live_xxxxxxxxxxxx
    endpoint: https://api.burnlens.app/v1/ingest
    sync_interval_seconds: 60
    anonymise_prompts: true   # never send prompt content, only hashes

STEP 2 — Sync client:
Create burnlens/cloud/sync.py:

  class CloudSync:
    def __init__(self, config): ...

    async def push_batch(self, records: list[RequestRecord]) -> bool:
      POST to config.cloud.endpoint:
      {
        "api_key": "bl_live_xxx",
        "records": [
          {
            "ts": "2025-04-08T18:35:46Z",
            "provider": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "input_tokens": 14,
            "output_tokens": 10,
            "cost_usd": 0.000051,
            "latency_ms": 1100,
            "tag_feature": "chat",
            "tag_team": "backend",
            "tag_customer": "acme",
            "system_prompt_hash": "abc123..."
          }
        ]
      }
      Return True on 200, False on error. Never raise — sync failure must not affect proxy.

    async def start_sync_loop(self, db_path: str) -> None:
      Every sync_interval_seconds:
        - Query records not yet synced (add synced_at column to requests table)
        - Push batch of up to 500 records
        - On success: mark records as synced

STEP 3 — Schema migration:
Add synced_at TIMESTAMP NULL column to requests table.
Write migrate_add_synced_at(db_path) that runs ALTER TABLE safely (IF NOT EXISTS pattern).
Call migration on burnlens start.

STEP 4 — Integration:
In burnlens/server.py on startup:
  if config.cloud.enabled:
    asyncio.create_task(cloud_sync.start_sync_loop(db_path))

STEP 5 — CLI:
  burnlens login              # prompts for api_key, writes to burnlens.yaml
  burnlens sync --now         # manual immediate sync, prints count pushed
  burnlens sync --status      # shows last sync time + unsynced count

STEP 6 — Privacy guarantee:
  - Never sync raw prompt content
  - Only sync system_prompt_hash (SHA-256, one-way)
  - Add prominent note in docs: "Prompt content never leaves your machine"

TESTS:
Add tests/test_cloud_sync.py:
- test_push_batch_sends_correct_payload (mock HTTP)
- test_push_batch_returns_false_on_network_error_no_crash
- test_sync_loop_marks_records_synced
- test_anonymise_removes_prompt_content
- test_migration_adds_synced_at_column
- test_cloud_disabled_by_default_no_requests_sent

CRITICAL: Cloud sync failure must NEVER affect proxy performance.
All sync operations run in background tasks with try/except at every level.
```

---

## USAGE

Drop each prompt into Claude Code when you're ready for that feature.
Each prompt is self-contained — Claude Code has all the context it needs.
Run the tests after each prompt before moving to the next.

Recommended order:
1. I-1 (fix token extraction) — do this today
2. I-2 (export CSV) — before Reddit launch
3. I-3 (README rewrite) — before Reddit launch
4. S-1 (team budgets) — week 2
5. S-2 (weekly report) — week 3
6. M-1 (customer caps) — month 2
7. M-2 (recommendations) — month 2
8. G-1 (OpenTelemetry) — month 3
9. P-1 (cloud sync) — month 4
