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
    otel: bool = typer.Option(False, "--otel", help="Enable OpenTelemetry export for this session"),
) -> None:
    """Start the BurnLens proxy server."""
    cfg = load_config(config)
    if port is not None:
        cfg.port = port
    if host is not None:
        cfg.host = host
    if otel:
        cfg.telemetry.enabled = True

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

    # Initialise OpenTelemetry if enabled
    if cfg.telemetry.enabled:
        try:
            from burnlens.telemetry.otel import init_tracer
            init_tracer(
                endpoint=cfg.telemetry.otel_endpoint,
                service_name=cfg.telemetry.service_name,
            )
            console.print(
                f"[bold blue]OTEL[/bold blue] exporting to {cfg.telemetry.otel_endpoint}"
            )
        except ImportError:
            console.print(
                "[bold red]OpenTelemetry not installed.[/bold red] "
                "Run: [cyan]pip install burnlens\\[otel][/cyan]"
            )
            raise typer.Exit(code=1)

    uvicorn.run(
        fastapi_app,
        host=cfg.host,
        port=cfg.port,
        log_level=cfg.log_level.lower(),
        access_log=False,
    )


@app.command("check-otel")
def check_otel(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    endpoint: Optional[str] = typer.Option(None, "--endpoint", help="OTLP endpoint to test"),
) -> None:
    """Verify connectivity to the OpenTelemetry collector."""
    cfg = load_config(config)
    target = endpoint or cfg.telemetry.otel_endpoint

    try:
        from burnlens.telemetry.otel import check_otel_connection
    except ImportError:
        console.print(
            "[bold red]OpenTelemetry not installed.[/bold red] "
            "Run: [cyan]pip install burnlens\\[otel][/cyan]"
        )
        raise typer.Exit(code=1)

    console.print(f"Checking OTEL collector at [cyan]{target}[/cyan] …")
    if check_otel_connection(target):
        console.print("[green]Connection OK[/green]")
    else:
        console.print("[red]Connection failed[/red] — is the collector running?")
        raise typer.Exit(code=1)


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
    email: Optional[str] = typer.Option(None, "--email", "-e", help="Send report to this email address"),
) -> None:
    """Generate and print (or email) a cost summary report."""
    cfg = load_config(config)

    async def _run() -> None:
        from burnlens.reports.weekly import (
            generate_text_report,
            generate_weekly_report,
            send_report_email,
        )

        report_data = await generate_weekly_report(cfg.db_path, days=days)
        report_text = generate_text_report(report_data)

        console.print()
        console.print(report_text)
        console.print()

        if email:
            ec = cfg.email
            if not ec.smtp_host or not ec.smtp_user or not ec.smtp_password:
                console.print("[bold red]Email not configured.[/bold red]")
                console.print()
                console.print("Add this to your burnlens.yaml:")
                console.print()
                console.print("  [cyan]email:[/cyan]")
                console.print("  [cyan]  smtp_host: smtp.gmail.com[/cyan]")
                console.print("  [cyan]  smtp_port: 587[/cyan]")
                console.print("  [cyan]  smtp_user: you@gmail.com[/cyan]")
                console.print("  [cyan]  smtp_password: your-app-password[/cyan]")
                console.print("  [cyan]  from: BurnLens <you@gmail.com>[/cyan]")
                raise typer.Exit(code=1)

            from_addr = ec.from_addr or ec.smtp_user
            send_report_email(
                report_text=report_text,
                to_email=email,
                smtp_host=ec.smtp_host,
                smtp_port=ec.smtp_port,
                smtp_user=ec.smtp_user,
                smtp_password=ec.smtp_password,
                from_addr=from_addr,
            )
            console.print(f"[green]Report sent to {email}[/green]")

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
def customers(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    customer: Optional[str] = typer.Option(None, "--customer", help="Show detail for one customer"),
    over_budget: bool = typer.Option(False, "--over-budget", help="Only show customers who exceeded limit"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
) -> None:
    """Show per-customer spend and budget status for the current month."""
    import json as json_mod

    cfg = load_config(config)

    async def _run() -> None:
        from burnlens.storage.database import (
            get_customer_request_count,
            get_spend_by_customer_this_month,
            get_top_customers_by_cost,
        )

        cust_cfg = cfg.alerts.customer_budgets

        if customer:
            # Detail for one customer
            spend_map = await get_spend_by_customer_this_month(cfg.db_path)
            spent = spend_map.get(customer, 0.0)
            req_count = await get_customer_request_count(cfg.db_path, customer)
            limit = cust_cfg.customers.get(customer, cust_cfg.default)

            if json_output:
                console.print(json_mod.dumps({
                    "customer": customer,
                    "spent": round(spent, 6),
                    "requests_30d": req_count,
                    "limit": limit,
                    "pct_used": round(spent / limit * 100, 1) if limit else None,
                }))
                return

            console.print()
            console.print(f"[bold cyan]{customer}[/bold cyan]")
            console.print(f"  Spent this month: {_fmt_cost(spent)}")
            console.print(f"  Requests (30d):   {req_count}")
            if limit:
                pct = spent / limit * 100
                console.print(f"  Budget limit:     ${limit:.2f}")
                console.print(f"  Budget used:      {pct:.1f}%")
            else:
                console.print("  Budget limit:     [dim]none[/dim]")
            console.print()
            return

        # All customers
        rows = await get_top_customers_by_cost(cfg.db_path)

        if not rows:
            if json_output:
                console.print("[]")
            else:
                console.print("[yellow]No customer-tagged requests found.[/yellow]")
                console.print("Tag requests with [cyan]X-BurnLens-Tag-Customer[/cyan] header.")
            return

        # Enrich with budget info
        enriched = []
        for r in rows:
            name = r["customer"]
            limit = cust_cfg.customers.get(name, cust_cfg.default)
            pct = (r["total_cost"] / limit * 100) if limit and limit > 0 else None
            if pct is not None and pct >= 100:
                status = "EXCEEDED"
            elif pct is not None and pct >= 80:
                status = "WARNING"
            elif pct is not None:
                status = "OK"
            else:
                status = "NO_LIMIT"
            enriched.append({**r, "limit": limit, "pct_used": pct, "status": status})

        if over_budget:
            enriched = [r for r in enriched if r["status"] == "EXCEEDED"]

        if json_output:
            console.print(json_mod.dumps(enriched, indent=2))
            return

        console.print()
        table = Table(title="[bold]Customer Spend[/bold] — current month", expand=True)
        table.add_column("Customer", style="cyan")
        table.add_column("Requests", justify="right")
        table.add_column("Total Cost", justify="right", style="green")
        table.add_column("Budget", justify="right")
        table.add_column("% Used", justify="right")
        table.add_column("Status", justify="center")

        for r in enriched:
            pct_str = f"{r['pct_used']:.1f}%" if r["pct_used"] is not None else "—"
            status = r["status"]
            if status == "EXCEEDED":
                status_str = "[bold red]EXCEEDED[/bold red]"
                pct_str = f"[red]{pct_str}[/red]"
            elif status == "WARNING":
                status_str = "[yellow]WARNING[/yellow]"
                pct_str = f"[yellow]{pct_str}[/yellow]"
            elif status == "OK":
                status_str = "[green]OK[/green]"
            else:
                status_str = "[dim]—[/dim]"

            table.add_row(
                r["customer"],
                str(r["request_count"]),
                f"${r['total_cost']:.4f}",
                f"${r['limit']:.2f}" if r["limit"] else "—",
                pct_str,
                status_str,
            )

        console.print(table)
        console.print()

    asyncio.run(_run())


@app.command()
def recommend(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    days: int = typer.Option(30, "--days", "-d", help="Number of days to analyze"),
    apply: bool = typer.Option(False, "--apply", help="Print env/sed commands to make the switch"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
) -> None:
    """Analyse usage patterns and suggest cheaper model alternatives."""
    import json as json_mod

    cfg = load_config(config)

    async def _run() -> None:
        from burnlens.analysis.recommender import analyse_model_fit

        recs = await analyse_model_fit(cfg.db_path, days=days)

        if json_output:
            console.print(json_mod.dumps(
                [
                    {
                        "current_model": r.current_model,
                        "suggested_model": r.suggested_model,
                        "feature_tag": r.feature_tag,
                        "request_count": r.request_count,
                        "avg_output_tokens": r.avg_output_tokens,
                        "current_cost": r.current_cost,
                        "projected_cost": r.projected_cost,
                        "projected_saving": r.projected_saving,
                        "saving_pct": r.saving_pct,
                        "confidence": r.confidence,
                        "reason": r.reason,
                    }
                    for r in recs
                ],
                indent=2,
            ))
            return

        console.print()
        console.rule(
            f"[bold]BurnLens Recommendations[/bold] — last {days} day(s)"
        )
        console.print()

        if not recs:
            console.print("[green]No recommendations — your model usage looks efficient![/green]")
            console.print()
            return

        total_saving = 0.0
        for rec in recs:
            total_saving += rec.projected_saving

            conf_color = {
                "high": "green",
                "medium": "yellow",
                "low": "dim",
            }.get(rec.confidence, "white")
            conf_badge = f"[{conf_color}][{rec.confidence.upper()}][/{conf_color}]"

            if rec.suggested_model == "prompt-caching":
                title = f"Enable prompt caching for [cyan]{rec.feature_tag}[/cyan]"
            else:
                title = (
                    f"Switch [cyan]{rec.feature_tag}[/cyan] from "
                    f"[red]{rec.current_model}[/red] → [green]{rec.suggested_model}[/green]"
                )

            lines = [
                f"  {conf_badge}  {rec.reason}",
                f"\n  Projected saving: [bold yellow]${rec.projected_saving:.4f}[/bold yellow] ({rec.saving_pct:.1f}%)",
                f"  Based on {rec.request_count} requests averaging {rec.avg_output_tokens:.0f} output tokens",
            ]

            console.print(
                Panel(
                    "\n".join(lines),
                    title=f"[bold]{title}[/bold]",
                    border_style=conf_color,
                )
            )

        console.print(
            Panel(
                f"  Total projected savings: [bold yellow]${total_saving:.4f}[/bold yellow]",
                title="Summary",
                border_style="yellow",
            )
        )

        if apply:
            console.print()
            console.print("[bold]To apply these recommendations:[/bold]")
            console.print()
            for rec in recs:
                if rec.suggested_model == "prompt-caching":
                    console.print(
                        f"  # {rec.feature_tag}: enable prompt caching in your SDK config"
                    )
                else:
                    console.print(
                        f"  [cyan]# {rec.feature_tag}: {rec.current_model} → {rec.suggested_model}[/cyan]"
                    )
                    console.print(
                        f"  sed -i '' 's/{rec.current_model}/{rec.suggested_model}/g' "
                        f"<your-code-file>"
                    )
            console.print()

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
