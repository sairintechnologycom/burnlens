# Frontend↔API Contract Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a field-name or primitive-type drift between a backend Pydantic `response_model` and the frontend interface that consumes it turn CI red, instead of crashing prod (as PR #18 did).

**Architecture:** A committed OpenAPI snapshot (generated from the live FastAPI app) is the backend's frozen truth. The frontend's response interfaces live in one module, each paired with a `Record<keyof Interface, true>` field manifest so TS proves the manifest equals the interface keys. A vitest contract test asserts every frontend field exists with a compatible primitive type in the snapshot. A new PR CI workflow gates on snapshot-freshness + vitest.

**Tech Stack:** FastAPI (`app.openapi()`), Python 3.11, TypeScript, Vitest, GitHub Actions.

---

## Context for the implementer (read once)

- **Repo root:** `/Users/bhushan/Documents/Projects/burnlens`. Frontend lives in `frontend/`.
- **Branch:** work happens on `feat/frontend-api-contract-test` (already checked out; the spec was committed there).
- **Python:** this machine's `python3` has NO fastapi. Use `/opt/homebrew/bin/python3.11` (fastapi 0.136 + pytest installed) for any local Python run. In CI we use `actions/setup-python` + `pip install`, where plain `python` has the deps.
- **Frontend tests:** `cd frontend && npm run test` runs vitest (`vitest run`). Config: `frontend/vitest.config.ts` — `environment: "node"`, includes `tests/**/*.test.ts(x)`, excludes `tests/e2e/**`, alias `@` → `src`.
- **The 5 backend schemas (verified field names & OpenAPI types via `app.openapi()` on 2026-05-26):**
  - `StatsSummary`: `total_cost_usd` number, `total_requests` integer, `avg_cost_per_request_usd` number, `models_used` integer, `budget_limit_usd` number?, `budget_pct_used` number?
  - `CostByModel`: `model` string, `provider` string, `request_count` integer, `total_input_tokens` integer, `total_output_tokens` integer, `total_cost_usd` number
  - `CostByTag`: `tag` string, `request_count` integer, `total_cost_usd` number, `total_input_tokens` integer, `total_output_tokens` integer
  - `CostTimeline`: `date` string, `request_count` integer, `total_cost_usd` number
  - `RequestRecordResponse`: `timestamp` string, `provider` string, `model` string, `input_tokens` integer?, `output_tokens` integer?, `reasoning_tokens` integer?, `cache_read_tokens` integer?, `cache_write_tokens` integer?, `cost_usd` number?, `duration_ms` integer?, `status_code` integer?, `tags` object?, `system_prompt_hash` string?, `workspace_id` string, `id` integer, `received_at` string
- **Optional-field gotcha:** in the OpenAPI schema, optional fields are NOT a flat `{"type": "..."}`. They serialize as `{"anyOf": [{"type": "number"}, {"type": "null"}]}`. The type-compatibility check MUST unwrap `anyOf` and ignore the `null` branch.
- **Frontend fields actually read by each consumer (from grep on 2026-05-26):**
  - `dashboard/page.tsx`: summary → `total_cost_usd, total_requests, avg_cost_per_request_usd, models_used`; timeseries point → `date, total_cost_usd`; request row → `timestamp, model, cost_usd, duration_ms, tags`
  - `models/page.tsx`: `model, provider, request_count, total_input_tokens, total_output_tokens, total_cost_usd`
  - `RightPanel.tsx`: by-model subset → `model, total_cost_usd`
  - `features/page.tsx`, `customers/page.tsx`, `teams/page.tsx`: `tag, request_count, total_cost_usd`

## File structure (created / modified)

- **Create** `scripts/dump_openapi.py` — dumps `app.openapi()["components"]["schemas"]` to the snapshot file. Path computed from `__file__` so CWD doesn't matter.
- **Create** `frontend/tests/contract/openapi-schemas.snapshot.json` — generated, committed.
- **Create** `frontend/src/lib/contracts.ts` — shared response interfaces + `Record<keyof I, true>` field manifests.
- **Create** `frontend/tests/contract/api-contract.test.ts` — the contract test.
- **Modify** `frontend/package.json` — add `contract:snapshot` script.
- **Modify** consumers to import shared interfaces: `frontend/src/app/dashboard/page.tsx`, `frontend/src/app/models/page.tsx`, `frontend/src/app/features/page.tsx`, `frontend/src/app/customers/page.tsx`, `frontend/src/app/teams/page.tsx`, `frontend/src/components/RightPanel.tsx`.
- **Create** `.github/workflows/test.yml` — PR CI gate.

---

## Task 1: OpenAPI dump script + committed snapshot

**Files:**
- Create: `scripts/dump_openapi.py`
- Create: `frontend/tests/contract/openapi-schemas.snapshot.json` (generated output)

