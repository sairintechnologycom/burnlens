// Shared response shapes the frontend reads from the cloud API, paired with a
// runtime field manifest. The manifest type `Record<keyof I, true>` forces it to
// list EXACTLY the interface keys (TS errors otherwise), so Object.keys(manifest)
// is provably the set of fields the frontend depends on. The contract test
// (tests/contract/api-contract.test.ts) checks each manifest against the committed
// OpenAPI snapshot. Backend schema name for each is noted alongside.

// --- /api/v1/usage/summary  ->  StatsSummary ---
export interface UsageSummary {
  total_cost_usd: number;
  total_requests: number;
  avg_cost_per_request_usd: number;
  models_used: number;
  cache_saved_usd: number;
  cache_hits: number;
}
export const UsageSummaryFields: Record<keyof UsageSummary, true> = {
  total_cost_usd: true,
  total_requests: true,
  avg_cost_per_request_usd: true,
  models_used: true,
  cache_saved_usd: true,
  cache_hits: true,
};

// --- /api/v1/team-budgets  ->  TeamBudgetRow ---
export interface TeamBudgetRow {
  team: string;
  spent: number;
  limit: number;
  pct_used: number;
  status: string;
}
export const TeamBudgetRowFields: Record<keyof TeamBudgetRow, true> = {
  team: true,
  spent: true,
  limit: true,
  pct_used: true,
  status: true,
};

// --- /api/v1/recommendations  ->  RecommendationItem ---
export interface RecommendationRow {
  current_model: string;
  suggested_model: string;
  feature_tag: string;
  request_count: number;
  avg_output_tokens: number;
  current_cost: number;
  projected_cost: number;
  projected_saving: number;
  saving_pct: number;
  confidence: string;
  reason: string;
}
export const RecommendationRowFields: Record<keyof RecommendationRow, true> = {
  current_model: true,
  suggested_model: true,
  feature_tag: true,
  request_count: true,
  avg_output_tokens: true,
  current_cost: true,
  projected_cost: true,
  projected_saving: true,
  saving_pct: true,
  confidence: true,
  reason: true,
};

// --- /api/v1/usage/by-model  ->  CostByModel ---
export interface CostByModelRow {
  model: string;
  provider: string;
  request_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
}
export const CostByModelFields: Record<keyof CostByModelRow, true> = {
  model: true,
  provider: true,
  request_count: true,
  total_input_tokens: true,
  total_output_tokens: true,
  total_cost_usd: true,
};

// --- /api/v1/usage/by-feature | by-customer | by-team  ->  CostByTag ---
// All three tag-breakdown endpoints return the same row shape.
export interface CostByTagRow {
  tag: string;
  request_count: number;
  total_cost_usd: number;
}
export const CostByTagFields: Record<keyof CostByTagRow, true> = {
  tag: true,
  request_count: true,
  total_cost_usd: true,
};

// Used by the customers and teams pages, which render budget columns alongside
// the CostByTag data. These budget fields are FRONTEND-ONLY: the by-customer /
// by-team endpoints (CostByTag) do NOT currently return them, so they are always
// undefined ("—" in the UI).
// budget_cap is used by the customers page; budget and budget_status by the teams page.
// They are deliberately NOT in the contract manifest /
// contract test — only the real CostByTag fields are checked. If the backend
// starts returning these, promote them into CostByTagRow + CostByTagFields and
// regenerate the snapshot.
export interface CostByTagBudgetRow extends CostByTagRow {
  budget_cap?: number;
  budget?: number;
  budget_status?: "ok" | "warning" | "critical";
}

// --- /api/v1/usage/timeseries  ->  CostTimeline ---
export interface CostTimelinePoint {
  date: string;
  request_count: number;
  total_cost_usd: number;
}
export const CostTimelineFields: Record<keyof CostTimelinePoint, true> = {
  date: true,
  request_count: true,
  total_cost_usd: true,
};

// --- /api/v1/requests  ->  RequestRecordResponse ---
export interface RequestRow {
  timestamp: string;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  duration_ms?: number;
  // tags shape is freeform; the contract test only checks key presence, not nested fields.
  tags?: { feature?: string; team?: string; [k: string]: unknown } | null;
}
export const RequestRowFields: Record<keyof RequestRow, true> = {
  timestamp: true,
  provider: true,
  model: true,
  input_tokens: true,
  output_tokens: true,
  cost_usd: true,
  duration_ms: true,
  tags: true,
};

