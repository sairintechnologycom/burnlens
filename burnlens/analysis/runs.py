"""BL-E5 slice 2: reconstruct Run → Step from data that already exists.

The run key is ``tags.session`` first, ``trace_id`` second — deliberately that
order, and the measurement behind it matters:

* 99.6% of real traffic is scan-ingested (``scan_codex`` / ``scan_claude`` /
  ``scan_gemini``), and **100% of those rows carry a ``session`` tag**. A
  coding-agent session IS the run.
* The scan path can never carry a ``trace_id``: it parses JSONL log files after
  the fact, so there is no HTTP request and no ``traceparent`` header to read.
  Keying on trace first would return nothing for almost every database.

``trace_id`` remains the right key for proxy users running an OpenTelemetry
instrumented application, which is why it is the fallback rather than absent.
``burnlens economics`` reports which of the two a given database actually has.

Read-only, over the existing ``requests`` fact table. No new tables, and
explicitly no ``graph_nodes``/``graph_edges``.

A note on depth
---------------
This is two levels — run, then its steps in time order — and not a tree. Scan
data has no ``parent_span_id`` (again: no headers), so there is nothing to nest
by for the traffic that dominates. ``parent_span_id`` is surfaced per step when
present rather than used to build a hierarchy that only OTEL users could ever
see filled in.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiosqlite

# Session first, trace second. Rows with neither cannot be grouped and are
# excluded rather than collapsed into one giant NULL run.
RUN_KEY = "COALESCE(json_extract(tags, '$.session'), trace_id)"
_SESSION_TAG = "json_extract(tags, '$.session')"


@dataclass(frozen=True)
class _Schema:
    """SQL expressions this database can actually evaluate.

    Databases written before the canonical columns existed still hold plenty of
    runs — they are 100% scan data, which is session-keyed and session-tagged
    anyway — so each missing column degrades to the tag or to NULL. The
    alternative is a traceback on exactly the oldest and largest databases,
    which is where a user would try this first.
    """

    run_key: str
    repo: str
    parent_span: str


async def _schema(db: aiosqlite.Connection) -> _Schema:
    cursor = await db.execute("PRAGMA table_info(requests)")
    columns = {row[1] for row in await cursor.fetchall()}
    return _Schema(
        run_key=RUN_KEY if "trace_id" in columns else _SESSION_TAG,
        repo=(
            "COALESCE(repo, json_extract(tags, '$.repo'))"
            if "repo" in columns
            else "json_extract(tags, '$.repo')"
        ),
        parent_span="parent_span_id" if "parent_span_id" in columns else "NULL",
    )


@dataclass
class Run:
    """One run: a coding-agent session, or a trace for instrumented callers."""

    run_id: str
    step_count: int
    cost_usd: float
    # Whole prompt side: uncached input plus cache reads and writes. Coding
    # agents cache almost everything, so `input_tokens` alone reads as 6 tokens
    # against a $0.69 step — a number that looks like a bug rather than a cache
    # hit. Both figures are kept so the split stays visible.
    prompt_tokens: int
    cached_tokens: int
    input_tokens: int
    output_tokens: int
    started_at: str
    ended_at: str
    models: list[str]
    source: str | None
    repo: str | None
    # "session" or "trace" — which key grouped this run. Worth showing: it tells
    # the user whether they are looking at agent sessions or OTEL traces.
    key_kind: str


@dataclass
class Step:
    """One request inside a run."""

    timestamp: str
    model: str | None
    prompt_tokens: int
    cached_tokens: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int | None
    status_code: int | None
    # Present only for OTEL callers. Shown, not used for nesting — see module docstring.
    parent_span_id: str | None


def _run_select(s: _Schema) -> str:
    return f"""
    SELECT {s.run_key} AS run_id,
           COUNT(*),
           COALESCE(SUM(cost_usd), 0.0),
           COALESCE(SUM(input_tokens + cache_read_tokens + cache_write_tokens), 0),
           COALESCE(SUM(cache_read_tokens + cache_write_tokens), 0),
           COALESCE(SUM(input_tokens), 0),
           COALESCE(SUM(output_tokens), 0),
           MIN(timestamp),
           MAX(timestamp),
           GROUP_CONCAT(DISTINCT model),
           MAX(source),
           MAX({s.repo}),
           MAX({_SESSION_TAG} IS NOT NULL)
      FROM requests
     WHERE timestamp >= ? AND {s.run_key} IS NOT NULL
