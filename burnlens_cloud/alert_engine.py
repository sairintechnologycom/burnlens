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
from urllib.parse import urlparse

import httpx

from .email import send_usage_warning_email
from .config import settings
from .action_tokens import create_action_token

log = logging.getLogger(__name__)

_SLACK_VALID_HOST = "hooks.slack.com"


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
    top_key_id: str | None = None,
) -> bool:
    """
    POST a Slack notification with interactive action buttons (Phase 10).
    """
    parsed = urlparse(webhook_url) if webhook_url else None
    if not parsed or parsed.scheme != "https" or parsed.hostname != _SLACK_VALID_HOST:
        log.warning(
            "alert_engine: invalid Slack webhook URL for workspace %s (must be https://hooks.slack.com/...)",
            workspace_id,
        )
        return False

    text = (
        f"BurnLens Alert: Your workspace has used {threshold_pct}% of its monthly "
        f"request quota ({current:,} / {limit:,} requests). "
    )

    # Generate action tokens (Phase 10)
    inc_token = await create_action_token("increase_budget", workspace_id)
    dwn_token = await create_action_token("downgrade_model", workspace_id)
    
    actions = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Increase Budget (50%)"},
            "url": f"{base_url}/api/v1/actions/confirm?token={inc_token}",
            "style": "primary"
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Downgrade Model"},
            "url": f"{base_url}/api/v1/actions/confirm?token={dwn_token}"
        }
    ]

    if top_key_id:
        pause_token = await create_action_token("pause_api_key", workspace_id, top_key_id)
        actions.insert(0, {
            "type": "button",
            "text": {"type": "plain_text", "text": "Pause Top API Key"},
            "url": f"{base_url}/api/v1/actions/confirm?token={pause_token}",
            "style": "danger"
        })

    actions.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "View Dashboard"},
        "url": f"{base_url}/dashboard"
    })

    payload = {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":warning: *{text}*"}
            },
            {
                "type": "actions",
                "elements": actions
            }
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
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

            # Phase 10: identify top API key for the current cycle to allow 'pause' action
            top_key_row = await conn.fetchrow(
                """
                SELECT ak.id, ak.name, COUNT(rr.id) as req_count
                FROM api_keys ak
                JOIN request_records rr ON rr.tags->>'key_label' = ak.name
                INNER JOIN workspace_usage_cycles wuc ON wuc.workspace_id = ak.workspace_id AND wuc.cycle_end >= NOW()
                WHERE ak.workspace_id = $1 AND ak.revoked_at IS NULL AND ak.paused_at IS NULL
                  AND rr.ts >= wuc.cycle_start
                GROUP BY ak.id, ak.name
                ORDER BY req_count DESC
                LIMIT 1
                """,
                workspace_id
            )
            top_key_id = str(top_key_row["id"]) if top_key_row else None

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
                    top_key_id=top_key_id,
                )
                recipient = "slack" if channel == "slack" else recipient

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
