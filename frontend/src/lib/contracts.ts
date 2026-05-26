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
  tags?: { feature?: string; team?: string; [k: string]: unknown } | null;
}
export const RequestRowFields: Record<keyof RequestRow, true> = {
  timestamp: true,
  model: true,
  cost_usd: true,
  duration_ms: true,
  tags: true,
};
