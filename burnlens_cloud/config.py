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

    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()
