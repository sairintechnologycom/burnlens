"""Named conversion-funnel events. No prompt bodies, no local-scan telemetry.

A purely local ``burnlens scan`` never reaches this module. Events fire only
on cloud-observable transitions (workspace create, ingest, invite, billing).
"""
from __future__ import annotations

import logging

logger = logging.getLogger("burnlens.funnel")

LANDING_VIEW = "landing_view"
SCAN_DOCS_VIEW = "scan_docs_view"
INSTALL_COPY = "install_copy"
CLOUD_CONNECT_STARTED = "cloud_connect_started"
WORKSPACE_CREATED = "workspace_created"
FIRST_SYNC = "first_sync"
ECONOMICS_VISIBLE = "economics_visible"
TEAMMATE_INVITED = "teammate_invited"
SECOND_ACTIVE_DAY = "second_active_day"
TRIAL_STARTED = "trial_started"
SUBSCRIPTION_STARTED = "subscription_started"
RENEWED = "renewed"


def emit(event: str, *, workspace_id: str | None = None) -> None:
    """Log one funnel step. Workspace id is an opaque uuid, never an email."""
    if workspace_id:
        logger.info("funnel.%s workspace=%s", event, workspace_id)
    else:
        logger.info("funnel.%s", event)
