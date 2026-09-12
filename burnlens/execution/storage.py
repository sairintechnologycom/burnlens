"""Phase 6: BL-AE-006 Assisted Execution Storage Management.

Persists execution records, approval tokens, and immutable audit timeline events
in SQLite with strict workspace tenant isolation.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from burnlens.execution.models import (
    ApprovalToken,
    ExecutionResult,
    ExecutionStatus,
    ExecutionTimelineEvent,
)

logger = logging.getLogger(__name__)


class ExecutionStorage:
    """Async SQLite storage for assisted execution records and audit timelines."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init_execution_schema(self) -> None:
        """Create tables for execution records, approval tokens, and timeline events."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_records (
                    execution_id      TEXT PRIMARY KEY,
                    workspace_id      TEXT NOT NULL,
                    agent_id          TEXT NOT NULL,
                    task_id           TEXT NOT NULL,
                    recommendation_id TEXT NOT NULL,
                    repo              TEXT NOT NULL,
                    base_branch       TEXT NOT NULL,
                    target_branch     TEXT NOT NULL,
                    idempotency_key   TEXT NOT NULL,
                    status            TEXT NOT NULL,
                    branch_name       TEXT,
                    commit_sha        TEXT,
                    pr_number         INTEGER,
                    pr_url            TEXT,
                    ci_status         TEXT,
                    is_unmerged       INTEGER NOT NULL DEFAULT 1,
                    error_code        TEXT,
                    error_message     TEXT,
                    executed_at       TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_exec_idempotency ON execution_records (workspace_id, idempotency_key)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_exec_ws_time ON execution_records (workspace_id, executed_at)"
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_tokens (
                    token_id          TEXT PRIMARY KEY,
                    binding_hash      TEXT NOT NULL,
                    workspace_id      TEXT NOT NULL,
                    approver          TEXT NOT NULL,
                    signature         TEXT NOT NULL,
                    approved_at       TEXT NOT NULL,
                    expires_at        TEXT NOT NULL,
                    consumed          INTEGER NOT NULL DEFAULT 0,
                    consumed_at       TEXT,
                    metadata          TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_appr_tokens_ws ON approval_tokens (workspace_id, binding_hash)"
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_timeline (
                    event_id          TEXT PRIMARY KEY,
                    execution_id      TEXT NOT NULL,
                    stage             TEXT NOT NULL,
                    message           TEXT NOT NULL,
                    details           TEXT NOT NULL DEFAULT '{}',
                    timestamp         TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_exec ON execution_timeline (execution_id, timestamp)"
            )
            await db.commit()

    async def save_approval_token(self, token: ApprovalToken) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO approval_tokens (
                    token_id, binding_hash, workspace_id, approver, signature,
                    approved_at, expires_at, consumed, consumed_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token.token_id,
                    token.binding_hash,
                    token.workspace_id,
                    token.approver,
                    token.signature,
                    token.approved_at.isoformat(),
                    token.expires_at.isoformat(),
                    1 if token.consumed else 0,
                    token.consumed_at.isoformat() if token.consumed_at else None,
                    json.dumps(token.metadata),
                ),
            )
            await db.commit()

    async def mark_token_consumed(self, token_id: str, consumed_at: datetime) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE approval_tokens SET consumed = 1, consumed_at = ? WHERE token_id = ?",
                (consumed_at.isoformat(), token_id),
            )
            await db.commit()

    async def get_approval_token(self, token_id: str, workspace_id: str) -> ApprovalToken | None:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT token_id, binding_hash, workspace_id, approver, signature,
                       approved_at, expires_at, consumed, consumed_at, metadata
                FROM approval_tokens
                WHERE token_id = ? AND workspace_id = ?
                """,
                (token_id, workspace_id),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            return ApprovalToken(
                token_id=row[0],
                binding_hash=row[1],
                workspace_id=row[2],
                approver=row[3],
                signature=row[4],
                approved_at=datetime.fromisoformat(row[5]),
                expires_at=datetime.fromisoformat(row[6]),
                consumed=bool(row[7]),
                consumed_at=datetime.fromisoformat(row[8]) if row[8] else None,
                metadata=json.loads(row[9] or "{}"),
            )

    async def get_by_idempotency(self, workspace_id: str, idempotency_key: str) -> ExecutionResult | None:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT execution_id, status, workspace_id, repo, branch_name,
                       commit_sha, pr_number, pr_url, ci_status, is_unmerged,
                       error_code, error_message, executed_at
                FROM execution_records
                WHERE workspace_id = ? AND idempotency_key = ?
                """,
                (workspace_id, idempotency_key),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            exec_id = row[0]
            timeline = await self.get_timeline(exec_id)
            return ExecutionResult(
                execution_id=exec_id,
                status=ExecutionStatus(row[1]),
                workspace_id=row[2],
                repo=row[3],
                branch_name=row[4],
                commit_sha=row[5],
                pr_number=row[6],
                pr_url=row[7],
                ci_status=row[8],
                is_unmerged=bool(row[9]),
                idempotent_replay=True,
                error_code=row[10],
                error_message=row[11],
                timeline=timeline,
                executed_at=datetime.fromisoformat(row[12]),
            )

    async def save_execution(
        self,
        result: ExecutionResult,
        agent_id: str,
        task_id: str,
        recommendation_id: str,
        base_branch: str,
        target_branch: str,
        idempotency_key: str,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO execution_records (
                    execution_id, workspace_id, agent_id, task_id, recommendation_id,
                    repo, base_branch, target_branch, idempotency_key, status,
                    branch_name, commit_sha, pr_number, pr_url, ci_status,
                    is_unmerged, error_code, error_message, executed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.execution_id,
                    result.workspace_id,
                    agent_id,
                    task_id,
                    recommendation_id,
                    result.repo,
                    base_branch,
                    target_branch,
                    idempotency_key,
                    result.status.value,
                    result.branch_name,
                    result.commit_sha,
                    result.pr_number,
                    result.pr_url,
                    result.ci_status,
                    1 if result.is_unmerged else 0,
                    result.error_code,
                    result.error_message,
                    result.executed_at.isoformat(),
                ),
            )
            for event in result.timeline:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO execution_timeline (
                        event_id, execution_id, stage, message, details, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.execution_id,
                        event.stage,
                        event.message,
                        json.dumps(event.details),
                        event.timestamp.isoformat(),
                    ),
                )
            await db.commit()

    async def add_timeline_event(self, event: ExecutionTimelineEvent) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO execution_timeline (
                    event_id, execution_id, stage, message, details, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.execution_id,
                    event.stage,
                    event.message,
                    json.dumps(event.details),
                    event.timestamp.isoformat(),
                ),
            )
            await db.commit()

    async def get_timeline(self, execution_id: str) -> list[ExecutionTimelineEvent]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT event_id, execution_id, stage, message, details, timestamp
                FROM execution_timeline
                WHERE execution_id = ?
                ORDER BY timestamp ASC
                """,
                (execution_id,),
            )
            rows = await cursor.fetchall()
            return [
                ExecutionTimelineEvent(
                    event_id=row[0],
                    execution_id=row[1],
                    stage=row[2],
                    message=row[3],
                    details=json.loads(row[4] or "{}"),
                    timestamp=datetime.fromisoformat(row[5]),
                )
                for row in rows
            ]
