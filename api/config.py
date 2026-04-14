"""Environment variable configuration for BurnLens Cloud."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://localhost:5432/burnlens")
JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

JWT_ALGORITHM: str = "HS256"
JWT_EXPIRATION_SECONDS: int = 86400  # 24 hours

API_KEY_CACHE_TTL: int = 60  # seconds

FREE_TIER_MONTHLY_LIMIT: int = 10_000

# Stripe
STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_CLOUD_PRICE_ID: str = os.getenv("STRIPE_CLOUD_PRICE_ID", "")
STRIPE_TEAMS_PRICE_ID: str = os.getenv("STRIPE_TEAMS_PRICE_ID", "")

PLAN_HISTORY_DAYS: dict[str, int] = {
    "free": 7,
    "cloud": 90,
    "teams": 365,
    "enterprise": 3650,
}
