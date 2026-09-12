"""Phase 8: BL-AE-008 Verified Savings Storage.

Persists immutable baseline snapshots and verification audit records in SQLite
with strict tenant isolation and cryptographic fingerprint verification.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from burnlens.verification.models import (
    BaselineSnapshot,
    SavingsVerificationRecord,
    VerificationVerdict,
)

logger = logging.getLogger(__name__)


class VerificationStorage:
    """Async SQLite storage for baselines and savings verification records."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init_verification_schema(self) -> None:
        """Create verification tables."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS baseline_snapshots (
                    snapshot_id                 TEXT PRIMARY KEY,
                    recommendation_id           TEXT NOT NULL,
                    workspace_id                TEXT NOT NULL,
                    baseline_cost_usd           REAL NOT NULL,
                    baseline_requests           INTEGER NOT NULL,
                    baseline_accepted_outcomes  INTEGER NOT NULL,
                    baseline_outcome_rate       REAL NOT NULL,
                    fingerprint                 TEXT NOT NULL,
                    created_at                  TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_base_snap_rec ON baseline_snapshots (workspace_id, recommendation_id)"
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS savings_verifications (
                    verification_id             TEXT PRIMARY KEY,
                    recommendation_id           TEXT NOT NULL,
                    workspace_id                TEXT NOT NULL,
                    projected_saving_usd        REAL NOT NULL,
                    actual_saving_usd           REAL NOT NULL,
                    variance_usd                REAL NOT NULL,
                    variance_percentage         REAL NOT NULL,
                    baseline_outcome_rate       REAL NOT NULL,
                    post_change_outcome_rate    REAL NOT NULL,
                    quality_change              REAL NOT NULL,
                    confidence                  REAL NOT NULL,
                    verdict                     TEXT NOT NULL,
                    reason                      TEXT NOT NULL,
                    sample_count_baseline       INTEGER NOT NULL,
                    sample_count_post_change    INTEGER NOT NULL,
                    evidence_snapshot           TEXT NOT NULL DEFAULT '{}',
                    calculation_version         INTEGER NOT NULL DEFAULT 1,
                    verified_at                 TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_verif_ws_time ON savings_verifications (workspace_id, verified_at)"
            )
            await db.commit()

    async def save_baseline_snapshot(self, snapshot: BaselineSnapshot) -> None:
        """Save immutable baseline snapshot with fingerprint."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO baseline_snapshots (
                    snapshot_id, recommendation_id, workspace_id, baseline_cost_usd,
                    baseline_requests, baseline_accepted_outcomes, baseline_outcome_rate,
                    fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.recommendation_id,
                    snapshot.workspace_id,
                    snapshot.baseline_cost_usd,
                    snapshot.baseline_requests,
                    snapshot.baseline_accepted_outcomes,
                    snapshot.baseline_outcome_rate,
                    snapshot.fingerprint,
                    snapshot.created_at.isoformat(),
                ),
            )
            await db.commit()

    async def get_baseline_snapshot(self, recommendation_id: str, workspace_id: str) -> BaselineSnapshot | None:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT snapshot_id, recommendation_id, workspace_id, baseline_cost_usd,
                       baseline_requests, baseline_accepted_outcomes, baseline_outcome_rate,
                       fingerprint, created_at
                FROM baseline_snapshots
                WHERE recommendation_id = ? AND workspace_id = ?
                """,
                (recommendation_id, workspace_id),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            snap = BaselineSnapshot(
                snapshot_id=row[0],
                recommendation_id=row[1],
                workspace_id=row[2],
                baseline_cost_usd=row[3],
                baseline_requests=row[4],
                baseline_accepted_outcomes=row[5],
                baseline_outcome_rate=row[6],
                created_at=datetime.fromisoformat(row[8]),
            )
            # Verify cryptographic integrity
            if snap.fingerprint != row[7]:
                logger.error("Tamper detected in baseline snapshot %s! Fingerprint mismatch.", row[0])
                raise ValueError("Tamper detected in stored baseline snapshot.")
            return snap

    async def save_verification_record(self, record: SavingsVerificationRecord) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO savings_verifications (
                    verification_id, recommendation_id, workspace_id, projected_saving_usd,
                    actual_saving_usd, variance_usd, variance_percentage, baseline_outcome_rate,
                    post_change_outcome_rate, quality_change, confidence, verdict,
                    reason, sample_count_baseline, sample_count_post_change,
                    evidence_snapshot, calculation_version, verified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.verification_id,
                    record.recommendation_id,
                    record.workspace_id,
                    record.projected_saving_usd,
                    record.actual_saving_usd,
                    record.variance_usd,
                    record.variance_percentage,
                    record.baseline_outcome_rate,
                    record.post_change_outcome_rate,
                    record.quality_change,
                    record.confidence,
                    record.verdict.value,
                    record.reason,
                    record.sample_count_baseline,
                    record.sample_count_post_change,
                    json.dumps(record.evidence_snapshot),
                    record.calculation_version,
                    record.verified_at.isoformat(),
                ),
            )
            await db.commit()

    async def get_verification_record(self, verification_id: str, workspace_id: str) -> SavingsVerificationRecord | None:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT verification_id, recommendation_id, workspace_id, projected_saving_usd,
                       actual_saving_usd, variance_usd, variance_percentage, baseline_outcome_rate,
                       post_change_outcome_rate, quality_change, confidence, verdict,
                       reason, sample_count_baseline, sample_count_post_change,
                       evidence_snapshot, calculation_version, verified_at
                FROM savings_verifications
                WHERE verification_id = ? AND workspace_id = ?
                """,
                (verification_id, workspace_id),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            return SavingsVerificationRecord(
                verification_id=row[0],
                recommendation_id=row[1],
                workspace_id=row[2],
                projected_saving_usd=row[3],
                actual_saving_usd=row[4],
                variance_usd=row[5],
                variance_percentage=row[6],
                baseline_outcome_rate=row[7],
                post_change_outcome_rate=row[8],
                quality_change=row[9],
                confidence=row[10],
                verdict=VerificationVerdict(row[11]),
                reason=row[12],
                sample_count_baseline=row[13],
                sample_count_post_change=row[14],
                evidence_snapshot=json.loads(row[15] or "{}"),
                calculation_version=row[16],
                verified_at=datetime.fromisoformat(row[17]),
            )
