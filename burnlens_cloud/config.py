import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Cloud backend configuration from environment variables."""

    # Database
    database_url: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost/burnlens_cloud")

    # JWT
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
    jwt_algorithm: str = "HS256"
    jwt_expiration_seconds: int = 86400  # 24 hours

    # Stripe
    stripe_api_key: str = os.getenv("STRIPE_API_KEY", "")
    stripe_webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")

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

    # SSO Configuration
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_redirect_uri: str = os.getenv("GOOGLE_REDIRECT_URI", "https://api.burnlens.app/auth/google/callback")

    github_client_id: str = os.getenv("GITHUB_CLIENT_ID", "")
    github_client_secret: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    github_redirect_uri: str = os.getenv("GITHUB_REDIRECT_URI", "https://api.burnlens.app/auth/github/callback")

    # Email Configuration
    sendgrid_api_key: str = os.getenv("SENDGRID_API_KEY", "")
    sendgrid_from_email: str = os.getenv("SENDGRID_FROM_EMAIL", "noreply@burnlens.app")
    burnlens_frontend_url: str = os.getenv("BURNLENS_FRONTEND_URL", "https://burnlens.app")

    # Invitation expiry (hours)
    invitation_expiry_hours: int = 48

    # Enterprise OTEL features
    otel_encryption_key: str = os.getenv("OTEL_ENCRYPTION_KEY", "")

    # Scheduler configuration
    scheduler_enabled: bool = True
    status_check_interval_seconds: int = 60
    status_check_timeout_seconds: int = 5

    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()
