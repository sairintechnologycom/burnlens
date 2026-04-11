"""Continuous aggregates for request_log hypertable.

Revision ID: 002
Revises: 001
Create Date: 2026-04-11

TimescaleDB continuous aggregates cannot be created inside a transaction block.
We use the raw DBAPI connection with autocommit to work around this.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


HOURLY_VIEW = """
CREATE MATERIALIZED VIEW IF NOT EXISTS request_log_hourly
WITH (timescaledb.continuous) AS
SELECT
    org_id,
    time_bucket('1 hour', timestamp) AS bucket,
    provider,
    model,
    tag_team,
    tag_feature,
    COUNT(*) AS request_count,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(cost_usd) AS total_cost,
    AVG(duration_ms) AS avg_latency_ms
FROM request_log
GROUP BY org_id, bucket, provider, model, tag_team, tag_feature
"""

DAILY_VIEW = """
CREATE MATERIALIZED VIEW IF NOT EXISTS request_log_daily
WITH (timescaledb.continuous) AS
SELECT
    org_id,
    time_bucket('1 day', timestamp) AS bucket,
    provider,
    model,
    tag_team,
    tag_feature,
    tag_customer,
    COUNT(*) AS request_count,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(reasoning_tokens) AS total_reasoning_tokens,
    SUM(cache_read_tokens) AS total_cache_read_tokens,
    SUM(cost_usd) AS total_cost,
    AVG(duration_ms) AS avg_latency_ms
FROM request_log
GROUP BY org_id, bucket, provider, model, tag_team, tag_feature, tag_customer
"""


def upgrade() -> None:
    # Get the raw DBAPI connection and commit the current Alembic transaction
    conn = op.get_bind()
    conn.execute(sa.text("COMMIT"))
    conn.execute(sa.text(HOURLY_VIEW))
    conn.execute(sa.text(DAILY_VIEW))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("COMMIT"))
    conn.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS request_log_daily CASCADE"))
    conn.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS request_log_hourly CASCADE"))
