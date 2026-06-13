"""Dataclasses for BurnLens request records."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import threading
import time


_last_uuid7_ts = 0
_uuid7_lock = threading.Lock()


def uuid7() -> str:
    """Generate an RFC 9562-compatible UUIDv7 string."""
    global _last_uuid7_ts
    with _uuid7_lock:
        ts_ms = int(time.time() * 1000)
        if ts_ms <= _last_uuid7_ts:
            ts_ms = _last_uuid7_ts + 1
        _last_uuid7_ts = ts_ms

    rand_bytes = bytearray(os.urandom(16))

    # Write timestamp to first 6 bytes
    rand_bytes[0] = (ts_ms >> 40) & 0xFF
    rand_bytes[1] = (ts_ms >> 32) & 0xFF
    rand_bytes[2] = (ts_ms >> 24) & 0xFF
    rand_bytes[3] = (ts_ms >> 16) & 0xFF
    rand_bytes[4] = (ts_ms >> 8) & 0xFF
    rand_bytes[5] = ts_ms & 0xFF

    # Set version to 7 (bits 4-7 of byte 6)
    rand_bytes[6] = (rand_bytes[6] & 0x0F) | 0x70

    # Set variant to 2 (bits 6-7 of byte 8)
    rand_bytes[8] = (rand_bytes[8] & 0x3F) | 0x80

    h = rand_bytes.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


@dataclass
class TokenUsageEvent:
    """Canonical representation of token counts for a GenAI event."""

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class GenAICostEvent:
    """Canonical schema for a single AI cost event."""

    event_id: str
    request_id: str | None
    trace_id: str | None
    workspace_id: str | None
    org_id: str | None
    team: str | None
    feature: str | None
    customer_hash: str | None
    app_id: str | None
    env: str | None
    repo: str | None
    branch: str | None
    commit_sha: str | None
    timestamp: datetime
    provider: str
    model: str
    usage: TokenUsageEvent
    cost_usd: float
    duration_ms: float
    status_code: int
    pricing_version: str | None
    ttft_ms: float | None = None


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
    routed_model: str | None = None
    downgrade_reason: str | None = None
    budget_remaining_usd: float | None = None
    budget_remaining_pct: float | None = None
    prompt_system_tokens: int = 0
    prompt_user_tokens: int = 0
    prompt_tools_tokens: int = 0
    prompt_rag_tokens: int = 0
    prompt_history_tokens: int = 0

    # Phase 1: Canonical event fields
    event_id: str | None = None
    trace_id: str | None = None
    workspace_id: str | None = None
    org_id: str | None = None
    team: str | None = None
    feature: str | None = None
    customer_hash: str | None = None
    app_id: str | None = None
    env: str | None = None
    repo: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    pricing_version: str | None = None
    ttft_ms: float | None = None

    @property
    def tag_repo(self) -> str | None:
        """Fallback property for backwards compatibility."""
        return self.repo or (self.tags or {}).get("repo")

    @property
    def tag_dev(self) -> str | None:
        """Fallback property for backwards compatibility."""
        return (self.tags or {}).get("dev")

    @property
    def tag_pr(self) -> str | None:
        """Fallback property for backwards compatibility."""
        return (self.tags or {}).get("pr")

    @property
    def tag_branch(self) -> str | None:
        """Fallback property for backwards compatibility."""
        return self.branch or (self.tags or {}).get("branch")

    @property
    def tag_key_label(self) -> str | None:
        """Fallback property for backwards compatibility."""
        return (self.tags or {}).get("key_label")

    def to_event(self) -> GenAICostEvent:
        """Convert this RequestRecord to a canonical GenAICostEvent."""
        import hashlib

        usage = TokenUsageEvent(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            reasoning_tokens=self.reasoning_tokens,
            cache_read_tokens=self.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens,
        )
        event_id = self.event_id or uuid7()
        
        # Calculate customer hash safely
        customer = (self.tags or {}).get("customer")
        cust_hash = self.customer_hash
        if not cust_hash and customer:
            cust_hash = hashlib.sha256(customer.encode()).hexdigest()

        return GenAICostEvent(
            event_id=event_id,
            request_id=self.request_id,
            trace_id=self.trace_id,
            workspace_id=self.workspace_id,
            org_id=self.org_id,
            team=self.team or (self.tags or {}).get("team"),
            feature=self.feature or (self.tags or {}).get("feature"),
            customer_hash=cust_hash,
            app_id=self.app_id or (self.tags or {}).get("app_id"),
            env=self.env or (self.tags or {}).get("env"),
            repo=self.repo or (self.tags or {}).get("repo"),
            branch=self.branch or (self.tags or {}).get("branch"),
            commit_sha=self.commit_sha or (self.tags or {}).get("commit_sha"),
            timestamp=self.timestamp,
            provider=self.provider,
            model=self.model,
            usage=usage,
            cost_usd=self.cost_usd,
            duration_ms=self.duration_ms,
            status_code=self.status_code,
            pricing_version=self.pricing_version,
            ttft_ms=self.ttft_ms,
        )

    @classmethod
    def from_event(cls, event: GenAICostEvent) -> RequestRecord:
        """Construct a RequestRecord from a canonical GenAICostEvent."""
        tags = {
            "team": event.team,
            "feature": event.feature,
            "app_id": event.app_id,
            "env": event.env,
            "commit_sha": event.commit_sha,
        }
        if event.repo:
            tags["repo"] = event.repo
        if event.branch:
            tags["branch"] = event.branch
        # Clean out None values
        tags = {k: v for k, v in tags.items() if v is not None}

        return cls(
            provider=event.provider,
            model=event.model,
            request_path="",
            timestamp=event.timestamp,
            input_tokens=event.usage.input_tokens,
            output_tokens=event.usage.output_tokens,
            reasoning_tokens=event.usage.reasoning_tokens,
            cache_read_tokens=event.usage.cache_read_tokens,
            cache_write_tokens=event.usage.cache_write_tokens,
            cost_usd=event.cost_usd,
            duration_ms=event.duration_ms,
            status_code=event.status_code,
            tags=tags,
            request_id=event.request_id,
            event_id=event.event_id,
            trace_id=event.trace_id,
            workspace_id=event.workspace_id,
            org_id=event.org_id,
            team=event.team,
            feature=event.feature,
            customer_hash=event.customer_hash,
            app_id=event.app_id,
            env=event.env,
            repo=event.repo,
            branch=event.branch,
            commit_sha=event.commit_sha,
            pricing_version=event.pricing_version,
            ttft_ms=event.ttft_ms,
        )



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


@dataclass
class AnomalyEvent:
    """An event representing a detected cost spike or runaway loop anomaly."""

    event_type: str  # 'cost_spike' | 'runaway_loop'
    scope: str       # 'org' | 'team' | 'app' | 'customer' | 'api_key' | 'model'
    target: str
    severity: str    # 'warning' | 'critical'
    details: dict = field(default_factory=dict)
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: int | None = None

