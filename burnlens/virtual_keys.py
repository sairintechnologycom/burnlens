"""Virtual keys — turn the passive proxy into an active gateway.

A *virtual key* (``bl-sk-…``) is handed to a team/app instead of a real
provider key. On each request the proxy resolves the virtual key, enforces a
model allowlist and a per-team monthly budget, then swaps in the operator's
real upstream key before forwarding.

Option A (env-reference): the DB never stores a recoverable provider secret —
only the *name* of an environment variable the operator already exports. The
virtual key itself is stored as a SHA-256 hash (like ``api_keys``); the raw
token is shown once, at issue time, and never persisted.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiosqlite

# Every issued token starts with this prefix so the interceptor can cheaply
# tell a virtual key apart from a passed-through provider key.
VIRTUAL_PREFIX = "bl-sk-"


class VirtualKeyExists(Exception):
    """Raised when the chosen label is already in use."""


@dataclass
class VirtualKey:
    """A resolved, non-revoked virtual key."""

    label: str
    team: str
    provider: str
    upstream_key_env: str
    allowed_models: list[str] | None  # None → all models allowed
    monthly_budget_usd: float | None  # None → no budget
    token_prefix: str


def generate_token() -> str:
    """Return a fresh virtual key. Cryptographically random, URL-safe."""
    return VIRTUAL_PREFIX + secrets.token_urlsafe(24)


def hash_token(raw_token: str) -> str:
    """SHA-256 of the raw token, hex-encoded (stable across processes)."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def looks_like_virtual_key(token: str | None) -> bool:
    """True if ``token`` has the virtual-key prefix."""
    return bool(token) and token.startswith(VIRTUAL_PREFIX)  # type: ignore[union-attr]


async def issue_key(
    db_path: str,
    label: str,
    team: str,
    provider: str,
    upstream_key_env: str,
    allowed_models: list[str] | None = None,
    monthly_budget_usd: float | None = None,
) -> tuple[str, str]:
    """Create a virtual key. Returns ``(raw_token, token_prefix)``.

    The raw token is returned exactly once — only its hash is stored.
    Raises ``VirtualKeyExists`` if the label is taken, ``ValueError`` on bad input.
    """
    if not label or not team or not provider or not upstream_key_env:
        raise ValueError("label, team, provider, and upstream_key_env are all required")

    raw_token = generate_token()
    token_hash = hash_token(raw_token)
    token_prefix = raw_token[: len(VIRTUAL_PREFIX) + 6]
    created_at = datetime.now(timezone.utc).isoformat()
    allowed_json = json.dumps(allowed_models) if allowed_models else None

    async with aiosqlite.connect(db_path) as db:
        try:
            await db.execute(
                "INSERT INTO virtual_keys (label, team, provider, upstream_key_env, "
                "token_hash, token_prefix, allowed_models, monthly_budget_usd, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (label, team, provider, upstream_key_env, token_hash, token_prefix,
                 allowed_json, monthly_budget_usd, created_at),
            )
            await db.commit()
        except aiosqlite.IntegrityError as exc:
            raise VirtualKeyExists(f"label '{label}' already in use") from exc

    return raw_token, token_prefix


async def resolve(db_path: str, token_hash: str) -> VirtualKey | None:
    """Look up a non-revoked virtual key by token hash, or ``None``."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT label, team, provider, upstream_key_env, allowed_models, "
            "monthly_budget_usd, token_prefix FROM virtual_keys "
            "WHERE token_hash = ? AND revoked_at IS NULL LIMIT 1",
            (token_hash,),
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    allowed = row["allowed_models"]
    return VirtualKey(
        label=row["label"],
        team=row["team"],
        provider=row["provider"],
        upstream_key_env=row["upstream_key_env"],
        allowed_models=json.loads(allowed) if allowed else None,
        monthly_budget_usd=row["monthly_budget_usd"],
        token_prefix=row["token_prefix"],
    )


async def list_keys(db_path: str) -> list[dict[str, Any]]:
    """Return all virtual keys (raw tokens are never stored, so never shown)."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT label, team, provider, upstream_key_env, token_prefix, "
            "allowed_models, monthly_budget_usd, created_at, revoked_at "
            "FROM virtual_keys ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
    return [
        {
            "label": r["label"],
            "team": r["team"],
            "provider": r["provider"],
            "upstream_key_env": r["upstream_key_env"],
            "token_prefix": r["token_prefix"],
            "allowed_models": json.loads(r["allowed_models"]) if r["allowed_models"] else None,
            "monthly_budget_usd": r["monthly_budget_usd"],
            "created_at": r["created_at"],
            "revoked_at": r["revoked_at"],
        }
        for r in rows
    ]


async def revoke_key(db_path: str, label: str) -> bool:
    """Revoke a virtual key by label. Returns True if a live key was revoked."""
    ts = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "UPDATE virtual_keys SET revoked_at = ? WHERE label = ? AND revoked_at IS NULL",
            (ts, label),
        )
        await db.commit()
        return cursor.rowcount > 0
