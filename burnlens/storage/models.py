"""Dataclasses for BurnLens request records."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import threading
import time


_last_uuid7_ts = 0
_uuid7_lock = threading.Lock()

REQUEST_RELATION_FIELDS = ("parent_event_id", "retry_of_event_id", "fallback_of_event_id")


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
    pricing_fingerprint: str | None = None
    ttft_ms: float | None = None
    cache_hit: int = 0
    cache_saved_usd: float = 0.0
    parent_span_id: str | None = None
    parent_event_id: str | None = None
    retry_of_event_id: str | None = None
    fallback_of_event_id: str | None = None
    agent_id: str | None = None
    workflow_id: str | None = None
    workflow_run_id: str | None = None
    run_id: str | None = None
    task_id: str | None = None
    action_id: str | None = None
    parent_run_id: str | None = None


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
    requested_model: str | None = None
    routed_model: str | None = None
    downgrade_reason: str | None = None
    budget_remaining_usd: float | None = None
    budget_remaining_pct: float | None = None
    prompt_system_tokens: int = 0
    prompt_user_tokens: int = 0
    prompt_tools_tokens: int = 0
    prompt_rag_tokens: int = 0
    prompt_history_tokens: int = 0
    cache_hit: int = 0
    cache_saved_usd: float = 0.0
    tool_calls: int = 0

    # Phase 1: Canonical event fields
    event_id: str | None = None
    trace_id: str | None = None
    # Caller's span id from traceparent: nests LLM calls under the run/step that
    # made them, without asking anyone to instrument anything.
    parent_span_id: str | None = None
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
    pricing_fingerprint: str | None = None
    pricing_class: str | None = None
    ttft_ms: float | None = None

    # Phase 1: BL-AE-001 Agent Economics correlation fields
    agent_id: str | None = None
    workflow_id: str | None = None
    workflow_run_id: str | None = None
    run_id: str | None = None
    task_id: str | None = None
    action_id: str | None = None
    parent_run_id: str | None = None
    parent_event_id: str | None = None
    retry_of_event_id: str | None = None
    fallback_of_event_id: str | None = None

    def __post_init__(self) -> None:
        if self.tags:
            if not self.agent_id:
                self.agent_id = self.tags.get("agent_id")
            if not self.workflow_id:
                self.workflow_id = self.tags.get("workflow_id")
            if not self.workflow_run_id:
                self.workflow_run_id = self.tags.get("workflow_run_id")
            if not self.run_id:
                self.run_id = self.tags.get("run_id")
            if not self.task_id:
                self.task_id = self.tags.get("task_id")
            if not self.action_id:
                self.action_id = self.tags.get("action_id")
            if not self.parent_run_id:
                self.parent_run_id = self.tags.get("parent_run_id")

    @property
    def tag_agent_id(self) -> str | None:
        """Fallback property for agent_id."""
        return self.agent_id or (self.tags or {}).get("agent_id")

    @property
    def tag_workflow_id(self) -> str | None:
        """Fallback property for workflow_id."""
        return self.workflow_id or (self.tags or {}).get("workflow_id")

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
            parent_span_id=self.parent_span_id,
            parent_event_id=self.parent_event_id,
            retry_of_event_id=self.retry_of_event_id,
            fallback_of_event_id=self.fallback_of_event_id,
            agent_id=self.agent_id,
            workflow_id=self.workflow_id,
            workflow_run_id=self.workflow_run_id,
            run_id=self.run_id,
            task_id=self.task_id,
            action_id=self.action_id,
            parent_run_id=self.parent_run_id,
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
            pricing_fingerprint=self.pricing_fingerprint,
            ttft_ms=self.ttft_ms,
            cache_hit=self.cache_hit,
            cache_saved_usd=self.cache_saved_usd,
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
            parent_span_id=event.parent_span_id,
            parent_event_id=event.parent_event_id,
            retry_of_event_id=event.retry_of_event_id,
            fallback_of_event_id=event.fallback_of_event_id,
            agent_id=event.agent_id,
            workflow_id=event.workflow_id,
            workflow_run_id=event.workflow_run_id,
            run_id=event.run_id,
            task_id=event.task_id,
            action_id=event.action_id,
            parent_run_id=event.parent_run_id,
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
            pricing_fingerprint=event.pricing_fingerprint,
            ttft_ms=event.ttft_ms,
            cache_hit=event.cache_hit,
            cache_saved_usd=event.cache_saved_usd,
        )



OUTCOME_STATUSES = ("accepted", "rejected", "failed")


@dataclass
class Outcome:
    """A business result produced by a workflow — the other half of unit economics.

    ``outcome_id`` is the caller's own id for the business event (ticket, PR,
    document). It is the idempotency key, so recording the same outcome twice —
    a rerun of a derived-outcome importer, a retried CLI call — cannot inflate
    the count that cost-per-outcome divides by.
    """

    outcome_id: str
    workflow_id: str
    status: str
    outcome_type: str = "unspecified"
    event_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    business_value: float | None = None
    currency: str | None = None
    source: str = "cli"
    metadata: dict = field(default_factory=dict)
    id: int | None = None

    def __post_init__(self) -> None:
        if self.status not in OUTCOME_STATUSES:
            raise ValueError(
                f"status must be one of {OUTCOME_STATUSES}, got {self.status!r}"
            )
        self.outcome_type = (self.outcome_type or "unspecified").strip() or "unspecified"


@dataclass
class WorkflowEconomics:
    """Unit economics for one workflow.

    ``cost_per_accepted_usd`` divides TOTAL workflow spend by accepted outcomes,
    not only the spend allocated to accepted ones: failed and rejected attempts
    cost real money and charging them to the successes is the honest unit cost.
    It is None when nothing has been accepted yet — a workflow burning money
    with nothing to show for it has no meaningful unit cost, and 0 or infinity
    would both read as a number rather than an absence.
    """

    workflow_id: str
    outcome_type: str
    accepted_count: int
    rejected_count: int
    failed_count: int
    cost_total_usd: float
    cost_accepted_usd: float
    cost_rework_usd: float
    cost_unattributed_usd: float
    cost_per_accepted_usd: float | None = None
    business_value_accepted: float | None = None
    business_value_currency: str | None = None
    business_value_currencies: list[str] = field(default_factory=list)
    business_value_excluded: bool = False


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


# ===========================================================================
# Phase 1: BL-AE-001 Agent Economics Domain Entities
# ===========================================================================

@dataclass
class Agent:
    """Agent entity registered with BurnLens for economics and lifecycle tracking."""

    agent_id: str
    name: str
    workspace_id: str = "default"
    version: str = "1.0.0"
    owner: str = ""
    environment: str = "production"
    purpose: str = ""
    status: str = "active"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AgentWorkflow:
    """Workflow grouping related agent runs and tasks."""

    workflow_id: str
    name: str
    workspace_id: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class WorkflowRun:
    """A single execution of a registered workflow in one workspace."""

    workflow_run_id: str
    workflow_id: str
    workspace_id: str = "default"
    status: str = "active"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


@dataclass
class AgentRun:
    """A discrete execution run of an agent, supporting hierarchical parent-child relationships."""

    run_id: str
    agent_id: str
    workflow_id: str | None = None
    workflow_run_id: str | None = None
    parent_run_id: str | None = None
    root_run_id: str | None = None
    workspace_id: str = "default"
    status: str = "active"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


@dataclass
class AgentTask:
    """A discrete unit of work within an agent run."""

    task_id: str
    run_id: str
    name: str = ""
    status: str = "active"
    workspace_id: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


@dataclass
class AgentAction:
    """An action taken by an agent during a task (e.g. tool call, API interaction)."""

    action_id: str
    task_id: str
    run_id: str
    action_type: str = "tool_call"
    tool_name: str = ""
    status: str = "completed"
    cost_usd: float = 0.0
    workspace_id: str = "default"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
