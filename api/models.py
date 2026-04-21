"""Pydantic models for all request/response bodies."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# --- Auth ---

class SignupRequest(BaseModel):
    email: str
    workspace_name: str


class SignupResponse(BaseModel):
    api_key: str
    workspace_id: UUID
    workspace_name: str


class LoginRequest(BaseModel):
    api_key: str


class LoginResponse(BaseModel):
    token: str
    workspace_name: str
    plan: str
    expires_in: int = 86400


class WaitlistRequest(BaseModel):
    email: str


# --- Ingest ---

class RecordIn(BaseModel):
    ts: datetime
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    tag_feature: Optional[str] = None
    tag_team: Optional[str] = None
    tag_customer: Optional[str] = None
    system_prompt_hash: Optional[str] = None


class IngestRequest(BaseModel):
    api_key: str
    # Bound list size — a single batch above this is rejected to prevent
    # memory/DB exhaustion from a misbehaving or stolen-key client.
    records: list[RecordIn] = Field(..., max_length=10_000)


class IngestResponse(BaseModel):
    accepted: int
    rejected: int


# --- Team ---

class InviteRequest(BaseModel):
    email: str
    role: Literal["viewer", "admin"] = "viewer"


class InviteResponse(BaseModel):
    invitation_id: UUID
    expires_at: datetime


class InvitationInfo(BaseModel):
    workspace_name: str
    role: str
    inviter_email: Optional[str] = None
    expires_at: datetime


class AcceptRequest(BaseModel):
    email: str
    name: str


class MemberOut(BaseModel):
    user_id: UUID
    email: str
    name: Optional[str] = None
    role: str
    joined_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    active: bool


class PendingInviteOut(BaseModel):
    email: str
    role: str
    created_at: datetime
    expires_at: datetime


class MembersResponse(BaseModel):
    members: list[MemberOut]
    pending: list[PendingInviteOut]


class RoleUpdate(BaseModel):
    role: Literal["viewer", "admin"]


class ActivityEntry(BaseModel):
    action: str
    detail: Optional[dict] = None
    created_at: datetime
    user_email: Optional[str] = None


# --- Enterprise OTEL ---

class OtelConfig(BaseModel):
    endpoint: str
    api_key: str
    enabled: bool


class OtelConfigResponse(BaseModel):
    endpoint: str
    api_key_masked: str
    enabled: bool
    last_push: Optional[datetime] = None


class OtelTestResponse(BaseModel):
    ok: bool
    latency_ms: Optional[int] = None
    error: Optional[str] = None
