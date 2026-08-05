# Cloud event identity rollout

## Contract

When `EVENT_IDENTITY_ENABLED=true`, `event_id` is a workspace-scoped source
identity.  `(workspace_id, event_id)` is immutable and maps to exactly one
canonical `request_records` row.  The cloud never recalculates `cost_usd`.

| Input | Result |
| --- | --- |
| No `event_id` | Legacy ingest behavior; no new deduplication claim. |
| New `event_id` | Insert one canonical cost record and identity row. |
| Same ID, identical financial payload | `200`, `accepted=0`, `rejected=0`; no new cost or quota increment. |
| Same ID, conflicting payload | `200`, `accepted=0`, `rejected=1`; original cost is retained. |
| Same ID, different workspace | Both are valid independent events. |

The payload fingerprint covers timestamps, provider/model, usage, canonical
cost, status, tags, cache fields, trace ID, and provider request ID.  A timeout
retry is safe after the first transaction commits.  Out-of-order distinct events
remain distinct; no timestamp-based deduplication is attempted.

## Deployment order

1. Leave `EVENT_IDENTITY_ENABLED=false`.
2. Apply Postgres migration:

   ```sh
   DATABASE_URL=postgresql://... python3 -m burnlens_cloud.migrations.runner postgres
   ```

3. If `STREAMING_ENABLED=true`, apply the ClickHouse migration during a normal
   stream-consumer maintenance window:

   ```sh
   DATABASE_URL=postgresql://... python3 -m burnlens_cloud.migrations.runner clickhouse
   ```

4. Inspect duplicates before enabling. The migration refuses to create the
   unique index if source identities already have duplicates; it never deletes
   or rewrites historical cost rows.

   ```sql
   SELECT workspace_id, source_event_id, COUNT(*)
   FROM request_records
   WHERE source_event_id IS NOT NULL
   GROUP BY 1, 2
   HAVING COUNT(*) > 1;
   ```

5. Deploy application code, then enable `EVENT_IDENTITY_ENABLED=true` for the
   API process. Roll back by setting it false; all additive tables and columns
   remain for later retry.

## Streaming failure handling

Event-bearing records commit first to Postgres and `stream_ingest_outbox` in one
transaction. A broker failure leaves the outbox pending and returns an error;
the next same-event retry or identity-enabled API startup drains that pending
entry without reinserting cost.
If a process dies after broker acknowledgement but before marking delivered,
broker delivery can repeat. The ClickHouse migration preserves `source_event_id`
for downstream deduplication; Postgres remains the canonical financial record.

Existing event-less stream messages preserve their established behavior.
