"""Periodic digest email functions for BurnLens alert system.

Provides daily and weekly digest generation and email dispatch:
  - send_daily_digest: model_changed events from the last 24 hours (ALRT-03)
  - send_weekly_digest: AI assets inactive for more than 30 days (ALRT-04)

Both functions are async and fail-open (all exceptions caught internally).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from burnlens.alerts.email import EmailSender

from burnlens.storage.queries import (
    get_asset_by_id,
    get_inactive_assets,
    get_model_change_events_since,
)

logger = logging.getLogger(__name__)


async def send_daily_digest(
    db_path: str,
    email_sender: EmailSender,
    recipients: list[str],
) -> int:
    """Query model_changed events from the last 24 hours and send a digest email.

    No-op (returns 0) when recipients is empty, no events were found, or all
    events reference assets that can no longer be found in the database.

    All exceptions are caught and logged (fail-open).

    Args:
        db_path:      Path to the BurnLens SQLite database.
        email_sender: Configured EmailSender instance.
        recipients:   List of recipient email addresses.

    Returns:
        Number of events included in the digest (0 if email was not sent).
    """
    if not recipients:
        return 0

    try:
        since_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        events = await get_model_change_events_since(db_path, since_iso)

        if not events:
            return 0

        rows: list[list[str]] = []
        for event in events:
            asset = await get_asset_by_id(db_path, event.asset_id)
            if asset is None:
                logger.debug(
                    "send_daily_digest: asset %s not found for event %s, skipping",
                    event.asset_id,
                    event.id,
                )
                continue

            change_details = "; ".join(
                f"{k}: {v}" for k, v in event.details.items()
            ) or "\u2014"

            rows.append([
                asset.model_name,
                asset.provider,
                change_details,
                event.detected_at.strftime("%Y-%m-%d %H:%M UTC"),
            ])

        if not rows:
            return 0

        headers = ("Model", "Provider", "Change Details", "Detected At")
        html = _build_digest_html(
            title="BurnLens Daily Digest: Model Changes",
            intro=f"The following model changes were detected in the last 24 hours ({date.today()}).",
            headers=headers,
            rows=rows,
        )

        subject = f"BurnLens Daily Digest: Model Changes \u2014 {date.today()}"
        await email_sender.send(to_addrs=recipients, subject=subject, body_html=html)

        return len(rows)

    except Exception:
        logger.error("send_daily_digest failed", exc_info=True)
        return 0


async def send_weekly_digest(
    db_path: str,
    email_sender: EmailSender,
    recipients: list[str],
) -> int:
    """Query AI assets inactive for more than 30 days and send a digest email.

    No-op (returns 0) when recipients is empty or no inactive assets exist.
    All exceptions are caught and logged (fail-open).

    Args:
        db_path:      Path to the BurnLens SQLite database.
        email_sender: Configured EmailSender instance.
        recipients:   List of recipient email addresses.

    Returns:
        Number of inactive assets included in the digest (0 if not sent).
    """
    if not recipients:
        return 0

    try:
        assets = await get_inactive_assets(db_path, inactive_days=30)

        if not assets:
            return 0

        rows: list[list[str]] = []
        for asset in assets:
            rows.append([
                asset.model_name,
                asset.provider,
                asset.owner_team or "\u2014",
                asset.last_active_at.strftime("%Y-%m-%d"),
                asset.status,
            ])

        headers = ("Model", "Provider", "Team", "Last Active", "Status")
        html = _build_digest_html(
            title="BurnLens Weekly Digest: Inactive Assets",
            intro=f"The following AI assets have been inactive for more than 30 days ({date.today()}). Consider reviewing or deprecating them.",
            headers=headers,
            rows=rows,
        )

        subject = f"BurnLens Weekly Digest: Inactive Assets \u2014 {date.today()}"
        await email_sender.send(to_addrs=recipients, subject=subject, body_html=html)

        return len(rows)

    except Exception:
        logger.error("send_weekly_digest failed", exc_info=True)
        return 0


def _build_html_table(headers: list[str], rows: list[list[str]]) -> str:
    """Build a simple HTML table with inline styles for email compatibility.

    Args:
        headers: Column header labels.
        rows:    List of rows; each row is a list of cell values.

    Returns:
        HTML string for the table.
    """
    header_html = "".join(
        f'<th style="background:#1a1a2e; color:#e0e0e0; padding:8px 12px; text-align:left; border:1px solid #333;">{h}</th>'
        for h in headers
    )

    rows_html = ""
    for row in rows:
        cells = "".join(
            f'<td style="padding:8px 12px; border:1px solid #ddd; color:#333;">{cell}</td>'
            for cell in row
        )
        rows_html += f"<tr>{cells}</tr>\n"

    return (
        f'<table style="border-collapse:collapse; width:100%; font-family:sans-serif; font-size:14px;">'
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{rows_html}</tbody></table>"
    )


def _build_digest_html(
    title: str,
    intro: str,
    headers: list[str],
    rows: list[list[str]],
) -> str:
    """Build a complete HTML email body for a digest.

    Args:
        title:   Heading text.
        intro:   Introductory paragraph.
        headers: Table column headers.
        rows:    Table data rows.

    Returns:
        Full HTML document string suitable for email.
    """
    table_html = _build_html_table(headers, rows)
    return (
        '<!DOCTYPE html>\n'
        '<html>\n'
        '<head><meta charset="utf-8"></head>\n'
        '<body style="font-family:sans-serif; background:#f9f9f9; padding:20px;">\n'
        '  <div style="max-width:700px; margin:0 auto; background:#fff; border-radius:6px; padding:24px; box-shadow:0 2px 4px rgba(0,0,0,0.08);">\n'
        '    <h1 style="color:#1a1a2e; font-size:20px; margin-top:0;">\n'
        '      <span style="color:#e74c3c;">&#9679;</span> BurnLens\n'
        '    </h1>\n'
        f'    <h2 style="color:#333; font-size:16px; border-bottom:2px solid #e74c3c; padding-bottom:8px;">{title}</h2>\n'
        f'    <p style="color:#555; font-size:14px;">{intro}</p>\n'
        f'    {table_html}\n'
        '    <p style="color:#aaa; font-size:11px; margin-top:20px;">\n'
        '      Sent by BurnLens &mdash; <a href="https://github.com/burnlens/burnlens" style="color:#aaa;">github.com/burnlens/burnlens</a>\n'
        '    </p>\n'
        '  </div>\n'
        '</body>\n'
        '</html>'
    )
