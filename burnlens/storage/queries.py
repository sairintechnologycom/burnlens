"""Aggregation queries for the BurnLens dashboard and CLI."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from burnlens.storage.models import AggregatedUsage, AiAsset, DiscoveryEvent, ProviderSignature


# ---------------------------------------------------------------------------
# Private deserialization helpers
# ---------------------------------------------------------------------------


def _row_to_asset(row: aiosqlite.Row) -> AiAsset:
    """Deserialize a DB row into an AiAsset dataclass."""
    return AiAsset(
        id=row["id"],
        provider=row["provider"],
        model_name=row["model_name"],
        endpoint_url=row["endpoint_url"],
        api_key_hash=row["api_key_hash"],
        owner_team=row["owner_team"],
        project=row["project"],
        status=row["status"],
        risk_tier=row["risk_tier"],
        first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
        last_active_at=datetime.fromisoformat(row["last_active_at"]),
        monthly_spend_usd=float(row["monthly_spend_usd"] or 0.0),
        monthly_requests=int(row["monthly_requests"] or 0),
        tags=json.loads(row["tags"] or "{}"),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_event(row: aiosqlite.Row) -> DiscoveryEvent:
    """Deserialize a DB row into a DiscoveryEvent dataclass."""
    return DiscoveryEvent(
        id=row["id"],
        event_type=row["event_type"],
        asset_id=row["asset_id"],
        details=json.loads(row["details"] or "{}"),
        detected_at=datetime.fromisoformat(row["detected_at"]),
    )


# ---------------------------------------------------------------------------
# Phase 1: Query helpers for AI Asset Discovery tables
# ---------------------------------------------------------------------------


async def get_asset_by_id(db_path: str, asset_id: int) -> AiAsset | None:
    """Return an AiAsset by its primary key, or None if not found.

    Tags are deserialized from JSON to a Python dict.
    Datetime fields are parsed from ISO format strings.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM ai_assets WHERE id = ?", (asset_id,)
        )
        row = await cursor.fetchone()

    if row is None:
        return None
    return _row_to_asset(row)


async def get_assets(
    db_path: str,
    provider: str | None = None,
    status: str | None = None,
    owner_team: str | None = None,
    risk_tier: str | None = None,
    date_since: str | None = None,
    search_query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AiAsset]:
    """Return a list of AiAsset records, ordered by last_active_at DESC.

    Filters are applied only when the corresponding argument is not None.
    Supports pagination via limit and offset parameters.
    date_since filters on first_seen_at >= ? (ISO date string, e.g. '2026-01-01').
    search_query performs an OR LIKE search across model_name, provider, owner_team,
    endpoint_url, and tags (stored as JSON text).
    """
    where_clauses: list[str] = []
    params: list[Any] = []

    if provider is not None:
        where_clauses.append("provider = ?")
        params.append(provider)
    if status is not None:
        where_clauses.append("status = ?")
        params.append(status)
    if owner_team is not None:
        where_clauses.append("owner_team = ?")
        params.append(owner_team)
    if risk_tier is not None:
        where_clauses.append("risk_tier = ?")
        params.append(risk_tier)
    if date_since is not None:
        where_clauses.append("first_seen_at >= ?")
        params.append(date_since)
    if search_query is not None:
        search_pattern = f"%{search_query}%"
        where_clauses.append(
            "(model_name LIKE ? OR provider LIKE ? OR owner_team LIKE ? OR endpoint_url LIKE ? OR tags LIKE ?)"
        )
        params.extend([search_pattern] * 5)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params.extend([limit, offset])

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""
            SELECT * FROM ai_assets
            {where_sql}
            ORDER BY last_active_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        )
        rows = await cursor.fetchall()

    return [_row_to_asset(row) for row in rows]


