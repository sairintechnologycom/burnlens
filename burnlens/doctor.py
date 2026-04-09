"""BurnLens doctor: system health checks for proxy, database, and providers."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx


@dataclass
class CheckResult:
    """Result of a single doctor check."""

    status: Literal["pass", "warn", "fail", "skip"]
    label: str
    message: str
    fix: str | None = None


def check_proxy(host: str, port: int) -> CheckResult:
    """Check if the BurnLens proxy is reachable."""
    url = f"http://{host}:{port}/health"
    try:
        resp = httpx.get(url, timeout=3.0)
        if resp.status_code == 200:
            return CheckResult("pass", "Proxy", f"Proxy running on :{port}")
        return CheckResult(
            "fail", "Proxy",
            f"Proxy returned HTTP {resp.status_code}",
            fix="burnlens start",
        )
    except httpx.ConnectError:
        return CheckResult(
            "fail", "Proxy",
            "Proxy not running",
            fix="burnlens start",
        )
    except Exception as exc:
        return CheckResult(
            "fail", "Proxy",
            f"Could not reach proxy: {exc}",
            fix="burnlens start",
        )


def check_database(db_path: str) -> CheckResult:
    """Check if the database exists and is readable."""
    path = Path(db_path)
    if not path.exists():
        return CheckResult(
            "fail", "Database",
            f"Database not found at {db_path}",
            fix="Run burnlens start to initialise",
        )
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM requests")
        count = cursor.fetchone()[0]
        conn.close()
        return CheckResult("pass", "Database", f"Database OK — {count:,} requests logged")
    except Exception as exc:
        return CheckResult(
            "fail", "Database",
            f"Database corrupt or unreadable: {exc}",
            fix=f"Check file permissions on {db_path}",
        )


def check_openai() -> CheckResult:
    """Check OpenAI environment variables."""
    base_url = os.environ.get("OPENAI_BASE_URL")
    api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        return CheckResult(
            "warn", "OpenAI",
            "OPENAI_API_KEY not set",
            fix="export OPENAI_API_KEY=sk-...",
        )

    if not base_url:
        return CheckResult(
            "warn", "OpenAI",
            "OPENAI_BASE_URL not set — requests bypass BurnLens",
            fix="export OPENAI_BASE_URL=http://127.0.0.1:8420/proxy/openai/v1",
        )

    expected = "http://127.0.0.1:8420/proxy/openai/v1"
    if base_url.rstrip("/") == expected:
        return CheckResult("pass", "OpenAI", "OPENAI_BASE_URL correctly set with /v1")

    if "proxy/openai" in base_url and not base_url.rstrip("/").endswith("/v1"):
        return CheckResult(
            "warn", "OpenAI",
            "OPENAI_BASE_URL missing /v1 suffix — SDK will get 404s",
            fix=f"export OPENAI_BASE_URL={expected}",
        )

    return CheckResult(
        "warn", "OpenAI",
        f"OPENAI_BASE_URL set to {base_url} — not pointing at BurnLens",
        fix=f"export OPENAI_BASE_URL={expected}",
    )


def check_anthropic() -> CheckResult:
    """Check Anthropic environment variables."""
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:
        return CheckResult(
            "warn", "Anthropic",
            "ANTHROPIC_API_KEY not set",
            fix="export ANTHROPIC_API_KEY=sk-ant-...",
        )

    if not base_url:
        return CheckResult(
            "warn", "Anthropic",
            "ANTHROPIC_BASE_URL not set — requests bypass BurnLens",
            fix="export ANTHROPIC_BASE_URL=http://127.0.0.1:8420/proxy/anthropic",
        )

    expected = "http://127.0.0.1:8420/proxy/anthropic"
    if base_url.rstrip("/") == expected:
        return CheckResult("pass", "Anthropic", "ANTHROPIC_BASE_URL correctly set")

    return CheckResult(
        "warn", "Anthropic",
        f"ANTHROPIC_BASE_URL set to {base_url} — not pointing at BurnLens",
        fix=f"export ANTHROPIC_BASE_URL={expected}",
    )


def check_google() -> CheckResult:
    """Check Google environment variables and warn about patch requirement."""
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return CheckResult(
            "warn", "Google",
            "GOOGLE_API_KEY / GEMINI_API_KEY not set",
            fix="export GOOGLE_API_KEY=...",
        )

    return CheckResult(
        "warn", "Google",
        "Google requires burnlens.patch.patch_google() in your code",
        fix="import burnlens.patch; burnlens.patch.patch_google()",
    )


def check_recent_activity(db_path: str) -> CheckResult:
    """Check for recent request activity."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT COUNT(*) FROM requests WHERE timestamp > datetime('now', '-1 hour')"
        )
        count = cursor.fetchone()[0]

        recent: list[dict[str, Any]] = []
        rows = conn.execute(
            "SELECT timestamp, provider, model, cost_usd "
            "FROM requests ORDER BY timestamp DESC LIMIT 3"
        ).fetchall()
        for row in rows:
            recent.append({
                "timestamp": row[0],
                "provider": row[1],
                "model": row[2],
                "cost_usd": row[3],
            })
        conn.close()

        if count > 0:
            return CheckResult(
                "pass", "Recent activity",
                f"{count} request(s) in last hour",
            )
        msg = "No requests in last hour. Is your SDK pointing at the proxy?"
        if recent:
            lines = [msg]
            for r in recent:
                lines.append(
                    f"  Last seen: {r['provider']}/{r['model']} ${r['cost_usd']:.6f}"
                )
            msg = "\n".join(lines)
        return CheckResult("warn", "Recent activity", msg)
    except Exception as exc:
        return CheckResult("fail", "Recent activity", f"Query failed: {exc}")


