"""Disk-based session scanners for coding-agent traffic.

Counterpart to the live proxy: instead of intercepting requests on the wire,
scanners parse session log files written to disk by coding agents
(Claude Code, Cursor, etc.) and import the cost records into the same
``requests`` table the proxy writes to. Scan-imported rows carry
``source='scan_<provider>'`` and a populated ``request_id``; a partial
unique index makes re-runs idempotent.
"""
from burnlens.scan.claude_code import (
    ClaudeSession,
    decode_project_path,
    discover_sessions,
    parse_session,
    resolve_dev_identity,
    scan_claude_code,
)

__all__ = [
    "ClaudeSession",
    "decode_project_path",
    "discover_sessions",
    "parse_session",
    "resolve_dev_identity",
    "scan_claude_code",
]
