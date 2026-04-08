"""Typer CLI for BurnLens."""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Optional

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from burnlens.config import load_config
from burnlens.proxy.providers import build_env_exports

app = typer.Typer(
    name="burnlens",
    help="See where your LLM money goes.",
    add_completion=False,
)
console = Console()


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
        console.print(
            f"[dim]Database: [/dim] {cfg.db_path}"
        )
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
    limit: int = typer.Option(10, "--limit", "-n", help="Number of rows"),
) -> None:
    """Show top models by cost."""
    cfg = load_config(config)

    async def _run() -> None:
        from burnlens.storage.queries import get_usage_by_model

        rows = await get_usage_by_model(cfg.db_path)
        if not rows:
            console.print("[yellow]No requests logged yet.[/yellow]")
            return

        table = Table(title="Top Models by Cost", show_lines=False)
        table.add_column("Model", style="cyan")
        table.add_column("Provider", style="dim")
        table.add_column("Requests", justify="right")
        table.add_column("Input Tokens", justify="right")
        table.add_column("Output Tokens", justify="right")
        table.add_column("Cost (USD)", justify="right", style="green")

        for row in rows[:limit]:
            table.add_row(
                row.model,
                row.provider,
                str(row.request_count),
                f"{row.total_input_tokens:,}",
                f"{row.total_output_tokens:,}",
                f"${row.total_cost_usd:.4f}",
            )

        console.print(table)

    asyncio.run(_run())


@app.command()
def report(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
) -> None:
    """Print a cost summary report."""
    cfg = load_config(config)

    async def _run() -> None:
        from burnlens.storage.queries import get_total_cost, get_usage_by_model

        total = await get_total_cost(cfg.db_path)
        models = await get_usage_by_model(cfg.db_path)
        total_requests = sum(m.request_count for m in models)

        console.print()
        console.print(f"[bold]BurnLens Report[/bold]")
        console.print(f"  Total cost:     [green]${total:.4f}[/green]")
        console.print(f"  Total requests: {total_requests}")
        console.print(f"  Models used:    {len(models)}")
        console.print()

    asyncio.run(_run())


@app.command()
def ui(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
) -> None:
    """Open the dashboard in the default browser."""
    import webbrowser

    cfg = load_config(config)
    url = f"http://{cfg.host}:{cfg.port}/ui"
    console.print(f"Opening [underline]{url}[/underline]")
    webbrowser.open(url)


if __name__ == "__main__":
    app()