async def get_assets_count(
    db_path: str,
    provider: str | None = None,
    status: str | None = None,
    owner_team: str | None = None,
    risk_tier: str | None = None,
    date_since: str | None = None,
    search_query: str | None = None,
) -> int:
    """Return the total count of AiAsset records matching the given filters.

    Accepts the same filter parameters as get_assets() (minus limit/offset).
    Used to power pagination total_count in API responses.
    search_query performs an OR LIKE search across model_name, provider, owner_team,
    endpoint_url, and tags (stored as JSON text).
    """
    where_clauses: list[str] = []
    params: list[Any] = []

    if provider is not None:
        where_clauses.append("provider = ?")
        params.append(provider)
    if status is not None:
        where_clauses.append("status = ?")
        params.append(status)
    if owner_team is not None:
        where_clauses.append("owner_team = ?")
        params.append(owner_team)
    if risk_tier is not None:
        where_clauses.append("risk_tier = ?")
        params.append(risk_tier)
    if date_since is not None:
        where_clauses.append("first_seen_at >= ?")
        params.append(date_since)
    if search_query is not None:
        search_pattern = f"%{search_query}%"
        where_clauses.append(
            "(model_name LIKE ? OR provider LIKE ? OR owner_team LIKE ? OR endpoint_url LIKE ? OR tags LIKE ?)"
        )
        params.extend([search_pattern] * 5)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            f"SELECT COUNT(*) FROM ai_assets {where_sql}",
            params,
        )
        row = await cursor.fetchone()

    return int(row[0]) if row else 0


async def get_asset_summary(db_path: str) -> dict[str, Any]:
    """Return aggregated counts of AI assets.

    Returns a dict with:
    - total: total asset count
    - by_provider: dict mapping provider -> count
    - by_status: dict mapping status -> count
    - by_risk_tier: dict mapping risk_tier -> count
    - new_this_week: count of assets with first_seen_at in the last 7 days
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Total count
        cursor = await db.execute("SELECT COUNT(*) FROM ai_assets")
        row = await cursor.fetchone()
        total = int(row[0]) if row else 0

        # By provider
        cursor = await db.execute(
            "SELECT provider, COUNT(*) AS cnt FROM ai_assets GROUP BY provider"
        )
        by_provider = {r["provider"]: r["cnt"] for r in await cursor.fetchall()}

        # By status
        cursor = await db.execute(
            "SELECT status, COUNT(*) AS cnt FROM ai_assets GROUP BY status"
        )
        by_status = {r["status"]: r["cnt"] for r in await cursor.fetchall()}

        # By risk_tier
        cursor = await db.execute(
            "SELECT risk_tier, COUNT(*) AS cnt FROM ai_assets GROUP BY risk_tier"
        )
        by_risk_tier = {r["risk_tier"]: r["cnt"] for r in await cursor.fetchall()}

        # New this week
        cursor = await db.execute(
            "SELECT COUNT(*) FROM ai_assets WHERE first_seen_at >= date('now', '-7 days')"
        )
        row = await cursor.fetchone()
        new_this_week = int(row[0]) if row else 0

    return {
        "total": total,
        "by_provider": by_provider,
        "by_status": by_status,
        "by_risk_tier": by_risk_tier,
        "new_this_week": new_this_week,
    }


async def update_asset_fields(
    db_path: str,
    asset_id: int,
    owner_team: str | None = None,
    risk_tier: str | None = None,
    tags: dict[str, Any] | None = None,
    status: str | None = None,
) -> "AiAsset":
    """Update specified fields of an AiAsset atomically.

    Only non-None arguments are included in the UPDATE statement.
    updated_at is always set to now. If status changes, a discovery_event is inserted
    in the same transaction.

    Returns the updated AiAsset after commit.

    Raises:
        ValueError: If no asset with asset_id exists.
    """
    set_clauses: list[str] = []
    params: list[Any] = []

    now = datetime.now(timezone.utc).isoformat()

    if owner_team is not None:
        set_clauses.append("owner_team = ?")
        params.append(owner_team)
    if risk_tier is not None:
        set_clauses.append("risk_tier = ?")
        params.append(risk_tier)
    if tags is not None:
        set_clauses.append("tags = ?")
        params.append(json.dumps(tags))
    if status is not None:
        set_clauses.append("status = ?")
        params.append(status)

    # Always update updated_at
    set_clauses.append("updated_at = ?")
    params.append(now)
    params.append(asset_id)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Verify asset exists and read current status (for event logging)
        cursor = await db.execute(
            "SELECT status FROM ai_assets WHERE id = ?", (asset_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"Asset {asset_id} not found")

        old_status = row["status"]

        # Apply the SET clauses
        set_sql = ", ".join(set_clauses)
        await db.execute(
            f"UPDATE ai_assets SET {set_sql} WHERE id = ?",
            params,
        )

        # Log status change event if status was modified
        if status is not None and status != old_status:
            await db.execute(
                """
                INSERT INTO discovery_events (event_type, asset_id, details, detected_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "model_changed",
                    asset_id,
                    json.dumps({
                        "old_status": old_status,
                        "new_status": status,
                        "change": "status_update",
                    }),
                    now,
                ),
            )

        await db.commit()

    # Return the refreshed asset
    return await get_asset_by_id(db_path, asset_id)  # type: ignore[return-value]


