"""Dataclasses for BurnLens request records."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RequestRecord:
    """A single intercepted LLM API request + response pair."""

    provider: str                       # openai | anthropic | google
    model: str                          # e.g. gpt-4o, claude-3-5-sonnet-20241022
    request_path: str                   # e.g. /v1/chat/completions
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0          # OpenAI o-series reasoning tokens
    cache_read_tokens: int = 0         # Anthropic / OpenAI cached input tokens
    cache_write_tokens: int = 0        # Anthropic cache-write tokens

    cost_usd: float = 0.0
    duration_ms: int = 0
    status_code: int = 200

    tags: dict[str, str] = field(default_factory=dict)  # from X-BurnLens-Tag-* headers
    system_prompt_hash: str | None = None               # SHA-256 of system prompt

    # Set by DB layer after insert
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

    provider: str                           # openai | anthropic | google | azure_openai | bedrock | cohere | mistral | custom
    model_name: str                         # e.g. gpt-4o, claude-3-5-sonnet-20241022
    endpoint_url: str                       # API endpoint being called

    api_key_hash: str | None = None         # SHA-256 hash of API key (never raw keys)
    owner_team: str | None = None           # Plain text team name (e.g. "ML Platform")
    project: str | None = None             # Plain text project name

    status: str = "shadow"                 # active | inactive | shadow | approved | deprecated
    risk_tier: str = "unclassified"        # unclassified | low | medium | high

    first_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))  # When first detected
    last_active_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))  # Most recent activity

    monthly_spend_usd: float = 0.0         # Current month spend
    monthly_requests: int = 0             # Current month request count

    tags: dict[str, str] = field(default_factory=dict)  # Flexible key-value tags

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Set by DB layer after insert
    id: int | None = None


@dataclass
class ProviderSignature:
    """Detection fingerprint for identifying an AI provider from network traffic."""

    provider: str                           # Provider key (openai, anthropic, etc.)
    endpoint_pattern: str                   # Glob/regex match pattern for endpoint URLs

    header_signature: dict = field(default_factory=dict)  # Expected headers as JSON
    model_field_path: str = "body.model"   # JSONPath to model name in request body

    # Set by DB layer after insert
    id: int | None = None


@dataclass
class DiscoveryEvent:
    """An immutable event record for the AI asset audit log."""

    event_type: str                         # new_asset_detected | model_changed | provider_changed | key_rotated | asset_inactive

    asset_id: int | None = None            # FK to ai_assets (nullable for org-level events)
    details: dict = field(default_factory=dict)  # Event-specific metadata as JSON
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))  # When event occurred

    # Set by DB layer after insert
    id: int | None = None
