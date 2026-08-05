-- Read-only historical duplicate export.  Do not remediate from this query.
WITH identified AS (
    SELECT
        workspace_id, source_event_id, id, ts, provider, model, cost_usd,
        md5(concat_ws('|', ts::text, provider, model, input_tokens::text,
            output_tokens::text, cost_usd::text, duration_ms::text,
            status_code::text, coalesce(tags::text, '{}'))) AS payload_fingerprint
    FROM request_records
    WHERE source_event_id IS NOT NULL
), grouped AS (
    SELECT workspace_id, source_event_id,
        count(*) AS duplicate_count, min(ts) AS first_timestamp,
        max(ts) AS last_timestamp, array_agg(DISTINCT provider) AS providers,
        array_agg(DISTINCT model) AS models, array_agg(id ORDER BY id) AS request_ids,
        sum(cost_usd) AS duplicate_cost_usd,
        count(DISTINCT payload_fingerprint) AS payload_versions
    FROM identified
    GROUP BY workspace_id, source_event_id
    HAVING count(*) > 1
)
SELECT workspace_id, source_event_id, duplicate_count, first_timestamp, last_timestamp,
    providers, models, request_ids, duplicate_cost_usd,
    CASE WHEN payload_versions = 1 THEN 'exact historical retry'
         WHEN payload_versions > 1 THEN 'conflicting payload'
         ELSE 'incomplete evidence' END AS classification,
    CASE WHEN payload_versions = 1 THEN 'hold; reconcile against provider source before approved correction'
         WHEN payload_versions > 1 THEN 'manual source reconciliation required; never auto-merge'
         ELSE 'retain and investigate' END AS recommended_remediation_state
FROM grouped
ORDER BY duplicate_cost_usd DESC, first_timestamp;
