"""Environment variable configuration for BurnLens Cloud."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://localhost:5432/burnlens")
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

_JWT_SECRET = os.getenv("JWT_SECRET", "")
if ENVIRONMENT == "production":
    if not _JWT_SECRET or len(_JWT_SECRET) < 32:
        raise RuntimeError(
            "JWT_SECRET env var must be set to a value of at least 32 chars in production"
        )
elif not _JWT_SECRET:
    _JWT_SECRET = "dev-only-insecure-do-not-use-in-production"
JWT_SECRET: str = _JWT_SECRET

JWT_ALGORITHM: str = "HS256"
JWT_EXPIRATION_SECONDS: int = 86400  # 24 hours

API_KEY_CACHE_TTL: int = 60  # seconds

FREE_TIER_MONTHLY_LIMIT: int = 10_000

PLAN_HISTORY_DAYS: dict[str, int] = {
    "free": 7,
    "cloud": 90,
    "teams": 365,
    "enterprise": 3650,
}

# Seat limits per plan
PLAN_SEAT_LIMITS: dict[str, int | None] = {
    "free": 1,
    "cloud": 3,
    "teams": 10,
    "enterprise": None,  # unlimited
}

# SMTP for invitation emails
SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASS: str = os.getenv("SMTP_PASS", "")
SMTP_FROM: str = os.getenv("SMTP_FROM", "noreply@burnlens.app")

INVITATION_EXPIRY_HOURS: int = 48

# OAuth SSO
GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "")
BASE_URL: str = os.getenv("BASE_URL", "https://burnlens.app")

# Encryption (Fernet key for OTEL API keys)
OTEL_ENCRYPTION_KEY: str = os.getenv("OTEL_ENCRYPTION_KEY", "")
