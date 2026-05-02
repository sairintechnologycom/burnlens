"""
Phase 12: Alert evaluation engine.

Called hourly by POST /cron/evaluate-alerts.
Evaluates all active alert rules against current workspace spend.
Fail-open: exceptions are caught per-rule and per-workspace; the cron always completes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from .email import send_usage_warning_email
from .config import settings

log = logging.getLogger(__name__)

_SLACK_HOST_PREFIX = "https://hooks.slack.com/"


async def _should_fire(conn: Any, rule_id: str, now: datetime) -> bool:
    """Return True if no alert_events row exists for this rule within the last 24 hours."""
    row = await conn.fetchrow(
        """
        SELECT 1 FROM alert_events
        WHERE rule_id = $1
          AND fired_at > $2 - INTERVAL '24 hours'
        LIMIT 1
        """,
        rule_id,
        now,
    )
    return row is None


async def _dispatch_email(
    workspace_id: str,
    threshold_pct: int,
    current: int,
    limit: int,
    cycle_end_date: str,
    plan_label: str,
) -> bool:
    """Dispatch email alert via SendGrid. Returns True on success, False on failure."""
    try:
        return await send_usage_warning_email(
            workspace_id=workspace_id,
            threshold=str(threshold_pct),
            current=current,
            limit=limit,
            cycle_end_date=cycle_end_date,
            plan_label=plan_label,
        )
    except Exception as exc:
        log.warning("alert_engine: email dispatch failed for workspace %s: %s", workspace_id, exc)
        return False


async def _dispatch_slack(
    webhook_url: str,
    workspace_id: str,
    threshold_pct: int,
    current: int,
    limit: int,
) -> bool:
    """
    POST a Slack notification to the configured webhook URL.

    Validates URL prefix before making any HTTP request.
    Returns True on 2xx, False on any error. Never raises.
    NOTE: webhook_url is not logged — it is a secret.
    """
    if not webhook_url or not webhook_url.startswith(_SLACK_HOST_PREFIX):
        log.warning(
            "alert_engine: invalid Slack webhook URL for workspace %s (must start with %s)",
            workspace_id,
            _SLACK_HOST_PREFIX,
        )
        return False

    text = (
        f"BurnLens Alert: Your workspace has used {threshold_pct}% of its monthly "
        f"request quota ({current:,} / {limit:,} requests). "
        f"Manage at {settings.burnlens_frontend_url}/settings"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json={"text": text})
            resp.raise_for_status()
            return True
    except Exception as exc:
        log.warning("alert_engine: Slack dispatch failed for workspace %s: %s", workspace_id, exc)
        return False


async def evaluate_workspace(
    conn: Any,
    workspace_id: str,
    plan: str,
    current_count: int,
    monthly_cap: int,
    cycle_end_date: str,
) -> list[dict]:
    """
    Evaluate all enabled alert rules for a single workspace.

    Returns list of dicts describing each fired alert (for logging/counting).
    Never raises — per-rule exceptions are caught and logged.
    """
    fired: list[dict] = []
    now = datetime.now(tz=timezone.utc)
    plan_label = plan.capitalize()

    rules = await conn.fetch(
        """
        SELECT id, threshold_pct, channel, slack_webhook_url, extra_emails
        FROM alert_rules
        WHERE workspace_id = $1 AND enabled = TRUE
        ORDER BY threshold_pct
        """,
        workspace_id,
    )

    for rule in rules:
        rule_id = str(rule["id"])
        threshold_pct: int = rule["threshold_pct"]
        channel: str = rule["channel"]
        slack_webhook_url: str | None = rule["slack_webhook_url"]

        try:
            # Check if threshold is crossed.
            if monthly_cap <= 0 or (current_count / monthly_cap) < (threshold_pct / 100):
                continue

            # 24h dedup check.
            if not await _should_fire(conn, rule_id, now):
                log.debug(
                    "alert_engine: rule %s deduped (fired within 24h)", rule_id
                )
                continue

            # Dispatch based on channel.
            email_ok = False
            slack_ok = False
            recipient = ""

            if channel in ("email", "both"):
                email_ok = await _dispatch_email(
                    workspace_id=workspace_id,
                    threshold_pct=threshold_pct,
                    current=current_count,
                    limit=monthly_cap,
                    cycle_end_date=cycle_end_date,
                    plan_label=plan_label,
                )
                recipient = f"email:{workspace_id}"

            if channel in ("slack", "both") and slack_webhook_url:
                slack_ok = await _dispatch_slack(
                    webhook_url=slack_webhook_url,
                    workspace_id=workspace_id,
                    threshold_pct=threshold_pct,
                    current=current_count,
                    limit=monthly_cap,
                )
                recipient = slack_webhook_url if channel == "slack" else recipient

            # Record in audit log (even on dispatch failure — status reflects outcome).
            dispatched_ok = email_ok or slack_ok
            status = "sent" if dispatched_ok else "failed"
            await conn.execute(
                """
                INSERT INTO alert_events
                    (rule_id, workspace_id, threshold_pct, channel, recipient, fired_at, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                rule_id,
                workspace_id,
                threshold_pct,
                channel,
                recipient,
                now,
                status,
            )

            fired.append({
                "rule_id": rule_id,
                "workspace_id": workspace_id,
                "threshold_pct": threshold_pct,
                "channel": channel,
                "status": status,
            })

        except Exception as exc:
            log.error(
                "alert_engine: rule %s for workspace %s failed: %s",
                rule_id,
                workspace_id,
                exc,
            )
            continue

    return fired


async def evaluate_all_workspaces(db_pool: Any) -> dict:
    """
    Main cron entry point. Evaluates all non-free workspaces.

    Returns {"evaluated": N, "fired": M}.
    Fail-open: per-workspace exceptions are logged and skipped.
    """
    evaluated = 0
    total_fired = 0

    async with db_pool.acquire() as conn:
        workspaces = await conn.fetch(
            """
            SELECT w.id, w.plan, pl.monthly_request_cap,
                   wuc.request_count, wuc.cycle_end
            FROM workspaces w
            JOIN plan_limits pl ON pl.plan = w.plan
            INNER JOIN workspace_usage_cycles wuc
                   ON wuc.workspace_id = w.id AND wuc.cycle_end >= NOW()
            WHERE w.plan != 'free'
            ORDER BY w.id
            """
        )

        for ws in workspaces:
            workspace_id = str(ws["id"])
            plan: str = ws["plan"]
            monthly_cap: int = ws["monthly_request_cap"] or 0
            current_count: int = ws["request_count"] or 0
            cycle_end = ws["cycle_end"]
            cycle_end_date = cycle_end.strftime("%-d %B, %Y") if cycle_end else ""

            try:
                fired = await evaluate_workspace(
                    conn=conn,
                    workspace_id=workspace_id,
                    plan=plan,
                    current_count=current_count,
                    monthly_cap=monthly_cap,
                    cycle_end_date=cycle_end_date,
                )
                evaluated += 1
                total_fired += len(fired)
            except Exception as exc:
                log.error(
                    "alert_engine: workspace %s evaluation failed: %s",
                    workspace_id,
                    exc,
                )
                evaluated += 1
                continue

    log.info("alert_engine: evaluated=%d fired=%d", evaluated, total_fired)
    return {"evaluated": evaluated, "fired": total_fired}
