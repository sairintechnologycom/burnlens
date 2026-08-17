"""Weekly spend digest: the email that pulls a workspace owner back in.

Shape mirrors the OSS report (burnlens/reports/weekly.py) but reads Postgres
per workspace instead of a local SQLite file, so nothing is importable between
them. Sent by POST /cron/weekly-digest, which GitHub Actions triggers Monday
mornings — the same external-cron pattern as alert evaluation and reconciliation.

Two rules the queries encode:
  * A digest with no spend is not sent. An email saying "you spent $0" is
    unsubscribe bait, and a quiet week is the common case for small workspaces.
  * Token counts are prompt-aware. Never render input_tokens alone: coding
    agents cache almost the whole prompt, so raw input reads as a handful of
    tokens next to a real bill.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .email import deliver_now, mail_configured
from .models import INCLUSIVE_PROMPT_TOKEN_PROVIDERS
from .pii_crypto import decrypt_pii

logger = logging.getLogger(__name__)

DIGEST_DAYS = 7

# A workspace that already got a digest this recently is skipped. This is the
# whole of the idempotency guard: the endpoint is externally triggered, so a
# retried or hand-fired run must not mail everyone a second time. Six rather
# than seven days so a schedule that drifts by an hour still sends.
DIGEST_MIN_GAP_DAYS = 6

# Same provider-aware prompt total as the dashboard's run queries: OpenAI and
# Google fold cache reads into input_tokens, Anthropic reports them disjointly.
_PROMPT_TOKENS = (
    "CASE WHEN provider IN ("
    + ", ".join(f"'{p}'" for p in INCLUSIVE_PROMPT_TOKEN_PROVIDERS)
    + ") THEN input_tokens ELSE input_tokens + cache_read_tokens END"
    " + cache_write_tokens"
)


async def build_weekly_digest(
    conn: Any,
    workspace_id: str,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """Gather one workspace's week. Returns None when there is nothing to say.

    `now` is injectable so tests do not depend on the wall clock.
    """
    now = now or datetime.now(timezone.utc)
    this_start = now - timedelta(days=DIGEST_DAYS)
    prev_start = now - timedelta(days=DIGEST_DAYS * 2)

    # One scan covering both weeks: the prior week is only needed for a delta,
    # so a second round trip to fetch it would be waste in a job that runs over
    # every workspace.
    totals = await conn.fetchrow(
        f"""
        SELECT
            COALESCE(SUM(cost_usd) FILTER (WHERE ts >= $2), 0)      AS cost_this,
            COUNT(*)               FILTER (WHERE ts >= $2)          AS requests_this,
            COALESCE(SUM({_PROMPT_TOKENS}) FILTER (WHERE ts >= $2), 0) AS prompt_tokens,
            COALESCE(SUM(cache_read_tokens) FILTER (WHERE ts >= $2), 0) AS cache_read_tokens,
            COALESCE(SUM(cost_usd) FILTER (WHERE ts < $2), 0)       AS cost_prev
        FROM request_records
        WHERE workspace_id = $1 AND ts >= $3
        """,
        workspace_id,
        this_start,
        prev_start,
    )

    cost_this = float(totals["cost_this"] or 0)
    if cost_this <= 0:
        return None

    cost_prev = float(totals["cost_prev"] or 0)
    prompt_tokens = int(totals["prompt_tokens"] or 0)
    cache_read = int(totals["cache_read_tokens"] or 0)

    model_rows = await conn.fetch(
        """
        SELECT model, SUM(cost_usd) AS cost, COUNT(*) AS requests
        FROM request_records
        WHERE workspace_id = $1 AND ts >= $2 AND model IS NOT NULL
        GROUP BY model
        ORDER BY cost DESC
        LIMIT 5
        """,
        workspace_id,
        this_start,
    )

    # tags->>'feature' rather than a column: attribution lives in the tag blob.
    feature_rows = await conn.fetch(
        """
        SELECT COALESCE(tags->>'feature', '(untagged)') AS tag,
               SUM(cost_usd) AS cost
        FROM request_records
        WHERE workspace_id = $1 AND ts >= $2
        GROUP BY tag
        ORDER BY cost DESC
        LIMIT 5
        """,
        workspace_id,
        this_start,
    )

    waste = await conn.fetchrow(
        """
        SELECT COUNT(*) AS open_count,
               COALESCE(SUM(estimated_waste_usd), 0) AS waste_usd
        FROM waste_findings
        WHERE workspace_id = $1 AND status = 'open'
        """,
        workspace_id,
    )

    return {
        "period_start": this_start.date().isoformat(),
        "period_end": now.date().isoformat(),
        "cost_usd": round(cost_this, 4),
        "prev_cost_usd": round(cost_prev, 4),
        # None (not 0) when there is no prior week to compare against: a first
        # week must not render as "+100% vs last week".
        "change_pct": (
            round((cost_this - cost_prev) / cost_prev * 100, 1) if cost_prev > 0 else None
        ),
        "request_count": int(totals["requests_this"] or 0),
        "prompt_tokens": prompt_tokens,
        "cache_read_tokens": cache_read,
        "cache_read_rate": round(cache_read / prompt_tokens, 4) if prompt_tokens else 0.0,
        "top_models": [
            {"model": r["model"], "cost_usd": round(float(r["cost"]), 4),
             "request_count": int(r["requests"])}
            for r in model_rows
        ],
        "top_features": [
            {"tag": r["tag"], "cost_usd": round(float(r["cost"]), 4)}
            for r in feature_rows
        ],
        "open_finding_count": int(waste["open_count"] or 0) if waste else 0,
        "waste_usd": round(float(waste["waste_usd"] or 0), 4) if waste else 0.0,
    }


def _delta_line(digest: dict) -> str:
    """Week-over-week phrasing, or a first-week note when there is no prior."""
    pct = digest["change_pct"]
    if pct is None:
        return "No spend in the prior week to compare against."
    direction = "up" if pct >= 0 else "down"
    colour = "#e07840" if pct >= 0 else "#3fb950"
    return (
        f'<span style="color:{colour};">{direction} {abs(pct):.1f}%</span> '
        f"vs the previous 7 days (${digest['prev_cost_usd']:,.2f})"
    )


def _rows_html(rows: list[tuple[str, str]]) -> str:
    out = ""
    for label, value in rows:
        out += (
            '<tr>'
            f'<td style="padding:6px 12px; border-bottom:1px solid #eee; color:#333;">{html.escape(label)}</td>'
            f'<td style="padding:6px 12px; border-bottom:1px solid #eee; color:#333; text-align:right;">{value}</td>'
            '</tr>'
        )
    return out


def render_digest_html(digest: dict, workspace_name: str, frontend_url: str) -> str:
    """Build the digest email body.

    Hand-built rather than templated: the shared template registry does literal
    {{name}} replacement with no loops, and every section here is a table of
    variable length.
    """
    models = _rows_html([
        (m["model"], f"${m['cost_usd']:,.2f} · {m['request_count']:,} req")
        for m in digest["top_models"]
    ]) or '<tr><td style="padding:6px 12px; color:#888;">No model data</td><td></td></tr>'

    features = _rows_html([
        (f["tag"], f"${f['cost_usd']:,.2f}") for f in digest["top_features"]
    ]) or '<tr><td style="padding:6px 12px; color:#888;">No tagged traffic</td><td></td></tr>'

    waste_block = ""
    if digest["open_finding_count"] > 0:
        waste_block = (
            '<p style="color:#555; font-size:14px;">'
            f'<strong>${digest["waste_usd"]:,.2f}</strong> of estimated waste across '
            f'{digest["open_finding_count"]} open finding(s). '
            f'<a href="{html.escape(frontend_url)}/waste" style="color:#e07840;">Review them</a>.'
            '</p>'
        )

    return (
        '<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8"></head>\n'
        '<body style="font-family:sans-serif; background:#f9f9f9; padding:20px;">\n'
        '  <div style="max-width:640px; margin:0 auto; background:#fff; border-radius:6px; padding:24px;">\n'
        '    <h1 style="color:#1a1a2e; font-size:18px; margin-top:0;">BurnLens weekly digest</h1>\n'
        f'    <p style="color:#888; font-size:12px; margin-top:-8px;">{html.escape(workspace_name)} · '
        f'{digest["period_start"]} to {digest["period_end"]}</p>\n'
        f'    <p style="font-size:28px; color:#1a1a2e; margin:16px 0 4px;">${digest["cost_usd"]:,.2f}</p>\n'
        f'    <p style="color:#555; font-size:13px; margin-top:0;">{_delta_line(digest)}</p>\n'
        f'    <p style="color:#555; font-size:13px;">{digest["request_count"]:,} requests · '
        f'{digest["prompt_tokens"]:,} prompt tokens · '
        f'{digest["cache_read_rate"] * 100:.1f}% served from cache</p>\n'
        f'    {waste_block}\n'
        '    <h2 style="color:#333; font-size:14px; border-bottom:2px solid #e07840; padding-bottom:6px;">Top models</h2>\n'
        f'    <table style="border-collapse:collapse; width:100%; font-size:13px;">{models}</table>\n'
        '    <h2 style="color:#333; font-size:14px; border-bottom:2px solid #e07840; padding-bottom:6px; margin-top:20px;">Top features</h2>\n'
        f'    <table style="border-collapse:collapse; width:100%; font-size:13px;">{features}</table>\n'
        f'    <p style="margin-top:24px;"><a href="{html.escape(frontend_url)}/dashboard" '
        'style="background:#e07840; color:#fff; padding:10px 18px; border-radius:4px; '
        'text-decoration:none; font-size:13px;">Open dashboard</a></p>\n'
        '    <p style="color:#aaa; font-size:11px; margin-top:20px;">\n'
        f'      Turn this off in <a href="{html.escape(frontend_url)}/settings" style="color:#aaa;">Settings</a>.\n'
        '    </p>\n'
        '  </div>\n</body>\n</html>'
    )


async def _owner_email(conn: Any, workspace_id: str) -> Optional[str]:
    """Decrypted email of the workspace's active owner, or None."""
    row = await conn.fetchrow(
        """
        SELECT u.email_encrypted
        FROM workspace_members wm
        JOIN users u ON u.id = wm.user_id
        WHERE wm.workspace_id = $1 AND wm.role = 'owner' AND wm.active = true
        LIMIT 1
        """,
        workspace_id,
    )
    if not row or not row["email_encrypted"]:
        return None
    try:
        return decrypt_pii(row["email_encrypted"])
    except Exception:
        logger.warning("weekly digest: decrypt_pii failed for workspace=%s", workspace_id)
        return None