"""


def _row_to_run(row: Any) -> Run:
    return Run(
        run_id=row[0],
        step_count=int(row[1]),
        cost_usd=float(row[2]),
        prompt_tokens=int(row[3]),
        cached_tokens=int(row[4]),
        input_tokens=int(row[5]),
        output_tokens=int(row[6]),
        started_at=row[7],
        ended_at=row[8],
        models=sorted(m for m in (row[9] or "").split(",") if m),
        source=row[10],
        repo=row[11],
        key_kind="session" if row[12] else "trace",
    )


async def list_runs(
    db_path: str,
    since: str,
    limit: int = 20,
    order: str = "cost",
) -> list[Run]:
    """Runs in the window, most expensive (or most recent) first.

    ``order`` is ``"cost"`` or ``"recent"``; anything else falls back to cost.
    Recency matters as much as spend here — without it you cannot find the run
    you just made.
    """
    order_by = "MAX(timestamp) DESC" if order == "recent" else "SUM(cost_usd) DESC"
    async with aiosqlite.connect(db_path) as db:
        s = await _schema(db)
        cursor = await db.execute(
            f"{_run_select(s)} GROUP BY run_id ORDER BY {order_by} LIMIT ?",
            (since, limit),
        )
        rows = await cursor.fetchall()
    return [_row_to_run(r) for r in rows]


async def resolve_run_id(db_path: str, prefix: str, since: str) -> list[str]:
    """Run ids matching a prefix. Sessions are UUIDs; nobody types those in full.

    Returns every match so the caller can refuse an ambiguous prefix rather than
    silently picking one.
    """
    async with aiosqlite.connect(db_path) as db:
        s = await _schema(db)
        cursor = await db.execute(
            f"""
            SELECT DISTINCT {s.run_key} AS run_id
              FROM requests
             WHERE timestamp >= ? AND {s.run_key} LIKE ? || '%'
             ORDER BY run_id
            """,
            (since, prefix),
        )
        return [r[0] for r in await cursor.fetchall()]


async def get_run(db_path: str, run_id: str, since: str) -> tuple[Run, list[Step]] | None:
    """One run and its steps in time order, or None if the id matches nothing."""
    async with aiosqlite.connect(db_path) as db:
        s = await _schema(db)
        cursor = await db.execute(
            f"{_run_select(s)} AND {s.run_key} = ? GROUP BY run_id",
            (since, run_id),
        )
        row = await cursor.fetchone()
        if row is None or row[0] is None:
            return None
        run = _row_to_run(row)

        cursor = await db.execute(
            f"""
            SELECT timestamp, model,
                   input_tokens + cache_read_tokens + cache_write_tokens,
                   cache_read_tokens + cache_write_tokens,
                   input_tokens, output_tokens, cost_usd,
                   duration_ms, status_code, {s.parent_span}
              FROM requests
             WHERE timestamp >= ? AND {s.run_key} = ?
             ORDER BY timestamp
            """,
            # Same window as the aggregate above. Without it a run straddling the
            # boundary would list steps its own totals do not account for.
            (since, run_id),
        )
        steps = [
            Step(
                timestamp=r[0],
                model=r[1],
                prompt_tokens=int(r[2] or 0),
                cached_tokens=int(r[3] or 0),
                input_tokens=int(r[4] or 0),
                output_tokens=int(r[5] or 0),
                cost_usd=float(r[6] or 0.0),
                duration_ms=r[7],
                status_code=r[8],
                parent_span_id=r[9],
            )
            for r in await cursor.fetchall()
        ]
    return (run, steps)


def run_to_dict(run: Run) -> dict[str, Any]:
    """Serialise for the dashboard API."""
    return {
        "run_id": run.run_id,
        "step_count": run.step_count,
        "cost_usd": round(run.cost_usd, 6),
        "prompt_tokens": run.prompt_tokens,
        "cached_tokens": run.cached_tokens,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "models": run.models,
        "source": run.source,
        "repo": run.repo,
        "key_kind": run.key_kind,
    }


def step_to_dict(step: Step) -> dict[str, Any]:
    return {
        "timestamp": step.timestamp,
        "model": step.model,
        "prompt_tokens": step.prompt_tokens,
        "cached_tokens": step.cached_tokens,
        "input_tokens": step.input_tokens,
        "output_tokens": step.output_tokens,
        "cost_usd": round(step.cost_usd, 6),
        "duration_ms": step.duration_ms,
        "status_code": step.status_code,
        "parent_span_id": step.parent_span_id,
    }
