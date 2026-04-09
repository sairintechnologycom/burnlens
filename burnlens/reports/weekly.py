"""Weekly cost report generation and rendering."""
from __future__ import annotations

import json
import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Any

import re

import aiosqlite

# Strip trailing date suffixes like -20251001 or -20250219 from model IDs
_DATE_SUFFIX_RE = re.compile(r"-\d{8}$")


def normalize_model_name(name: str) -> str:
    """Strip date suffixes from API model IDs for display.

    e.g. 'claude-haiku-4-5-20251001' → 'claude-haiku-4-5'
    """
    return _DATE_SUFFIX_RE.sub("", name) if name else name


@dataclass
class WeeklyReport:
    """Aggregated cost report for a time period."""

    period_start: datetime
    period_end: datetime
    total_cost: float
    total_requests: int
    cost_by_model: dict[str, float]
    cost_by_team: dict[str, float]
    cost_by_feature: dict[str, float]
    top_waste_findings: list[str]
    vs_prior_week: float  # percent change


async def generate_weekly_report(db_path: str, days: int = 7) -> WeeklyReport:
    """Query the database and produce a WeeklyReport for the last N days."""
    now = datetime.now(timezone.utc)
    period_end = now
    period_start = now - timedelta(days=days)
    prior_start = period_start - timedelta(days=days)

    since = period_start.isoformat()
    prior_since = prior_start.isoformat()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Total cost and requests for current period
        cur = await db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total_cost, COUNT(*) AS total_requests "
            "FROM requests WHERE timestamp >= ?",
            (since,),
        )
        row = await cur.fetchone()
        total_cost = float(row["total_cost"])
        total_requests = int(row["total_requests"])

        # Prior period cost for comparison
        cur = await db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total_cost "
            "FROM requests WHERE timestamp >= ? AND timestamp < ?",
            (prior_since, since),
        )
        row = await cur.fetchone()
        prior_cost = float(row["total_cost"])

        # Cost by model
        cur = await db.execute(
            "SELECT model, SUM(cost_usd) AS cost FROM requests "
            "WHERE timestamp >= ? GROUP BY model ORDER BY cost DESC",
            (since,),
        )
        rows = await cur.fetchall()
        cost_by_model: dict[str, float] = {}
        for r in rows:
            name = normalize_model_name(r["model"] or "unknown")
            cost_by_model[name] = cost_by_model.get(name, 0.0) + float(r["cost"])

        # Cost by team and feature (from JSON tags)
        cur = await db.execute(
            "SELECT tags, cost_usd FROM requests WHERE timestamp >= ?",
            (since,),
        )
        rows = await cur.fetchall()

    cost_by_team: dict[str, float] = {}
    cost_by_feature: dict[str, float] = {}
    for row in rows:
        tags = json.loads(row["tags"] or "{}")
        team = tags.get("team")
        feature = tags.get("feature")
        cost = float(row["cost_usd"] or 0.0)
        if team:
            cost_by_team[team] = cost_by_team.get(team, 0.0) + cost
        if feature:
            cost_by_feature[feature] = cost_by_feature.get(feature, 0.0) + cost

    # Waste findings (lightweight — reuse detector summaries)
    top_waste_findings = await _detect_waste_summaries(db_path, since)

    # Percent change vs prior period
    if prior_cost > 0:
        vs_prior_week = ((total_cost - prior_cost) / prior_cost) * 100
    elif total_cost > 0:
        vs_prior_week = 100.0
    else:
        vs_prior_week = 0.0

    return WeeklyReport(
        period_start=period_start,
        period_end=period_end,
        total_cost=total_cost,
        total_requests=total_requests,
        cost_by_model=cost_by_model,
        cost_by_team=cost_by_team,
        cost_by_feature=cost_by_feature,
        top_waste_findings=top_waste_findings,
        vs_prior_week=vs_prior_week,
    )


async def _detect_waste_summaries(db_path: str, since: str) -> list[str]:
    """Run waste detectors and return human-readable summary strings."""
    from burnlens.analysis.waste import run_all_detectors
    from burnlens.storage.queries import get_requests_for_analysis

    requests = await get_requests_for_analysis(db_path, since=since)
    if not requests:
        return []

    findings = run_all_detectors(requests)
    return [
        f"{f.title}: {f.description}" for f in findings if f.severity != "low"
    ]


def generate_text_report(report: WeeklyReport) -> str:
    """Render a WeeklyReport as plain text suitable for terminal or email."""
    start_str = report.period_start.strftime("%-d %b")
    end_str = report.period_end.strftime("%-d %b %Y")

    sign = "+" if report.vs_prior_week >= 0 else ""
    change_str = f"({sign}{report.vs_prior_week:.0f}% vs prior period)"

    lines: list[str] = []
    lines.append(f"BurnLens Weekly Report — {start_str} to {end_str}")
    lines.append("─" * len(lines[0]))
    lines.append(f"Total spend:    ${report.total_cost:.2f}  {change_str}")
    lines.append(f"Total requests: {report.total_requests:,}")
    lines.append("")

    # By model
    if report.cost_by_model:
        lines.append("By model:")
        for model, cost in sorted(
            report.cost_by_model.items(), key=lambda x: x[1], reverse=True
        ):
            pct = (cost / report.total_cost * 100) if report.total_cost else 0
            lines.append(f"  {model:<20s} ${cost:.2f}  ({pct:.0f}%)")
        lines.append("")

    # By team
    if report.cost_by_team:
        lines.append("By team:")
        for team, cost in sorted(
            report.cost_by_team.items(), key=lambda x: x[1], reverse=True
        ):
            lines.append(f"  {team:<20s} ${cost:.2f}")
        lines.append("")

    # By feature
    if report.cost_by_feature:
        lines.append("By feature:")
        for feature, cost in sorted(
            report.cost_by_feature.items(), key=lambda x: x[1], reverse=True
        ):
            lines.append(f"  {feature:<20s} ${cost:.2f}")
        lines.append("")

    # Waste alerts
    lines.append("Waste alerts:")
    if report.top_waste_findings:
        for finding in report.top_waste_findings:
            lines.append(f"  - {finding}")
    else:
        lines.append("  - No significant waste detected")

    return "\n".join(lines)


def send_report_email(
    report_text: str,
    to_email: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    from_addr: str,
) -> None:
    """Send the report as a plain-text email via SMTP/TLS."""
    msg = MIMEText(report_text)
    msg["Subject"] = "BurnLens Weekly Report"
    msg["From"] = from_addr
    msg["To"] = to_email

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(from_addr, [to_email], msg.as_string())
