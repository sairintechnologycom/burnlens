"""BL-E5 slice 2: Run → Step reconstruction over the existing fact table.

The load-bearing decision is the key ORDER — `tags.session` first, `trace_id`
second. Measured on real data: 99.6% of traffic is scan-ingested and 100% of
those rows carry a session tag, while the scan path can never carry a trace id
(it parses log files; there are no HTTP headers). Keying on trace first would
return nothing for almost every database.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from burnlens.analysis.runs import get_run, list_runs, resolve_run_id, run_to_dict
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"


def _since(days: int = 30) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _record(session=None, minutes_ago=0, **overrides) -> RequestRecord:
    tags = {}
    if session:
        tags["session"] = session
    tags.update(overrides.pop("tags", {}))
    base = dict(
        provider="anthropic",
        model="claude-opus-5",
        request_path="/v1/messages",
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        input_tokens=1_000,
        output_tokens=50,
        cost_usd=0.10,
        duration_ms=400,
        status_code=200,
        tags=tags,
    )
    base.update(overrides)
    return RequestRecord(**base)


@pytest.fixture
async def db(tmp_path):
    path = str(tmp_path / "runs.db")
    await init_db(path)
    return path


class TestGrouping:
    async def test_session_groups_steps_into_one_run(self, db):
        await insert_request(db, _record(session="sess-a", minutes_ago=3))
        await insert_request(db, _record(session="sess-a", minutes_ago=2))
        await insert_request(db, _record(session="sess-b", minutes_ago=1))

        found = await list_runs(db, since=_since())
        assert {r.run_id for r in found} == {"sess-a", "sess-b"}
        by_id = {r.run_id: r for r in found}
        assert by_id["sess-a"].step_count == 2
        assert by_id["sess-a"].cost_usd == pytest.approx(0.20)
        assert by_id["sess-a"].key_kind == "session"

    async def test_trace_id_is_the_fallback_key(self, db):
        # No session tag: an OTEL caller's traffic must still group.
        await insert_request(db, _record(trace_id=TRACE, parent_span_id="a" * 16))
        await insert_request(db, _record(trace_id=TRACE, parent_span_id="b" * 16))

        found = await list_runs(db, since=_since())
        assert len(found) == 1
        assert found[0].run_id == TRACE
        assert found[0].key_kind == "trace"
        assert found[0].step_count == 2

    async def test_session_wins_over_trace_when_both_present(self, db):
        """Order is the whole point: scan data has sessions, so sessions lead."""
        await insert_request(db, _record(session="sess-a", trace_id=TRACE))
        found = await list_runs(db, since=_since())
        assert [r.run_id for r in found] == ["sess-a"]
        assert found[0].key_kind == "session"

    async def test_ungroupable_traffic_is_excluded_not_lumped(self, db):
        """Rows with neither key must not collapse into one giant NULL run."""
        await insert_request(db, _record())
        await insert_request(db, _record())
        await insert_request(db, _record(session="sess-a"))

        found = await list_runs(db, since=_since())
        assert [r.run_id for r in found] == ["sess-a"]
        assert found[0].step_count == 1


class TestCachedPromptTokens:
    """Coding agents cache nearly the whole prompt.

    Measured on real dogfood data: a step with `input_tokens=6` and
    `cache_read=22,756` cost $0.69. Reporting "6 in" beside that price reads as
    a bug rather than a cache hit, so the prompt side is reported whole with the
    cached share alongside it.
    """

    async def test_prompt_totals_include_cache_and_keep_the_split(self, db):
        await insert_request(
            db,
            _record(
                session="s",
                input_tokens=6,
                cache_read_tokens=22_756,
                cache_write_tokens=33_868,
                output_tokens=252,
                cost_usd=0.688059,
            ),
        )
        run, steps = await get_run(db, "s", since=_since())

        assert run.prompt_tokens == 56_630
        assert run.cached_tokens == 56_624
        assert run.input_tokens == 6  # raw figure still available
        assert (steps[0].prompt_tokens, steps[0].cached_tokens) == (56_630, 56_624)


class TestOrderingAndWindow:
    async def test_cost_order_is_the_default(self, db):
        await insert_request(db, _record(session="cheap", cost_usd=0.01, minutes_ago=1))
        await insert_request(db, _record(session="pricey", cost_usd=5.00, minutes_ago=90))

        assert [r.run_id for r in await list_runs(db, since=_since())] == [
            "pricey",
            "cheap",
        ]

    async def test_recent_order_finds_the_run_you_just_made(self, db):
        await insert_request(db, _record(session="cheap", cost_usd=0.01, minutes_ago=1))
        await insert_request(db, _record(session="pricey", cost_usd=5.00, minutes_ago=90))

        found = await list_runs(db, since=_since(), order="recent")
        assert [r.run_id for r in found] == ["cheap", "pricey"]

    async def test_window_applies_to_totals_and_steps_alike(self, db):
        """A run straddling the boundary must not list steps its totals exclude."""
        await insert_request(db, _record(session="sess-a", minutes_ago=60 * 24 * 45))
        await insert_request(db, _record(session="sess-a", minutes_ago=5))

        run, steps = await get_run(db, "sess-a", since=_since(30))
        assert run.step_count == 1
        assert len(steps) == run.step_count


class TestDetail:
    async def test_steps_come_back_in_time_order(self, db):
        await insert_request(db, _record(session="s", minutes_ago=3, model="a"))
        await insert_request(db, _record(session="s", minutes_ago=1, model="c"))
        await insert_request(db, _record(session="s", minutes_ago=2, model="b"))

        run, steps = await get_run(db, "s", since=_since())
        assert [s.model for s in steps] == ["a", "b", "c"]
        assert run.models == ["a", "b", "c"]

    async def test_unknown_run_is_none_not_an_empty_run(self, db):
        assert await get_run(db, "nope", since=_since()) is None

    async def test_caller_span_is_surfaced_per_step(self, db):
        await insert_request(
            db, _record(session="s", trace_id=TRACE, parent_span_id="a" * 16)
        )
        _, steps = await get_run(db, "s", since=_since())
        assert steps[0].parent_span_id == "a" * 16


class TestPrefixResolution:
    async def test_prefix_matches_a_single_run(self, db):
        await insert_request(db, _record(session="0198f2a1-dead-beef"))
        assert await resolve_run_id(db, "0198", since=_since()) == ["0198f2a1-dead-beef"]

    async def test_ambiguous_prefix_returns_every_match(self, db):
        """The caller must be able to refuse rather than silently pick one —
        showing the wrong run's costs is worse than asking for more characters."""
        await insert_request(db, _record(session="0198-aaa"))
        await insert_request(db, _record(session="0198-bbb"))

        assert await resolve_run_id(db, "0198", since=_since()) == ["0198-aaa", "0198-bbb"]

    async def test_no_match_is_empty(self, db):
        assert await resolve_run_id(db, "zzz", since=_since()) == []


