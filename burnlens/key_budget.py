"""CODE-2: per-API-key daily hard caps — spend tracking, cache, enforcement.

This module is the single source of truth for "how much has this label spent
today, and is it over the cap?". It owns:

- ``resolve_timezone`` — IANA name → ``ZoneInfo``, fail-open to UTC.
- ``next_midnight_in_tz`` — used in the 429 ``resets_at`` field.
- ``today_window_utc`` — UTC ISO bounds for "today" in the configured tz,
  fed to SQLite ``WHERE timestamp >= ?``.
- ``SpendCache`` — module-level singleton, 30s TTL per label.
- ``enforce_daily_cap`` — returns a 429 tuple or None.

Design notes
------------

- We never enforce on unregistered keys (label is None). Enforcement is
  opt-in via ``burnlens key register`` followed by an entry in
  ``alerts.api_key_budgets``. Unregistered traffic still records cost; it
  just isn't blocked.
- The cache stores "spent so far today, measured at monotonic time T". On
  every successful request log we invalidate the entry so the next request
  re-queries SQLite.
- All timestamps in ``requests`` are UTC ISO. We translate "today" in the
  configured tz into a UTC half-open interval ``[start, end)`` for the SQL.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


try:  # Python 3.9+
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover — covered by Python 3.10+ requirement
    ZoneInfo = None  # type: ignore
    ZoneInfoNotFoundError = Exception  # type: ignore


# ---------------------------------------------------------------------------
# Timezone helpers
# ---------------------------------------------------------------------------


def resolve_timezone(name: str) -> Any:
    """Resolve an IANA timezone name. Falls back to UTC on bad input."""
    if not name or name.upper() == "UTC":
        return timezone.utc
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, Exception) as exc:
        logger.warning(
            "Unknown reset_timezone %r — falling back to UTC. (%s)",
            name,
            exc,
        )
        return timezone.utc


def today_window_utc(tz: Any, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return ``[start, end)`` of *today in tz*, expressed in UTC.

    ``end`` is the next midnight in ``tz``. ``now`` is injectable for tests.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    local_now = now.astimezone(tz)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    next_midnight_local = local_midnight + timedelta(days=1)
    return local_midnight.astimezone(timezone.utc), next_midnight_local.astimezone(timezone.utc)


def next_midnight_in_tz(tz: Any, now: datetime | None = None) -> datetime:
    """Return the next midnight in ``tz`` as a UTC-aware datetime."""
    _, end_utc = today_window_utc(tz, now=now)
    return end_utc


def month_start_utc(tz: Any, now: datetime | None = None) -> datetime:
    """Return the first instant of the current month in ``tz``, expressed in UTC."""
    if now is None:
        now = datetime.now(timezone.utc)
    local_now = now.astimezone(tz)
    local_month_start = local_now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    return local_month_start.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# 30-second spend cache
# ---------------------------------------------------------------------------


class SpendCache:
    """Per-label cache of today's spend with a fixed TTL.

    Thread-safe within a single asyncio event loop via an ``asyncio.Lock``.
    The DB query runs **outside** the lock so concurrent requests for
    different labels don't serialize on each other.
    """

    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self._ttl = ttl_seconds
        self._data: dict[str, tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def get_today_spend(
        self,
        label: str,
        db_path: str,
        tz: Any,
    ) -> float:
        now_mono = time.monotonic()
        async with self._lock:
            entry = self._data.get(label)
            if entry and (now_mono - entry[1]) < self._ttl:
                return entry[0]

        # Lazy import avoids a circular dependency with storage.database.
        from burnlens.storage.database import get_spend_by_key_label_today
        spent = await get_spend_by_key_label_today(db_path, label, tz)

        async with self._lock:
            self._data[label] = (spent, time.monotonic())
        return spent

    def invalidate(self, label: str) -> None:
        self._data.pop(label, None)

    def clear(self) -> None:
        self._data.clear()


# Module-level singleton — proxy server and tests share the same instance.
spend_cache = SpendCache()


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------


async def enforce_daily_cap(
    label: str | None,
    db_path: str,
    api_key_budgets: Any,
    cache: SpendCache | None = None,
) -> tuple[float, float, datetime] | None:
    """Return ``(spent_today, daily_cap, resets_at)`` if the cap is exceeded.

    Returns ``None`` when the request should pass through. The caller is
    responsible for synthesising the 429 response from this tuple — keeping
    the HTTP shape out of this module makes it easier to unit-test.
    """
    if not label:
        return None

    daily_cap = api_key_budgets.daily_cap_for(label)
    if daily_cap is None:
        return None

    cache = cache or spend_cache
    tz = resolve_timezone(api_key_budgets.reset_timezone)
    spent = await cache.get_today_spend(label, db_path, tz)
    if spent >= daily_cap:
        return spent, daily_cap, next_midnight_in_tz(tz)
    return None


# ---------------------------------------------------------------------------
# Today's spend roll-up — shared by /api/keys-today and `burnlens keys` CLI
# ---------------------------------------------------------------------------


async def compute_keys_today(
    db_path: str,
    api_key_budgets: Any | None,
) -> list[dict[str, Any]]:
    """Return per-label rows of today's spend, cap, % used, and status.

    Merges three sources so a fresh registration, a config-only label, and
    surprise traffic all show up:
      - labels in the ``api_keys`` table (``burnlens key register``)
      - labels with explicit caps in ``api_key_budgets.keys``
      - labels with traffic today

    Status: ``OK`` (<80%), ``WARNING`` (80-99%), ``CRITICAL`` (>=100%),
    ``NO_CAP`` when no daily cap applies. Sort: capped by pct desc, then
    uncapped by spend desc, ties broken by label.
    """
    # Lazy imports avoid a circular dependency with storage.database / keys.
    from burnlens.storage.database import get_all_keys_today_spend
    from burnlens.keys import list_keys

    tz_name = api_key_budgets.reset_timezone if api_key_budgets else "UTC"
    tz = resolve_timezone(tz_name)

    spent_today = await get_all_keys_today_spend(db_path, tz)

    labels: set[str] = set(spent_today.keys())
    if api_key_budgets:
        labels.update(api_key_budgets.keys.keys())
    try:
        registered = await list_keys(db_path)
        labels.update(row["label"] for row in registered if row.get("label"))
    except Exception as exc:  # fail open — never break the caller
        logger.warning("compute_keys_today: list_keys failed (%s); continuing", exc)

    rows: list[dict[str, Any]] = []
    for label in labels:
        spent = spent_today.get(label, 0.0)
        cap = api_key_budgets.daily_cap_for(label) if api_key_budgets else None

        if cap is None:
            pct: float | None = None
            status = "NO_CAP"
        else:
            pct = (spent / cap * 100.0) if cap > 0 else 0.0
            if pct >= 100:
                status = "CRITICAL"
            elif pct >= 80:
                status = "WARNING"
            else:
                status = "OK"

        rows.append({
            "label": label,
            "spent_usd": round(spent, 6),
            "daily_cap": cap,
            "pct_used": round(pct, 1) if pct is not None else None,
            "status": status,
            "reset_timezone": tz_name,
        })

    rows.sort(
        key=lambda r: (
            0 if r["pct_used"] is not None else 1,
            -(r["pct_used"] or 0.0),
            -r["spent_usd"],
            r["label"],
        )
    )
    return rows
