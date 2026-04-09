"""CSV export for BurnLens request data."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


# CSV column order as specified
CSV_COLUMNS = [
    "timestamp",
    "provider",
    "model",
    "feature",
    "team",
    "customer",
    "tokens_in",
    "tokens_out",
    "reasoning_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cost_usd",
    "latency_ms",
    "status_code",
]


def _row_to_csv_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a database row dict to a CSV-ready dict."""
    tags = row.get("tags") or {}
    if isinstance(tags, str):
        tags = json.loads(tags)

    return {
        "timestamp": row.get("timestamp", ""),
        "provider": row.get("provider", ""),
        "model": row.get("model", ""),
        "feature": tags.get("feature", ""),
        "team": tags.get("team", ""),
        "customer": tags.get("customer", ""),
        "tokens_in": row.get("input_tokens", 0),
        "tokens_out": row.get("output_tokens", 0),
        "reasoning_tokens": row.get("reasoning_tokens", 0),
        "cache_read_tokens": row.get("cache_read_tokens", 0),
        "cache_write_tokens": row.get("cache_write_tokens", 0),
        "cost_usd": f"{row.get('cost_usd', 0.0):.8f}",
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