async def get_discovery_events(
    db_path: str,
    asset_id: int | None = None,
    event_type: str | None = None,
    date_since: str | None = None,
    date_until: str | None = None,
    limit: int = 50,
) -> list[DiscoveryEvent]:
    """Return a list of DiscoveryEvent records, ordered by detected_at DESC.

    Filters are applied only when the corresponding argument is not None.
    date_since filters on detected_at >= ? (ISO date string, e.g. '2026-01-01').
    date_until filters on detected_at <= ? (ISO date string, e.g. '2026-12-31').
    """
    where_clauses: list[str] = []
    params: list[Any] = []

    if asset_id is not None:
        where_clauses.append("asset_id = ?")
        params.append(asset_id)
    if event_type is not None:
        where_clauses.append("event_type = ?")
        params.append(event_type)
    if date_since is not None:
        where_clauses.append("detected_at >= ?")
        params.append(date_since)
    if date_until is not None:
        where_clauses.append("detected_at <= ?")
        params.append(date_until)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params.append(limit)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""
            SELECT * FROM discovery_events
            {where_sql}
            ORDER BY detected_at DESC
            LIMIT ?
            """,
            params,
        )
        rows = await cursor.fetchall()

    return [_row_to_event(row) for row in rows]


async def get_provider_signatures(
    db_path: str,
    provider: str | None = None,
) -> list[ProviderSignature]:
    """Return a list of ProviderSignature records.

    Optionally filter by provider name. header_signature is deserialized from JSON.
    """
    where_sql = "WHERE provider = ?" if provider is not None else ""
    params: tuple[Any, ...] = (provider,) if provider is not None else ()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT * FROM provider_signatures {where_sql}",
            params,
        )
        rows = await cursor.fetchall()

    return [
        ProviderSignature(
            id=row["id"],
            provider=row["provider"],
            endpoint_pattern=row["endpoint_pattern"],
            header_signature=json.loads(row["header_signature"] or "{}"),
            model_field_path=row["model_field_path"],
        )
        for row in rows
    ]


async def get_usage_by_model(
    db_path: str,
    since: str | None = None,
) -> list[AggregatedUsage]:
    """Return per-model cost/usage aggregated over all time (or since ISO timestamp)."""
    where = "WHERE timestamp >= ?" if since else ""
    params: tuple[Any, ...] = (since,) if since else ()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""
            SELECT
                model, provider,
                COUNT(*) AS request_count,
                SUM(input_tokens)  AS total_input_tokens,
                SUM(output_tokens) AS total_output_tokens,
                SUM(cost_usd)      AS total_cost_usd
            FROM requests
            {where}
            GROUP BY model, provider
            ORDER BY total_cost_usd DESC
            """,
            params,
        )
        rows = await cursor.fetchall()

    return [
        AggregatedUsage(
            model=row["model"],
            provider=row["provider"],
            request_count=row["request_count"],
            total_input_tokens=row["total_input_tokens"],
            total_output_tokens=row["total_output_tokens"],
            total_cost_usd=row["total_cost_usd"],
        )
        for row in rows
    ]


