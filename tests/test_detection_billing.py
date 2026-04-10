"""Tests for billing API parsers (OpenAI, Anthropic, Google) and scheduler."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
import respx

from apscheduler.triggers.interval import IntervalTrigger

from burnlens.config import BurnLensConfig
from burnlens.storage.database import init_db
from burnlens.storage.queries import get_assets, get_discovery_events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(tmp_path):
    """Initialised in-memory SQLite DB path."""
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return db_path


@pytest.fixture
def config_with_keys(tmp_path):
    """BurnLensConfig with admin keys set."""
    cfg = BurnLensConfig()
    cfg.db_path = str(tmp_path / "test.db")
    cfg.openai_admin_key = "sk-openai-admin-key"
    cfg.anthropic_admin_key = "sk-ant-admin-key"
    return cfg


@pytest.fixture
def config_no_keys(tmp_path):
    """BurnLensConfig with admin keys left as None."""
    cfg = BurnLensConfig()
    cfg.db_path = str(tmp_path / "test.db")
    return cfg


# ---------------------------------------------------------------------------
# OpenAI billing parser tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_fetch_openai_assets():
    """Parser returns list of dicts with model, api_key_id, token counts."""
    from burnlens.detection.billing import fetch_openai_usage

    mock_response = {
        "data": [
            {
                "results": [
                    {
                        "model": "gpt-4o",
                        "api_key_id": "key_abc123",
                        "input_tokens": 1000,
                        "output_tokens": 500,
                        "num_model_requests": 10,
                    }
                ]
            }
        ],
        "has_more": False,
    }

    respx.get("https://api.openai.com/v1/organization/usage/completions").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    results = await fetch_openai_usage("sk-openai-admin-key")

    assert len(results) == 1
    assert results[0]["model"] == "gpt-4o"
    assert results[0]["api_key_id"] == "key_abc123"
    assert results[0]["input_tokens"] == 1000
    assert results[0]["output_tokens"] == 500
    assert results[0]["num_model_requests"] == 10


@pytest.mark.asyncio
@respx.mock
async def test_fetch_openai_assets_group_by_params():
    """Parser sends group_by[]=model and group_by[]=api_key_id query params."""
    from burnlens.detection.billing import fetch_openai_usage

    mock_response = {"data": [], "has_more": False}
    route = respx.get("https://api.openai.com/v1/organization/usage/completions").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    await fetch_openai_usage("sk-openai-admin-key")

    # Verify request was made
    assert route.called
    request = route.calls[0].request
    assert "group_by%5B%5D=model" in str(request.url) or "group_by[]=model" in str(request.url)
    assert "group_by%5B%5D=api_key_id" in str(request.url) or "group_by[]=api_key_id" in str(request.url)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_openai_pagination():
    """Multi-page OpenAI responses are fully collected via has_more + next_page."""
    from burnlens.detection.billing import fetch_openai_usage

    page1 = {
        "data": [
            {
                "results": [
                    {
                        "model": "gpt-4o",
                        "api_key_id": "key_page1",
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "num_model_requests": 1,
                    }
                ]
            }
        ],
        "has_more": True,
        "next_page": "cursor_abc",
    }
    page2 = {
        "data": [
            {
                "results": [
                    {
                        "model": "gpt-4-turbo",
                        "api_key_id": "key_page2",
                        "input_tokens": 200,
                        "output_tokens": 100,
                        "num_model_requests": 2,
                    }
                ]
            }
        ],
        "has_more": False,
    }

    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json=page1)
        return httpx.Response(200, json=page2)

    respx.get("https://api.openai.com/v1/organization/usage/completions").mock(side_effect=side_effect)

    results = await fetch_openai_usage("sk-openai-admin-key")

    assert len(results) == 2
    models = {r["model"] for r in results}
    assert "gpt-4o" in models
    assert "gpt-4-turbo" in models
    assert call_count == 2


@pytest.mark.asyncio
async def test_fetch_openai_no_key(caplog):
    """When admin key is None, fetch_openai_usage returns [] and logs a warning."""
    import logging
    from burnlens.detection.billing import fetch_openai_usage

    with caplog.at_level(logging.WARNING):
        results = await fetch_openai_usage(None)

    assert results == []
    assert any("openai" in msg.lower() for msg in caplog.messages)


# ---------------------------------------------------------------------------
# Anthropic billing parser tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_fetch_anthropic_assets():
    """Parser returns list of dicts with model and token counts."""
    from burnlens.detection.billing import fetch_anthropic_usage

    mock_response = {
        "data": [
            {
                "model": "claude-3-5-sonnet-20241022",
                "input_tokens": 2000,
                "output_tokens": 800,
                "num_model_requests": 5,
            }
        ],
        "has_more": False,
    }

    respx.get("https://api.anthropic.com/v1/organizations/usage_report/messages").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    results = await fetch_anthropic_usage("sk-ant-admin-key")

    assert len(results) == 1
    assert results[0]["model"] == "claude-3-5-sonnet-20241022"
    assert results[0]["input_tokens"] == 2000
    assert results[0]["output_tokens"] == 800


@pytest.mark.asyncio
@respx.mock
async def test_fetch_anthropic_auth_headers():
    """Anthropic parser sends x-api-key and anthropic-version headers."""
    from burnlens.detection.billing import fetch_anthropic_usage

    mock_response = {"data": [], "has_more": False}
    route = respx.get("https://api.anthropic.com/v1/organizations/usage_report/messages").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    await fetch_anthropic_usage("sk-ant-admin-key")

    assert route.called
    request = route.calls[0].request
    assert request.headers.get("x-api-key") == "sk-ant-admin-key"
    assert "anthropic-version" in request.headers


@pytest.mark.asyncio
@respx.mock
async def test_fetch_anthropic_pagination():
    """Multi-page Anthropic responses are fully collected."""
    from burnlens.detection.billing import fetch_anthropic_usage

    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json={
                "data": [{"model": "claude-3-5-sonnet-20241022", "input_tokens": 100, "output_tokens": 50, "num_model_requests": 1}],
                "has_more": True,
                "next_page": "cursor_xyz",
            })
        return httpx.Response(200, json={
            "data": [{"model": "claude-3-haiku-20240307", "input_tokens": 200, "output_tokens": 100, "num_model_requests": 2}],
            "has_more": False,
        })

    respx.get("https://api.anthropic.com/v1/organizations/usage_report/messages").mock(side_effect=side_effect)

    results = await fetch_anthropic_usage("sk-ant-admin-key")

    assert len(results) == 2
    models = {r["model"] for r in results}
    assert "claude-3-5-sonnet-20241022" in models
    assert "claude-3-haiku-20240307" in models
    assert call_count == 2


@pytest.mark.asyncio
async def test_fetch_anthropic_no_key(caplog):
    """When admin key is None, fetch_anthropic_usage returns [] and logs a warning."""
    import logging
    from burnlens.detection.billing import fetch_anthropic_usage

    with caplog.at_level(logging.WARNING):
        results = await fetch_anthropic_usage(None)

    assert results == []
    assert any("anthropic" in msg.lower() for msg in caplog.messages)


# ---------------------------------------------------------------------------
# Google billing parser tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_google_stub(caplog):
    """Google fetch returns empty list and logs info about proxy-only detection."""
    import logging
    from burnlens.detection.billing import fetch_google_usage

    with caplog.at_level(logging.INFO):
        results = await fetch_google_usage()

    assert results == []
    assert any("proxy" in msg.lower() or "google" in msg.lower() for msg in caplog.messages)


# ---------------------------------------------------------------------------
# run_all_parsers integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_all_parsers_upserts_assets(db, config_with_keys):
    """run_all_parsers upserts ai_assets for each result and creates discovery events."""
    from burnlens.detection.billing import run_all_parsers

    await init_db(db)
    config_with_keys.db_path = db

    openai_results = [
        {
            "model": "gpt-4o",
            "api_key_id": "key_abc",
            "input_tokens": 1000,
            "output_tokens": 500,
            "num_model_requests": 10,
        }
    ]
    anthropic_results = [
        {
            "model": "claude-3-5-sonnet-20241022",
            "input_tokens": 2000,
            "output_tokens": 800,
            "num_model_requests": 5,
        }
    ]

    with (
        patch("burnlens.detection.billing.fetch_openai_usage", new=AsyncMock(return_value=openai_results)),
        patch("burnlens.detection.billing.fetch_anthropic_usage", new=AsyncMock(return_value=anthropic_results)),
        patch("burnlens.detection.billing.fetch_google_usage", new=AsyncMock(return_value=[])),
    ):
        await run_all_parsers(db, config_with_keys)

    assets = await get_assets(db)
    assert len(assets) == 2

    providers = {a.provider for a in assets}
    assert "openai" in providers
    assert "anthropic" in providers


@pytest.mark.asyncio
async def test_run_all_parsers_new_assets_are_shadow(db, config_with_keys):
    """New assets discovered via billing API get status=shadow."""
    from burnlens.detection.billing import run_all_parsers

    await init_db(db)
    config_with_keys.db_path = db

    openai_results = [
        {
            "model": "gpt-4o",
            "api_key_id": "key_abc",
            "input_tokens": 1000,
            "output_tokens": 500,
            "num_model_requests": 10,
        }
    ]

    with (
        patch("burnlens.detection.billing.fetch_openai_usage", new=AsyncMock(return_value=openai_results)),
        patch("burnlens.detection.billing.fetch_anthropic_usage", new=AsyncMock(return_value=[])),
        patch("burnlens.detection.billing.fetch_google_usage", new=AsyncMock(return_value=[])),
    ):
        await run_all_parsers(db, config_with_keys)

    assets = await get_assets(db, provider="openai")
    assert len(assets) == 1
    assert assets[0].status == "shadow"


@pytest.mark.asyncio
async def test_run_all_parsers_discovery_events_for_new_assets(db, config_with_keys):
    """New assets get a new_asset_detected discovery event."""
    from burnlens.detection.billing import run_all_parsers

    await init_db(db)
    config_with_keys.db_path = db

    openai_results = [
        {
            "model": "gpt-4o",
            "api_key_id": "key_abc",
            "input_tokens": 1000,
            "output_tokens": 500,
            "num_model_requests": 10,
        }
    ]

    with (
        patch("burnlens.detection.billing.fetch_openai_usage", new=AsyncMock(return_value=openai_results)),
        patch("burnlens.detection.billing.fetch_anthropic_usage", new=AsyncMock(return_value=[])),
        patch("burnlens.detection.billing.fetch_google_usage", new=AsyncMock(return_value=[])),
    ):
        await run_all_parsers(db, config_with_keys)

    events = await get_discovery_events(db, event_type="new_asset_detected")
    assert len(events) == 1
    assert events[0].event_type == "new_asset_detected"


@pytest.mark.asyncio
async def test_run_all_parsers_no_duplicate_assets(db, config_with_keys):
    """Running run_all_parsers twice does not create duplicate assets."""
    from burnlens.detection.billing import run_all_parsers

    await init_db(db)
    config_with_keys.db_path = db

    openai_results = [
        {
            "model": "gpt-4o",
            "api_key_id": "key_abc",
            "input_tokens": 1000,
            "output_tokens": 500,
            "num_model_requests": 10,
        }
    ]

    for _ in range(2):
        with (
            patch("burnlens.detection.billing.fetch_openai_usage", new=AsyncMock(return_value=openai_results)),
            patch("burnlens.detection.billing.fetch_anthropic_usage", new=AsyncMock(return_value=[])),
            patch("burnlens.detection.billing.fetch_google_usage", new=AsyncMock(return_value=[])),
        ):
            await run_all_parsers(db, config_with_keys)

    assets = await get_assets(db, provider="openai")
    assert len(assets) == 1  # No duplicate


@pytest.mark.asyncio
async def test_run_all_parsers_api_key_hashed(db, config_with_keys):
    """api_key_id from billing API is stored as SHA-256 hash, not raw."""
    from burnlens.detection.billing import run_all_parsers

    await init_db(db)
    config_with_keys.db_path = db

    raw_key_id = "key_abc123"
    expected_hash = _sha256(raw_key_id)

    openai_results = [
        {
            "model": "gpt-4o",
            "api_key_id": raw_key_id,
            "input_tokens": 1000,
            "output_tokens": 500,
            "num_model_requests": 10,
        }
    ]

    with (
        patch("burnlens.detection.billing.fetch_openai_usage", new=AsyncMock(return_value=openai_results)),
        patch("burnlens.detection.billing.fetch_anthropic_usage", new=AsyncMock(return_value=[])),
        patch("burnlens.detection.billing.fetch_google_usage", new=AsyncMock(return_value=[])),
    ):
        await run_all_parsers(db, config_with_keys)

    assets = await get_assets(db, provider="openai")
    assert assets[0].api_key_hash == expected_hash
    assert raw_key_id not in (assets[0].api_key_hash or "")


# ---------------------------------------------------------------------------
# Scheduler tests
# ---------------------------------------------------------------------------


def test_scheduler_registers_job():
    """register_detection_jobs creates a detection_hourly job with 1-hour interval
    and a deferred first_run_time (approximately 1 hour from now)."""
    from burnlens.detection.scheduler import register_detection_jobs, reset_scheduler

    reset_scheduler()

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    cfg = BurnLensConfig()
    cfg.db_path = "/tmp/test.db"

    before = datetime.now(timezone.utc)
    register_detection_jobs(scheduler, cfg.db_path, cfg)
    after = datetime.now(timezone.utc)

    job = scheduler.get_job("detection_hourly")
    assert job is not None, "detection_hourly job not found"

    # Trigger must be an interval trigger
    assert isinstance(job.trigger, IntervalTrigger)

    # First run must be approximately 1 hour from now (not immediate)
    from datetime import timedelta

    assert job.next_run_time is not None
    # next_run_time should be between now+55min and now+65min
    lower = before + timedelta(minutes=55)
    upper = after + timedelta(minutes=65)
    assert lower <= job.next_run_time <= upper, (
        f"next_run_time {job.next_run_time} is not within expected range "
        f"[{lower}, {upper}]"
    )

    reset_scheduler()


@pytest.mark.asyncio
async def test_run_detection_calls_parsers():
    """run_detection calls run_all_parsers and classify_new_assets with correct args."""
    from burnlens.detection.scheduler import run_detection

    cfg = BurnLensConfig()
    cfg.db_path = "/tmp/test_run_detection.db"

    with (
        patch(
            "burnlens.detection.scheduler.run_all_parsers",
            new_callable=AsyncMock,
        ) as mock_parsers,
        patch(
            "burnlens.detection.scheduler.classify_new_assets",
            new_callable=AsyncMock,
            return_value=0,
        ) as mock_classify,
    ):
        await run_detection(db_path=cfg.db_path, config=cfg)

    mock_parsers.assert_awaited_once_with(cfg.db_path, cfg)
    mock_classify.assert_awaited_once_with(cfg.db_path)


@pytest.mark.asyncio
async def test_run_detection_swallows_errors():
    """run_detection does not raise even when run_all_parsers raises an exception."""
    from burnlens.detection.scheduler import run_detection

    cfg = BurnLensConfig()
    cfg.db_path = "/tmp/test_run_detection_error.db"

    with patch(
        "burnlens.detection.scheduler.run_all_parsers",
        new_callable=AsyncMock,
        side_effect=Exception("Simulated billing API failure"),
    ):
        # Must not raise — fail open per design
        await run_detection(db_path=cfg.db_path, config=cfg)
