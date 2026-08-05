# Railway event-identity canary readiness

**Assessment date:** 2026-08-05 (rechecked after Railway limit restoration)
**Scope:** read-only Railway/GitHub/public-health evidence and local test execution. No production deployment, variable, migration, database, feature flag, monitoring, or infrastructure setting was changed. This document supersedes the runtime-status portion of `PRODUCTION_RUNTIME_TRUTH.md` as of this date.

## Outcome

BurnLens is **not** ready for an event-identity canary. Railway service was restored after a platform-limit interruption: both services now have successful active deployments and the public health endpoint returns `200`. The required PostgreSQL-scale evidence, duplicate assessment, deployed monitoring, workspace allowlist, rollback test, backup/recovery evidence, and named operational owners are still absent.

## 1. Railway runtime configuration record

All Railway identifiers below are deployment/service identifiers, not credentials. No variable values, database URLs, passwords, API tokens, or encryption keys were read.

| Item | Evidence on 2026-08-05 | Status |
| --- | --- | --- |
| Railway project/environment | `burnlens` / `production` | Verified |
| API service | `burnlens-proxy` | Verified |
| Active API deployment | `a75cfe08-ce52-4688-b375-455354c81799`; `SUCCESS`; redeployed 2026-08-05 06:32:16 UTC | Verified |
| Active PostgreSQL deployment | `59f71ab9-424d-4933-ab80-3afcb6706321`; `SUCCESS`; redeployed 2026-08-05 06:32:17 UTC | Verified |
| Previous observed API deployment | `24adda42-98b1-48db-bb2e-922f179a13aa`, previously successful on 2026-08-04, remains `REMOVED` | Verified |
| API source commit | Not exposed by current Railway deployment metadata | Unknown |
| Region / replicas | `asia-southeast1-eqsg3a`; one replica | Verified deployment configuration |
| Restart policy | `ON_FAILURE`, maximum 10 retries | Verified deployment configuration |
| Health check | No Railway `healthcheckPath` or timeout configured | Verified |
| Pre-deploy command | None | Verified |
| Start command | No explicit Railway command; Railpack auto-detects Python. [`Procfile`](../Procfile) is repository indication only. | Verified / repository indication |
| PostgreSQL service | `Postgres` service exists but has no active/latest deployment | Verified |
| Database persistence | Volume at `/var/lib/postgresql/data`: 345.6 MB used of 5 GB | Verified |
| Application-to-database binding | A `DATABASE_URL` is required by source ([`config.py`](../burnlens_cloud/config.py#L9)); deployed binding was not read. | Unknown |
| `STREAMING_ENABLED` | No secret/non-secret value metadata available without reading variables. No production Redpanda/ClickHouse service is present. | Unknown; streaming is not a canary dependency |
| `EVENT_IDENTITY_ENABLED` | No runtime value available without reading variables. The feature code is uncommitted locally, so it cannot be in the currently failed April deployment. | Not deployed / unknown value |
| Workspace allowlist | No allowlist configuration exists in current code or checked-in deployment configuration. [`config.py`](../burnlens_cloud/config.py#L103-L107) has only the global identity flag. | **Missing canary control** |
| Migration mechanism | Versioned local runner exists at [`migrations/runner.py`](../burnlens_cloud/migrations/runner.py), but no Railway pre-deploy command or GitHub migration step is configured. | Not deployed / unproven |
| Backup/PITR / maintenance | No Railway metadata or approved operator evidence obtained. | Unknown |

Earlier on 2026-08-05, the public endpoint returned HTTP `404 Application not found` while Railway had no active deployments. After the Railway limit was raised, both services were redeployed successfully and `https://api.burnlens.app/health` returned HTTP `200 {"status":"ok"}`. No action was taken by this workstream; the recovery was operator initiated.

## 2. GitHub deployment authority record

| Item | Evidence | Status |
| --- | --- | --- |
| Backend deployment workflow | [`deploy-railway.yml`](../.github/workflows/deploy-railway.yml#L1) deploys `burnlens-proxy` to Railway production after backend tests and frontend test/build. | Verified source |
| Production GitHub environment | Exists; no protection rules or required reviewers. | Verified GitHub metadata |
| Main-branch protection | Not enabled. | Verified GitHub metadata |
| Repository secret names | `RAILWAY_TOKEN`, `CRON_SECRET`; no repository Actions variables. | Verified names only |
| Production environment secrets / variables | None listed. | Verified names only |
| Recent backend workflow history | 55 completed runs: 51 success, 4 failure. The latest was successful run `29759144642`, commit `6f0f22615821f6a76b5424077444618700012618`, 2026-07-20 16:20–16:22 UTC. | Verified GitHub metadata |
| Recent failures | Four failed workflow runs: `29684299567`, `29652642208`, `25620622683`, `25620577875`. Their causes were not read from logs. | Verified metadata; cause unknown |
| GitHub-to-Railway mapping | GitHub created a `production` deployment record for commit `6f0f…` at 16:22 UTC, contemporaneous with the previously successful Railway deployment. Railway did not retain the source SHA in its deployment metadata. | Strong inference, not exact proof |
| Railway-token owner / workflow owner / rollback approver | GitHub metadata shows the organisation account as workflow actor. It does not establish an accountable human or role assignment. | Assignment pending |

The workflow contains no migration step ([`deploy-railway.yml`](../.github/workflows/deploy-railway.yml#L45-L65)) and no rollback procedure. GitHub environment presence is not an approval control while its protection-rule list is empty.

## 3. Operational ownership matrix

Named owners were not authorised or available in the inspected metadata. Each role must be assigned before canary approval.

| Responsibility | Required accountable role | Current assignment |
| --- | --- | --- |
| Production deployment approval | GitHub production-environment administrator | Pending |
| Railway service operation | Railway project administrator | Pending |
| PostgreSQL administration | Railway PostgreSQL administrator | Pending |
| Backup and recovery | Database owner with restore authority | Pending |
| Migration execution | Change-approved migration operator | Pending |
| Event-identity enable/allowlist | BurnLens service owner | Pending |
| Monitoring / alert delivery | On-call owner with destination access | Pending |
| Incident response | Incident commander / on-call owner | Pending |
| Rollback | Railway deployer plus production-change approver | Pending |
| Security and secrets | GitHub/Railway secrets owner | Pending |

## 4. PostgreSQL migration certification

### Result: not executed at representative scale

No approved Railway clone, restored sanitized backup, read-only replica, or database connection metadata is available. Although PostgreSQL is now active, production data must not be used for this benchmark without separate approval. Therefore none of the following can be truthfully measured: `request_records` row count/table/index sizes, workspace distribution, concurrent ingestion, migration/index duration, lock waits, blocked statements, latency percentiles, CPU/I/O, ledger growth, or dashboard latency.

The local migration design is additive: nullable identity columns plus identity/outbox tables and a partial unique index ([`20260804_01_event_identity.py`](../burnlens_cloud/migrations/versions/20260804_01_event_identity.py)). It explicitly stops before unique-index creation when historical identity duplicates exist; it does not rewrite historical cost. This is design evidence, not production-scale certification.

Local targeted test run, using `.venv` on 2026-08-05:

```text
.venv/bin/pytest -q tests/test_event_identity_ingest.py \
  tests/test_event_identity_postgres_integration.py \
  tests/test_event_identity_cloud_topology.py
10 passed, 2 skipped, 4 warnings in 0.82s
```

The two real-integration tests skipped because `BURNLENS_TEST_DATABASE_URL` and isolated topology configuration were absent. These results prove neither Railway compatibility nor representative scale.

### Required approved benchmark before enablement

1. Restore a sanitized production snapshot into an isolated Railway project/environment or approved equivalent, preserving table sizes, workspace skew, provider/model cardinality, and timestamp distribution.
2. Capture baseline `pg_stat_activity`, `pg_locks`, table/index sizes, database CPU/I/O, and API/dashboard p50/p95/p99 under representative concurrent writers.
3. Run the read-only duplicate preflight, then the versioned PostgreSQL migration with `EVENT_IDENTITY_ENABLED=false`.
4. Record migration/index timings, lock waits, blocked statements, ingestion errors, exact replay contention, and post-migration dashboard latency.
5. Re-run migrations, test legacy/no-ID writes, exact/conflicting replays, same ID in separate workspaces, and global/workspace disablement.
6. Preserve the clone only for the agreed evidence-retention period, then destroy it under the database-owner procedure.

## 5. Historical duplicate assessment

### Result: not run

[`event_identity_duplicate_assessment.sql`](../scripts/event_identity_duplicate_assessment.sql) is read-only and produces the required workspace/source-ID groups, timestamps, providers/models, request IDs, represented cost, payload classification, and remediation state. It was not executed because no approved clone/read-only connection exists; production data was not accessed.

**Partial unique-index decision: blocked.** It cannot be enabled until the assessment reports zero unresolved duplicate groups for rows with `source_event_id`, or a separately approved manual remediation decision exists. No historical row may be deleted, merged, or rewritten by the migration.

## 6. Railway-compatible monitoring

### Result: not deployed or evidenced

Current evidence is limited to:

* the deployment workflow's one-time `curl` health check;
* a GitHub-scheduled application alert evaluator; and
* application `/health` and `/api/status` endpoints.

None provides the required persistent measurements, alarm delivery, owner, or escalation path. The current outage was detectable only by this manual read-only check, which demonstrates the gap.

The smallest compliant implementation, after production-change approval, is structured event-identity log records emitted by the existing Railway API plus a deployed scheduled collector with a **read-only database role** for aggregated counts. It must route failures to the assigned on-call destination. Do not introduce a new streaming system for this.

| Signal | Source / aggregation | Initial threshold / interval | Owner and runbook |
| --- | --- | --- | --- |
| Public health failure | Scheduled unauthenticated `GET /health` | Any failure; every 5 min | On-call; service-outage runbook |
| API 5xx and ingest failure | Railway HTTP/application logs | Any sustained 5xx or 5 ingest failures in 5 min | On-call; ingest-failure runbook |
| Ingest success, exact replay, conflict, ledger failure | Structured identity ingest log fields, aggregated without event IDs | Alert on ledger error; conflict rate above approved baseline; every 5 min | Service owner; event-identity runbook |
| Ingest latency | Railway HTTP logs or application duration field | p95 regression >20% over approved baseline; every 5 min | Service owner |
| Database connection failure | Application error log | Any occurrence | Database owner |
| Migration failure | Migration operator command result plus deployment log | Any occurrence | Migration operator |
| Restart count | Railway deployment/service status | More than one unplanned restart in 15 min | Railway operator |

No alert destination, scheduled collector, log filter, dashboard, or delivery test was provisioned. A design or SQL query is intentionally not counted as monitoring evidence.

## 7. Rollback and recovery evidence

### Result: not exercised

No Railway deployment or variable was changed by this workstream. The platform is now healthy, but testing feature disablement, service restart, legacy ingestion, dashboard parity, or deployment rollback would still be an unapproved production change. The prior deployment history reports older deployments `REMOVED`; this is not proof that a rollback can restore the old runtime.

Database data volume persists, but backup/PITR and restore evidence is unknown. No restore test may be claimed.

The approved rollback sequence, once the baseline is restored and ownership is assigned, is:

1. Set `EVENT_IDENTITY_ENABLED=false` and remove the internal workspace from the allowlist.
2. Deploy/restart the previously approved API artifact; do not drop identity columns, ledger rows, or canonical cost rows.
3. Verify no-ID ingestion and PostgreSQL dashboard/export totals.
4. Reconcile already accepted identity-bearing canonical rows; retain additive data.
5. If database recovery is required, use the database owner's documented Railway restore/PITR process on an isolated target first, record RPO/RTO, and obtain explicit recovery approval before any production cutover.

## 8. Bounded canary procedure (not authorised to run)

Preconditions: a healthy baseline, active API and PostgreSQL deployments, assigned owners, backup/restore evidence, representative-scale migration pass, zero unresolved duplicate groups, deployed monitoring with successful alert delivery, and a workspace-allowlist implementation.

1. Deploy the approved event-identity build with `STREAMING_ENABLED=false` and `EVENT_IDENTITY_ENABLED=false`.
2. Run the versioned PostgreSQL migration; validate schema history, no historical cost changes, and dashboard/export parity.
3. Configure exactly one internal workspace in the non-secret allowlist. The current code does not yet provide this control, so stop here until it exists and is tested.
4. Enable identity for that workspace only; retain one Railway API replica and make no HA or rolling-deployment claim.
5. Send a normal identity-bearing event, exact replay, conflicting replay, no-ID event, concurrent same-ID events, and the same ID from two test workspaces where safe.
6. Restart the application; repeat replay and no-ID tests. Confirm canonical count/cost parity, dashboard/export parity, health, and alert delivery.
7. Disable identity and remove the workspace from the allowlist; confirm legacy ingestion remains operational and additive data remains.
8. Re-enable only if every promotion gate is green: zero duplicate canonical cost, zero unexplained financial delta/cross-workspace collision, no material latency regression, delivered alerts, proven rollback, and assigned owners.

## Risks and unresolved dependencies

1. **Recovery provenance:** service health is restored after a Railway limit change, but the exact cause, incident record, and recovery owner remain unrecorded.
2. **No workspace-scoped allowlist:** a global feature flag cannot provide the requested one-workspace canary boundary.
3. **No deployment-time migration control:** the migration runner is not invoked by GitHub Actions or Railway pre-deploy configuration.
4. **No representative PostgreSQL evidence:** migration safety, lock impact, data distribution, duplicate preflight, and latency remain unmeasured.
5. **No monitoring or alert delivery:** the outage has no evidenced automated detection/escalation.
6. **No backup/PITR or rollback proof:** persistent volume existence is not a recovery guarantee.
7. **No accountable owners / approval gate:** GitHub production environment and `main` have no evidenced protection controls.
8. **Exact deployed code cannot be proven:** Railway deployment metadata lacks source SHA.

## Files changed in this workstream

* `docs/RAILWAY_EVENT_IDENTITY_CANARY_READINESS.md` (this evidence record only)

**NOT READY FOR RAILWAY EVENT-IDENTITY CANARY**
