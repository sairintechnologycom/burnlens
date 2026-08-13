"""Guard the tag plumbing between the OSS proxy and the cloud backend.

A tag has to survive six hops to be useful end to end:

1. ``burnlens.proxy.interceptor._ALLOWED_TAGS``  -- header/env extraction
2. the local SQLite ``tags`` JSON column          -- automatic
3. ``burnlens.cloud.sync._row_to_payload``        -- flattened to ``tag_<name>``
4. ``burnlens.cloud.sync.SYNC_ALLOWED_FIELDS``    -- privacy whitelist
5. ``burnlens_cloud.models._lift_flat_tags``      -- re-nested into ``tags``
6. the cloud Postgres ``tags`` JSONB column       -- automatic

Hops 3 and 4 are now derived from ``CLOUD_SYNCED_TAGS``, so they cannot drift.
Hop 5 lives in a separate deployable (this backend ships to Railway, the proxy
to PyPI) and cannot import the proxy's copy, so it is duplicated -- and the
duplicate is exactly the kind of thing that rots. These tests pin it.

This is the same failure family as tests/test_provider_hooks_wired.py: code that
exists, is unit-tested in isolation, and is never reached in the real path. Here
the symptom would be silent -- attribution simply empty in the cloud dashboard,
with no error anywhere.
"""
from __future__ import annotations

import pytest

from burnlens.cloud.sync import (
    CLOUD_SYNCED_TAGS,
    SYNC_ALLOWED_FIELDS,
    _row_to_payload,
    _sanitize_record,
)
from burnlens.proxy.interceptor import _ALLOWED_TAGS

# Phase A of the economics-graph roadmap: agent/workflow attribution is the
# foundation every later phase joins on, so name them explicitly rather than
# trusting the generic checks below.
ECONOMICS_GRAPH_TAGS = ("agent_id", "workflow_id")

# The run key for the hosted Run -> Step view. Same reasoning: name it, because
# without it the SaaS has nothing to group requests by.
RUN_KEY_TAGS = ("session",)


@pytest.mark.parametrize("tag", ECONOMICS_GRAPH_TAGS)
def test_economics_graph_tags_are_collectable(tag):
    assert tag in _ALLOWED_TAGS


@pytest.mark.parametrize("tag", ECONOMICS_GRAPH_TAGS)
def test_economics_graph_tags_are_cloud_synced(tag):
    assert tag in CLOUD_SYNCED_TAGS


@pytest.mark.parametrize("tag", RUN_KEY_TAGS)
def test_run_key_tags_are_cloud_synced(tag):
    """Scans write `session` straight to SQLite; the proxy takes it as a header.

    Both paths are useless to the hosted run view unless the tag syncs.
    """
    assert tag in CLOUD_SYNCED_TAGS
    assert tag in _ALLOWED_TAGS


def test_streaming_payload_tag_omissions_are_deliberate():
    """Hop 5b: the Kafka payload is narrower than CLOUD_SYNCED_TAGS on purpose.

    ingest.py builds it from STREAM_TAG_COLUMNS -- the tags with a dedicated
    ClickHouse column. A tag added to CLOUD_SYNCED_TAGS is therefore NOT
    streamed, which is correct (no column to land in) but was previously a
    silent hand-written drop. This pins the delta so adding a tag forces the
    decision instead of skipping it.
    """
    pytest.importorskip("burnlens_cloud.models", reason="cloud deps not installed")
    from burnlens_cloud.models import STREAM_TAG_COLUMNS

    assert set(STREAM_TAG_COLUMNS) <= set(CLOUD_SYNCED_TAGS)
    unstreamed = [t for t in CLOUD_SYNCED_TAGS if t not in STREAM_TAG_COLUMNS]
    assert unstreamed == ["agent_id", "workflow_id", "session"], (
        f"streaming-plane tag coverage changed: {unstreamed}. Either add a "
        "column to the ClickHouse queue/raw tables + both materialized views "
        "(clickhouse.py) and list the tag in STREAM_TAG_COLUMNS, or update this "
        "assertion to record that it stays Postgres-only."
    )


def test_every_synced_tag_is_collectable():
    """A tag can't be synced if the interceptor never extracts it."""
    missing = [t for t in CLOUD_SYNCED_TAGS if t not in _ALLOWED_TAGS]
    assert not missing, f"synced but never extracted: {missing}"


def test_every_synced_tag_survives_the_privacy_whitelist():
    """Hop 4: _sanitize_record drops anything not in SYNC_ALLOWED_FIELDS."""
    missing = [t for t in CLOUD_SYNCED_TAGS if f"tag_{t}" not in SYNC_ALLOWED_FIELDS]
    assert not missing, f"flattened but stripped before upload: {missing}"


