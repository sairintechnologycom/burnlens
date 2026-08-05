-- Replace :workspace_id, :start_ts and :end_ts.  Run against the same UTC window.
-- The ClickHouse CTE intentionally preserves append-only no-ID legacy rows.
WITH pg AS (
    SELECT workspace_id, provider, model, date_trunc('hour', ts) AS hour,
        CASE WHEN source_event_id IS NULL THEN 'legacy' ELSE 'identity' END AS identity_kind,
        count(*) AS pg_count, sum(cost_usd) AS pg_cost,
        min(ts) AS oldest_event, max(ts) AS newest_event
    FROM request_records
    WHERE workspace_id = :workspace_id AND ts >= :start_ts AND ts < :end_ts
    GROUP BY 1,2,3,4,5
)
SELECT * FROM pg ORDER BY hour, provider, model, identity_kind;

-- ClickHouse side (same parameters; run in ClickHouse client):
-- SELECT workspace_id, provider, model, toStartOfHour(ts) AS hour,
--   if(source_event_id = '', 'legacy', 'identity') AS identity_kind,
--   count() AS clickhouse_logical_count, sum(cost_usd) AS clickhouse_cost,
--   min(ts) AS oldest_event, max(ts) AS newest_event
-- FROM (
--   SELECT argMax(ts, received_at) AS ts, argMax(provider, received_at) AS provider,
--     argMax(model, received_at) AS model, argMax(cost_usd, received_at) AS cost_usd,
--     argMax(source_event_id, received_at) AS source_event_id, workspace_id
--   FROM request_records_raw
--   WHERE workspace_id = {workspace_id:UUID} AND ts >= {start:DateTime} AND ts < {end:DateTime}
--   GROUP BY workspace_id, if(source_event_id = '', concat('__legacy__', toString(id)), source_event_id)
-- ) GROUP BY 1,2,3,4,5 ORDER BY hour, provider, model, identity_kind;
