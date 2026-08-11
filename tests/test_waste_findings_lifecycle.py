"""BL-E1: subject-scoped findings, stable fingerprints, status lifecycle."""
from __future__ import annotations

import pytest

from burnlens.analysis.waste import (
    ModelOverkillDetector,
    WasteFinding,
    run_all_detectors,
)
from burnlens.storage.database import init_db
from burnlens.storage.findings import (
    get_waste_summary,
    list_findings,
    set_finding_status,
    sync_findings,
)


def _request(**overrides):
    base = {
        "model": "claude-opus-5",
        "input_tokens": 1_000,
        "output_tokens": 50,
        "cost_usd": 0.10,
        "tags": {},
        "system_prompt_hash": None,
        "prompt_system_tokens": 0,
        "prompt_tools_tokens": 0,
        "prompt_rag_tokens": 0,
        "prompt_history_tokens": 0,
        "cache_read_tokens": 0,
    }
    base.update(overrides)
    return base


@pytest.fixture
async def db(tmp_path):
    # Full init_db: resolving a finding snapshots the subject's spend, so the
    # requests table has to exist.
    path = str(tmp_path / "findings.db")
    await init_db(path)
    return path


# ---------------------------------------------------------------------------
# Detection: subjects and empty state
# ---------------------------------------------------------------------------


def test_findings_are_split_per_workflow():
    """Two workflows wasting money are two findings, not one lumped total."""
    requests = [
        _request(tags={"workflow_id": "invoice-gen"}) for _ in range(3)
    ] + [_request(tags={"workflow_id": "summarizer"}) for _ in range(3)]

    findings = ModelOverkillDetector().run(requests)

    subjects = {(f.subject_type, f.subject_key) for f in findings}
    assert subjects == {("workflow", "invoice-gen"), ("workflow", "summarizer")}
    assert all(f.affected_count == 3 for f in findings)


def test_untagged_requests_fall_back_to_model_subject():
    findings = ModelOverkillDetector().run([_request(model="gpt-5.2-pro")])
    assert findings[0].subject_type == "model"
    assert findings[0].subject_key == "gpt-5.2-pro"


def test_clean_workspace_emits_no_findings():
    """A clean run means an empty list, not eight zero-waste rows."""
    clean = [_request(model="gpt-4o-mini", output_tokens=500, cost_usd=0.0001)]
    assert run_all_detectors(clean) == []


def test_no_requests_emits_no_findings():
    assert run_all_detectors([]) == []


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


def test_fingerprint_is_stable_as_evidence_moves():
    """The whole lifecycle rests on this: same issue keeps its identity.

    If the dollar figure or the description leaked into the fingerprint, every
    detection run would mint a new finding and 'resolved' would never stick.
    """
    a = WasteFinding(
        detector="ModelOverkillDetector",
        severity="high",
        title="Model Overkill",
        description="184 requests ...",
        estimated_waste_usd=84.30,
        affected_count=184,
        subject_type="workflow",
        subject_key="invoice-gen",
    )
    b = WasteFinding(
        detector="ModelOverkillDetector",
        severity="medium",           # changed
        title="Model Overkill",
        description="12 requests ...",  # changed
        estimated_waste_usd=3.10,       # changed
        affected_count=12,              # changed
        subject_type="workflow",
        subject_key="invoice-gen",
    )
    assert a.fingerprint == b.fingerprint


def test_fingerprint_differs_per_subject():
    def make(subject_key):
        return WasteFinding(
            detector="ModelOverkillDetector",
            severity="high",
            title="Model Overkill",
            description="",
            subject_type="workflow",
            subject_key=subject_key,
        )

    assert make("invoice-gen").fingerprint != make("summarizer").fingerprint


# ---------------------------------------------------------------------------
# Persistence + lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_is_idempotent(db):
    """Re-running detection updates in place — it does not duplicate."""
    findings = ModelOverkillDetector().run(
        [_request(tags={"workflow_id": "invoice-gen"})]
    )

    first = await sync_findings(db, findings)
    second = await sync_findings(db, findings)

    assert first.new == 1
    assert second.new == 0 and second.updated == 1
    stored = await list_findings(db)
    assert len(stored) == 1
    assert stored[0].detection_count == 2


@pytest.mark.asyncio
async def test_status_survives_the_next_detection_run(db):
    """Acknowledging a finding must not be undone by the next sync."""
    findings = ModelOverkillDetector().run(
        [_request(tags={"workflow_id": "invoice-gen"})]
    )
    await sync_findings(db, findings)
    fingerprint = findings[0].fingerprint

    await set_finding_status(db, fingerprint, "acknowledged")
    await sync_findings(db, findings)

    stored = await list_findings(db)
    assert stored[0].status == "acknowledged"


@pytest.mark.asyncio
async def test_resolved_finding_reopens_when_waste_returns(db):
    """A fix that did not hold has to come back, or the list quietly lies."""
    findings = ModelOverkillDetector().run(
        [_request(tags={"workflow_id": "invoice-gen"})]
    )
    await sync_findings(db, findings)
    fingerprint = findings[0].fingerprint

    await set_finding_status(db, fingerprint, "resolved")
    result = await sync_findings(db, findings)

    stored = await list_findings(db)
    assert result.reopened == 1
    assert stored[0].status == "open"
    # resolved_at survives: a fix WAS applied then, even though it did not
    # hold, and savings verification needs that anchor to compare against.
    assert stored[0].resolved_at is not None


@pytest.mark.asyncio
async def test_accepted_risk_is_never_reopened(db):
    """The user already decided; re-nagging is how a findings list gets ignored."""
    findings = ModelOverkillDetector().run(
        [_request(tags={"workflow_id": "invoice-gen"})]
    )
    await sync_findings(db, findings)

    await set_finding_status(db, findings[0].fingerprint, "accepted_risk")
    await sync_findings(db, findings)

    stored = await list_findings(db)
    assert stored[0].status == "accepted_risk"


@pytest.mark.asyncio
async def test_resolving_captures_a_baseline_for_savings_verification(db):
    """BL-E3 needs a before-figure, and it cannot be reconstructed later."""
    findings = ModelOverkillDetector().run(
        [_request(tags={"workflow_id": "invoice-gen"}, cost_usd=1.00) for _ in range(4)]
    )
    await sync_findings(db, findings)
    waste_at_resolution = findings[0].estimated_waste_usd

    await set_finding_status(db, findings[0].fingerprint, "resolved")

    stored = await list_findings(db, status="resolved")
    assert stored[0].baseline_waste_usd == pytest.approx(waste_at_resolution)


@pytest.mark.asyncio
async def test_resolved_waste_leaves_the_outstanding_total(db):
    """Otherwise the headline number can never go down and nobody trusts it."""
    findings = ModelOverkillDetector().run(
        [_request(tags={"workflow_id": "invoice-gen"}) for _ in range(3)]
        + [_request(tags={"workflow_id": "summarizer"}) for _ in range(3)]
    )
    await sync_findings(db, findings)

    before = await get_waste_summary(db)
    assert before["open_finding_count"] == 2

    await set_finding_status(db, findings[0].fingerprint, "resolved")
    after = await get_waste_summary(db)

    assert after["open_finding_count"] == 1
    assert after["detected_waste_usd"] < before["detected_waste_usd"]


@pytest.mark.asyncio
async def test_invalid_status_is_rejected(db):
    with pytest.raises(ValueError):
        await set_finding_status(db, "whatever", "fixed-ish")


@pytest.mark.asyncio
async def test_unknown_fingerprint_reports_miss(db):
    assert await set_finding_status(db, "does-not-exist", "resolved") is False