// --- /billing/summary  ->  BillingSummary (+ nested schemas) ---
// The money-facing twin of the PR #18 crash. The sidebar usage meter, api-keys
// card, and settings page run arithmetic / .toLocaleString() on the NESTED
// numeric fields (request_count, monthly_request_cap, active_count, limit,
// price_cents), so all three nested schemas are contracted, not just the top
// level. Backend schemas: burnlens_cloud/models.py. The contract test adds a row
// per schema; openApiType only presence-checks the top-level usage/api_keys/
// available_plans containers, so the nested rows are what actually guard the
// numeric fields the UI formats.

export interface UsageCurrentCycle {
  start: string; // ISO-8601
  end: string; // ISO-8601
  request_count: number;
  monthly_request_cap: number;
}
export const UsageCurrentCycleFields: Record<keyof UsageCurrentCycle, true> = {
  start: true,
  end: true,
  request_count: true,
  monthly_request_cap: true,
};

export interface AvailablePlan {
  plan: string; // "cloud" | "teams" (Free excluded by backend)
  price_cents: number;
  currency: string; // "USD"
}
export const AvailablePlanFields: Record<keyof AvailablePlan, true> = {
  plan: true,
  price_cents: true,
  currency: true,
};

export interface ApiKeysSummary {
  active_count: number;
  limit: number | null; // null = unlimited
}
export const ApiKeysSummaryFields: Record<keyof ApiKeysSummary, true> = {
  active_count: true,
  limit: true,
};

// W5 resolution: `status` is loose `string` to match the backend Pydantic
// `status: str`; runtime defensiveness (coerce unknown Paddle states to
// "active") lives in BillingContext.refresh()/applyBilling(), not in the type.
// usage / available_plans / api_keys are additive (Phase 10) and optional so
// legacy callers keep type-checking; the backend always serializes them.
export interface BillingSummary {
  plan: string;
  price_cents: number | null;
  currency: string | null;
  status: string;
  trial_ends_at: string | null;
  current_period_ends_at: string | null;
  cancel_at_period_end: boolean;
  usage?: UsageCurrentCycle | null;
  available_plans?: AvailablePlan[];
  api_keys?: ApiKeysSummary | null;
}
export const BillingSummaryFields: Record<keyof BillingSummary, true> = {
  plan: true,
  price_cents: true,
  currency: true,
  status: true,
  trial_ends_at: true,
  current_period_ends_at: true,
  cancel_at_period_end: true,
  usage: true,
  available_plans: true,
  api_keys: true,
};

// --- /api/v1/reconciliation  ->  ProviderReconciliation (economics graph Phase E) ---
// The trust badge. `drift_pct` is signed against the provider's own bill:
// negative means BurnLens counted less than the invoice, which is the normal
// direction (traffic that never went through the proxy). Null when the provider
// billed nothing — there is no percentage of zero, so the UI shows the status
// word instead of a number.
export interface ProviderReconciliation {
  provider: string;
  status: "reconciled" | "drifted" | "unreconciled";
  day: string | null; // ISO date
  provider_cost_usd: number | null;
  burnlens_cost_usd: number | null;
  drift_pct: number | null;
  computed_at: string | null; // ISO-8601
}
export const ProviderReconciliationFields: Record<keyof ProviderReconciliation, true> = {
  provider: true,
  status: true,
  day: true,
  provider_cost_usd: true,
  burnlens_cost_usd: true,
  drift_pct: true,
  computed_at: true,
};

// --- /api/v1/economics  ->  EconomicsOverview ---
export interface TraceCoverage {
  request_count: number;
  traced_count: number;
  parented_count: number;
  distinct_traces: number;
  traced_rate: number;
  columns_missing: boolean;
}
export const TraceCoverageFields: Record<keyof TraceCoverage, true> = {
  request_count: true,
  traced_count: true,
  parented_count: true,
  distinct_traces: true,
  traced_rate: true,
  columns_missing: true,
};

export interface EconomicsOverview {
  total_spend_usd: number;
  detected_waste_usd: number;
  waste_rate: number;
  open_finding_count: number;
  error_spend_usd: number;
  error_request_count: number;
  cost_per_accepted_usd: number | null;
  accepted_count: number;
  waste_by_detector: Record<string, number>;
  waste_estimate_clamped: boolean;
  trace_coverage: TraceCoverage;
}
export const EconomicsOverviewFields: Record<keyof EconomicsOverview, true> = {
  total_spend_usd: true,
  detected_waste_usd: true,
  waste_rate: true,
  open_finding_count: true,
  error_spend_usd: true,
  error_request_count: true,
  cost_per_accepted_usd: true,
  accepted_count: true,
  waste_by_detector: true,
  waste_estimate_clamped: true,
  trace_coverage: true,
};

