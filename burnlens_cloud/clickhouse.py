import logging
import asyncio
from typing import Any, Optional
import clickhouse_connect
from clickhouse_connect.driver.client import Client

from .config import settings

logger = logging.getLogger(__name__)

_client: Optional[Client] = None
_client_lock = asyncio.Lock()


def get_clickhouse_client() -> Client:
    """Get or create synchronous ClickHouse client."""
    global _client
    if _client is None:
        try:
            _client = clickhouse_connect.get_client(
                host=settings.clickhouse_host,
                port=settings.clickhouse_port,
                username=settings.clickhouse_user,
                password=settings.clickhouse_password,
                database=settings.clickhouse_database,
                secure=settings.clickhouse_secure,
                connect_timeout=10,
            )
            logger.info("ClickHouse client connected successfully to %s:%d", settings.clickhouse_host, settings.clickhouse_port)
        except Exception as e:
            logger.error("Failed to connect to ClickHouse: %s", e)
            raise
    return _client


async def close_clickhouse() -> None:
    """Close ClickHouse client connection."""
    global _client
    async with _client_lock:
        if _client is not None:
            try:
                _client.close()
                logger.info("ClickHouse client connection closed.")
            except Exception as e:
                logger.warning("Error closing ClickHouse client: %s", e)
            finally:
                _client = None


async def init_clickhouse() -> None:
    """Initialize ClickHouse database and run DDL migrations (tables, views, rollups)."""
    # Run in a thread since clickhouse-connect client DDL methods are blocking
    try:
        await asyncio.to_thread(_init_clickhouse_sync)
    except Exception as e:
        logger.error("ClickHouse schema initialization failed: %s", e)
        # Fail open or raise depending on environment/setup
        if settings.environment == "production":
            raise


def _init_clickhouse_sync() -> None:
    """Sync execution of ClickHouse DDL queries."""
    # First connect to default database to create target database if needed
    try:
        temp_client = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            secure=settings.clickhouse_secure,
            connect_timeout=10,
        )
        temp_client.command(f"CREATE DATABASE IF NOT EXISTS {settings.clickhouse_database}")
        temp_client.close()
    except Exception as e:
        logger.warning("Database pre-creation check failed (continuing directly): %s", e)

    client = get_clickhouse_client()

    # 1. Raw request records table
    client.command("""
        CREATE TABLE IF NOT EXISTS request_records_raw (
            id UUID,
            workspace_id UUID,
            ts DateTime64(3, 'UTC'),
            provider LowCardinality(String),
            model LowCardinality(String),
            input_tokens UInt32,
            output_tokens UInt32,
            reasoning_tokens UInt32,
            cache_read_tokens UInt32,
            cache_write_tokens UInt32,
            cost_usd Decimal(18, 8),
            duration_ms UInt32,
            status_code UInt16,
            tag_feature String,
            tag_team String,
            tag_customer String,
            system_prompt_hash FixedString(64),
            received_at DateTime('UTC')
        ) ENGINE = MergeTree()
        PARTITION BY toYYYYMM(ts)
        ORDER BY (workspace_id, ts, provider, model);
    """)

    # 2. Kafka stream queue table
    # Resolves Redpanda/Kafka broker hostname inside Docker Compose network
    client.command(f"""
        CREATE TABLE IF NOT EXISTS request_records_queue (
            workspace_id UUID,
            ts String,
            provider String,
            model String,
            input_tokens UInt32,
            output_tokens UInt32,
            reasoning_tokens UInt32,
            cache_read_tokens UInt32,
            cache_write_tokens UInt32,
            cost_usd Decimal(18, 8),
            duration_ms UInt32,
            status_code UInt16,
            tag_feature String,
            tag_team String,
            tag_customer String,
            system_prompt_hash String
        ) ENGINE = Kafka
        SETTINGS kafka_broker_list = '{settings.kafka_bootstrap_servers}',
                 kafka_topic_list = '{settings.kafka_topic}',
                 kafka_group_name = 'clickhouse-consumer',
                 kafka_format = 'JSONEachRow',
                 kafka_num_consumers = 1;
    """)

    # 3. Consumer Materialized View (pipe queue to raw table)
    client.command("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_request_records_consumer TO request_records_raw AS
        SELECT
            generateUUIDv4() AS id,
            workspace_id,
            parseDateTime64BestEffortOrZero(ts) AS ts,
            provider,
            model,
            input_tokens,
            output_tokens,
            reasoning_tokens,
            cache_read_tokens,
            cache_write_tokens,
            cost_usd,
            duration_ms,
            status_code,
            tag_feature,
            tag_team,
            tag_customer,
            system_prompt_hash,
            now() AS received_at
        FROM request_records_queue;
    """)

    # 4. Daily rollup aggregation table
    client.command("""
        CREATE TABLE IF NOT EXISTS daily_spend_rollup (
            workspace_id UUID,
            day Date,
            provider LowCardinality(String),
            model LowCardinality(String),
            tag_feature String,
            tag_team String,
            tag_customer String,
            request_count SimpleAggregateFunction(sum, UInt64),
            input_tokens SimpleAggregateFunction(sum, UInt64),
            output_tokens SimpleAggregateFunction(sum, UInt64),
            reasoning_tokens SimpleAggregateFunction(sum, UInt64),
            cache_read_tokens SimpleAggregateFunction(sum, UInt64),
            cache_write_tokens SimpleAggregateFunction(sum, UInt64),
            cost_usd SimpleAggregateFunction(sum, Decimal(18, 8)),
            duration_ms SimpleAggregateFunction(avg, Float64),
            status_code_ok_count SimpleAggregateFunction(sum, UInt64)
        ) ENGINE = SummingMergeTree()
        PARTITION BY toYYYYMM(day)
        ORDER BY (workspace_id, day, provider, model, tag_feature, tag_team, tag_customer);
    """)

    # 5. Rollup Materialized View
    client.command("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_spend_rollup TO daily_spend_rollup AS
        SELECT
            workspace_id,
            toDate(ts) AS day,
            provider,
            model,
            tag_feature,
            tag_team,
            tag_customer,
            count() AS request_count,
            sum(input_tokens) AS input_tokens,
            sum(output_tokens) AS output_tokens,
            sum(reasoning_tokens) AS reasoning_tokens,
            sum(cache_read_tokens) AS cache_read_tokens,
            sum(cache_write_tokens) AS cache_write_tokens,
            sum(cost_usd) AS cost_usd,
            avg(duration_ms) AS duration_ms,
            sum(status_code = 200 OR status_code = 201) AS status_code_ok_count
        FROM request_records_raw
        GROUP BY workspace_id, day, provider, model, tag_feature, tag_team, tag_customer;
    """)

    logger.info("ClickHouse tables and materialized views initialized.")


