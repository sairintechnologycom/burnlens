"""Anomaly and runaway agent detection engine for BurnLens."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from burnlens.storage.models import AnomalyEvent, RequestRecord
from burnlens.storage.database import insert_anomaly_event, was_alert_fired, mark_alert_fired
from burnlens.config import BurnLensConfig

logger = logging.getLogger(__name__)


def calculate_median(values: list[float]) -> float:
    """Calculate median of a numeric list in pure Python."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    else:
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0


def calculate_mad(values: list[float], median: float) -> float:
    """Calculate Median Absolute Deviation (MAD) in pure Python."""
    if not values:
        return 0.0
    abs_deviations = [abs(v - median) for v in values]
    return calculate_median(abs_deviations)


def calculate_mean_std(values: list[float]) -> tuple[float, float]:
    """Calculate mean and standard deviation in pure Python."""
    if not values:
        return 0.0, 0.0
    n = len(values)
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / n
    std = variance ** 0.5
    return mean, std


class AnomalyDetector:
    """Detects cost spikes and runaway agent loops in real-time.

    Continuously aggregates requests in sliding windows (1m, 5m, 15m, 1h) and
    runs robust statistical checks (Median Absolute Deviation / Z-score)
    against the last 24 hours of baseline traffic.
    """

    WINDOWS = {
        "1m": {"duration_min": 1, "min_count": 10, "min_cost": 0.10},
        "5m": {"duration_min": 5, "min_count": 25, "min_cost": 0.50},
        "15m": {"duration_min": 15, "min_count": 50, "min_cost": 1.50},
        "1h": {"duration_min": 60, "min_count": 100, "min_cost": 5.00},
    }

    def __init__(self, config: BurnLensConfig, db_path: str) -> None:
        self.config = config
        self.db_path = db_path

        if config.alerts.slack_webhook:
            from burnlens.alerts.slack import SlackWebhookAlert
            self._slack = SlackWebhookAlert(config.alerts.slack_webhook)
        else:
            self._slack = None

    async def check_request(self, record: RequestRecord) -> None:
        """Run anomaly checks for all applicable scopes of a RequestRecord.

        Runs asynchronously via background task to prevent proxy delays.
        """
        scopes = [
            ("org", "*"),
            ("model", record.model),
        ]
        
        team = record.team or (record.tags or {}).get("team")
        if team:
            scopes.append(("team", team))

        app_id = record.app_id or (record.tags or {}).get("app_id")
        if app_id:
            scopes.append(("app", app_id))

        customer = (record.tags or {}).get("customer")
        if customer:
            scopes.append(("customer", customer))

        key_label = (record.tags or {}).get("key_label")
        if key_label:
            scopes.append(("api_key", key_label))

        for scope, target in scopes:
            if not target:
                continue
            try:
                await self.check_scope(scope, target)
            except Exception as exc:
                logger.error(
                    "Anomaly detection failed for scope=%s target=%s: %s",
                    scope,
                    target,
                    exc,
                    exc_info=True,
                )

    async def check_scope(self, scope: str, target: str) -> None:
        """Fetch past 24 hours of traffic for scope/target and check windows."""
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=24)

        # Build SQL condition based on scope
        where_clause = ""
        params: list[Any] = [since.isoformat()]

        if scope == "org":
            where_clause = "1=1"
        elif scope == "model":
            where_clause = "model = ?"
            params.append(target)
        elif scope == "team":
            where_clause = "(team = ? OR json_extract(tags, '$.team') = ?)"
            params.extend([target, target])
        elif scope == "app":
            where_clause = "(app_id = ? OR json_extract(tags, '$.app_id') = ?)"
            params.extend([target, target])
        elif scope == "customer":
            where_clause = "(json_extract(tags, '$.customer') = ? OR customer_hash = ?)"
            params.extend([target, target])
        elif scope == "api_key":
            where_clause = "tag_key_label = ?"
            params.append(target)
        else:
            return

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                f"""
                SELECT timestamp, cost_usd, system_prompt_hash
                FROM requests
                WHERE timestamp >= ? AND {where_clause}
                ORDER BY timestamp ASC
                """,
                params,
            )
            rows = await cursor.fetchall()

        if not rows:
            return

        requests_data: list[tuple[datetime, float, str | None]] = []
        for r in rows:
            try:
                # Handle possible naive or timezone-aware timestamps
                ts_str = r[0]
                if ts_str.endswith("Z"):
                    ts_str = ts_str[:-1] + "+00:00"
                elif "+" not in ts_str and "-" not in ts_str[10:]:
                    ts_str += "+00:00"
                dt = datetime.fromisoformat(ts_str)
                requests_data.append((dt, float(r[1] or 0.0), r[2]))
            except Exception:
                pass

        # Evaluate each sliding window
        for win_name, win_cfg in self.WINDOWS.items():
            await self._check_window(
                win_name=win_name,
                win_cfg=win_cfg,
                scope=scope,
                target=target,
                requests_data=requests_data,
                now=now,
            )

    async def _check_window(
        self,
        win_name: str,
        win_cfg: dict[str, Any],
        scope: str,
        target: str,
        requests_data: list[tuple[datetime, float, str | None]],
        now: datetime,
    ) -> None:
        duration_min = win_cfg["duration_min"]
        min_count = win_cfg["min_count"]
        min_cost = win_cfg["min_cost"]

        win_delta = timedelta(minutes=duration_min)
        current_window_start = now - win_delta
        start_time = now - timedelta(hours=24)

        # 1. Bucket requests into Current Window vs Baseline
        current_requests = []
        
        # Calculate number of baseline intervals of size duration_min
        baseline_duration_sec = (current_window_start - start_time).total_seconds()
        win_sec = win_delta.total_seconds()
        num_intervals = int(baseline_duration_sec / win_sec)

        if num_intervals <= 0:
            return

        baseline_costs = [0.0] * num_intervals
        baseline_counts = [0] * num_intervals

        for req_time, cost_usd, prompt_hash in requests_data:
            if req_time >= current_window_start:
                current_requests.append((req_time, cost_usd, prompt_hash))
            elif start_time <= req_time < current_window_start:
                idx = int((req_time - start_time).total_seconds() / win_sec)
                if 0 <= idx < num_intervals:
                    baseline_costs[idx] += cost_usd
                    baseline_counts[idx] += 1

        curr_cost = sum(r[1] for r in current_requests)
        curr_count = len(current_requests)

        # 2. Compute Statistics for Cost
        med_cost = calculate_median(baseline_costs)
        mad_cost = calculate_mad(baseline_costs, med_cost)
        z_cost = 0.0

        if curr_cost >= min_cost:
            if mad_cost > 0:
                z_cost = 0.6745 * (curr_cost - med_cost) / mad_cost
            else:
                mean_cost, std_cost = calculate_mean_std(baseline_costs)
                if std_cost > 0:
                    z_cost = (curr_cost - mean_cost) / std_cost
                elif curr_cost > med_cost:
                    z_cost = 10.0  # Significant jump from zero baseline

        # 3. Compute Statistics for Request Count
        med_count = calculate_median(baseline_counts)
        mad_count = calculate_mad(baseline_counts, med_count)
        z_count = 0.0

        if curr_count >= min_count:
            if mad_count > 0:
                z_count = 0.6745 * (curr_count - med_count) / mad_count
            else:
                mean_count, std_count = calculate_mean_std(baseline_counts)
                if std_count > 0:
                    z_count = (curr_count - mean_count) / std_count
                elif curr_count > med_count:
                    z_count = 10.0

        # 4. Check for Runaway Loop
        # High count Z-score AND high duplicate prompt ratio
        is_runaway = False
        duplicate_ratio = 0.0
        if curr_count >= min_count and z_count >= 3.5:
            hashes = [r[2] for r in current_requests if r[2] is not None]
            if len(hashes) > 0:
                unique_hashes = set(hashes)
                duplicate_ratio = 1.0 - (len(unique_hashes) / len(hashes))
                if duplicate_ratio >= 0.8:
                    is_runaway = True

        # 5. Check for Cost Spike
        is_spike = curr_cost >= min_cost and z_cost >= 3.5

        # 6. Fire & Store events
        if is_runaway:
            severity = "critical" if z_count >= 5.0 else "warning"
            details = {
                "window": win_name,
                "current_value": curr_count,
                "median_value": med_count,
                "z_score": z_count,
                "duplicate_ratio": duplicate_ratio,
                "description": (
                    f"Runaway loop detected in {win_name} window for {scope} '{target}': "
                    f"{curr_count} requests (expected median: {med_count:.1f}) with "
                    f"{duplicate_ratio * 100:.1f}% duplicate prompts."
                ),
            }
            await self._trigger_event(
                event_type="runaway_loop",
                scope=scope,
                target=target,
                severity=severity,
                details=details,
            )

        if is_spike and not is_runaway:  # loops take precedence
            severity = "critical" if z_cost >= 5.0 else "warning"
            details = {
                "window": win_name,
                "current_value": curr_cost,
                "median_value": med_cost,
                "z_score": z_cost,
                "description": (
                    f"Cost spike detected in {win_name} window for {scope} '{target}': "
                    f"${curr_cost:.4f} spent (expected median: ${med_cost:.4f}) with Z-score {z_cost:.2f}."
                ),
            }
            await self._trigger_event(
                event_type="cost_spike",
                scope=scope,
                target=target,
                severity=severity,
                details=details,
            )

    async def _trigger_event(
        self,
        event_type: str,
        scope: str,
        target: str,
        severity: str,
        details: dict[str, Any],
    ) -> None:
        alert_key = f"anomaly:{event_type}:{scope}:{target}:{details['window']}"

        # Deduplicate alert: check if already fired in last 1 hour
        try:
            if await was_alert_fired(self.db_path, alert_key, event_type, within_hours=1):
                return
        except Exception as exc:
            logger.debug("Anomaly DB dedup check failed: %s", exc)

        event = AnomalyEvent(
            event_type=event_type,
            scope=scope,
            target=target,
            severity=severity,
            details=details,
        )

        try:
            await insert_anomaly_event(self.db_path, event)
            await mark_alert_fired(self.db_path, alert_key, event_type)
        except Exception as exc:
            logger.error("Failed to insert/mark anomaly event: %s", exc)
            return

        # Alerts delivery
        msg = f"[{severity.upper()}] {details['description']}"
        logger.warning("BurnLens Anomaly: %s", msg)

        if self.config.alerts.terminal:
            self._print_terminal_anomaly(event, details)

        if self._slack:
            try:
                await self._slack.send_anomaly(event)
            except Exception as exc:
                logger.debug("Failed to dispatch Slack anomaly alert: %s", exc)

    def _print_terminal_anomaly(self, event: AnomalyEvent, details: dict[str, Any]) -> None:
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.text import Text

            console = Console(stderr=True)
            color = "red" if event.severity == "critical" else "yellow"
            emoji = "🚨" if event.severity == "critical" else "⚠️"

            body = Text()
            body.append(f"{emoji} BurnLens Anomaly Detected\n\n", style=f"bold {color}")
            body.append("Event Type:  ", style="bold")
            body.append(f"{event.event_type.replace('_', ' ').capitalize()}\n")
            body.append("Scope:       ", style="bold")
            body.append(f"{event.scope.capitalize()}\n")
            body.append("Target:      ", style="bold")
            body.append(f"{event.target}\n")
            body.append("Severity:    ", style="bold")
            body.append(f"{event.severity.upper()}\n", style=f"bold {color}")
            body.append("Window:      ", style="bold")
            body.append(f"{details.get('window', 'unknown')}\n")

            if event.event_type == "cost_spike":
                body.append("Current Cost: ", style="bold")
                body.append(f"${details.get('current_value', 0.0):.4f}\n")
                body.append("Median Cost:  ", style="bold")
                body.append(f"${details.get('median_value', 0.0):.4f}\n")
                body.append("Z-Score:      ", style="bold")
                body.append(f"{details.get('z_score', 0.0):.2f}\n")
            else:  # runaway_loop
                body.append("Current Count: ", style="bold")
                body.append(f"{details.get('current_value', 0)}\n")
                body.append("Median Count:  ", style="bold")
                body.append(f"{details.get('median_value', 0.0):.1f}\n")
                body.append("Z-Score:       ", style="bold")
                body.append(f"{details.get('z_score', 0.0):.2f}\n")
                body.append("Duplicate %:   ", style="bold")
                body.append(f"{details.get('duplicate_ratio', 0.0) * 100:.1f}%\n")

            panel = Panel(
                body,
                title=f"[{color}]BurnLens — Anomaly Detected ({event.severity.upper()})[/]",
                border_style=f"bold {color}",
                expand=False,
            )
            console.print(panel)
        except Exception as exc:
            logger.debug("Terminal anomaly print failed: %s", exc)
