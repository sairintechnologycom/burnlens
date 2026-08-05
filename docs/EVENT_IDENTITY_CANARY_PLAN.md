# Event-identity canary plan

This is a deployment gate, not authorization for Workload, Run, or runtime-attribution work. The feature remains off unless both Postgres migrations and the additive ClickHouse identity-topic migration are complete.

## Scope and ownership

- Scope: one internal workspace, one non-production environment, and one provider path.
- Rollback owner: the on-call cloud owner who can change the workspace allowlist / `EVENT_IDENTITY_ENABLED` deployment variable.
- Escalation: cloud owner, database owner, then finance owner for any non-zero reconciliation delta.

## Preconditions

1. Obtain read/write access to the actual streaming deployment, RDS/managed PostgreSQL clone, Redpanda, ClickHouse, and the existing monitoring account.
2. Confirm the deployed image includes `aiokafka`, ClickHouse credentials, `KAFKA_IDENTITY_TOPIC`, and migrations `20260804_01` / `20260804_02`.
3. Run `scripts/event_identity_duplicate_assessment.sql` read-only. Any historical duplicate blocks the partial unique index until an approved manual remediation decision.
4. Capture table/index sizes, active writers, p50/p95/p99 ingest latency, and dashboard query latency before migration.
5. Provision actual alarms from the durable outbox/reconciliation metrics in `CLOUD_EVENT_IDENTITY_OPERATIONS.md`; a document or log query alone is insufficient.

## Controlled sequence

1. Deploy new code with `EVENT_IDENTITY_ENABLED=false`.
2. Apply `python -m burnlens_cloud.migrations.runner postgres`, then the ClickHouse target. Re-run both as the repeatability check.
3. Keep an old application instance and a new disabled instance serving no-ID ingestion; compare contract responses and dashboard totals.
4. Enable only the internal workspace/environment allowlist.
5. Send: one known identity event, exact replay, same-ID conflicting payload, and no-ID legacy payload.
6. Verify canonical PostgreSQL cost/count and ClickHouse logical cost/count per workspace/provider/model/hour using `scripts/event_identity_reconciliation.sql`.
7. Inject broker and ClickHouse failures, recover, drain the outbox, and re-run exact reconciliation.
8. Disable the workspace allowlist. Confirm no-ID ingestion continues and pending outbox rows persist. Re-enable and drain.

## Promotion criteria

- Zero unexplained PostgreSQL/ClickHouse count or cost delta.
- Zero retry-created canonical PostgreSQL duplicates.
- Zero cross-workspace source-ID collision.
- No unresolved dead letters, poison-message blockage, or outbox growth.
- Ingest and dashboard p95 stay within the agreed pre-canary error budget.
- Alarm delivery, ownership, disablement, and restart recovery are exercised successfully.

## Required evidence

Record infrastructure versions, dataset size/distribution, concurrent-writer and traffic assumptions, exact commands, migration/index timings, lock/transaction waits, resource metrics, Redpanda/ClickHouse lag, pass/fail/skip counts, reconciliation rows, alarm notifications, and deployed image/task identifiers. Do not call the canary ready without this evidence.
