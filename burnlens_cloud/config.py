import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Cloud backend configuration from environment variables."""

    # Database
    database_url: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost/burnlens_cloud")

    # JWT — in production, JWT_SECRET must be set to >=32 chars (validated post-init).
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    jwt_algorithm: str = "HS256"
    jwt_expiration_seconds: int = 86400  # 24 hours

    # Paddle Billing
    paddle_api_key: str = os.getenv("PADDLE_API_KEY", "")
    paddle_webhook_secret: str = os.getenv("PADDLE_WEBHOOK_SECRET", "")
    paddle_cloud_price_id: str = os.getenv("PADDLE_CLOUD_PRICE_ID", "")
    paddle_teams_price_id: str = os.getenv("PADDLE_TEAMS_PRICE_ID", "")
    paddle_environment: str = os.getenv("PADDLE_ENVIRONMENT", "production")  # "sandbox" | "production"

    # App
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    environment: str = os.getenv("ENVIRONMENT", "development")

    # API key caching (seconds)
    api_key_cache_ttl: int = 60

    # Free tier limits
    free_tier_monthly_limit: int = 10000

    # Plan-based history retention (days)
    plan_history_days: dict = {
        "free": 7,
        "cloud": 90,
        "teams": 365,
        "enterprise": 3650,
    }

    # Seat limits per plan
    seat_limits: dict = {
        "free": 1,
        "cloud": 3,
        "teams": 10,
        "enterprise": 999,
    }

    # SSO Configuration (disabled — not implemented yet, API key auth only for now)
    # google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    # google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    # google_redirect_uri: str = os.getenv("GOOGLE_REDIRECT_URI", "https://api.burnlens.app/auth/google/callback")
    # github_client_id: str = os.getenv("GITHUB_CLIENT_ID", "")
    # github_client_secret: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    # github_redirect_uri: str = os.getenv("GITHUB_REDIRECT_URI", "https://api.burnlens.app/auth/github/callback")

    # Email Configuration
    sendgrid_api_key: str = os.getenv("SENDGRID_API_KEY", "")
    sendgrid_from_email: str = os.getenv("SENDGRID_FROM_EMAIL", "noreply@burnlens.app")
    cron_secret: str = os.getenv("CRON_SECRET", "")
    burnlens_frontend_url: str = os.getenv("BURNLENS_FRONTEND_URL", "https://burnlens.app")

    # Company / Legal
    parent_company: str = "Sairin Technology"
    parent_company_domain: str = "sairintechnology.com"

    # Invitation expiry (hours)
    invitation_expiry_hours: int = 48

    # Enterprise OTEL features
    otel_encryption_key: str = os.getenv("OTEL_ENCRYPTION_KEY", "")

    # Scheduler configuration
    scheduler_enabled: bool = True
    status_check_interval_seconds: int = 60
    status_check_timeout_seconds: int = 5

    # Phase 3: workspace_activity ip_address / user_agent retention window.
    # Rows older than this have those two columns NULL-ed by a background
    # purge. The audit row itself (action, timestamp, workspace_id, user_id)
    # is preserved; only the PII fields are redacted.
    activity_pii_retention_days: int = int(os.getenv("ACTIVITY_PII_RETENTION_DAYS", "90"))
    activity_pii_purge_interval_seconds: int = int(
        os.getenv("ACTIVITY_PII_PURGE_INTERVAL_SECONDS", "86400")
    )

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


# Global settings instance
settings = Settings()

# Fail-fast JWT secret validation (avoids silent fallback to a weak default).
if settings.environment == "production":
    if not settings.jwt_secret or len(settings.jwt_secret) < 32:
        raise RuntimeError(
            "JWT_SECRET env var must be set to a value of at least 32 chars in production"
        )
elif not settings.jwt_secret:
    settings.jwt_secret = "dev-only-insecure-do-not-use-in-production"


# Fail-fast PII_MASTER_KEY validation. Production boots must refuse to start
# without a real key so future PII columns can never silently write plaintext.
# In development we allow the key to be absent — the pii_crypto module is only
# exercised by tests and the phased migrations that start in Phase 1.
if settings.environment == "production":
    _pii_key = os.getenv("PII_MASTER_KEY", "").strip()
    if not _pii_key:
        raise RuntimeError(
            "PII_MASTER_KEY env var must be set in production. Generate with:\n"
            '  python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"'
        )
