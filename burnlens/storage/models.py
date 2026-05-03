"""Dataclasses for BurnLens request records."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RequestRecord:
    """A single intercepted LLM API request + response pair."""

    provider: str
    model: str
    request_path: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    status_code: int = 200
    tags: dict[str, str] = field(default_factory=dict)
    system_prompt_hash: str | None = None
    source: str = "proxy"
    request_id: str | None = None
    id: int | None = None


@dataclass
class AggregatedUsage:
    """Aggregated cost/usage stats for reporting."""

    model: str
    provider: str
    request_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


@dataclass
class AiAsset:
    """A discovered AI API integration (an LLM being used in the org)."""

    provider: str
    model_name: str
    endpoint_url: str
    api_key_hash: str | None = None
    owner_team: str | None = None
    project: str | None = None
    status: str = "shadow"
    risk_tier: str = "unclassified"
    first_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    monthly_spend_usd: float = 0.0
    monthly_requests: int = 0
    tags: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: int | None = None


@dataclass
class ProviderSignature:
    """Detection fingerprint for identifying an AI provider from network traffic."""

    provider: str
    endpoint_pattern: str
    header_signature: dict = field(default_factory=dict)
    model_field_path: str = "body.model"
    id: int | None = None


@dataclass
class DiscoveryEvent:
    """An immutable event record for the AI asset audit log."""

    event_type: str
    asset_id: int | None = None
    details: dict = field(default_factory=dict)
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: int | None = None
