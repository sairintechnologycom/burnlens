"""Typer CLI for BurnLens."""
from __future__ import annotations

import asyncio
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import typer
import uvicorn
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from burnlens.config import load_config
from burnlens.proxy.providers import build_env_exports

app = typer.Typer(
    name="burnlens",
    help="See where your LLM money goes.",
    add_completion=False,
)
console = Console()

_SEVERITY_COLORS = {"high": "red", "medium": "yellow", "low": "dim"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _since_iso(days: int) -> str:
    """Return ISO timestamp for N days ago (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _fmt_cost(usd: float) -> str:
    if usd == 0.0:
        return "[dim]$0.0000[/dim]"
    return f"[green]${usd:.4f}[/green]"


def _build_top_table(rows: list[dict[str, Any]], today_cost: float, budget_usd: float | None) -> Table:
    """Build the Rich table for `burnlens top`."""
    table = Table(
        title="[bold]BurnLens — Live Traffic[/bold]",
        show_lines=False,
        expand=True,
    )
    table.add_column("Time", style="dim", no_wrap=True, width=12)
    table.add_column("Model", style="cyan", min_width=20)
    table.add_column("Tokens In", justify="right")
    table.add_column("Tokens Out", justify="right")
    table.add_column("Cost", justify="right", style="green")
    table.add_column("Tag", style="magenta")
    table.add_column("Latency", justify="right", style="dim")

    for r in rows:
        ts = r.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M:%S")
        except Exception:
            time_str = ts[:8]

        tags: dict[str, str] = r.get("tags") or {}
        tag_str = tags.get("feature") or tags.get("team") or ""
        latency_ms = r.get("duration_ms") or 0
        latency_str = f"{latency_ms}ms" if latency_ms else "—"

        table.add_row(
            time_str,
            r.get("model", "—"),
            f"{(r.get('input_tokens') or 0):,}",
            f"{(r.get('output_tokens') or 0):,}",
            f"${(r.get('cost_usd') or 0.0):.4f}",
            tag_str,
            latency_str,
        )

    # Footer row with today's totals
    budget_str = ""
    if budget_usd:
        pct = (today_cost / budget_usd) * 100
        budget_str = f"  [dim]|[/dim]  Budget: {_fmt_cost(today_cost)} / ${budget_usd:.2f} ({pct:.1f}%)"

    table.caption = (
        f"Today: {_fmt_cost(today_cost)}{budget_str}  [dim]•  auto-refresh every 2s  •  Ctrl+C to quit[/dim]"
    )
    return table


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def start(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to burnlens.yaml"),
    port: Optional[int] = typer.Option(None, "--port", "-p", help="Proxy port (default 8420)"),
    host: Optional[str] = typer.Option(None, "--host", help="Bind host (default 127.0.0.1)"),
    no_env: bool = typer.Option(False, "--no-env", help="Don't print env var exports"),
) -> None:
    """Start the BurnLens proxy server."""
    cfg = load_config(config)
    if port is not None:
        cfg.port = port
    if host is not None:
        cfg.host = host

    from burnlens.proxy.server import get_app

    fastapi_app = get_app(cfg)
    env_exports = build_env_exports(cfg.host, cfg.port)

    if not no_env:
        console.print()
        console.print("[bold green]BurnLens[/bold green] — LLM cost proxy starting…")
        console.print()
        console.print("[dim]Set these env vars so your SDK routes through BurnLens:[/dim]")
        console.print()
        for var, url in env_exports.items():
            console.print(f"  [cyan]export {var}={url}[/cyan]")
        console.print()
        console.print(
            f"[dim]Dashboard:[/dim] [underline]http://{cfg.host}:{cfg.port}/ui[/underline]"
        )
        console.print(f"[dim]Database: [/dim] {cfg.db_path}")
        console.print()

    uvicorn.run(
        fastapi_app,
        host=cfg.host,
        port=cfg.port,
        log_level=cfg.log_level.lower(),
        access_log=False,
    )


@app.command()
def top(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    limit: int = typer.Option(20, "--limit", "-n", help="Rows to display"),
    refresh: float = typer.Option(2.0, "--refresh", "-r", help="Refresh interval in seconds"),
) -> None:
    """Live API traffic viewer with auto-refresh."""
    cfg = load_config(config)

    async def _fetch() -> tuple[list[dict[str, Any]], float]:
        from burnlens.storage.queries import get_recent_requests, get_total_cost

        today_since = _since_iso(0)  # since midnight-ish
        rows, cost = await asyncio.gather(
            get_recent_requests(cfg.db_path, limit=limit),
            get_total_cost(cfg.db_path, since=today_since),
        )
        return rows, cost

    def _render() -> Table:
        rows, cost = asyncio.run(_fetch())
        return _build_top_table(rows, cost, cfg.alerts.budget_limit_usd)

    with Live(_render(), refresh_per_second=1, screen=False) as live:
        try:
            while True:
                time.sleep(refresh)
                live.update(_render())
        except KeyboardInterrupt:
            pass


@app.command()
def report(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    days: int = typer.Option(7, "--days", "-d", help="Number of days to include"),
) -> None:
    """Print a cost digest report."""
    cfg = load_config(config)

    async def _run() -> None:
        from burnlens.analysis.budget import compute_budget_status
        from burnlens.storage.queries import (
            get_daily_cost,
            get_total_cost,
            get_total_request_count,
            get_usage_by_model,
            get_usage_by_tag,
        )

        since = _since_iso(days)

        (
            total_cost,
            total_requests,
            models,
            by_feature,
            by_team,
            daily,
        ) = await asyncio.gather(
            get_total_cost(cfg.db_path, since=since),
            get_total_request_count(cfg.db_path, since=since),
            get_usage_by_model(cfg.db_path, since=since),
            get_usage_by_tag(cfg.db_path, tag_key="feature", since=since),
            get_usage_by_tag(cfg.db_path, tag_key="team", since=since),
            get_daily_cost(cfg.db_path, days=days),
        )

        budget_status = compute_budget_status(
            spent_usd=total_cost,
            budget_usd=cfg.alerts.budget_limit_usd,
            period_days=30,
        )

        console.print()
        console.rule(f"[bold]BurnLens Report[/bold] — last {days} day(s)")
        console.print()

        # ── Summary panel ────────────────────────────────────────────────────
        summary_lines = [
            f"  Total spend:    [bold green]${total_cost:.4f}[/bold green]",
            f"  Requests:       {total_requests:,}",
            f"  Models used:    {len(models)}",
            f"  Period:         last {days} day(s)",
        ]
        console.print(Panel("\n".join(summary_lines), title="Summary", border_style="green"))

        # ── By model ─────────────────────────────────────────────────────────
        if models:
            model_table = Table(show_header=True, box=None, padding=(0, 2))
            model_table.add_column("Model", style="cyan")
            model_table.add_column("Provider", style="dim")
            model_table.add_column("Requests", justify="right")
            model_table.add_column("In Tokens", justify="right")
            model_table.add_column("Out Tokens", justify="right")
            model_table.add_column("Cost", justify="right", style="green")
            model_table.add_column("% of Total", justify="right")

            for m in models:
                pct = (m.total_cost_usd / total_cost * 100) if total_cost else 0.0
                model_table.add_row(
                    m.model,
                    m.provider,
                    f"{m.request_count:,}",
                    f"{m.total_input_tokens:,}",
                    f"{m.total_output_tokens:,}",
                    f"${m.total_cost_usd:.4f}",
                    f"{pct:.1f}%",
                )

            console.print(Panel(model_table, title="By Model", border_style="blue"))

        # ── By tag ───────────────────────────────────────────────────────────
        def _tag_panel(data: list[dict[str, Any]], title: str, key: str) -> None:
            if not data or (len(data) == 1 and data[0]["tag"] == "(untagged)"):
                return
            t = Table(show_header=True, box=None, padding=(0, 2))
            t.add_column(key.capitalize(), style="magenta")
            t.add_column("Requests", justify="right")
            t.add_column("Cost", justify="right", style="green")
            t.add_column("% of Total", justify="right")
            for row in data:
                pct = (row["total_cost_usd"] / total_cost * 100) if total_cost else 0.0
                t.add_row(
                    row["tag"],
                    f"{row['request_count']:,}",
                    f"${row['total_cost_usd']:.4f}",
                    f"{pct:.1f}%",
                )
            console.print(Panel(t, title=title, border_style="magenta"))

        _tag_panel(by_feature, "By Feature Tag", "feature")
        _tag_panel(by_team, "By Team Tag", "team")

        # ── Daily trend ──────────────────────────────────────────────────────
        if daily:
            trend_lines = []
            max_cost = max((d["total_cost_usd"] or 0.0) for d in daily) or 1.0
            bar_width = 30
            for d in daily:
                day_cost = d["total_cost_usd"] or 0.0
                bar_len = int((day_cost / max_cost) * bar_width)
                bar = "█" * bar_len
                trend_lines.append(
                    f"  {d['day']}  [green]{bar:<{bar_width}}[/green]  ${day_cost:.4f}"
                )
            console.print(
                Panel("\n".join(trend_lines), title="Daily Spend", border_style="dim")
            )

        # ── Budget status ────────────────────────────────────────────────────
        if budget_status.has_budget:
            pct = budget_status.pct_used or 0.0
            bar_len = min(int(pct / 2), 50)
            bar = "█" * bar_len
            color = "red" if budget_status.is_over_budget else "yellow" if pct > 75 else "green"
            budget_lines = [
                f"  Limit:     ${budget_status.budget_usd:.2f}",
                f"  Spent:     ${budget_status.spent_usd:.4f}  ({pct:.1f}%)",
                f"  Forecast:  ${budget_status.forecast_usd:.4f}",
                f"  [{color}]{bar}[/{color}]",
            ]
            if budget_status.is_over_budget:
                budget_lines.append("  [bold red]OVER BUDGET[/bold red]")
            elif budget_status.is_on_pace_to_exceed:
                budget_lines.append("  [yellow]On pace to exceed budget[/yellow]")
            else:
                budget_lines.append(
                    f"  Remaining: [green]${budget_status.remaining_usd:.4f}[/green]"
                )
            console.print(
                Panel("\n".join(budget_lines), title="Budget Status", border_style=color)
            )
        else:
            console.print(
                Panel(
                    f"  No budget configured.\n"
                    f"  Forecast (30-day): [yellow]${budget_status.forecast_usd:.4f}[/yellow]\n"
                    f"  Add [cyan]budget_limit_usd[/cyan] to burnlens.yaml to enable tracking.",
                    title="Budget Status",
                    border_style="dim",
                )
            )

        console.print()

    asyncio.run(_run())


@app.command()
def analyze(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    days: int = typer.Option(1, "--days", "-d", help="Number of days to analyze"),
) -> None:
    """Run waste detectors and print findings."""
    cfg = load_config(config)

    async def _run() -> None:
        from burnlens.analysis.waste import run_all_detectors
        from burnlens.storage.queries import get_requests_for_analysis

        since = _since_iso(days)
        requests = await get_requests_for_analysis(cfg.db_path, since=since)

        console.print()
        console.rule(
            f"[bold]BurnLens Waste Analysis[/bold] — last {days} day(s) ({len(requests)} requests)"
        )
        console.print()

        if not requests:
            console.print("[yellow]No requests found in the analysis window.[/yellow]")
            console.print()
            return

        findings = run_all_detectors(requests)
        total_waste = sum(f.estimated_waste_usd for f in findings)

        for finding in findings:
            color = _SEVERITY_COLORS.get(finding.severity, "white")
            severity_badge = f"[{color}][{finding.severity.upper()}][/{color}]"

            lines = [f"  {severity_badge}  {finding.description}"]
            if finding.estimated_waste_usd > 0:
                lines.append(
                    f"\n  Estimated waste: [yellow]${finding.estimated_waste_usd:.4f}[/yellow]"
                )
            if finding.affected_count > 0:
                lines.append(f"  Affected:        {finding.affected_count} request(s)")

            console.print(
                Panel(
                    "\n".join(lines),
                    title=f"[bold]{finding.title}[/bold]",
                    border_style=color,
                )
            )

        if total_waste > 0:
            console.print(
                Panel(
                    f"  Total estimated savings available: [bold yellow]${total_waste:.4f}[/bold yellow]",
                    title="Summary",
                    border_style="yellow",
                )
            )
        else:
            console.print(
                Panel(
                    "  [green]No significant waste detected.[/green] Keep it up!",
                    title="Summary",
                    border_style="green",
                )
            )

        console.print()

    asyncio.run(_run())


@app.command()
def export(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    days: int = typer.Option(7, "--days", "-d", help="Number of days to export"),
    output: Path = typer.Option(
        "burnlens_export.csv", "--output", "-o", help="Output CSV file path"
    ),
    team: Optional[str] = typer.Option(None, "--team", help="Filter by tag_team"),
    feature: Optional[str] = typer.Option(None, "--feature", help="Filter by tag_feature"),
) -> None:
    """Export request data to CSV."""
    cfg = load_config(config)

    async def _run() -> None:
        from burnlens.export import export_to_csv
        from burnlens.storage.database import get_requests_for_export

        rows = await get_requests_for_export(
            cfg.db_path, days=days, team=team, feature=feature
        )

        if not rows:
            console.print("[yellow]No requests found for the given filters.[/yellow]")
            return

        export_to_csv(rows, output)
        console.print(
            f"Exporting {len(rows)} requests to {output}... [green]done.[/green]"
        )

    asyncio.run(_run())


@app.command()
def budgets(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
) -> None:
    """Show per-team budget status for the current month."""
    import json as json_mod

    cfg = load_config(config)

    async def _run() -> None:
        from burnlens.storage.database import get_spend_by_team_this_month

        team_limits = cfg.alerts.budgets.teams
        if not team_limits:
            if json_output:
                console.print("[]")
            else:
                console.print("[yellow]No team budgets configured.[/yellow]")
                console.print("Add a [cyan]budgets.teams[/cyan] section to burnlens.yaml.")
            return

        spend = await get_spend_by_team_this_month(cfg.db_path)

        rows = []
        for team, limit in sorted(team_limits.items()):
            spent = spend.get(team, 0.0)
            pct = (spent / limit * 100) if limit > 0 else 0.0
            if pct >= 100:
                status = "CRITICAL"
            elif pct >= 80:
                status = "WARNING"
            else:
                status = "OK"
            rows.append({
                "team": team,
                "spent": round(spent, 6),
                "limit": limit,
                "pct_used": round(pct, 1),
                "status": status,
            })

        if json_output:
            console.print(json_mod.dumps(rows, indent=2))
            return

        console.print()
        table = Table(title="[bold]Team Budgets[/bold] — current month", expand=True)
        table.add_column("Team", style="cyan")
        table.add_column("Spent", justify="right", style="green")
        table.add_column("Limit", justify="right")
        table.add_column("% Used", justify="right")
        table.add_column("Status", justify="center")

        for r in rows:
            pct_str = f"{r['pct_used']:.1f}%"
            status = r["status"]
            if status == "CRITICAL":
                status_str = "[bold red]CRITICAL[/bold red]"
                pct_str = f"[red]{pct_str}[/red]"
            elif status == "WARNING":
                status_str = "[yellow]WARNING[/yellow]"
                pct_str = f"[yellow]{pct_str}[/yellow]"
            else:
                status_str = "[green]OK[/green]"

            table.add_row(
                r["team"],
                f"${r['spent']:.4f}",
                f"${r['limit']:.2f}",
                pct_str,
                status_str,
            )

        console.print(table)
        console.print()

    asyncio.run(_run())


@app.command()
def ui(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
) -> None:
    """Open the dashboard in the default browser."""
    cfg = load_config(config)
    url = f"http://{cfg.host}:{cfg.port}/ui"
    console.print(f"Opening [underline]{url}[/underline]")
    webbrowser.open(url)


if __name__ == "__main__":
    app()
