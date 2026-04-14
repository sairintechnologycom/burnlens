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
    """Schema for login request."""
    api_key: str


class LoginResponse(BaseModel):
    """Schema for login response."""
    token: str
    expires_in: int
    workspace: WorkspaceResponse


class SignupRequest(BaseModel):
    """Schema for signup request."""
    email: str
    workspace_name: str


class SignupResponse(BaseModel):
    """Schema for signup response."""
    api_key: str
    workspace_id: UUID
    message: str = "Workspace created. Check your email for next steps."


class TokenPayload(BaseModel):
    """JWT token payload."""
    workspace_id: UUID
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
