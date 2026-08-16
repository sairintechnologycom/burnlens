import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import {
  UsageSummaryFields,
  RecommendationRowFields,
  TeamBudgetRowFields,
  CostByModelFields,
  CostByTagFields,
  CostTimelineFields,
  RequestRowFields,
  BillingSummaryFields,
  UsageCurrentCycleFields,
  AvailablePlanFields,
  ApiKeysSummaryFields,
  ProviderReconciliationFields,
  EconomicsOverviewFields,
  FindingItemFields,
  SavingsVerdictFields,
  TraceCoverageFields,
  WorkflowEconomicsFields,
  RunSummaryFields,
  RunStepFields,
  RunDetailFields,
  AlertRuleFields,
  ActivityLogEntryFields,
  TeamActivityResponseFields,
  CacheOverviewFields,
  CacheByModelRowFields,
} from "@/lib/contracts";

const here = dirname(fileURLToPath(import.meta.url));
const snapshot = JSON.parse(
  readFileSync(join(here, "openapi-schemas.snapshot.json"), "utf8"),
) as Record<string, { properties?: Record<string, OpenApiProp> }>;

interface OpenApiProp {
  type?: string;
  anyOf?: { type?: string }[];
}

// Each endpoint the frontend reads -> backend schema name -> the field manifest.
const CONTRACTS = [
  { endpoint: "/api/v1/usage/summary", schema: "StatsSummary", fields: UsageSummaryFields },
  { endpoint: "/api/v1/recommendations", schema: "RecommendationItem", fields: RecommendationRowFields },
  { endpoint: "/api/v1/team-budgets", schema: "TeamBudgetRow", fields: TeamBudgetRowFields },
  { endpoint: "/api/v1/usage/by-model", schema: "CostByModel", fields: CostByModelFields },
  { endpoint: "/api/v1/usage/by-feature", schema: "CostByTag", fields: CostByTagFields },
  { endpoint: "/api/v1/usage/by-customer", schema: "CostByTag", fields: CostByTagFields },
  { endpoint: "/api/v1/usage/by-team", schema: "CostByTag", fields: CostByTagFields },
  { endpoint: "/api/v1/usage/timeseries", schema: "CostTimeline", fields: CostTimelineFields },
  { endpoint: "/api/v1/requests", schema: "RequestRecordResponse", fields: RequestRowFields },
  // /billing/summary returns BillingSummary. The top-level row presence-checks
  // the usage/available_plans/api_keys containers; the three nested rows guard
  // the numeric fields the UI actually formats (.toLocaleString / arithmetic).
  { endpoint: "/billing/summary", schema: "BillingSummary", fields: BillingSummaryFields },
  { endpoint: "/billing/summary (usage)", schema: "UsageCurrentCycle", fields: UsageCurrentCycleFields },
  { endpoint: "/billing/summary (available_plans[])", schema: "AvailablePlan", fields: AvailablePlanFields },
  { endpoint: "/billing/summary (api_keys)", schema: "ApiKeysSummary", fields: ApiKeysSummaryFields },
  { endpoint: "/api/v1/reconciliation", schema: "ProviderReconciliation", fields: ProviderReconciliationFields },
  { endpoint: "/api/v1/economics", schema: "EconomicsOverview", fields: EconomicsOverviewFields },
  { endpoint: "/api/v1/economics (trace_coverage)", schema: "TraceCoverage", fields: TraceCoverageFields },
  { endpoint: "/api/v1/findings", schema: "FindingItem", fields: FindingItemFields },
  { endpoint: "/api/v1/findings/verify", schema: "SavingsVerdict", fields: SavingsVerdictFields },
  { endpoint: "/api/v1/outcomes/summary", schema: "WorkflowEconomics", fields: WorkflowEconomicsFields },
  { endpoint: "/api/v1/runs", schema: "RunSummary", fields: RunSummaryFields },
  { endpoint: "/api/v1/runs/{run_id}", schema: "RunDetail", fields: RunDetailFields },
  { endpoint: "/api/v1/runs/{run_id} (steps[])", schema: "RunStep", fields: RunStepFields },
  { endpoint: "/api/v1/alert-rules", schema: "AlertRule", fields: AlertRuleFields },
  { endpoint: "/api/v1/team/activity", schema: "TeamActivityResponse", fields: TeamActivityResponseFields },
  { endpoint: "/api/v1/team/activity (entries[])", schema: "ActivityLogEntry", fields: ActivityLogEntryFields },
  { endpoint: "/api/v1/usage/cache", schema: "CacheOverview", fields: CacheOverviewFields },
  { endpoint: "/api/v1/usage/cache (by_model[])", schema: "CacheByModelRow", fields: CacheByModelRowFields },
] as const;

// Resolve the OpenAPI type for a property, unwrapping the anyOf:[T, null] that
// FastAPI emits for Optional fields.
function openApiType(prop: OpenApiProp): string | undefined {
  if (prop.type) return prop.type;
  if (prop.anyOf) {
    const nonNull = prop.anyOf.find((p) => p.type && p.type !== "null");
    return nonNull?.type;
  }
  return undefined;
}

// Map a manifest field name to the expected TS-primitive category, then check it
// is compatible with the OpenAPI type. We only need coarse buckets — the crash
// class was wrong names + number-vs-string, not deep shape mismatches.
const NUMBER_TYPES = new Set(["number", "integer"]);

