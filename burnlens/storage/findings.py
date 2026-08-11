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
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from burnlens.analysis.waste import DETECTOR_VERSION, WasteFinding

VALID_STATUSES = ("open", "acknowledged", "resolved", "accepted_risk")


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

            await db.execute(
                """
                UPDATE waste_findings
                   SET severity = ?, description = ?, estimated_waste_usd = ?,
                       affected_count = ?, evidence = ?, last_seen_at = ?,
                       status = ?, detection_count = detection_count + 1,
                       resolved_at = CASE WHEN ? THEN NULL ELSE resolved_at END
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
                    reopen,
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
    db_path: str, fingerprint: str, status: str
) -> bool:
    """Move a finding through its lifecycle. Returns False if it doesn't exist.

    Marking a finding resolved snapshots its current waste as
    ``baseline_waste_usd``. That number cannot be recovered afterwards — the
    next detection pass overwrites ``estimated_waste_usd`` — and BL-E3 needs a
    before-figure to judge whether the fix actually saved anything.
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            f"invalid status {status!r}; expected one of {', '.join(VALID_STATUSES)}"
        )

    resolving = status == "resolved"
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            UPDATE waste_findings
               SET status = ?,
                   resolved_at = CASE WHEN ? THEN ? ELSE NULL END,
                   baseline_waste_usd = CASE
                       WHEN ? THEN estimated_waste_usd ELSE baseline_waste_usd END
             WHERE fingerprint = ?
            """,
            (status, resolving, _now(), resolving, fingerprint),
        )
        await db.commit()
        return cursor.rowcount > 0


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
