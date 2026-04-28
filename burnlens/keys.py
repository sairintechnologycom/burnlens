"""CODE-2: registered API key store.

Pure CRUD over the ``api_keys`` table. The raw key is **never** persisted —
we hash with SHA-256, keep the first 8 chars as a display-only prefix, and
let the interceptor look up a label by hash on every request.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import aiosqlite


class KeyAlreadyExists(Exception):
    """Raised when the chosen label is already registered."""


def hash_api_key(raw_key: str) -> str:
    """SHA-256 of the raw key, hex-encoded. Stable across processes."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def key_prefix(raw_key: str) -> str:
    """First 8 chars of the raw key — safe to display, useless to attackers."""
    return raw_key[:8]


async def register_key(
    db_path: str,
    label: str,
    provider: str,
    raw_key: str,
) -> dict[str, str]:
    """Insert a new label → key mapping.

    Returns a dict describing the stored row (without the raw key or hash).
    Raises ``KeyAlreadyExists`` if the label is taken.
    """
    if not label or not provider or not raw_key:
        raise ValueError("label, provider, and raw_key are all required")

    digest = hash_api_key(raw_key)
    prefix = key_prefix(raw_key)
    created_at = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(db_path) as db:
        try:
            await db.execute(
                "INSERT INTO api_keys (label, provider, key_hash, key_prefix, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (label, provider, digest, prefix, created_at),
            )
            await db.commit()
        except aiosqlite.IntegrityError as exc:
            raise KeyAlreadyExists(f"label '{label}' already registered") from exc

    return {
        "label": label,
        "provider": provider,
        "key_prefix": prefix,
        "created_at": created_at,
    }


async def list_keys(db_path: str) -> list[dict[str, Any]]:
    """Return all registered keys, newest first. Hash and raw key are omitted."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT label, provider, key_prefix, created_at, last_used_at "
            "FROM api_keys ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()

    return [
        {
            "label": row[0],
            "provider": row[1],
            "key_prefix": row[2],
            "created_at": row[3],
            "last_used_at": row[4],
        }
        for row in rows
    ]


async def remove_key(db_path: str, label: str) -> bool:
    """Delete a label. Returns True if a row was removed."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "DELETE FROM api_keys WHERE label = ?", (label,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_label_by_hash(db_path: str, key_hash: str) -> str | None:
    """Look up the label for a SHA-256 key hash, or ``None`` if unregistered."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT label FROM api_keys WHERE key_hash = ? LIMIT 1",
            (key_hash,),
        )
        row = await cursor.fetchone()
    return row[0] if row else None


async def touch_last_used(db_path: str, label: str) -> None:
    """Stamp ``last_used_at`` on a label. No-op if the label is gone."""
    ts = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE label = ?",
            (ts, label),
        )
        await db.commit()
