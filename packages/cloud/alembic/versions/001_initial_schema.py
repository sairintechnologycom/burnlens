"""Initial schema — Phase 2 tables + TimescaleDB hypertable + continuous aggregates.

Revision ID: 001
Revises: None
Create Date: 2026-04-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable TimescaleDB extension
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")

    # ── Organizations ──────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, unique=True, nullable=False),
        sa.Column("api_key_hash", sa.Text, unique=True, nullable=False),
        sa.Column("tier", sa.Text, nullable=False, server_default="free"),
        sa.Column("subscription_id", sa.Text),
        sa.Column("subscription_status", sa.Text, server_default="active"),
        sa.Column(
            "settings_json",
            postgresql.JSONB,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    # ── Provider Connections ───────────────────────────────────
    op.create_table(
        "provider_connections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text),
        sa.Column("encrypted_key", sa.LargeBinary, nullable=False),
        sa.Column("sync_cursor", sa.Text),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column(
            "metadata_json",
            postgresql.JSONB,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("org_id", "provider", "display_name"),
    )

    # ── Request Log ────────────────────────────────────────────
    op.create_table(
        "request_log",
        sa.Column("id", sa.BigInteger, autoincrement=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("request_path", sa.Text),
        # tokens
        sa.Column("input_tokens", sa.Integer, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.Integer, server_default=sa.text("0")),
        sa.Column("reasoning_tokens", sa.Integer, server_default=sa.text("0")),
        sa.Column("cache_read_tokens", sa.Integer, server_default=sa.text("0")),
        sa.Column("cache_write_tokens", sa.Integer, server_default=sa.text("0")),
        # cost
        sa.Column(
            "cost_usd",
            sa.Numeric(12, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        # metadata
        sa.Column("duration_ms", sa.Integer),
        sa.Column("status_code", sa.Integer),
        sa.Column("system_prompt_hash", sa.Text),
        # attribution
        sa.Column("tag_feature", sa.Text),
        sa.Column("tag_team", sa.Text),
        sa.Column("tag_customer", sa.Text),
        sa.Column(
            "tags_json",
            postgresql.JSONB,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # sync
        sa.Column("synced_at", sa.DateTime(timezone=True)),
        # composite PK required for hypertable
        sa.PrimaryKeyConstraint("id", "timestamp"),
    )

    # Convert to TimescaleDB hypertable (7-day chunks)
    op.execute(
        "SELECT create_hypertable('request_log', 'timestamp', "
        "chunk_time_interval => INTERVAL '7 days', "
        "if_not_exists => TRUE)"
    )

    # Indexes for common query patterns
    op.create_index(
        "idx_request_log_org_time", "request_log", ["org_id", sa.text("timestamp DESC")]
    )
    op.create_index(
        "idx_request_log_model",
        "request_log",
        ["org_id", "model", sa.text("timestamp DESC")],
    )
    op.create_index(
        "idx_request_log_team",
        "request_log",
        ["org_id", "tag_team", sa.text("timestamp DESC")],
    )
    op.create_index(
        "idx_request_log_customer",
        "request_log",
        ["org_id", "tag_customer", sa.text("timestamp DESC")],
    )

    # ── Alert Rules ────────────────────────────────────────────
    op.create_table(
        "alert_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("metric", sa.Text, nullable=False),
        sa.Column("period", sa.Text, server_default="daily"),
        sa.Column("threshold", sa.Numeric(12, 4), nullable=False),
        sa.Column("threshold_pct", postgresql.ARRAY(sa.Integer)),
        # filters
        sa.Column("provider_filter", sa.Text),
        sa.Column("model_filter", sa.Text),
        sa.Column("team_filter", sa.Text),
        sa.Column("customer_filter", sa.Text),
        # dispatch
        sa.Column("webhook_url", sa.Text),
        sa.Column("slack_webhook", sa.Text),
        sa.Column("email_recipients", postgresql.ARRAY(sa.Text)),
        sa.Column("terminal_notify", sa.Boolean, server_default=sa.text("false")),
        # state
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    # ── Webhook Events ─────────────────────────────────────────
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("webhook_id", sa.Text, unique=True, nullable=False),
        sa.Column("event_name", sa.Text, nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    # Continuous aggregates are in migration 002 (requires non-transactional execution)


def downgrade() -> None:
    op.drop_table("webhook_events")
    op.drop_table("alert_rules")
    op.drop_table("request_log")
    op.drop_table("provider_connections")
    op.drop_table("organizations")
