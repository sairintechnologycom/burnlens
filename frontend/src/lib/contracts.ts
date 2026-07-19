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
  total_cost_usd: number;
}
export const CostTimelineFields: Record<keyof CostTimelinePoint, true> = {
  date: true,
  total_cost_usd: true,
};

// --- /api/v1/requests  ->  RequestRecordResponse ---
export interface RequestRow {
  timestamp: string;
  model: string;
  cost_usd: number;
  duration_ms?: number;
  // tags shape is freeform; the contract test only checks key presence, not nested fields.
  tags?: { feature?: string; team?: string; [k: string]: unknown } | null;
}
export const RequestRowFields: Record<keyof RequestRow, true> = {
  timestamp: true,
  model: true,
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
