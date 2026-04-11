"""Application settings loaded from environment / .env.local."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    resend_api_key: str = "re_test_placeholder"
    dodo_api_key: str = "dodo_test_placeholder"
    dodo_webhook_secret: str = "whsec_test_placeholder"
    secret_key: str
    environment: str = "development"

    # Tier limits
    free_retention_days: int = 7
    team_retention_days: int = 90
    max_ingest_batch_size: int = 500

    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
    )


settings = Settings()
