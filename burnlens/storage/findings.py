"""Persistence + lifecycle for waste findings (BL-E1).

Detectors in ``burnlens/analysis/waste.py`` are pure — they recompute findings
from request rows and return them. This module is the only thing that writes
them down, so the CLI, reports, and dashboard can all run detection with no
database side effects.

The lifecycle is what turns detection into a workflow:

    open ──▶ acknowledged ──▶ resolved
      └────▶ accepted_risk

A finding keeps its identity across runs via its fingerprint, so "I fixed this"
survives the next detection pass, and a resolved finding that reappears is
reopened rather than silently duplicated.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from burnlens.analysis.waste import DETECTOR_VERSION, WasteFinding

VALID_STATUSES = ("open", "acknowledged", "resolved", "accepted_risk")

# How much history the baseline snapshot covers, and how long the after-window
# must run before a fix can be judged. The same length on both sides so the
# comparison is like-for-like.
BASELINE_WINDOW_DAYS = 7


@dataclass
class StoredFinding:
    """A finding as it lives in the database, with its lifecycle state."""

    fingerprint: str
    detector: str
    subject_type: str
    subject_key: str
    severity: str
    title: str
    description: str
    estimated_waste_usd: float
    affected_count: int
    evidence: dict[str, Any]
    status: str
    first_seen_at: str
    last_seen_at: str
    resolved_at: str | None
    baseline_waste_usd: float | None
    baseline_cost_usd: float | None
    baseline_requests: int | None
    baseline_window_days: int | None
    detection_count: int
    detector_version: int


@dataclass
class SyncResult:
    """What one sync pass changed. Returned so callers can log or report it."""

    new: int = 0
    updated: int = 0
    reopened: int = 0
    unchanged_resolved: int = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_finding(row: aiosqlite.Row) -> StoredFinding:
    try:
        evidence = json.loads(row["evidence"])
    except (ValueError, TypeError):
        evidence = {}
    return StoredFinding(
        fingerprint=row["fingerprint"],
        detector=row["detector"],
        subject_type=row["subject_type"],
        subject_key=row["subject_key"],
        severity=row["severity"],
        title=row["title"],
        description=row["description"],
        estimated_waste_usd=row["estimated_waste_usd"],
        affected_count=row["affected_count"],
        evidence=evidence,
        status=row["status"],
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        resolved_at=row["resolved_at"],
        baseline_waste_usd=row["baseline_waste_usd"],
        baseline_cost_usd=row["baseline_cost_usd"],
        baseline_requests=row["baseline_requests"],
        baseline_window_days=row["baseline_window_days"],
        detection_count=row["detection_count"],
        detector_version=row["detector_version"],
    )


async def sync_findings(
    db_path: str, findings: list[WasteFinding]
) -> SyncResult:
    """Persist a detection pass, preserving lifecycle state.

    Rules:

    - Unseen fingerprint → inserted as ``open``.
    - Seen fingerprint → evidence refreshed, ``last_seen_at`` bumped,
      ``detection_count`` incremented, lifecycle state left alone.
    - Previously ``resolved`` but detected again → reopened. A fix that did not
      hold must come back, otherwise the list quietly lies.
    - ``accepted_risk`` → refreshed but never reopened. The user has said they
      know; nagging them is how a findings list gets ignored.

    Findings that stop being detected are NOT deleted — they keep their history
    and simply stop having their ``last_seen_at`` bumped.
    """
    result = SyncResult()
    now = _now()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        for finding in findings:
            fingerprint = finding.fingerprint
            cursor = await db.execute(
                "SELECT status, resolved_at FROM waste_findings WHERE fingerprint = ?",
                (fingerprint,),
            )
            existing = await cursor.fetchone()
            evidence_json = json.dumps(finding.evidence, sort_keys=True)

            if existing is None:
                await db.execute(
                    """
                    INSERT INTO waste_findings (
                        fingerprint, detector, subject_type, subject_key,
                        severity, title, description, estimated_waste_usd,
                        affected_count, evidence, status,
                        first_seen_at, last_seen_at, detection_count, detector_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, 1, ?)
                    """,
                    (
                        fingerprint,
                        finding.detector,
                        finding.subject_type,
                        finding.subject_key,
                        finding.severity,
                        finding.title,
                        finding.description,
                        finding.estimated_waste_usd,
                        finding.affected_count,
                        evidence_json,
                        now,
                        now,
                        DETECTOR_VERSION,
                    ),
                )
                result.new += 1
                continue

            # A fix that did not hold has to come back. accepted_risk is the
            # deliberate exception — the user already decided.
            reopen = existing["status"] == "resolved"
            new_status = "open" if reopen else existing["status"]

            # resolved_at is NOT cleared on reopen. It records when the fix was
            # applied, which stays true even though the fix did not hold — and
            # savings verification needs that anchor to compare against. Status
            # is what says the finding is open again.
            await db.execute(
                """
                UPDATE waste_findings
                   SET severity = ?, description = ?, estimated_waste_usd = ?,
                       affected_count = ?, evidence = ?, last_seen_at = ?,
                       status = ?, detection_count = detection_count + 1
                 WHERE fingerprint = ?
                """,
                (
                    finding.severity,
                    finding.description,
                    finding.estimated_waste_usd,
                    finding.affected_count,
                    evidence_json,
                    now,
                    new_status,
                    fingerprint,
                ),
            )
            if reopen:
                result.reopened += 1
            else:
                result.updated += 1

        await db.commit()

    return result


async def list_findings(
    db_path: str,
    status: str | None = None,
    limit: int = 100,
) -> list[StoredFinding]:
    """List stored findings, worst and most expensive first."""
    query = "SELECT * FROM waste_findings"
    params: list[Any] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += (
        " ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,"
        " estimated_waste_usd DESC LIMIT ?"
    )
    params.append(limit)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
    return [_row_to_finding(row) for row in rows]


async def set_finding_status(
    db_path: str,
    fingerprint: str,
    status: str,
    baseline_window_days: int = BASELINE_WINDOW_DAYS,
) -> bool:
    """Move a finding through its lifecycle. Returns False if it doesn't exist.

    Marking a finding resolved snapshots the subject's economics as they stood
    at that moment: its waste, its total spend, and its request count over the
    preceding window. None of that can be recovered afterwards — the next
    detection pass overwrites ``estimated_waste_usd``, and the request window
    slides away.

    The request count is what makes verification honest. Comparing total waste
    before and after would credit the fix whenever traffic merely fell, so
    verification divides by requests and compares cost per request.
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            f"invalid status {status!r}; expected one of {', '.join(VALID_STATUSES)}"
        )

    if status != "resolved":
        # resolved_at and the baseline are left intact: they record that a fix
        # was applied at a point in time, which stays true regardless of what
        # the finding's status becomes afterwards.
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "UPDATE waste_findings SET status = ? WHERE fingerprint = ?",
                (status, fingerprint),
            )
            await db.commit()
            return cursor.rowcount > 0

    from burnlens.analysis.economics import get_subject_spend

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT subject_type, subject_key, estimated_waste_usd "
            "FROM waste_findings WHERE fingerprint = ?",
            (fingerprint,),
        )
        existing = await cursor.fetchone()

    if existing is None:
        return False

    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(days=baseline_window_days)).isoformat()
    baseline_cost, baseline_requests = await get_subject_spend(
        db_path,
        existing["subject_type"],
        existing["subject_key"],
        since=window_start,
        until=now.isoformat(),
    )

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            UPDATE waste_findings
               SET status = 'resolved',
                   resolved_at = ?,
                   baseline_waste_usd = estimated_waste_usd,
                   baseline_cost_usd = ?,
                   baseline_requests = ?,
                   baseline_window_days = ?
             WHERE fingerprint = ?
            """,
            (
                now.isoformat(),
                baseline_cost,
                baseline_requests,
                baseline_window_days,
                fingerprint,
            ),
        )
        await db.commit()
        return cursor.rowcount > 0


@dataclass
class SavingsVerdict:
    """Did the fix actually reduce spend? (BL-E3)

    ``status`` is one of:

    - ``verified``    — enough after-window elapsed and traffic to judge
    - ``pending``     — resolved too recently; ``days_remaining`` says how long
    - ``no_traffic``  — nothing ran since the fix, so nothing can be concluded
    - ``no_baseline`` — resolved before baselines were captured, or by a path
      that did not record one

    Everything is per request. Comparing totals would credit a fix whenever
    traffic simply fell.
    """

    fingerprint: str
    title: str
    subject_type: str
    subject_key: str
    status: str
    baseline_cost_per_request: float | None = None
    current_cost_per_request: float | None = None
    delta_per_request: float | None = None
    pct_change: float | None = None
    projected_monthly_savings_usd: float | None = None
    baseline_requests: int | None = None
    current_requests: int | None = None
    days_remaining: float | None = None
    reopened: bool = False


async def verify_savings(
    db_path: str, fingerprint: str
) -> SavingsVerdict | None:
    """Compare a resolved finding's subject before and after the fix.

    Returns None if the fingerprint is unknown.
    """
    from burnlens.analysis.economics import get_subject_spend

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM waste_findings WHERE fingerprint = ?", (fingerprint,)
        )
        row = await cursor.fetchone()

    if row is None:
        return None

    finding = _row_to_finding(row)
    verdict = SavingsVerdict(
        fingerprint=finding.fingerprint,
        title=finding.title,
        subject_type=finding.subject_type,
        subject_key=finding.subject_key,
        status="no_baseline",
        # A finding that was resolved and is open again is itself evidence the
        # fix did not hold. The numbers below still describe what changed, so
        # report both rather than picking one.
        reopened=finding.status == "open" and finding.resolved_at is not None,
    )

    if not finding.resolved_at or not finding.baseline_requests:
        # Either never resolved, or resolved with no traffic to compare
        # against — in both cases there is no honest before-figure.
        return verdict

    window_days = finding.baseline_window_days or BASELINE_WINDOW_DAYS
    resolved_at = datetime.fromisoformat(finding.resolved_at)
    elapsed = datetime.now(timezone.utc) - resolved_at

    if elapsed < timedelta(days=window_days):
        verdict.status = "pending"
        verdict.days_remaining = round(
            (timedelta(days=window_days) - elapsed).total_seconds() / 86_400, 2
        )
        return verdict

    current_cost, current_requests = await get_subject_spend(
        db_path,
        finding.subject_type,
        finding.subject_key,
        since=resolved_at.isoformat(),
        until=(resolved_at + timedelta(days=window_days)).isoformat(),
    )

    verdict.baseline_requests = finding.baseline_requests
    verdict.current_requests = current_requests

    if current_requests == 0:
        # Silence is not a saving. A workflow that stopped running entirely
        # would otherwise show as a 100% cost reduction.
        verdict.status = "no_traffic"
        return verdict

    baseline_per_request = (finding.baseline_cost_usd or 0.0) / finding.baseline_requests
    current_per_request = current_cost / current_requests

    verdict.status = "verified"
    verdict.baseline_cost_per_request = baseline_per_request
    verdict.current_cost_per_request = current_per_request
    verdict.delta_per_request = baseline_per_request - current_per_request
    verdict.pct_change = (
        ((current_per_request - baseline_per_request) / baseline_per_request * 100)
        if baseline_per_request
        else None
    )
    # Project at the CURRENT request rate, not the baseline's: the saving you
    # keep getting depends on how much you run now, not how much you used to.
    verdict.projected_monthly_savings_usd = (
        verdict.delta_per_request * current_requests * (30.0 / window_days)
    )
    return verdict


async def verify_all_resolved(db_path: str) -> list[SavingsVerdict]:
    """Verify every finding that has a baseline, worst regressions last."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT fingerprint FROM waste_findings WHERE baseline_requests IS NOT NULL"
        )
        rows = await cursor.fetchall()

    verdicts = []
    for row in rows:
        verdict = await verify_savings(db_path, row["fingerprint"])
        if verdict is not None:
            verdicts.append(verdict)
    return sorted(
        verdicts, key=lambda v: -(v.projected_monthly_savings_usd or 0.0)
    )


async def get_waste_summary(db_path: str) -> dict[str, Any]:
    """Open waste totals, for the economics KPIs.

    Only ``open`` and ``acknowledged`` count as outstanding waste — resolved and
    accepted-risk findings are decisions the user has already made, and leaving
    them in the total would mean the number never goes down.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT COALESCE(SUM(estimated_waste_usd), 0.0) AS total_waste,
                   COUNT(*) AS open_count
              FROM waste_findings
             WHERE status IN ('open', 'acknowledged')
            """
        )
        row = await cursor.fetchone()

        cursor = await db.execute(
            """
            SELECT detector, COALESCE(SUM(estimated_waste_usd), 0.0) AS waste
              FROM waste_findings
             WHERE status IN ('open', 'acknowledged')
             GROUP BY detector
             ORDER BY waste DESC
            """
        )
        by_detector = await cursor.fetchall()

    return {
        "detected_waste_usd": row["total_waste"],
        "open_finding_count": row["open_count"],
        "by_detector": {r["detector"]: r["waste"] for r in by_detector},
    }
