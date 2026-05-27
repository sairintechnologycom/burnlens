import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import {
  UsageSummaryFields,
  CostByModelFields,
  CostByTagFields,
  CostTimelineFields,
  RequestRowFields,
  BillingSummaryFields,
  UsageCurrentCycleFields,
  AvailablePlanFields,
  ApiKeysSummaryFields,
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
]);
const BOOLEAN_FIELDS = new Set(["cancel_at_period_end"]);

// Check a manifest field's OpenAPI type against how the frontend uses it. We use
// coarse buckets — the crash class was wrong names + number-vs-string, not deep
// shape mismatches.
function typesCompatible(field: string, apiType: string | undefined): boolean {
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
            typesCompatible(field, apiType),
            `Field "${field}" on ${schema} is OpenAPI type "${apiType}", ` +
              `incompatible with how the frontend uses it.`,
          ).toBe(true);
        });
      }
    });
  }
});
