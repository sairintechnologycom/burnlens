"""Cloud findings persistence + sync-on-read detector execution (BL-F1).

Detectors stay in ``burnlens.analysis.waste`` (pure, no I/O). This module is
the persistence layer: adapt ``request_records`` rows, run the detectors, and
upsert into ``waste_findings`` with the same lifecycle the local SQLite
stack already pins.

# ponytail: sync-on-read with 1h staleness; move to a scheduled task only if
# read latency ever matters
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from burnlens.analysis.waste import DETECTOR_VERSION, WasteFinding, run_all_detectors

logger = logging.getLogger(__name__)

VALID_STATUSES = ("open", "acknowledged", "resolved", "accepted_risk")
BASELINE_WINDOW_DAYS = 7
DETECTION_WINDOW_DAYS = 7
STALE_AFTER = timedelta(hours=1)


def records_to_detector_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    """Adapt asyncpg Records (or dicts) into the plain dicts detectors consume.

    ``tags`` is JSONB. The pool registers a codec so it usually arrives as a
    dict; if it arrives as a string, parse it. Detectors read
    ``tags["workflow_id"]`` — a leftover JSON string silently collapses every
    finding to model-scope.
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        tags = d.get("tags")
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except (ValueError, TypeError):
                tags = {}
        if not isinstance(tags, dict):
            tags = {}
        d["tags"] = tags
        cost = d.get("cost_usd")
        if isinstance(cost, Decimal):
            d["cost_usd"] = float(cost)
        elif cost is None:
            d["cost_usd"] = 0.0
        out.append(d)
    return out


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _parse_evidence(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def finding_to_dict(row: Any) -> dict[str, Any]:
    """Full column set; ``id`` is the fingerprint."""
    d = dict(row)
    fingerprint = d["fingerprint"]

    def _ts(key: str) -> str | None:
        val = d.get(key)
        if val is None:
            return None
        if isinstance(val, datetime):
            return val.isoformat()
        return str(val)

    def _num(key: str) -> float | None:
        val = d.get(key)
        if val is None:
            return None
        return float(val)

    def _int(key: str) -> int | None:
        val = d.get(key)
        if val is None:
            return None
        return int(val)

    return {
        "id": fingerprint,
        "fingerprint": fingerprint,
        "detector": d["detector"],
        "subject_type": d["subject_type"],
        "subject_key": d["subject_key"],
        "severity": d["severity"],
        "title": d["title"],
        "description": d["description"],
        "estimated_waste_usd": float(d.get("estimated_waste_usd") or 0),
        "affected_count": int(d.get("affected_count") or 0),
        "evidence": _parse_evidence(d.get("evidence")),
        "status": d["status"],
        "first_seen_at": _ts("first_seen_at"),
        "last_seen_at": _ts("last_seen_at"),
        "resolved_at": _ts("resolved_at"),
        "baseline_waste_usd": _num("baseline_waste_usd"),
        "baseline_cost_usd": _num("baseline_cost_usd"),
        "baseline_requests": _int("baseline_requests"),
        "baseline_window_days": _int("baseline_window_days"),
        "detection_count": int(d.get("detection_count") or 1),
        "detector_version": int(d.get("detector_version") or DETECTOR_VERSION),
    }


def waste_alert_from_finding(row: Any) -> dict[str, Any]:
    """Map a stored finding onto the existing waste-alerts response shape."""
    d = dict(row)
    waste = float(d.get("estimated_waste_usd") or 0)
    return {
        "id": d["fingerprint"],
        "detector": d["detector"],
        "severity": d["severity"],
        "title": d["title"],
        "description": d["description"],
        "estimated_waste_usd": round(waste, 6),
        "monthly_savings": round(waste, 2),
        "affected_count": int(d.get("affected_count") or 0),
        "subject_type": d["subject_type"],
        "subject_key": d["subject_key"],
    }


async def sync_findings(conn, workspace_id, findings: list[WasteFinding]) -> None:
    """Persist a detection pass. Semantics match ``burnlens.storage.findings``."""
    now = _now()
    ws = workspace_id
    for finding in findings:
        existing = await conn.fetchrow(
            """
            SELECT status, resolved_at FROM waste_findings
             WHERE workspace_id = $1 AND fingerprint = $2
            """,
            ws,
            finding.fingerprint,
        )
        evidence_json = json.dumps(finding.evidence, sort_keys=True)

        if existing is None:
            await conn.execute(
                """
                INSERT INTO waste_findings (
                    workspace_id, fingerprint, detector, subject_type, subject_key,
                    severity, title, description, estimated_waste_usd,
                    affected_count, evidence, status,
                    first_seen_at, last_seen_at, detection_count, detector_version
                ) VALUES (
                    $1, $2, $3, $4, $5,
                    $6, $7, $8, $9,
                    $10, $11::jsonb, 'open',
                    $12, $13, 1, $14
                )
                """,
                ws,
                finding.fingerprint,
                finding.detector,
                finding.subject_type,
                finding.subject_key,
                finding.severity,
                finding.title,
                finding.description,
                finding.estimated_waste_usd,
                finding.affected_count,
                evidence_json,
                now,
                now,
                DETECTOR_VERSION,
            )
            continue

        # accepted_risk never reopens. resolved + still detected → open.
        # resolved_at is NOT cleared (G8).
        reopen = existing["status"] == "resolved"
        new_status = "open" if reopen else existing["status"]

        await conn.execute(
            """
            UPDATE waste_findings
               SET severity = $1,
                   description = $2,
                   estimated_waste_usd = $3,
                   affected_count = $4,
                   evidence = $5::jsonb,
                   last_seen_at = $6,
                   status = $7,
                   detection_count = detection_count + 1
             WHERE workspace_id = $8 AND fingerprint = $9
            """,
            finding.severity,
            finding.description,
            finding.estimated_waste_usd,
            finding.affected_count,
            evidence_json,
            now,
            new_status,
            ws,
            finding.fingerprint,
        )


async def refresh_findings(conn, workspace_id) -> None:
    """Run detectors if the workspace's findings are older than one hour."""
    try:
        latest = await conn.fetchval(
            "SELECT MAX(last_seen_at) FROM waste_findings WHERE workspace_id = $1",
            workspace_id,
        )
        latest = _as_aware(latest)
        if latest is not None and _now() - latest < STALE_AFTER:
            return

        cutoff = _now() - timedelta(days=DETECTION_WINDOW_DAYS)
        rows = await conn.fetch(
            """
            SELECT cost_usd, input_tokens, output_tokens, model, system_prompt_hash,
                   cache_read_tokens, tags,
                   prompt_system_tokens, prompt_tools_tokens,
                   prompt_rag_tokens, prompt_history_tokens
              FROM request_records
             WHERE workspace_id = $1 AND ts >= $2
            """,
            workspace_id,
            cutoff,
        )
        candidates = run_all_detectors(records_to_detector_dicts(rows))
        await sync_findings(conn, workspace_id, candidates)
    except Exception:
        logger.exception("refresh_findings failed for workspace %s", workspace_id)


async def list_findings(conn, workspace_id, status: str | None = None) -> list[Any]:
    """List stored findings, worst and most expensive first."""
    if status:
        return await conn.fetch(
            """
            SELECT * FROM waste_findings
             WHERE workspace_id = $1 AND status = $2
             ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                      estimated_waste_usd DESC
            """,
            workspace_id,
            status,
        )
    return await conn.fetch(
        """
        SELECT * FROM waste_findings
         WHERE workspace_id = $1
         ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                  estimated_waste_usd DESC
        """,
        workspace_id,
    )


async def get_subject_spend(
    conn,
    workspace_id,
    subject_type: str,
    subject_key: str,
    since: datetime,
    until: datetime,
) -> tuple[float, int]:
    """Spend and request count for one finding subject over a window (G12)."""
    if subject_type == "workflow":
        predicate = "tags->>'workflow_id' = $4"
    elif subject_type == "model":
        predicate = "model = $4"
    else:
        return (0.0, 0)

    row = await conn.fetchrow(
        f"""
        SELECT COALESCE(SUM(cost_usd), 0) AS spend, COUNT(*) AS n
          FROM request_records
         WHERE workspace_id = $1 AND ts >= $2 AND ts < $3 AND {predicate}
        """,
        workspace_id,
        since,
        until,
        subject_key,
    )
    if row is None:
        return (0.0, 0)
    return (float(row["spend"] or 0), int(row["n"] or 0))


async def set_finding_status(
    conn,
    workspace_id,
    fingerprint: str,
    status: str,
    baseline_window_days: int = BASELINE_WINDOW_DAYS,
) -> bool:
    """Move a finding through its lifecycle. Returns False if it doesn't exist."""
    if status not in VALID_STATUSES:
        raise ValueError(
            f"invalid status {status!r}; expected one of {', '.join(VALID_STATUSES)}"
        )

    if status != "resolved":
        result = await conn.execute(
            """
            UPDATE waste_findings SET status = $1
             WHERE workspace_id = $2 AND fingerprint = $3
            """,
            status,
            workspace_id,
            fingerprint,
        )
        return _rowcount(result) > 0

    existing = await conn.fetchrow(
        """
        SELECT subject_type, subject_key, estimated_waste_usd
          FROM waste_findings
         WHERE workspace_id = $1 AND fingerprint = $2
        """,
        workspace_id,
        fingerprint,
    )
    if existing is None:
        return False

    now = _now()
    window_start = now - timedelta(days=baseline_window_days)
    baseline_cost, baseline_requests = await get_subject_spend(
        conn,
        workspace_id,
        existing["subject_type"],
        existing["subject_key"],
        since=window_start,
        until=now,
    )

    result = await conn.execute(
        """
        UPDATE waste_findings
           SET status = 'resolved',
               resolved_at = $1,
               baseline_waste_usd = estimated_waste_usd,
               baseline_cost_usd = $2,
               baseline_requests = $3,
               baseline_window_days = $4
         WHERE workspace_id = $5 AND fingerprint = $6
        """,
        now,
        baseline_cost,
        baseline_requests,
        baseline_window_days,
        workspace_id,
        fingerprint,
    )
    return _rowcount(result) > 0


def _verdict_base(finding: dict[str, Any]) -> dict[str, Any]:
    resolved_at = finding.get("resolved_at")
    return {
        "fingerprint": finding["fingerprint"],
        "title": finding["title"],
        "subject_type": finding["subject_type"],
        "subject_key": finding["subject_key"],
        "status": "no_baseline",
        "baseline_cost_per_request": None,
        "current_cost_per_request": None,
        "delta_per_request": None,
        "pct_change": None,
        "projected_monthly_savings_usd": None,
        "baseline_requests": None,
        "current_requests": None,
        "days_remaining": None,
        "reopened": finding.get("status") == "open" and resolved_at is not None,
    }


async def verify_savings(conn, workspace_id, fingerprint: str) -> dict[str, Any] | None:
    """Compare a finding's subject before and after resolve (G12)."""
    row = await conn.fetchrow(
        """
        SELECT * FROM waste_findings
         WHERE workspace_id = $1 AND fingerprint = $2
        """,
        workspace_id,
        fingerprint,
    )
    if row is None:
        return None

    finding = dict(row)
    verdict = _verdict_base(finding)
    if not finding.get("resolved_at") or not finding.get("baseline_requests"):
        return verdict

    window_days = int(finding.get("baseline_window_days") or BASELINE_WINDOW_DAYS)
    resolved_at = _as_aware(finding["resolved_at"])
    if resolved_at is None:
        return verdict

    elapsed = _now() - resolved_at
    if elapsed < timedelta(days=window_days):
        verdict["status"] = "pending"
        verdict["days_remaining"] = round(
            (timedelta(days=window_days) - elapsed).total_seconds() / 86_400, 2
        )
        return verdict

    current_cost, current_requests = await get_subject_spend(
        conn,
        workspace_id,
        finding["subject_type"],
        finding["subject_key"],
        since=resolved_at,
        until=resolved_at + timedelta(days=window_days),
    )
    verdict["baseline_requests"] = int(finding["baseline_requests"])
    verdict["current_requests"] = current_requests

    if current_requests == 0:
        verdict["status"] = "no_traffic"
        return verdict

    baseline_per = float(finding.get("baseline_cost_usd") or 0.0) / finding["baseline_requests"]
    current_per = current_cost / current_requests
    delta = baseline_per - current_per
    verdict["status"] = "verified"
    verdict["baseline_cost_per_request"] = baseline_per
    verdict["current_cost_per_request"] = current_per
    verdict["delta_per_request"] = delta
    verdict["pct_change"] = (
        ((current_per - baseline_per) / baseline_per * 100) if baseline_per else None
    )
    verdict["projected_monthly_savings_usd"] = delta * current_requests * (30.0 / window_days)
    return verdict


async def verify_all_resolved(conn, workspace_id) -> list[dict[str, Any]]:
    """Verify every finding that has a baseline. Reopened ones still verify."""
    rows = await conn.fetch(
        """
        SELECT fingerprint FROM waste_findings
         WHERE workspace_id = $1 AND baseline_requests IS NOT NULL
        """,
        workspace_id,
    )
    verdicts = []
    for row in rows:
        verdict = await verify_savings(conn, workspace_id, row["fingerprint"])
        if verdict is not None:
            verdicts.append(verdict)
    return sorted(
        verdicts, key=lambda v: -(v["projected_monthly_savings_usd"] or 0.0)
    )


def recommendations_from_records(records: list[dict[str, Any]]) -> list[Any]:
    """Run the canonical recommender rules over already-fetched request dicts.

    ``analyse_model_fit`` opens SQLite. Calling it here would need a proxy
    change or a throwaway DB. The rules and pricing helpers are imported from
    ``burnlens.analysis.recommender`` so there is still one engine; this is
    only the Postgres adapter.
    """
    from collections import defaultdict

    from burnlens.analysis.recommender import (
        _CHEAPER_EQUIVALENT,
        _match_overkill_model,
        _match_reasoning_model,
        _project_cost,
    )
    from .models import RecommendationItem

    def _feature(r: dict[str, Any]) -> str:
        tags = r.get("tags") or {}
        if not isinstance(tags, dict):
            return "(untagged)"
        return str(tags.get("feature") or "(untagged)")

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        groups[(str(r.get("model") or ""), _feature(r))].append(r)

    recs: list[RecommendationItem] = []
    for (model, feature_tag), bucket in groups.items():
        count = len(bucket)
        avg_in = sum(int(r.get("input_tokens") or 0) for r in bucket) / count
        avg_out = sum(int(r.get("output_tokens") or 0) for r in bucket) / count
        current_cost = sum(float(r.get("cost_usd") or 0) for r in bucket)
        avg_reasoning = sum(int(r.get("reasoning_tokens") or 0) for r in bucket) / count

        matched_key = _match_overkill_model(model)
        if matched_key is not None and avg_out < 200 and count > 20:
            suggested = _CHEAPER_EQUIVALENT[matched_key]
            projected = _project_cost(count, avg_in, avg_out, suggested)
            if projected is not None:
                saving = current_cost - projected
                pct = (saving / current_cost * 100) if current_cost > 0 else 0.0
                recs.append(
                    RecommendationItem(
                        current_model=model,
                        suggested_model=suggested,
                        feature_tag=feature_tag,
                        request_count=count,
                        avg_output_tokens=round(avg_out, 1),
                        current_cost=round(current_cost, 6),
                        projected_cost=round(projected, 6),
                        projected_saving=round(saving, 6),
                        saving_pct=round(pct, 1),
                        confidence="high" if avg_out < 50 else "medium",
                        reason=(
                            f"Average output is only {avg_out:.0f} tokens across {count} requests "
                            f"— {suggested} can handle short tasks at a fraction of the cost"
                        ),
                    )
                )

        matched_r = _match_reasoning_model(model)
        if (
            matched_r is not None
            and 0 < avg_out < 100
            and avg_reasoning > avg_out * 5
        ):
            suggested = "gpt-4o-mini"
            projected = _project_cost(count, avg_in, avg_out, suggested)
            if projected is not None:
                saving = current_cost - projected
                pct = (saving / current_cost * 100) if current_cost > 0 else 0.0
                ratio = avg_reasoning / avg_out if avg_out else 0
                recs.append(
                    RecommendationItem(
                        current_model=model,
                        suggested_model=suggested,
                        feature_tag=feature_tag,
                        request_count=count,
                        avg_output_tokens=round(avg_out, 1),
                        current_cost=round(current_cost, 6),
                        projected_cost=round(projected, 6),
                        projected_saving=round(saving, 6),
                        saving_pct=round(pct, 1),
                        confidence="medium",
                        reason=(
                            f"Reasoning tokens are {ratio:.0f}x output tokens "
                            f"— this task may not need deep reasoning"
                        ),
                    )
                )

    cutoff_24h = _now() - timedelta(hours=24)
    cache_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        tags = r.get("tags") or {}
        if not isinstance(tags, dict) or not tags.get("feature"):
            continue
        ts = r.get("ts")
        if isinstance(ts, datetime) and _as_aware(ts) < cutoff_24h:
            continue
        cache_groups[(str(r.get("model") or ""), str(tags["feature"]))].append(r)

    for (model, feature_tag), bucket in cache_groups.items():
        count = len(bucket)
        avg_in = sum(int(r.get("input_tokens") or 0) for r in bucket) / count
        if count <= 50 or avg_in <= 2000:
            continue
        current_cost = sum(float(r.get("cost_usd") or 0) for r in bucket)
        avg_out = sum(int(r.get("output_tokens") or 0) for r in bucket) / count
        saving_pct = 30.0
        saving = current_cost * saving_pct / 100
        recs.append(
            RecommendationItem(
                current_model=model,
                suggested_model="prompt-caching",
                feature_tag=feature_tag,
                request_count=count,
                avg_output_tokens=round(avg_out, 1),
                current_cost=round(current_cost, 6),
                projected_cost=round(current_cost - saving, 6),
                projected_saving=round(saving, 6),
                saving_pct=round(saving_pct, 1),
                confidence="low",
                reason=(
                    f"High-volume feature with large prompts ({avg_in:.0f} avg input tokens, "
                    f"{count} requests/24h) — prompt caching could save ~{saving_pct:.0f}%"
                ),
            )
        )

    # Same guard as burnlens/analysis/recommender.py, and for the same reason:
    # a "cheaper equivalent" reached by prefix-matching a model family can be
    # dearer than the variant in hand (gpt-5.6-luna $1/$6 per M matched the
    # gpt-5.6 family and was told to move to gpt-5.6-terra $2.5/$15). Advice
    # that costs money must not be emitted, let alone summed into a total.
    recs = [r for r in recs if r.projected_saving > 0]

    recs.sort(key=lambda r: r.projected_saving, reverse=True)
    return recs


async def get_economics_overview(
    conn,
    workspace_id,
    since: datetime,
    window_seconds: float = 86_400.0,
) -> dict[str, Any]:
    """Top-line runtime economics. Mirrors ``burnlens.analysis.economics``.

    Waste is an estimate of avoidable spend, never a disjoint bucket (G9).
    ``cost_per_accepted_usd`` is null when nothing is accepted (G11).
    """
    from .outcomes_api import _SUMMARY_SQL

    spend_row = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(cost_usd), 0) AS spend
          FROM request_records
         WHERE workspace_id = $1 AND ts >= $2
        """,
        workspace_id,
        since,
    )
    total_spend = float((spend_row or {}).get("spend") or 0)

    waste_row = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(estimated_waste_usd), 0) AS total_waste,
               COUNT(*) AS open_count
          FROM waste_findings
         WHERE workspace_id = $1 AND status IN ('open', 'acknowledged')
        """,
        workspace_id,
    )
    detected_waste = float((waste_row or {}).get("total_waste") or 0)
    open_count = int((waste_row or {}).get("open_count") or 0)

    by_det = await conn.fetch(
        """
        SELECT detector, COALESCE(SUM(estimated_waste_usd), 0) AS waste
          FROM waste_findings
         WHERE workspace_id = $1 AND status IN ('open', 'acknowledged')
         GROUP BY detector
         ORDER BY waste DESC
        """,
        workspace_id,
    )
    waste_by_detector = {r["detector"]: float(r["waste"]) for r in by_det}

    error_row = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(cost_usd), 0) AS spend, COUNT(*) AS n
          FROM request_records
         WHERE workspace_id = $1 AND ts >= $2 AND status_code >= 400
        """,
        workspace_id,
        since,
    )
    error_spend = float((error_row or {}).get("spend") or 0)
    error_count = int((error_row or {}).get("n") or 0)

    outcome_rows = await conn.fetch(
        _SUMMARY_SQL, str(workspace_id), since, float(window_seconds)
    )
    accepted_count = sum(int(r["accepted_count"] or 0) for r in outcome_rows)
    attributed_cost = sum(float(r["cost_total"] or 0) for r in outcome_rows)
    cost_per_accepted = (
        attributed_cost / accepted_count if accepted_count else None
    )

    clamped = bool(total_spend) and detected_waste > total_spend
    if clamped:
        detected_waste = total_spend
    waste_rate = (detected_waste / total_spend) if total_spend else 0.0

    trace_row = await conn.fetchrow(
        """
        SELECT COUNT(*) AS request_count,
               COUNT(trace_id) AS traced_count,
               COUNT(parent_span_id) AS parented_count,
               COUNT(DISTINCT trace_id) AS distinct_traces
          FROM request_records
         WHERE workspace_id = $1 AND ts >= $2
        """,
        workspace_id,
        since,
    )
    request_count = int((trace_row or {}).get("request_count") or 0)
    traced_count = int((trace_row or {}).get("traced_count") or 0)
    parented_count = int((trace_row or {}).get("parented_count") or 0)
    distinct_traces = int((trace_row or {}).get("distinct_traces") or 0)

    return {
        "total_spend_usd": round(total_spend, 6),
        "detected_waste_usd": round(detected_waste, 6),
        "waste_rate": round(waste_rate, 4),
        "open_finding_count": open_count,
        "error_spend_usd": round(error_spend, 6),
        "error_request_count": error_count,
        "cost_per_accepted_usd": (
            round(cost_per_accepted, 6) if cost_per_accepted is not None else None
        ),
        "accepted_count": accepted_count,
        "waste_by_detector": {k: round(v, 6) for k, v in waste_by_detector.items()},
        "waste_estimate_clamped": clamped,
        "trace_coverage": {
            "request_count": request_count,
            "traced_count": traced_count,
            "parented_count": parented_count,
            "distinct_traces": distinct_traces,
            "traced_rate": round(
                (traced_count / request_count) if request_count else 0.0, 4
            ),
            "columns_missing": False,
        },
    }


def _rowcount(result: Any) -> int:
    """asyncpg execute() returns ``UPDATE N``; FakeConn may return an int."""
    if isinstance(result, int):
        return result
    if isinstance(result, str) and result.split():
        try:
            return int(result.split()[-1])
        except ValueError:
            return 0
    return 0
