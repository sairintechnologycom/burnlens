# Frontend↔API Contract Test — Design

**Date:** 2026-05-26
**Status:** Approved (design)
**Author:** Bhushan + Claude

## Problem

PR #18 (commit `d8512e7`) fixed a production crash where every authenticated page
threw "This page couldn't load". Root cause: the frontend hand-wrote TypeScript
interfaces (`SummaryData`, `RequestRecord`, …) that duplicated the backend's
Pydantic `response_model` shapes, and the two drifted. The frontend read
`total_cost`/`api_calls`/`cost`/`latency_ms`; the backend serialized
`total_cost_usd`/`request_count`/`cost_usd`/`duration_ms`. An undefined field hit
an unguarded `.toFixed()`/`.toLocaleString()`, threw, and crashed the shared
`RightPanel` chrome — taking down every authed page. Empty workspaces dodged it
via an early return, which is why QA missed it.

Nothing connected the two sides, and **no CI runs tests today** (the only
workflows are the hourly alert cron, Railway deploy, and PyPI publish). A field
rename on either side ships silently.

## Goal

A field-name or primitive-type drift between a backend Pydantic `response_model`
and the frontend interface that consumes it must turn **CI red**, not crash prod.
The backend remains the single source of truth.

## Non-goals

- No frontend logic refactor beyond relocating response-shape interfaces.
- No OpenAPI→TypeScript codegen toolchain (considered and rejected — see
  Alternatives).
- No deep/recursive schema validation. Top-level field presence + primitive type
  is the crash surface.

## Architecture

Three pieces plus a CI workflow.

### 1. OpenAPI snapshot (generated, committed)

`scripts/dump_openapi.py` imports the FastAPI app, calls `app.openapi()`, and
writes `components.schemas` to a committed
`frontend/tests/contract/openapi-schemas.snapshot.json`. This is the backend's
serialized truth frozen into the frontend test tree. Exposed as
`npm run contract:snapshot` (which shells out to Python) for local regeneration.

### 2. Frontend contract module — `frontend/src/lib/contracts.ts`

Relocate the response interfaces that currently live inline in pages
(`SummaryData`, `RequestRecord`, the by-model / by-tag / timeseries shapes) into
one module. Each interface gets a runtime **field manifest** typed as
`Record<keyof Interface, true>`:

```ts
export interface SummaryData {
  total_cost_usd: number;
  total_requests: number;
  avg_cost_per_request_usd: number;
  models_used: number;
}
export const SummaryFields: Record<keyof SummaryData, true> = {
  total_cost_usd: true,
  total_requests: true,
  avg_cost_per_request_usd: true,
  models_used: true,
};
```

The `Record<keyof T, true>` type forces the manifest to list **exactly** the
interface keys — TS compile-errors if a key is missing or extra. So
`Object.keys(SummaryFields)` is provably the set of fields the frontend depends
on. Pages import the interface from this module instead of declaring it inline
(a move, not a behavior change).

### 3. Contract test — `frontend/tests/contract/api-contract.test.ts`

A table maps each consumed endpoint → backend schema name → frontend manifest:

```ts
const CONTRACTS = [
  { endpoint: "/api/v1/usage/summary",     schema: "StatsSummary",          fields: SummaryFields },
  { endpoint: "/api/v1/usage/by-model",    schema: "CostByModel",           fields: ByModelFields },
  { endpoint: "/api/v1/usage/by-feature",  schema: "CostByTag",             fields: ByTagFields },
  { endpoint: "/api/v1/usage/by-customer", schema: "CostByTag",             fields: ByTagFields },
  { endpoint: "/api/v1/usage/by-team",     schema: "CostByTag",             fields: ByTagFields },
  { endpoint: "/api/v1/usage/timeseries",  schema: "CostTimeline",          fields: TimeseriesFields },
  { endpoint: "/api/v1/requests",          schema: "RequestRecordResponse", fields: RequestFields },
];
```

For each row the test asserts:
1. Every key in `fields` exists in `snapshot[schema].properties`.
2. The TS primitive of that field is compatible with the property's OpenAPI
   `type` (number ↔ `number`/`integer`, string ↔ `string`, boolean ↔ `boolean`).

Presence is checked against `properties`, not `required`, so backend-optional
fields are fine. Nested objects (e.g. `tags`) are asserted to exist as an
`object` and not recursed.

If `snapshot[schema]` is missing entirely, that row fails with a clear message
pointing at the snapshot regen step.

### 4. CI — new `.github/workflows/test.yml` (on PRs to `main`)

1. **Snapshot freshness:** set up Python, install backend deps, regenerate the
   snapshot, `git diff --exit-code` on it. Fails if the backend changed a model
   without the committed snapshot being regenerated.
2. **Contract + frontend tests:** `npm ci && npm run test` (vitest; includes the
   new contract test) in `frontend/`.
3. **Backend tests:** `pytest` — wired into CI here for the first time.

**Why both CI steps are needed (they compose):**
- Rename a backend field, forget the snapshot → step 1 (`git diff`) fails.
- Regenerate the snapshot, forget the frontend interface → contract test fails.
- Either path is red.

## Data flow (drift detection)

```
Pydantic model (source of truth)
   │  app.openapi()
   ▼
openapi-schemas.snapshot.json  ──[CI git diff]──> stale? → RED
   │
   ▼  (read by test)
api-contract.test.ts
   ▲
   │  Object.keys(manifest)
field manifest  ←─[TS: Record<keyof I, true>]── frontend interface
   ▲
   │  imported by
page / RightPanel component  (TS errors if it reads an off-interface field)
```

## Scope

- **Initial coverage:** the 7 usage/requests endpoints — the PR #18 crash
  surface.
- **Extensible:** adding alert-rules / connections / optimizations / budget is
  one new interface+manifest in `contracts.ts` and one row in the `CONTRACTS`
  table. Deferred to a follow-up unless requested.

## Alternatives considered

- **OpenAPI → generated TS types (openapi-typescript codegen).** Strongest
  guarantee (a rename becomes a TS compile error, zero hand-maintained lists) but
  a moderate refactor of all 6 consumers + `apiFetch`, plus a new codegen
  toolchain. Rejected as disproportionate for closing this specific debt; the
  `Record<keyof I, true>` manifest gives most of the safety for far less change.
- **Hand-maintained dual fixture (no OpenAPI).** A JSON fixture checked by both
  pytest and vitest. Simplest, but the fixture is hand-maintained and rots — it
  is not anchored to the real Pydantic models. Rejected on durability.

## Risks / edge cases

- **Backend not importable in CI without DB.** `app.openapi()` must not require a
  live Postgres connection. Verify the app object can be imported and schema
  generated standalone; if a module-level connection is needed, the dump script
  imports only what `openapi()` needs or stubs the connection.
- **Snapshot churn.** Unrelated model additions change the snapshot. Acceptable —
  regen is one command and the diff is reviewable.
- **`CostByTag` reused by three endpoints.** Intentional; all three share the
  same manifest.

## Success criteria

1. Renaming any covered backend field without updating the frontend makes CI red
   (demonstrated by a deliberate local rename during implementation).
2. The contract test passes against the current `main` schemas.
3. `test.yml` runs on PRs and gates merge on contract + vitest + pytest.
4. Adding a new covered endpoint is a two-line change (interface+manifest, table
   row).