// --- /api/v1/outcomes/summary  ->  WorkflowEconomics ---
export interface WorkflowEconomics {
  workflow_id: string;
  accepted_count: number;
  rejected_count: number;
  failed_count: number;
  cost_total_usd: number;
  cost_accepted_usd: number;
  cost_rework_usd: number;
  cost_unattributed_usd: number;
  cost_per_accepted_usd: number | null;
  business_value_accepted: number | null;
}
export const WorkflowEconomicsFields: Record<keyof WorkflowEconomics, true> = {
  workflow_id: true,
  accepted_count: true,
  rejected_count: true,
  failed_count: true,
  cost_total_usd: true,
  cost_accepted_usd: true,
  cost_rework_usd: true,
  cost_unattributed_usd: true,
  cost_per_accepted_usd: true,
  business_value_accepted: true,
};

// --- /api/v1/outcomes/concentration  ->  ProviderConcentration ---
// spend_share says who is expensive; sole_provider_workflows says who cannot be
// left. accepted_share may sum past 1.0 across providers — an outcome several
// providers contributed to counts for each.
export interface ProviderConcentration {
  provider: string;
  spend_usd: number;
  spend_share: number;
  accepted_outcomes: number;
  accepted_share: number;
  workflows: number;
  sole_provider_workflows: number;
}
export const ProviderConcentrationFields: Record<keyof ProviderConcentration, true> = {
  provider: true,
  spend_usd: true,
  spend_share: true,
  accepted_outcomes: true,
  accepted_share: true,
  workflows: true,
  sole_provider_workflows: true,
};

// --- /api/v1/runs  ->  RunSummary ; /api/v1/runs/{id}  ->  RunDetail ---
// prompt_tokens is the whole prompt (uncached input + cache reads + writes);
// input_tokens is the UNCACHED share only. Never render input_tokens alone in
// a cost context — coding agents cache ~99% of the prompt.
export interface RunSummary {
  run_id: string;
  step_count: number;
  cost_usd: number;
  prompt_tokens: number;
  cached_tokens: number;
  input_tokens: number;
  output_tokens: number;
  started_at: string;
  ended_at: string;
  models: string[];
  source: string | null;
  key_kind: "session" | "trace";
}
export const RunSummaryFields: Record<keyof RunSummary, true> = {
  run_id: true,
  step_count: true,
  cost_usd: true,
  prompt_tokens: true,
  cached_tokens: true,
  input_tokens: true,
  output_tokens: true,
  started_at: true,
  ended_at: true,
  models: true,
  source: true,
  key_kind: true,
};

export interface RunStep {
  timestamp: string;
  model: string | null;
  prompt_tokens: number;
  cached_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  duration_ms: number | null;
  status_code: number | null;
  parent_span_id: string | null;
}
export const RunStepFields: Record<keyof RunStep, true> = {
  timestamp: true,
  model: true,
  prompt_tokens: true,
  cached_tokens: true,
  input_tokens: true,
  output_tokens: true,
  cost_usd: true,
  duration_ms: true,
  status_code: true,
  parent_span_id: true,
};

export interface RunDetail {
  run: RunSummary;
  steps: RunStep[];
}
export const RunDetailFields: Record<keyof RunDetail, true> = {
  run: true,
  steps: true,
};

// --- /api/v1/alert-rules  ->  AlertRule ---
// Webhook URLs are never returned — only has_slack / has_teams presence flags.
export interface AlertRule {
  id: string;
  threshold_pct: number;
  channel: string;
  enabled: boolean;
  has_slack: boolean;
  has_teams: boolean;
  extra_emails: string[];
  created_at: string;
  updated_at: string;
}
export const AlertRuleFields: Record<keyof AlertRule, true> = {
  id: true,
  threshold_pct: true,
  channel: true,
  enabled: true,
  has_slack: true,
  has_teams: true,
  extra_emails: true,
  created_at: true,
  updated_at: true,
};

