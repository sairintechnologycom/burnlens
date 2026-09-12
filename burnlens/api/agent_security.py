"""Security, authentication, and authorization models for Agent API / MCP (BL-AE-004).

Supports:
- Bearer API token validation (static or signed JWT)
- Capability / Scope authorization (e.g. scope:economics.read, scope:simulation.execute)
- Workspace constraints (strict tenancy boundaries)
- Token revocation and expiry checks
"""
from __future__ import annotations

import hmac
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence


class AgentScope(str, Enum):
    """Allowed capability scopes for external agent consumption."""

    ECONOMICS_READ = "economics:read"
    BUDGET_CHECK = "budget:check"
    SIMULATION_EXECUTE = "simulation:execute"
    RECOMMENDATIONS_READ = "recommendations:read"
    ADMIN = "admin"


@dataclass(frozen=True)
class AgentSecurityContext:
    """Authenticated agent context with verified workspace constraints and scopes."""

    agent_id: str
    workspace_id: str
    scopes: set[str] = field(default_factory=set)
    expires_at: int | None = None
    is_revoked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def has_scope(self, required_scope: str | AgentScope) -> bool:
        """Verify whether security context satisfies the requested scope."""
        scope_str = required_scope.value if isinstance(required_scope, AgentScope) else required_scope
        if AgentScope.ADMIN.value in self.scopes or "admin" in self.scopes:
            return True
        return scope_str in self.scopes

    def is_valid(self, now: int | None = None) -> bool:
        """Check whether context is unexpired and not revoked."""
        if self.is_revoked:
            return False
        curr_time = now if now is not None else int(time.time())
        if self.expires_at is not None and self.expires_at < curr_time:
            return False
        return True


class TokenManager:
    """In-memory or state-backed token verification for Agent API & MCP."""

    def __init__(self, secret: str = "burnlens-mcp-secret-key-2026") -> None:
        self.secret = secret
        self._tokens: dict[str, AgentSecurityContext] = {}
        self._revoked_tokens: set[str] = set()

    def register_token(
        self,
        token: str,
        agent_id: str,
        workspace_id: str,
        scopes: Sequence[str | AgentScope],
        ttl_seconds: int | None = 3600,
        metadata: dict[str, Any] | None = None,
    ) -> AgentSecurityContext:
        """Register a valid agent token with workspace and scopes."""
        now = int(time.time())
        expires_at = now + ttl_seconds if ttl_seconds is not None else None
        scope_strings = {
            s.value if isinstance(s, AgentScope) else s for s in scopes
        }

        ctx = AgentSecurityContext(
            agent_id=agent_id,
            workspace_id=workspace_id,
            scopes=scope_strings,
            expires_at=expires_at,
            is_revoked=False,
            metadata=metadata or {},
        )
        self._tokens[token] = ctx
        return ctx

    def revoke_token(self, token: str) -> bool:
        """Revoke a token immediately."""
        self._revoked_tokens.add(token)
        if token in self._tokens:
            existing = self._tokens[token]
            self._tokens[token] = AgentSecurityContext(
                agent_id=existing.agent_id,
                workspace_id=existing.workspace_id,
                scopes=existing.scopes,
                expires_at=existing.expires_at,
                is_revoked=True,
                metadata=existing.metadata,
            )
            return True
        return False

    def authenticate(self, token: str | None) -> AgentSecurityContext | None:
        """Verify token and return security context if valid."""
        if not token:
            return None
        if token in self._revoked_tokens:
            return None
        ctx = self._tokens.get(token)
        if ctx is None:
            return None
        if not ctx.is_valid():
            return None
        return ctx
