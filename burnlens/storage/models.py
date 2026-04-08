"""Dataclasses for BurnLens request records."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RequestRecord:
    """A single intercepted LLM API request + response pair."""

    provider: str                       # openai | anthropic | google
    model: str                          # e.g. gpt-4o, claude-3-5-sonnet-20241022
    request_path: str                   # e.g. /v1/chat/completions
    timestamp: datetime = field(default_factory=datetime.utcnow)

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0          # OpenAI o-series reasoning tokens
    cache_read_tokens: int = 0         # Anthropic / OpenAI cached input tokens
    cache_write_tokens: int = 0        # Anthropic cache-write tokens

    cost_usd: float = 0.0
    duration_ms: int = 0
    status_code: int = 200

    tags: dict[str, str] = field(default_factory=dict)  # from X-BurnLens-Tag-* headers
    system_prompt_hash: str | None = None               # SHA-256 of system prompt

    # Set by DB layer after insert
    id: int | None = None


@dataclass
class AggregatedUsage:
    """Aggregated cost/usage stats for reporting."""

    model: str
    provider: str
    request_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