// --- /api/v1/team/activity  ->  TeamActivityResponse / ActivityLogEntry ---
// `id` is an integer, unlike every other id in this file. `user` is a nested
// UserResponse or null ("System" rows); the page reads user.email — never a
// flat user_email, which the backend has never returned.
export interface ActivityLogEntry {
  id: number;
  action: string;
  detail: Record<string, unknown>;
  created_at: string;
  user: { id: string; email: string; name?: string | null } | null;
}
export const ActivityLogEntryFields: Record<keyof ActivityLogEntry, true> = {
  id: true,
  action: true,
  detail: true,
  created_at: true,
  user: true,
};

export interface TeamActivityResponse {
  entries: ActivityLogEntry[];
  total: number;
  limit: number;
  offset: number;
}
export const TeamActivityResponseFields: Record<keyof TeamActivityResponse, true> = {
  entries: true,
  total: true,
  limit: true,
  offset: true,
};

// --- /api/v1/usage/cache  ->  CacheOverview / CacheByModelRow ---
// Two distinct cache layers: provider prompt caching (cache_read/write tokens,
// provider-aware conventions handled backend-side) and the OSS proxy's
// semantic response cache (proxy_cache_hits / proxy_cache_saved_usd).
// cache_read_rate is reads over the WHOLE prompt.
export interface CacheByModelRow {
  model: string;
  request_count: number;
  prompt_tokens: number;
  cache_read_tokens: number;
  cache_read_rate: number;
}
export const CacheByModelRowFields: Record<keyof CacheByModelRow, true> = {
  model: true,
  request_count: true,
  prompt_tokens: true,
  cache_read_tokens: true,
  cache_read_rate: true,
};

export interface CacheOverview {
  prompt_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  uncached_input_tokens: number;
  cache_read_rate: number;
  request_count: number;
  proxy_cache_hits: number;
  proxy_cache_saved_usd: number;
  by_model: CacheByModelRow[];
}
export const CacheOverviewFields: Record<keyof CacheOverview, true> = {
  prompt_tokens: true,
  cache_read_tokens: true,
  cache_write_tokens: true,
  uncached_input_tokens: true,
  cache_read_rate: true,
  request_count: true,
  proxy_cache_hits: true,
  proxy_cache_saved_usd: true,
  by_model: true,
};

// --- /api/v1/findings  ->  FindingItem ---
export interface FindingItem {
  id: string;
  fingerprint: string;
  detector: string;
  subject_type: string;
  subject_key: string;
  severity: string;
  title: string;
  description: string;
  estimated_waste_usd: number;
  affected_count: number;
  evidence: Record<string, unknown>;
  status: string;
  first_seen_at: string | null;
  last_seen_at: string | null;
  resolved_at: string | null;
  baseline_waste_usd: number | null;
  baseline_cost_usd: number | null;
  baseline_requests: number | null;
  baseline_window_days: number | null;
  detection_count: number;
  detector_version: number;
}
// --- /api/v1/findings/verify  ->  SavingsVerdict ---
export interface SavingsVerdict {
  fingerprint: string;
  title: string;
  subject_type: string;
  subject_key: string;
  status: string;
  baseline_cost_per_request: number | null;
  current_cost_per_request: number | null;
  delta_per_request: number | null;
  pct_change: number | null;
  projected_monthly_savings_usd: number | null;
  baseline_requests: number | null;
  current_requests: number | null;
  days_remaining: number | null;
  reopened: boolean;
}
export const SavingsVerdictFields: Record<keyof SavingsVerdict, true> = {
  fingerprint: true,
  title: true,
  subject_type: true,
  subject_key: true,
  status: true,
  baseline_cost_per_request: true,
  current_cost_per_request: true,
  delta_per_request: true,
  pct_change: true,
  projected_monthly_savings_usd: true,
  baseline_requests: true,
  current_requests: true,
  days_remaining: true,
  reopened: true,
};

export const FindingItemFields: Record<keyof FindingItem, true> = {
  id: true,
  fingerprint: true,
  detector: true,
  subject_type: true,
  subject_key: true,
  severity: true,
  title: true,
  description: true,
  estimated_waste_usd: true,
  affected_count: true,
  evidence: true,
  status: true,
  first_seen_at: true,
  last_seen_at: true,
  resolved_at: true,
  baseline_waste_usd: true,
  baseline_cost_usd: true,
  baseline_requests: true,
  baseline_window_days: true,
  detection_count: true,
  detector_version: true,
};
