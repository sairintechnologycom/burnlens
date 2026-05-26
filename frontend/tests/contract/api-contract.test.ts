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
function typesCompatible(field: string, apiType: string | undefined): boolean {
  // Fields the frontend treats as numbers (everything it runs .toFixed /
  // arithmetic / .toLocaleString on).
  const numericFields = new Set([
    "total_cost_usd",
    "total_requests",
    "avg_cost_per_request_usd",
    "models_used",
    "request_count",
    "total_input_tokens",
    "total_output_tokens",
    "cost_usd",
    "duration_ms",
  ]);
  if (numericFields.has(field)) return apiType !== undefined && NUMBER_TYPES.has(apiType);
  // string-ish fields
  const stringFields = new Set(["model", "provider", "tag", "date", "timestamp"]);
  if (stringFields.has(field)) return apiType === "string";
  // object-ish (tags)
  if (field === "tags") return apiType === "object";
  // any other field: presence is enough
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