class TestDashboardApi:
    """Read-only routes, so no X-Requested-With guard — that is for mutations."""

    @pytest.fixture
    async def client(self, db):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from burnlens.dashboard.routes import router as dashboard_router

        await insert_request(db, _record(session="sess-a", minutes_ago=2))
        await insert_request(db, _record(session="sess-a", minutes_ago=1))

        app = FastAPI()
        app.state.db_path = db
        app.include_router(dashboard_router, prefix="/api")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    async def test_runs_are_listed(self, client):
        body = (await client.get("/api/runs")).json()
        assert len(body) == 1
        assert body[0]["run_id"] == "sess-a"
        assert body[0]["step_count"] == 2
        assert body[0]["key_kind"] == "session"

    async def test_run_detail_carries_steps(self, client):
        body = (await client.get("/api/runs/sess-a")).json()
        assert body["run_id"] == "sess-a"
        assert len(body["steps"]) == 2
        assert body["steps"][0]["timestamp"] <= body["steps"][1]["timestamp"]

    async def test_unknown_run_is_404_not_an_empty_run(self, client):
        assert (await client.get("/api/runs/nope")).status_code == 404

    async def test_detail_takes_a_full_id_never_a_prefix(self, client):
        """Prefix resolution is a CLI convenience. Accepting one here would let
        a short string silently return some other run's costs."""
        assert (await client.get("/api/runs/sess")).status_code == 404


class TestSerialisation:
    async def test_run_to_dict_carries_the_key_kind(self, db):
        await insert_request(db, _record(session="s", tags={"repo": "burnlens"}))
        payload = run_to_dict((await list_runs(db, since=_since()))[0])
        assert payload["run_id"] == "s"
        assert payload["key_kind"] == "session"
        assert payload["repo"] == "burnlens"
        assert payload["cost_usd"] == 0.1