async def get_recent_requests(
    db_path: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return the most recent N requests as plain dicts."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM requests
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()

    result = []
    for row in rows:
        d = dict(row)
        d["tags"] = json.loads(d.get("tags") or "{}")
        result.append(d)
    return result


async def get_total_cost(db_path: str, since: str | None = None) -> float:
    """Return total cost in USD (optionally since an ISO timestamp)."""
    where = "WHERE timestamp >= ?" if since else ""
    params: tuple[Any, ...] = (since,) if since else ()

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            f"SELECT COALESCE(SUM(cost_usd), 0.0) FROM requests {where}",
            params,
        )
        row = await cursor.fetchone()

    return float(row[0]) if row else 0.0


async def get_usage_by_tag(
    db_path: str,
    tag_key: str = "feature",
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Return per-tag cost/usage for a given tag key."""
    where = "WHERE timestamp >= ?" if since else ""
    params: tuple[Any, ...] = (since,) if since else ()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT tags, cost_usd, input_tokens, output_tokens FROM requests {where}",
            params,
        )
        rows = await cursor.fetchall()

    # Aggregate in Python since SQLite JSON support may be limited
    totals: dict[str, dict[str, Any]] = {}
    for row in rows:
        tags = json.loads(row["tags"] or "{}")
        tag_val = tags.get(tag_key, "(untagged)")
        if tag_val not in totals:
            totals[tag_val] = {
                "tag": tag_val,
                "request_count": 0,
                "total_cost_usd": 0.0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
            }
        totals[tag_val]["request_count"] += 1
        totals[tag_val]["total_cost_usd"] += row["cost_usd"] or 0.0
        totals[tag_val]["total_input_tokens"] += row["input_tokens"] or 0
        totals[tag_val]["total_output_tokens"] += row["output_tokens"] or 0

    return sorted(totals.values(), key=lambda x: x["total_cost_usd"], reverse=True)


async def get_total_request_count(db_path: str, since: str | None = None) -> int:
    """Return total number of requests."""
    where = "WHERE timestamp >= ?" if since else ""
    params: tuple[Any, ...] = (since,) if since else ()

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            f"SELECT COUNT(*) FROM requests {where}",
            params,
        )
        row = await cursor.fetchone()

    return int(row[0]) if row else 0


async def get_daily_cost(
    db_path: str,
    days: int = 7,
) -> list[dict[str, Any]]:
    """Return cost per day for the last N days."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                DATE(timestamp) AS day,
                COUNT(*) AS request_count,
                SUM(cost_usd) AS total_cost_usd
            FROM requests
            WHERE timestamp >= DATE('now', ?)
            GROUP BY DATE(timestamp)
            ORDER BY day ASC
            """,
            (f"-{days} days",),
        )
        rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def get_new_shadow_events_since(
    db_path: str,
    since_iso: str,
) -> list[DiscoveryEvent]:
    """Return new_asset_detected DiscoveryEvents detected at or after since_iso.

    Args:
        db_path:  Path to the SQLite database.
        since_iso: ISO datetime string (e.g. '2026-04-01T00:00:00'). Only events
                   detected at or after this timestamp are returned.

    Returns:
        List of DiscoveryEvent with event_type='new_asset_detected', ordered by
        detected_at DESC.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM discovery_events
            WHERE event_type = 'new_asset_detected' AND detected_at >= ?
            ORDER BY detected_at DESC
            """,
            (since_iso,),
        )
        rows = await cursor.fetchall()
    return [_row_to_event(row) for row in rows]


async def get_new_provider_events_since(
    db_path: str,
    since_iso: str,
) -> list[DiscoveryEvent]:
    """Return provider_changed DiscoveryEvents detected at or after since_iso.

    Args:
        db_path:   Path to the SQLite database.
        since_iso: ISO datetime string. Only events detected at or after this
                   timestamp are returned.

    Returns:
        List of DiscoveryEvent with event_type='provider_changed', ordered by
        detected_at DESC.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM discovery_events
            WHERE event_type = 'provider_changed' AND detected_at >= ?
            ORDER BY detected_at DESC
            """,
            (since_iso,),
        )
        rows = await cursor.fetchall()
    return [_row_to_event(row) for row in rows]


async def get_model_change_events_since(
    db_path: str,
    since_iso: str,
) -> list[DiscoveryEvent]:
    """Return model_changed DiscoveryEvents detected at or after since_iso.

    Args:
        db_path:   Path to the SQLite database.
        since_iso: ISO datetime string. Only events detected at or after this
                   timestamp are returned.

    Returns:
        List of DiscoveryEvent with event_type='model_changed', ordered by
        detected_at DESC.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM discovery_events
            WHERE event_type = 'model_changed' AND detected_at >= ?
            ORDER BY detected_at DESC
            """,
            (since_iso,),
        )
        rows = await cursor.fetchall()
    return [_row_to_event(row) for row in rows]


async def get_inactive_assets(
    db_path: str,
    inactive_days: int = 30,
) -> list[AiAsset]:
    """Return AI assets that have not been active for at least inactive_days.

    Excludes assets with status 'deprecated' or 'inactive' (already known to be
    dormant — they do not need new alerts).

    Args:
        db_path:       Path to the SQLite database.
        inactive_days: Number of days of inactivity required. Defaults to 30.

    Returns:
        List of AiAsset ordered by last_active_at ASC (oldest first).
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""
            SELECT * FROM ai_assets
            WHERE last_active_at < date('now', '-{inactive_days} days')
              AND status NOT IN ('deprecated', 'inactive')
            ORDER BY last_active_at ASC
            """,
        )
        rows = await cursor.fetchall()
    return [_row_to_asset(row) for row in rows]


async def get_asset_spend_history(
    db_path: str,
    asset_id: int,
    days: int = 30,
) -> float:
    """Return the total spend (USD) for an asset's model+provider over the last N days.

    Fetches the asset's model_name and provider, then sums cost_usd from the
    requests table where model and provider match within the given period.

    Args:
        db_path:  Path to the SQLite database.
        asset_id: Primary key of the AiAsset to look up.
        days:     Number of days to include in the spend window. Defaults to 30.

    Returns:
        Total spend in USD as a float. Returns 0.0 if the asset is not found or
        has no matching requests within the period.
    """
    asset = await get_asset_by_id(db_path, asset_id)
    if asset is None:
        return 0.0

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            f"""
            SELECT COALESCE(SUM(cost_usd), 0.0)
            FROM requests
            WHERE model = ? AND provider = ?
              AND timestamp >= date('now', '-{days} days')
            """,
            (asset.model_name, asset.provider),
        )
        row = await cursor.fetchone()

    return float(row[0]) if row else 0.0


async def get_requests_for_analysis(
    db_path: str,
    since: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Return recent requests with all fields needed for waste analysis."""
    where = "WHERE timestamp >= ?" if since else ""
    params: tuple[Any, ...] = (since,) if since else ()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""
            SELECT
                id, timestamp, provider, model,
                input_tokens, output_tokens, cost_usd,
                duration_ms, tags, system_prompt_hash
            FROM requests
            {where}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (*params, limit),
        )
        rows = await cursor.fetchall()

    result = []
    for row in rows:
        d = dict(row)
        d["tags"] = json.loads(d.get("tags") or "{}")
        result.append(d)
    return result
