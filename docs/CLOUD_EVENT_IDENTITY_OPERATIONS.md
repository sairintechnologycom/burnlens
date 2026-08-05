# Event identity cloud operations

This runbook applies only after migrations `20260804_01` and `20260804_02` have completed. `EVENT_IDENTITY_ENABLED` remains false until the controlled workspace is selected. The canonical financial record is PostgreSQL `request_records.cost_usd`; neither the outbox nor ClickHouse recalculates it.

## Operator sequence

1. Take the standard PostgreSQL backup and record `pg_stat_user_tables` / `pg_total_relation_size('request_records')`.
2. Run [duplicate assessment](/Users/bhushan/Documents/Projects/burnlens/scripts/event_identity_duplicate_assessment.sql) read-only. Any result blocks migration. Export it; do not delete or merge rows.
3. Deploy code with `EVENT_IDENTITY_ENABLED=false`, then run `python -m burnlens_cloud.migrations.runner postgres`; when streaming is enabled, run the ClickHouse target too.
4. Validate `schema_migrations`, the nullable columns, the two outbox indexes, and legacy dashboard totals. Re-running both commands must be a no-op.
5. Enable the feature for one internal workspace only through the deployment environment/allowlist. Send a known event, exact replay, conflict, and a no-ID legacy record. Run [reconciliation](/Users/bhushan/Documents/Projects/burnlens/scripts/event_identity_reconciliation.sql) by hour.
6. Disable by setting `EVENT_IDENTITY_ENABLED=false` and redeploying. Do not drop the columns, ledger, or outbox. Re-enable only after reconciliation is exact.

## Operational metrics and alerts

The existing topology has CloudWatch/RDS logs and no checked-in Prometheus/Grafana stack. Collect these PostgreSQL queries into the existing deployment monitor; they are durable source metrics, not application estimates.

```sql
SELECT count(*) AS pending_outbox_count,
       EXTRACT(EPOCH FROM now() - min(created_at)) AS oldest_pending_seconds,
       sum(attempts) AS publish_attempt_count,
       sum(failed_attempts) AS publish_failure_count,
       count(*) FILTER (WHERE dead_lettered_at IS NOT NULL) AS dead_letter_count,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM delivered_at-created_at)) AS delivery_p50_s,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM delivered_at-created_at)) AS delivery_p95_s,
       percentile_cont(0.99) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM delivered_at-created_at)) AS delivery_p99_s
FROM stream_ingest_outbox;
SELECT coalesce(sum(conflict_count), 0) AS conflicting_replay_count
FROM ingest_event_identities;
```

Alert when oldest pending is over 300 seconds, pending depth rises for three collection periods, any dead letter exists, failed publishes cross the local baseline, reconciliation has non-zero count/cost delta, or conflict rejections exceed the deployment baseline. Record `source_event_id` only in restricted operational logs.

## Incident response

- **Broker outage / growing outbox:** leave identity enabled; canonical PostgreSQL writes are safe. Restore Redpanda, then restart one API instance or invoke the normal startup drain. Inspect pending count and parity.
- **ClickHouse outage:** do not retry the client ingest solely for analytics. Recover ClickHouse, then replay pending outbox items. Compare exact cost/count by workspace/hour before closing.
- **Stuck / dead-lettered outbox:** inspect `last_error`, repair the dependency, explicitly clear `dead_lettered_at` for the approved rows, then drain. Do not create new financial records.
- **Conflicting replay:** retain original record, correlate source payload using the ID and payload hash, and never overwrite cost.
- **Migration failure:** feature remains disabled; correct the blocking preflight/index condition and rerun. Additive data is retained.
- **Tenant-level disablement:** exclude the workspace from the deployment allowlist or set the global feature false; legacy clients continue on the old path.
