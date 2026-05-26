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
}
export const UsageSummaryFields: Record<keyof UsageSummary, true> = {
  total_cost_usd: true,
  total_requests: true,
  avg_cost_per_request_usd: true,
  models_used: true,
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