async def send_weekly_digests(db_pool: Any, now: Optional[datetime] = None) -> dict:
    """Send a digest to every opted-in paid workspace that is due one.

    Returns {"considered", "sent", "failed", "skipped_empty", "skipped_recent"}.
    `sent` counts messages the mail provider accepted, not messages queued —
    the whole point of awaiting delivery here.

    Fail-open per workspace: one bad row must not stop the rest of the run.
    """
    from .config import settings

    now = now or datetime.now(timezone.utc)
    due_before = now - timedelta(days=DIGEST_MIN_GAP_DAYS)
    considered = sent = failed = skipped_empty = skipped_recent = 0

    def _result() -> dict:
        return {
            "considered": considered,
            "sent": sent,
            "failed": failed,
            "skipped_empty": skipped_empty,
            "skipped_recent": skipped_recent,
        }

    if not mail_configured():
        logger.warning("weekly digest: email not configured, nothing sent")
        return _result()

    async with db_pool.acquire() as conn:
        # The recency filter runs in Python rather than SQL so an already-sent
        # workspace still lands in `considered` and `skipped_recent`. A run that
        # reports "considered: 0" is indistinguishable from a broken query.
        workspaces = await conn.fetch(
            """
            SELECT id, name, weekly_digest_last_sent_at
            FROM workspaces
            WHERE plan != 'free' AND active = true AND weekly_digest_enabled = true
            ORDER BY id
            """
        )

        for ws in workspaces:
            workspace_id = str(ws["id"])
            considered += 1
            try:
                last_sent = ws["weekly_digest_last_sent_at"]
                if last_sent is not None and last_sent >= due_before:
                    skipped_recent += 1
                    continue

                digest = await build_weekly_digest(conn, workspace_id, now=now)
                if digest is None:
                    skipped_empty += 1
                    continue

                recipient = await _owner_email(conn, workspace_id)
                if not recipient:
                    logger.warning("weekly digest: no owner email for workspace=%s", workspace_id)
                    continue

                body = render_digest_html(
                    digest,
                    workspace_name=ws["name"] or "your workspace",
                    frontend_url=settings.burnlens_frontend_url,
                )
                delivered = await deliver_now(
                    recipient,
                    f"BurnLens weekly: ${digest['cost_usd']:,.2f} across {digest['request_count']:,} requests",
                    body,
                    "weekly digest",
                )
                if not delivered:
                    failed += 1
                    continue

                # Stamped only after a confirmed delivery, so a failed send is
                # retried by the next run instead of being marked done.
                sent += 1
                await conn.execute(
                    "UPDATE workspaces SET weekly_digest_last_sent_at = $2 WHERE id = $1",
                    ws["id"],
                    now,
                )
            except Exception as exc:
                logger.error("weekly digest: workspace %s failed: %s", workspace_id, exc)

    return _result()
