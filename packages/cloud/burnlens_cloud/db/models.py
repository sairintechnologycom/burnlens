"""SQLAlchemy ORM models — Phase 2 scope."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False, server_default="free")
    subscription_id: Mapped[str | None] = mapped_column(Text)
    subscription_status: Mapped[str | None] = mapped_column(
        Text, server_default="active"
    )
    settings_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class ProviderConnection(Base):
    __tablename__ = "provider_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    encrypted_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sync_cursor: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    metadata_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class RequestLog(Base):
    __tablename__ = "request_log"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    request_path: Mapped[str | None] = mapped_column(Text)
    # tokens
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    reasoning_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cache_read_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cache_write_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # cost
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), nullable=False, server_default=text("0")
    )
    # metadata
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status_code: Mapped[int | None] = mapped_column(Integer)
    system_prompt_hash: Mapped[str | None] = mapped_column(Text)
    # attribution
    tag_feature: Mapped[str | None] = mapped_column(Text)
    tag_team: Mapped[str | None] = mapped_column(Text)
    tag_customer: Mapped[str | None] = mapped_column(Text)
    tags_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    # sync
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        {"comment": "TimescaleDB hypertable — composite PK (id, timestamp)"},
    )

    __mapper_args__ = {"primary_key": [id, timestamp]}


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    period: Mapped[str] = mapped_column(Text, server_default="daily")
    threshold: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    threshold_pct: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    # filters
    provider_filter: Mapped[str | None] = mapped_column(Text)
    model_filter: Mapped[str | None] = mapped_column(Text)
    team_filter: Mapped[str | None] = mapped_column(Text)
    customer_filter: Mapped[str | None] = mapped_column(Text)
    # dispatch
    webhook_url: Mapped[str | None] = mapped_column(Text)
    slack_webhook: Mapped[str | None] = mapped_column(Text)
    email_recipients: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    terminal_notify: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # state
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    webhook_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    event_name: Mapped[str] = mapped_column(Text, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