- [ ] **Step 1: Write the dump script**

Create `scripts/dump_openapi.py`:

```python
#!/usr/bin/env python3
"""Dump the FastAPI OpenAPI component schemas to a committed snapshot.

The frontend contract test (frontend/tests/contract/api-contract.test.ts) reads
this file as the backend's source of truth. Regenerate after changing any
Pydantic response_model:

    python scripts/dump_openapi.py        # CI / any python with deps
    BURNLENS_PYTHON=/opt/homebrew/bin/python3.11 npm run contract:snapshot  # local

app.openapi() does NOT open a DB connection (the pool is created in the FastAPI
lifespan, which this does not trigger), so this runs offline.
"""
import json
from pathlib import Path

from burnlens_cloud.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO_ROOT / "frontend" / "tests" / "contract" / "openapi-schemas.snapshot.json"


def main() -> None:
    schemas = app.openapi()["components"]["schemas"]
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    # Sort keys for a stable, diff-friendly snapshot.
    SNAPSHOT.write_text(json.dumps(schemas, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {len(schemas)} schemas to {SNAPSHOT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Generate the snapshot and verify the 5 schemas are present**

Run:
```bash
cd /Users/bhushan/Documents/Projects/burnlens
/opt/homebrew/bin/python3.11 scripts/dump_openapi.py
/opt/homebrew/bin/python3.11 -c "import json; s=json.load(open('frontend/tests/contract/openapi-schemas.snapshot.json')); print(sorted(k for k in ['StatsSummary','CostByModel','CostByTag','CostTimeline','RequestRecordResponse'] if k in s))"
```
Expected: first line prints `Wrote N schemas ...`; second line prints `['CostByModel', 'CostByTag', 'CostTimeline', 'RequestRecordResponse', 'StatsSummary']` (all 5).

- [ ] **Step 3: Commit**

```bash
git add scripts/dump_openapi.py frontend/tests/contract/openapi-schemas.snapshot.json
git commit -m "feat(contract): add OpenAPI schema dump script + snapshot"
```

---

## Task 2: Frontend contracts module

**Files:**
- Create: `frontend/src/lib/contracts.ts`

This module is the single home for the response shapes the frontend reads. Each
interface lists ONLY the fields the frontend actually consumes (a subset of the
backend schema is fine — the contract test asserts subset ⊆ backend). The
`Record<keyof I, true>` manifest is what the test reads at runtime; TS guarantees
it lists exactly the interface keys.

- [ ] **Step 1: Write the contracts module**

Create `frontend/src/lib/contracts.ts`:

```ts
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
```

- [ ] **Step 2: Type-check the module compiles**

Run:
```bash
cd /Users/bhushan/Documents/Projects/burnlens/frontend
npx tsc --noEmit
```
Expected: no errors referencing `contracts.ts`. (Pre-existing errors elsewhere, if any, are out of scope — but `contracts.ts` itself must be clean.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/contracts.ts
git commit -m "feat(contract): add shared frontend response contracts module"
```

---

## Task 3: The contract test

**Files:**
- Create: `frontend/tests/contract/api-contract.test.ts`

- [ ] **Step 1: Write the contract test**

Create `frontend/tests/contract/api-contract.test.ts`:

```ts
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
```

- [ ] **Step 2: Run the test — expect PASS against current main**

