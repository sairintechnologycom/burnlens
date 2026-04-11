"""Authentication and rate-limiting dependencies."""

import hashlib
import time

import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from burnlens_cloud.config import settings
from burnlens_cloud.db.engine import get_db
from burnlens_cloud.db.models import Organization

TIER_RATE_LIMITS: dict[str, int] = {
    "free": 100,
    "personal": 500,
    "team": 1000,
    "enterprise": 5000,
}

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Lazy-init shared Redis connection."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url)
    return _redis


async def get_current_org(
    x_api_key: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """Authenticate request via X-API-Key header and return the Organization."""
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    result = await db.execute(
        select(Organization).where(Organization.api_key_hash == key_hash)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return org


async def rate_limit(
    org: Organization = Depends(get_current_org),
    redis: aioredis.Redis = Depends(get_redis),
) -> Organization:
    """Enforce per-org rate limiting. Returns the org on success, raises 429 on excess."""
    minute_bucket = int(time.time()) // 60
    key = f"rate:{org.id}:{minute_bucket}"
    limit = TIER_RATE_LIMITS.get(org.tier, 100)

    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 120)

    if count > limit:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(60 - int(time.time()) % 60)},
        )

    return org
