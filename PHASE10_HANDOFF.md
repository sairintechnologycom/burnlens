# Phase 10 Handoff: Alerting + Click-to-Optimize Workflows

**Status:** ✅ COMPLETE
**Date:** June 14, 2026

## Overview
Phase 10 transforms passive notifications into an interactive remediation system. Users can now instantly neutralize spend anomalies or unblock traffic directly from Slack/Teams notifications using secure, signed action tokens.

## Key Changes

### 1. Remediation Infrastructure (Backend)
- **`burnlens_cloud/action_tokens.py`**: New JWT-based token system for secure remediation. Features 2-hour TTL and JTI-based single-use enforcement.
- **`burnlens_cloud/actions_api.py`**: New router for executing actions.
    - `GET /confirm`: Human-in-the-loop safety gate (prevents prefetch execution).
    - `POST /execute`: Atomic execution of `pause_api_key`, `increase_budget`, or `downgrade_model`.
- **Database Schema**: 
    - `api_keys`: Added `paused_at` column.
    - `workspaces`: Added `routing_overrides` JSONB column.
    - `used_action_tokens`: New table for single-use token tracking.
- **Audit Log**: Every remediation is recorded in `workspace_activity` (e.g., `action_pause_api_key`).

### 2. Interactive Alerting
- **`burnlens_cloud/alert_engine.py`**:
    - Updated `evaluate_workspace` to identify the top API key by request volume in the current cycle.
    - Enhanced `_dispatch_slack` to include interactive "Actions" blocks (Pause Top Key, Increase Budget, Downgrade Model).

### 3. Frontend Integration
- **API Key Management**: 
    - Updated `ApiKeysTable.tsx` and `ApiKeysCard.tsx` to display "Paused" status.
    - Added "Pause" and "Resume" controls to the settings dashboard.
    - Integrated `handlePause`/`handleResume` logic in `app/api-keys/page.tsx`.

### 4. Dynamic Proxy Policy
- **`burnlens/cloud/sync.py`**:
    - Heartbeat sync now pulls `routing_overrides` from the cloud.
    - Automatically updates local `config.routing` (budget downgrade settings) in memory.
- **Data Pipeline**: Added `tag_key_label` propagation from proxy to ClickHouse for precise attribution.

## Verification
- **New Tests**: `tests/test_phase10_actions.py` covers the full end-to-end token and execution lifecycle.
- **Regressions**: Updated `tests/test_cloud_sync.py` to match the new `BurnLensConfig` injection pattern.
- **Test Run**: `uv run pytest tests/test_phase10_actions.py tests/test_cloud_sync.py` -> **14 PASSED**.

## Operational Notes
- **Action Tokens**: Short-lived (2h) and stateless. Signature verification uses `JWT_SECRET`.
- **Cache Invalidation**: Pausing a key triggers `invalidate_api_key_cache` in the cloud to ensure immediate effect.
- **Proxy Sync**: Local proxy will reflect cloud settings within one `sync_interval_seconds` (default 60s).

## Future Work
- **Teams Notifications**: Extend the actionable payload format to Microsoft Teams webhooks.
- **Action Recovery**: Surface the "Audit Log" of remediations in the frontend UI for easy reversal.