async def get_spend_summary(workspace_id: str, start_date: str, end_date: str) -> dict[str, Any]:
    """Query workspace level total cost, requests, and token statistics from rollup table."""
    def _query():
        client = get_clickhouse_client()
        query = """
            SELECT 
                sum(request_count) as total_requests,
                sum(input_tokens) as total_input_tokens,
                sum(output_tokens) as total_output_tokens,
                sum(cost_usd) as total_cost_usd,
                avg(duration_ms) as avg_duration_ms
            FROM daily_spend_rollup
            WHERE workspace_id = {ws:UUID} AND day >= {start:Date} AND day <= {end:Date}
        """
        params = {"ws": workspace_id, "start": start_date, "end": end_date}
        result = client.query(query, params)
        if result.result_rows:
            row = result.result_rows[0]
            # clickhouse returns decimals and floats which we serialize
            return {
                "total_requests": int(row[0] or 0),
                "total_input_tokens": int(row[1] or 0),
                "total_output_tokens": int(row[2] or 0),
                "total_cost_usd": float(row[3] or 0.0),
                "avg_duration_ms": float(row[4] or 0.0)
            }
        return {
            "total_requests": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": 0.0,
            "avg_duration_ms": 0.0
        }

    return await asyncio.to_thread(_query)


async def get_spend_by_model(workspace_id: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Query spend broken down by model and provider from rollup table."""
    def _query():
        client = get_clickhouse_client()
        query = """
            SELECT 
                model,
                provider,
                sum(request_count) as request_count,
                sum(input_tokens) as total_input_tokens,
                sum(output_tokens) as total_output_tokens,
                sum(cost_usd) as total_cost_usd
            FROM daily_spend_rollup
            WHERE workspace_id = {ws:UUID} AND day >= {start:Date} AND day <= {end:Date}
            GROUP BY model, provider
            ORDER BY total_cost_usd DESC
        """
        params = {"ws": workspace_id, "start": start_date, "end": end_date}
        result = client.query(query, params)
        return [
            {
                "model": row[0],
                "provider": row[1],
                "request_count": int(row[2]),
                "total_input_tokens": int(row[3]),
                "total_output_tokens": int(row[4]),
                "total_cost_usd": float(row[5])
            }
            for row in result.result_rows
        ]

    return await asyncio.to_thread(_query)


async def get_spend_by_tag(workspace_id: str, tag_type: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Query spend broken down by a specific tag (feature, team, customer) from rollup table."""
    if tag_type not in ("feature", "team", "customer"):
        raise ValueError(f"Invalid tag type: {tag_type}")

    tag_column = f"tag_{tag_type}"

    def _query():
        client = get_clickhouse_client()
        # Note: formatting column name into query is safe here as we validated tag_type above
        query = f"""
            SELECT 
                {tag_column} as tag_value,
                sum(request_count) as request_count,
                sum(input_tokens) as total_input_tokens,
                sum(output_tokens) as total_output_tokens,
                sum(cost_usd) as total_cost_usd
            FROM daily_spend_rollup
            WHERE workspace_id = {{ws:UUID}} AND day >= {{start:Date}} AND day <= {{end:Date}} AND tag_value != ''
            GROUP BY tag_value
            ORDER BY total_cost_usd DESC
        """
        params = {"ws": workspace_id, "start": start_date, "end": end_date}
        result = client.query(query, params)
        return [
            {
                "tag": row[0],
                "request_count": int(row[1]),
                "total_input_tokens": int(row[2]),
                "total_output_tokens": int(row[3]),
                "total_cost_usd": float(row[4])
            }
            for row in result.result_rows
        ]

    return await asyncio.to_thread(_query)


async def get_spend_timeseries(workspace_id: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Query daily cost and request count timeseries from rollup table."""
    def _query():
        client = get_clickhouse_client()
        query = """
            SELECT 
                day,
                sum(request_count) as request_count,
                sum(cost_usd) as total_cost_usd
            FROM daily_spend_rollup
            WHERE workspace_id = {ws:UUID} AND day >= {start:Date} AND day <= {end:Date}
            GROUP BY day
            ORDER BY day ASC
        """
        params = {"ws": workspace_id, "start": start_date, "end": end_date}
        result = client.query(query, params)
        return [
            {
                "date": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                "request_count": int(row[1]),
                "total_cost_usd": float(row[2])
            }
            for row in result.result_rows
        ]

    return await asyncio.to_thread(_query)