// Static lookup tables: which manifest fields the frontend treats as numbers
// (anything it runs .toFixed / arithmetic / .toLocaleString on) vs strings.
const NUMERIC_FIELDS = new Set([
  "total_cost_usd",
  "total_requests",
  "avg_cost_per_request_usd",
  "models_used",
  "request_count",
  "total_input_tokens",
  "total_output_tokens",
  "cost_usd",
  "duration_ms",
  // BillingSummary + nested: the UI runs .toLocaleString / arithmetic on these.
  "price_cents",
  "monthly_request_cap",
  "active_count",
  "limit",
  // ProviderReconciliation: the badge formats these with .toFixed().
  "provider_cost_usd",
  "burnlens_cost_usd",
  "drift_pct",
  "total_spend_usd",
  "detected_waste_usd",
  "waste_rate",
  "open_finding_count",
  "error_spend_usd",
  "error_request_count",
  "cost_per_accepted_usd",
  "accepted_count",
  "rejected_count",
  "failed_count",
  "cost_total_usd",
  "cost_accepted_usd",
  "cost_rework_usd",
  "cost_unattributed_usd",
  "business_value_accepted",
  "estimated_waste_usd",
  "affected_count",
  "detection_count",
  "detector_version",
  "baseline_waste_usd",
  "baseline_cost_usd",
  "baseline_requests",
  "baseline_window_days",
  "traced_count",
  "parented_count",
  "distinct_traces",
  "traced_rate",
  "baseline_cost_per_request",
  "current_cost_per_request",
  "delta_per_request",
  "pct_change",
  "projected_monthly_savings_usd",
  "days_remaining",
  "current_requests",
  // RunSummary / RunStep: token columns the UI runs .toLocaleString on.
  "step_count",
  "prompt_tokens",
  "cached_tokens",
  "input_tokens",
  "output_tokens",
  "status_code",
  // AlertRule / TeamActivityResponse
  "threshold_pct",
  "total",
  "offset",
  // CacheOverview / CacheByModelRow
  "cache_read_tokens",
  "cache_write_tokens",
  "uncached_input_tokens",
  "cache_read_rate",
  "proxy_cache_hits",
  "proxy_cache_saved_usd",
]);
const STRING_FIELDS = new Set([
  "model",
  "provider",
  "tag",
  "date",
  "timestamp",
  // BillingSummary + nested (date-time strings unwrap to "string").
  "plan",
  "currency",
  "status",
  "trial_ends_at",
  "current_period_ends_at",
  "start",
  "end",
  "title",
  "description",
  "detector",
  "subject_type",
  "subject_key",
  "fingerprint",
  "id",
  "workflow_id",
  "first_seen_at",
  "last_seen_at",
  "resolved_at",
  "severity",
  // RunSummary / RunStep (date-times unwrap to "string")
  "run_id",
  "started_at",
  "ended_at",
  "key_kind",
  "source",
  // AlertRule / ActivityLogEntry
  "channel",
  "created_at",
  "updated_at",
  "action",
]);
const BOOLEAN_FIELDS = new Set([
  "cancel_at_period_end",
  "waste_estimate_clamped",
  "columns_missing",
  "reopened",
  "enabled",
  "has_slack",
  "has_teams",
]);

// Per-schema exceptions to the global field-name tables above.
// ActivityLogEntry.id is an integer while every other id is a string.
const SCHEMA_TYPE_OVERRIDES: Record<string, Record<string, "number" | "string">> = {
  ActivityLogEntry: { id: "number" },
};

// Check a manifest field's OpenAPI type against how the frontend uses it. We use
// coarse buckets — the crash class was wrong names + number-vs-string, not deep
// shape mismatches.
function typesCompatible(schema: string, field: string, apiType: string | undefined): boolean {
  const override = SCHEMA_TYPE_OVERRIDES[schema]?.[field];
  if (override === "number") return apiType !== undefined && NUMBER_TYPES.has(apiType);
  if (override === "string") return apiType === "string";
  if (NUMERIC_FIELDS.has(field)) return apiType !== undefined && NUMBER_TYPES.has(apiType);
  if (STRING_FIELDS.has(field)) return apiType === "string";
  if (BOOLEAN_FIELDS.has(field)) return apiType === "boolean";
  if (field === "tags") return apiType === "object";
  // NOTE: fields not listed above are only presence-checked, not type-checked.
  // If you add a numeric, string, or boolean field to a manifest in contracts.ts,
  // add it to NUMERIC_FIELDS / STRING_FIELDS / BOOLEAN_FIELDS here too, or type
  // drift won't be caught. Nested-object/array containers (usage, api_keys,
  // available_plans, tags) stay presence-only; their numeric fields are guarded
  // by adding the nested schema as its own CONTRACTS row.
  return true;
}

describe("frontend↔API contract", () => {
  for (const { endpoint, schema, fields } of CONTRACTS) {
    describe(`${endpoint} -> ${schema}`, () => {
      const def = snapshot[schema];

      it("schema exists in the OpenAPI snapshot", () => {
        expect(
          def,
          `Schema "${schema}" missing from snapshot. Regenerate: npm run contract:snapshot`,
        ).toBeDefined();
      });

      const props = def?.properties ?? {};
      for (const field of Object.keys(fields)) {
        it(`field "${field}" exists with a compatible type`, () => {
          expect(
            props[field],
            `Frontend reads "${field}" but ${schema} has no such property. ` +
              `Either the backend renamed it (update frontend/src/lib/contracts.ts) ` +
              `or the snapshot is stale (npm run contract:snapshot).`,
          ).toBeDefined();
          const apiType = openApiType(props[field]);
          expect(
            typesCompatible(schema, field, apiType),
            `Field "${field}" on ${schema} is OpenAPI type "${apiType}", ` +
              `incompatible with how the frontend uses it.`,
          ).toBe(true);
        });
      }
    });
  }
});
