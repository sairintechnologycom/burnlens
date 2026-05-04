"""Disk-based session scanners for coding-agent traffic.

Counterpart to the live proxy: instead of intercepting requests on the wire,
scanners parse session log files written to disk by coding agents
(Claude Code, Cursor, etc.) and import the cost records into the same
``requests`` table the proxy writes to. Scan-imported rows carry
``source='scan_<provider>'`` and a populated ``request_id``; a partial
unique index makes re-runs idempotent.
"""
from burnlens.scan._common import resolve_dev_identity
from burnlens.scan.claude_code import (
    ClaudeSession,
    ScanResult,
    decode_project_path,
    discover_sessions,
    parse_session,
    scan_claude_code,
)
from burnlens.scan.cursor import (
    AUTO_MODEL_LABEL,
    CursorBubble,
    CursorScanResult,
    bubble_to_record,
    cursor_db_path,
    read_bubbles,
    scan_cursor,
)
from burnlens.scan.codex import (
    CodexScanResult,
    CodexSession,
    codex_sessions_dir,
    scan_codex,
)
from burnlens.scan.gemini_cli import (
    GeminiScanResult,
    GeminiSession,
    gemini_sessions_dir,
    scan_gemini_cli,
)

# Provider dispatch table consumed by the CLI. Values are async coroutine
# functions taking ``(db_path, since=, dry_run=, **provider_specific)``.
PROVIDERS = {
    "claude": scan_claude_code,
    "cursor": scan_cursor,
    "codex": scan_codex,
    "gemini": scan_gemini_cli,
}

__all__ = [
    "AUTO_MODEL_LABEL",
    "ClaudeSession",
    "CodexScanResult",
    "CodexSession",
    "CursorBubble",
    "CursorScanResult",
    "GeminiScanResult",
    "GeminiSession",
    "PROVIDERS",
    "ScanResult",
    "bubble_to_record",
    "codex_sessions_dir",
    "cursor_db_path",
    "decode_project_path",
    "discover_sessions",
    "gemini_sessions_dir",
    "parse_session",
    "read_bubbles",
    "resolve_dev_identity",
    "scan_claude_code",
    "scan_codex",
    "scan_cursor",
    "scan_gemini_cli",
]
