import pytest


@pytest.mark.asyncio
async def test_init_db_accepts_documented_asyncpg_database_url(monkeypatch):
    """The deployment URL form must reach asyncpg without a dialect error."""
    from burnlens_cloud import database
    from burnlens_cloud.config import settings

    created = {}

    async def create_pool(url, **_kwargs):
        created["url"] = url
        raise RuntimeError("stop after connection URL validation")

    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://user:pass@db:5432/burnlens")
    monkeypatch.setattr(database.asyncpg, "create_pool", create_pool)
    with pytest.raises(RuntimeError, match="stop after"):
        await database.init_db()
    assert created["url"] == "postgresql://user:pass@db:5432/burnlens"
