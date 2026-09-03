"""CSV export for BurnLens request data."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from burnlens.cost.calculator import PRICING_UNPRICED, pricing_class_for


# CSV column order as specified
CSV_COLUMNS = [
    "timestamp",
    "provider",
    "model",
    "feature",
    "team",
    "customer",
    "repo",
    "dev",
    "pr",
    "branch",
    "tokens_in",
    "tokens_out",
    "reasoning_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cost_usd",
    "pricing_class",
    "latency_ms",
    "status_code",
]


def _row_to_csv_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a database row dict to a CSV-ready dict."""
    tags = row.get("tags") or {}
    if isinstance(tags, str):
        tags = json.loads(tags)

    pricing_class = row.get("pricing_class") or pricing_class_for(
        str(row.get("provider") or ""),
        str(row.get("model") or ""),
        str(row.get("source") or "proxy"),
    )
    # Unpriced cost_usd is a sentinel 0 in SQLite. Printing it as 0.00000000
    # would read as a measured zero; Cost Confidence shows "$ unknown" for the
    # same reason.
    if pricing_class == PRICING_UNPRICED:
        cost_cell = "unknown"
    else:
        cost_cell = f"{row.get('cost_usd', 0.0):.8f}"

    return {
        "timestamp": row.get("timestamp", ""),
        "provider": row.get("provider", ""),
        "model": row.get("model", ""),
        "feature": tags.get("feature", ""),
        "team": tags.get("team", ""),
        "customer": tags.get("customer", ""),
        "repo": tags.get("repo", ""),
        "dev": tags.get("dev", ""),
        "pr": tags.get("pr", ""),
        "branch": tags.get("branch", ""),
        "tokens_in": row.get("input_tokens", 0),
        "tokens_out": row.get("output_tokens", 0),
        "reasoning_tokens": row.get("reasoning_tokens", 0),
        "cache_read_tokens": row.get("cache_read_tokens", 0),
        "cache_write_tokens": row.get("cache_write_tokens", 0),
        "cost_usd": cost_cell,
        "pricing_class": pricing_class,
        "latency_ms": row.get("duration_ms", 0),
        "status_code": row.get("status_code", 200),
    }


def export_to_csv(rows: list[dict[str, Any]], output_path: str | Path) -> None:
    """Write rows to a CSV file with the standard BurnLens column order."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(_row_to_csv_dict(row))