def test_backend_renests_every_synced_tag():
    """Hop 5: the backend's duplicated list must match the proxy's."""
    pytest.importorskip("burnlens_cloud.models", reason="cloud deps not installed")
    from burnlens_cloud.models import CLOUD_SYNCED_TAGS as BACKEND_TAGS

    assert tuple(BACKEND_TAGS) == tuple(CLOUD_SYNCED_TAGS), (
        "burnlens_cloud.models.CLOUD_SYNCED_TAGS drifted from "
        "burnlens.cloud.sync.CLOUD_SYNCED_TAGS -- tags present in one but not "
        "the other are silently dropped on ingest"
    )


def _row(**overrides):
    row = {
        "timestamp": "2026-08-09T00:00:00+00:00",
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "cost_usd": 0.5,
        "tags": {t: f"{t}-value" for t in CLOUD_SYNCED_TAGS},
    }
    row.update(overrides)
    return row


def test_row_to_payload_flattens_every_synced_tag():
    """Hop 3, against the real function rather than a reimplementation."""
    payload = _row_to_payload(_row())
    for tag in CLOUD_SYNCED_TAGS:
        assert payload[f"tag_{tag}"] == f"{tag}-value"


def test_synced_tags_survive_sanitize():
    """Hops 3+4 together: what actually leaves the machine."""
    sanitized = _sanitize_record(_row_to_payload(_row()))
    for tag in CLOUD_SYNCED_TAGS:
        assert sanitized.get(f"tag_{tag}") == f"{tag}-value"


def test_unsynced_tags_stay_local():
    """repo/dev/pr/branch name private code and people -- they must NOT leave.

    This is a privacy assertion, not a plumbing one: it fails if somebody adds
    one of them to CLOUD_SYNCED_TAGS without making that decision deliberately.
    """
    tags = {"repo": "acme/secret", "dev": "someone", "pr": "42", "branch": "wip"}
    sanitized = _sanitize_record(_row_to_payload(_row(tags=tags)))
    for leaked in ("tag_repo", "tag_dev", "tag_pr", "tag_branch"):
        assert leaked not in sanitized


def test_row_to_payload_tolerates_json_string_tags():
    """Rows come straight from SQLite, where `tags` is TEXT."""
    import json

    payload = _row_to_payload(_row(tags=json.dumps({"agent_id": "a1"})))
    assert payload["tag_agent_id"] == "a1"
    assert payload["tag_team"] is None


def test_tool_calls_is_synced():
    payload = _row_to_payload(_row(tool_calls=3))
    assert payload["tool_calls"] == 3
    assert _sanitize_record(payload)["tool_calls"] == 3


def test_source_is_synced():
    """Without it the cloud cannot tell agent-scan rows from proxied traffic."""
    sanitized = _sanitize_record(_row_to_payload(_row(source="scan_claude")))
    assert sanitized["source"] == "scan_claude"


def test_source_missing_on_old_local_schema_is_tolerated():
    """Rows come from `SELECT *`; a DB predating the column has no key at all."""
    assert _row_to_payload(_row())["source"] is None


def test_backend_lifts_flat_tags_into_nested_tags():
    """End of hop 5: the payload the proxy sends parses into nested tags."""
    pytest.importorskip("burnlens_cloud.models", reason="cloud deps not installed")
    # RequestRecordBase, not ...Create: this is the model IngestRequest.records
    # actually parses, so the test exercises the real wire path.
    from burnlens_cloud.models import RequestRecordBase

    payload = _sanitize_record(_row_to_payload(_row(tool_calls=2)))
    record = RequestRecordBase(**payload)

    for tag in CLOUD_SYNCED_TAGS:
        assert record.tags.get(tag) == f"{tag}-value"
    assert record.tool_calls == 2


def test_explicit_tags_object_wins_over_flat_keys():
    """Regression guard on _lift_flat_tags' documented precedence."""
    pytest.importorskip("burnlens_cloud.models", reason="cloud deps not installed")
    # RequestRecordBase, not ...Create: this is the model IngestRequest.records
    # actually parses, so the test exercises the real wire path.
    from burnlens_cloud.models import RequestRecordBase

    record = RequestRecordBase(
        timestamp="2026-08-09T00:00:00+00:00",
        provider="openai",
        model="gpt-4.1-mini",
        tags={"agent_id": "explicit"},
        tag_agent_id="flat",
    )
    assert record.tags == {"agent_id": "explicit"}