def check_token_extraction(db_path: str) -> CheckResult:
    """Check for successful requests with zero cost (broken token extraction)."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT COUNT(*) FROM requests WHERE cost_usd = 0 AND status_code = 200"
        )
        count = cursor.fetchone()[0]
        conn.close()

        if count > 0:
            return CheckResult(
                "warn", "Token extraction",
                f"{count} successful request(s) logged $0.00 cost — token extraction may be broken",
            )
        return CheckResult(
            "pass", "Token extraction",
            "All successful requests have non-zero cost",
        )
    except Exception as exc:
        return CheckResult("fail", "Token extraction", f"Query failed: {exc}")


def run_all_checks(
    host: str = "127.0.0.1",
    port: int = 8420,
    db_path: str = str(Path.home() / ".burnlens" / "burnlens.db"),
) -> list[CheckResult]:
    """Run all doctor checks. Individual checks never crash the runner."""
    results: list[CheckResult] = []

    # 1. Proxy
    try:
        results.append(check_proxy(host, port))
    except Exception as exc:
        results.append(CheckResult("fail", "Proxy", f"Check crashed: {exc}"))

    proxy_up = results[0].status == "pass"

    # 2. Database
    try:
        results.append(check_database(db_path))
    except Exception as exc:
        results.append(CheckResult("fail", "Database", f"Check crashed: {exc}"))

    db_ok = results[1].status == "pass"

    # 3. OpenAI
    try:
        results.append(check_openai())
    except Exception as exc:
        results.append(CheckResult("fail", "OpenAI", f"Check crashed: {exc}"))

    # 4. Anthropic
    try:
        results.append(check_anthropic())
    except Exception as exc:
        results.append(CheckResult("fail", "Anthropic", f"Check crashed: {exc}"))

    # 5. Google
    try:
        results.append(check_google())
    except Exception as exc:
        results.append(CheckResult("fail", "Google", f"Check crashed: {exc}"))

    # 6. Recent activity (skip if proxy or db not available)
    if proxy_up and db_ok:
        try:
            results.append(check_recent_activity(db_path))
        except Exception as exc:
            results.append(CheckResult("fail", "Recent activity", f"Check crashed: {exc}"))
    else:
        results.append(CheckResult("skip", "Recent activity", "Skipped — proxy or database unavailable"))

    # 7. Token extraction (skip if proxy or db not available)
    if proxy_up and db_ok:
        try:
            results.append(check_token_extraction(db_path))
        except Exception as exc:
            results.append(CheckResult("fail", "Token extraction", f"Check crashed: {exc}"))
    else:
        results.append(CheckResult("skip", "Token extraction", "Skipped — proxy or database unavailable"))

    return results


def results_to_json(results: list[CheckResult]) -> str:
    """Serialize check results to JSON."""
    return json.dumps(
        [
            {
                "status": r.status,
                "label": r.label,
                "message": r.message,
                "fix": r.fix,
            }
            for r in results
        ],
        indent=2,
    )
