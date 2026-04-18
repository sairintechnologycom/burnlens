from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field


# Request/Response Schemas
class WorkspaceBase(BaseModel):
    """Base workspace schema."""
    name: str
    owner_email: str


class WorkspaceCreate(WorkspaceBase):
    """Schema for creating a workspace."""
    pass


class WorkspaceResponse(WorkspaceBase):
    """Schema for workspace response."""
    id: UUID
    plan: str
    api_key: str
    created_at: datetime
    active: bool


class RequestRecordBase(BaseModel):
    """Base request record schema."""
    timestamp: datetime
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    status_code: int = 200
    tags: dict = Field(default_factory=dict)
    system_prompt_hash: Optional[str] = None


class RequestRecordCreate(RequestRecordBase):
    """Schema for creating a request record."""
    workspace_id: UUID


class RequestRecordResponse(RequestRecordCreate):
    """Schema for request record response."""
    id: int
    received_at: datetime


class IngestRequest(BaseModel):
    """Schema for ingest endpoint request."""
    api_key: str
    records: list[RequestRecordBase]


class IngestResponse(BaseModel):
    """Schema for ingest endpoint response."""
    accepted: int
    rejected: int


class LoginRequest(BaseModel):
    """Schema for login request — API key OR email+password."""
    api_key: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None


class LoginResponse(BaseModel):
    """Schema for login response."""
    token: str
    expires_in: int
    workspace: WorkspaceResponse


class SignupRequest(BaseModel):
    """Schema for signup request."""
    email: str
    password: str
    workspace_name: str


class SignupResponse(BaseModel):
    """Schema for signup response."""
    api_key: str
    workspace_id: UUID
    token: str
    expires_in: int
    workspace: WorkspaceResponse
    message: str = "Workspace created successfully."


class TokenPayload(BaseModel):
    """JWT token payload."""
    workspace_id: UUID
    user_id: UUID
    role: str  # 'owner' | 'admin' | 'viewer'
    plan: str
    iat: int
    exp: int


class StatsSummary(BaseModel):
    """Summary statistics response."""
    total_cost_usd: float
    total_requests: int
    avg_cost_per_request_usd: float
    models_used: int
    budget_limit_usd: Optional[float] = None
    budget_pct_used: Optional[float] = None


class CostByModel(BaseModel):
    """Cost aggregated by model."""
    model: str
    provider: str
    request_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


class CostByTag(BaseModel):
    """Cost aggregated by tag (team, feature, customer)."""
    tag: str
    request_count: int
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int


class CostTimeline(BaseModel):
    """Cost over time."""
    date: str
    request_count: int
    total_cost_usd: float


class BillingPortalResponse(BaseModel):
    """Stripe billing portal response."""
    url: str


# Teams models
class UserResponse(BaseModel):
    """User response model."""
    id: UUID
    email: str
    name: Optional[str] = None
    last_login: Optional[datetime] = None


class WorkspaceMemberResponse(BaseModel):
    """Workspace member response model."""
    id: UUID
    email: str
    name: Optional[str] = None
    role: str  # 'owner' | 'admin' | 'viewer'
    joined_at: datetime
    last_login: Optional[datetime] = None
    invited_by: Optional[UUID] = None


class InvitationRequest(BaseModel):
    """Request to invite someone to workspace."""
    email: str
    role: str = "viewer"  # 'viewer' | 'admin'


class InvitationResponse(BaseModel):
    """Response for created invitation."""
    id: UUID
    email: str
    token: str
    expires_at: datetime
    created_at: datetime


class MemberRoleUpdate(BaseModel):
    """Request to update member role."""
    role: str  # 'viewer' | 'admin' | 'owner'


class ActivityLogEntry(BaseModel):
    """Workspace activity log entry."""
    id: int
    action: str
    detail: dict
    created_at: datetime
    user: Optional[UserResponse] = None


class TeamActivityResponse(BaseModel):
    """Response for activity log."""
    entries: list[ActivityLogEntry]
    total: int
    limit: int
    offset: int


# Enterprise OTEL features
class OtelConfig(BaseModel):
    """OpenTelemetry configuration for enterprise workspace."""
    endpoint: str
    api_key: str
    enabled: bool


class OtelConfigResponse(BaseModel):
    """Response for OTEL configuration (with masked API key)."""
    enabled: bool
    endpoint: str
    api_key_masked: str  # "Bearer ****...xxxx"


class OtelTestResponse(BaseModel):
    """Response for OTEL connectivity test."""
    ok: bool
    latency_ms: Optional[int] = None
    error: Optional[str] = None


# Enterprise status tracking
class StatusCheckRecord(BaseModel):
    """Individual status check record."""
    endpoint: str
    response_ms: int
    status_code: int
    ok: bool


class ComponentStatus(BaseModel):
    """Status of a service component."""
    name: str
    uptime_30d: float
    status: str  # "operational" | "degraded" | "down"


class StatusResponse(BaseModel):
    """Response for /status endpoint."""
    components: list[ComponentStatus]
    incidents: list[dict]


# Enterprise audit logging
class AuditLogEntryExtended(BaseModel):
    """Extended audit log entry with network info."""
    id: int
    user: Optional[str] = None
    action: str
    detail: dict
    created_at: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    api_key_last4: Optional[str] = None


class AuditLogResponse(BaseModel):
    """Response for audit log query."""
    entries: list[AuditLogEntryExtended]
    total: int
    limit: int
    offset: int


# Enterprise custom pricing
class PricingEntry(BaseModel):
    """Pricing entry for a model."""
    input_per_1m: float
    output_per_1m: float


class CustomPricingRequest(BaseModel):
    """Request to set custom pricing for workspace."""
    # Format: {"gpt-4o": {"input_per_1m": 4.50, "output_per_1m": 13.50}}
    pricing: dict[str, PricingEntry]


class PricingResponse(BaseModel):
    """Response for current pricing (default or custom)."""
    pricing: dict[str, dict[str, float]]


# Phase 6: plan limits
class PlanLimits(BaseModel):
    """Row from the plan_limits table — the plan default before any override merge.

    NULL scalar values mean "unlimited" (D-02). `gated_features` is an object of booleans
    whose keys follow D-08: `custom_signatures`, `team_seats`, `otel_export`.
    """
    plan: str
    monthly_request_cap: Optional[int] = None
    seat_count: Optional[int] = None
    retention_days: Optional[int] = None
    api_key_count: Optional[int] = None
    paddle_price_id: Optional[str] = None
    paddle_product_id: Optional[str] = None
    gated_features: dict = Field(default_factory=dict)


class ResolvedLimits(BaseModel):
    """Effective limits for a workspace — the per-workspace override merged over the
    plan default by the Postgres `resolve_limits()` function (PLAN-04).

    A `None` scalar means the workspace is uncapped on that dimension.
    `gated_features` is the shallow-merged boolean map (workspace override wins per flag).
    Does not carry paddle_price_id / paddle_product_id — those are billing-layer concerns.
    """
    plan: str
    monthly_request_cap: Optional[int] = None
    seat_count: Optional[int] = None
    retention_days: Optional[int] = None
    api_key_count: Optional[int] = None
    gated_features: dict = Field(default_factory=dict)
