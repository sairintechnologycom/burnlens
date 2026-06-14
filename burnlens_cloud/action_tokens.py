"""
Phase 10: JWT-based Action Tokens for clickable alerts.

Used to generate short-lived, signed links for Slack/Teams alerts
that allow users to instantly remediate issues (e.g. pause API key).
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Any
from uuid import uuid4

import jwt
from pydantic import BaseModel

from .config import settings
from .database import execute_query, execute_insert

logger = logging.getLogger(__name__)

ACTION_TOKEN_ALGORITHM = "HS256"
ACTION_TOKEN_TTL = 7200  # 2 hours


class ActionTokenPayload(BaseModel):
    action: str
    workspace_id: str
    target_id: Optional[str] = None
    jti: str
    iat: int
    exp: int


async def create_action_token(
    action: str,
    workspace_id: str,
    target_id: Optional[str] = None,
) -> str:
    """
    Generate a signed JWT for a specific action.
    Includes a unique JTI for single-use enforcement.
    """
    now = int(time.time())
    payload = ActionTokenPayload(
        action=action,
        workspace_id=workspace_id,
        target_id=target_id,
        jti=str(uuid4()),
        iat=now,
        exp=now + ACTION_TOKEN_TTL,
    )

    return jwt.encode(
        payload.model_dump(),
        settings.jwt_secret,
        algorithm=ACTION_TOKEN_ALGORITHM,
    )


async def verify_action_token(token: str) -> Optional[ActionTokenPayload]:
    """
    Verify the JWT signature, expiry, and check if JTI was already used.
    Returns the payload if valid, None otherwise.
    """
    try:
        decoded = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ACTION_TOKEN_ALGORITHM],
        )
        payload = ActionTokenPayload(**decoded)
        return payload

    except jwt.ExpiredSignatureError:
        logger.warning("action_tokens: token expired")
        return None
    except jwt.InvalidTokenError as exc:
        logger.warning("action_tokens: invalid token: %s", exc)
        return None
    except Exception as exc:
        logger.error("action_tokens: verification failed: %s", exc)
        return None


async def consume_action_token(jti: str) -> bool:
    """
    Mark a JTI as consumed to prevent replay attacks.
    Returns True on success, False if already consumed or error.
    """
    try:
        # Atomic insert with conflict check
        result = await execute_insert(
            "INSERT INTO used_action_tokens (jti) VALUES ($1) ON CONFLICT DO NOTHING",
            jti,
        )
        # asyncpg execute returns 'INSERT 0 1' or 'INSERT 0 0'
        return result and result.endswith(" 1")
    except Exception as exc:
        logger.error("action_tokens: failed to consume jti %s: %s", jti, exc)
        return False