Run:
```bash
cd /Users/bhushan/Documents/Projects/burnlens/frontend
npm run test -- tests/contract/api-contract.test.ts
```
Expected: all contract assertions PASS (current `main` is aligned post-PR #18). If any fail, the snapshot or `contracts.ts` is wrong — fix before continuing.

- [ ] **Step 3: Prove it fails on drift (RED demonstration), then revert**

Temporarily rename a field in the manifest to simulate frontend drift:
```bash
cd /Users/bhushan/Documents/Projects/burnlens/frontend
# break it: rename total_cost_usd -> total_cost in the UsageSummary interface AND manifest
sed -i.bak 's/total_cost_usd/total_cost/g' src/lib/contracts.ts
npm run test -- tests/contract/api-contract.test.ts
```
Expected: FAIL — `field "total_cost" exists ...` for `StatsSummary` (and the other schemas that use `total_cost_usd`), with the "backend renamed it / snapshot stale" message.

Now revert:
```bash
mv src/lib/contracts.ts.bak src/lib/contracts.ts
npm run test -- tests/contract/api-contract.test.ts
```
Expected: PASS again. Confirm no `.bak` file remains: `ls src/lib/*.bak` → "No such file".

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/contract/api-contract.test.ts
git commit -m "test(contract): assert frontend fields exist in OpenAPI snapshot"
```

---

## Task 4: Point consumers at the shared contracts

Replace each consumer's inline interface with an import from `@/lib/contracts`.
This is what makes the guarantee real: once a component reads off the shared
interface, TS errors if it reads a field the contract doesn't include. Behavior
is unchanged — only the type declaration moves.

**Files:**
- Modify: `frontend/src/app/dashboard/page.tsx`
- Modify: `frontend/src/app/models/page.tsx`
- Modify: `frontend/src/app/features/page.tsx`
- Modify: `frontend/src/app/customers/page.tsx`
- Modify: `frontend/src/app/teams/page.tsx`
- Modify: `frontend/src/components/RightPanel.tsx`

- [ ] **Step 1: dashboard/page.tsx** — remove the inline `interface SummaryData {...}` and `interface RequestRecord {...}` blocks. Add at the top of the imports:

```ts
import type { UsageSummary, RequestRow } from "@/lib/contracts";
```

Then replace usages: `useState<SummaryData | null>` → `useState<UsageSummary | null>`; `setRequests(reqs as RequestRecord[])` → `setRequests(reqs as RequestRow[])`; `useState<RequestRecord[]>` → `useState<RequestRow[]>`. (The timeseries point is read inline as `any`; leave that fetch as-is — `CostTimeline` coverage is exercised by the contract test directly, not via a typed consumer here.)

- [ ] **Step 2: models/page.tsx** — remove the inline `interface ModelData {...}`. Add:

```ts
import type { CostByModelRow } from "@/lib/contracts";
```

Replace every `ModelData` reference with `CostByModelRow` (e.g. `useState<ModelData[]>` → `useState<CostByModelRow[]>`, `models.map((m: ModelData) ...)` if present).

- [ ] **Step 3: RightPanel.tsx** — remove the inline `interface ModelEntry {...}`. Add:

```ts
import type { CostByModelRow } from "@/lib/contracts";
```

Replace `ModelEntry` references with `CostByModelRow`. RightPanel only reads `model` and `total_cost_usd`; reading a subset of the interface is fine.

- [ ] **Step 4: features/page.tsx** — remove the inline `interface FeatureRow {...}`. Add:

```ts
import type { CostByTagRow } from "@/lib/contracts";
```

Replace `FeatureRow` references with `CostByTagRow`.

- [ ] **Step 5: customers/page.tsx** — remove the inline `interface CustomerData {...}`. Add:

```ts
import type { CostByTagRow } from "@/lib/contracts";
```

Replace `CustomerData` references with `CostByTagRow`.

- [ ] **Step 6: teams/page.tsx** — remove the inline `interface TeamData {...}`. Add:

```ts
import type { CostByTagRow } from "@/lib/contracts";
```

Replace `TeamData` references with `CostByTagRow`.

- [ ] **Step 7: Type-check + build the consumers**

Run:
```bash
cd /Users/bhushan/Documents/Projects/burnlens/frontend
npx tsc --noEmit
```
Expected: no NEW errors in the 6 modified files. If a consumer reads a field not in the shared interface, this is where it surfaces — add that field to the interface AND its manifest in `contracts.ts` (and re-run the contract test from Task 3 Step 2 to confirm the new field is in the backend schema).

- [ ] **Step 8: Run the full frontend test suite**

Run:
```bash
cd /Users/bhushan/Documents/Projects/burnlens/frontend
npm run test
```
Expected: PASS (contract test + existing support tests). E2E is excluded by vitest config.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/app/dashboard/page.tsx frontend/src/app/models/page.tsx \
  frontend/src/app/features/page.tsx frontend/src/app/customers/page.tsx \
  frontend/src/app/teams/page.tsx frontend/src/components/RightPanel.tsx
git commit -m "refactor(frontend): consume shared API contracts in dashboard pages"
```

---

## Task 5: npm snapshot script + CI workflow

**Files:**
- Modify: `frontend/package.json`
- Create: `.github/workflows/test.yml`

- [ ] **Step 1: Add the snapshot npm script**

In `frontend/package.json`, add to `"scripts"` (after the existing `"test:e2e:ui"` line):

```json
    "contract:snapshot": "${BURNLENS_PYTHON:-python3} ../scripts/dump_openapi.py"
```

(Local use needs fastapi-capable Python: `BURNLENS_PYTHON=/opt/homebrew/bin/python3.11 npm run contract:snapshot`. In CI plain `python3` has the deps.)

- [ ] **Step 2: Verify the script runs**

Run:
```bash
cd /Users/bhushan/Documents/Projects/burnlens/frontend
BURNLENS_PYTHON=/opt/homebrew/bin/python3.11 npm run contract:snapshot
git status --short frontend/tests/contract/openapi-schemas.snapshot.json
```
Expected: prints `Wrote N schemas ...`; `git status` shows the snapshot UNCHANGED (it was already current from Task 1) — i.e. no output, confirming determinism.

- [ ] **Step 3: Write the CI workflow**

Create `.github/workflows/test.yml`:

```yaml
name: Tests

on:
  pull_request:
    branches: [main]
  workflow_dispatch:

jobs:
  contract-and-frontend:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v5

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install backend deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Regenerate OpenAPI snapshot
        run: python scripts/dump_openapi.py

      - name: Fail if snapshot is stale
        run: |
          if ! git diff --exit-code frontend/tests/contract/openapi-schemas.snapshot.json; then
            echo "::error::OpenAPI snapshot is out of date. Run 'npm run contract:snapshot' and commit the result."
            exit 1
          fi

      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install frontend deps
        working-directory: frontend
        run: npm ci

      - name: Run frontend tests (includes contract test)
        working-directory: frontend
        run: npm run test
```

- [ ] **Step 4: Validate the workflow YAML**

Run:
```bash
cd /Users/bhushan/Documents/Projects/burnlens
/opt/homebrew/bin/python3.11 -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml')); print('valid yaml')"
ls frontend/package-lock.json && echo "lockfile present (npm ci will work)"
```
Expected: `valid yaml` and `lockfile present ...`. If `package-lock.json` is absent, change `npm ci` to `npm install` and drop the `cache`/`cache-dependency-path` lines.

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json .github/workflows/test.yml
git commit -m "ci: gate PRs on OpenAPI snapshot freshness + frontend tests"
```

---

## Task 6: Final verification

- [ ] **Step 1: Clean tree + full local gate**

Run:
```bash
cd /Users/bhushan/Documents/Projects/burnlens
git status --short                     # expect: clean (all work committed)
BURNLENS_PYTHON=/opt/homebrew/bin/python3.11 frontend/../scripts/../scripts/dump_openapi.py >/dev/null 2>&1 || /opt/homebrew/bin/python3.11 scripts/dump_openapi.py
git diff --exit-code frontend/tests/contract/openapi-schemas.snapshot.json && echo "snapshot fresh"
cd frontend && npm run test
```
Expected: working tree clean, `snapshot fresh`, vitest all green.

- [ ] **Step 2: Re-confirm the RED path one more time (end-to-end)**

Simulate a BACKEND rename to prove the snapshot-freshness gate logic catches it locally:
```bash
cd /Users/bhushan/Documents/Projects/burnlens
# Temporarily edit the snapshot as if the backend renamed a field, WITHOUT regenerating:
/opt/homebrew/bin/python3.11 - <<'PY'
import json, pathlib
p = pathlib.Path("frontend/tests/contract/openapi-schemas.snapshot.json")
s = json.loads(p.read_text())
s["StatsSummary"]["properties"]["total_cost"] = s["StatsSummary"]["properties"].pop("total_cost_usd")
p.write_text(json.dumps(s, indent=2, sort_keys=True) + "\n")
PY
cd frontend && npm run test -- tests/contract/api-contract.test.ts; echo "exit=$?"
```
Expected: contract test FAILS (frontend reads `total_cost_usd`, snapshot now lacks it), `exit` non-zero.

Restore the real snapshot:
```bash
cd /Users/bhushan/Documents/Projects/burnlens
git checkout frontend/tests/contract/openapi-schemas.snapshot.json
cd frontend && npm run test -- tests/contract/api-contract.test.ts && echo "restored + green"
```
Expected: PASS, `restored + green`.

- [ ] **Step 3: Update the follow-up memory note**

Mark the contract-test debt as closed in
`/Users/bhushan/.claude/projects/-Users-bhushan-Documents-Projects-burnlens/memory/project_followups_2026_05_26.md`
(the "Tech-debt follow-up (still open)" paragraph) and note the separate, still-open
backend-pytest-suite-red debt discovered during this work.

---

## Self-review notes

- **Spec coverage:** snapshot script (Task 1) ✓; contracts module + manifests (Task 2) ✓; contract test with anyOf-unwrap + primitive type check (Task 3) ✓; consumer refactor that makes the TS guarantee real (Task 4) ✓; npm script + CI with snapshot-freshness + vitest, pytest intentionally omitted (Task 5) ✓; RED demonstrations for both frontend-drift (T3 S3) and backend-drift (T6 S2) satisfy success criterion #1 ✓.
- **Type consistency:** interface/manifest/import names are consistent across tasks — `UsageSummary`/`UsageSummaryFields`, `CostByModelRow`/`CostByModelFields`, `CostByTagRow`/`CostByTagFields`, `CostTimelinePoint`/`CostTimelineFields`, `RequestRow`/`RequestRowFields`. Schema names match the verified backend list.
- **Known external state:** backend pytest suite is pre-existing red (out of scope, logged in T6 S3). E2E excluded by vitest config — not run here.
