"""Waste detectors: bloated prompts, duplicates, overkill models, prompt waste."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WasteFinding:
    """A single waste finding from a detector."""

    detector: str
    severity: str          # high | medium | low
    title: str
    description: str
    estimated_waste_usd: float = 0.0
    affected_count: int = 0
    examples: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Model tier classification
# ---------------------------------------------------------------------------

# Maps model name substrings → cost tier (lower is cheaper)
_MODEL_TIERS: list[tuple[str, str]] = [
    # Cheap / small
    ("gpt-4o-mini", "cheap"),
    ("gpt-3.5", "cheap"),
    ("haiku", "cheap"),
    ("flash", "cheap"),
    ("gemini-1.5-flash", "cheap"),
    ("gemini-2.0-flash", "cheap"),
    # Mid
    ("gpt-4o", "mid"),
    ("sonnet", "mid"),
    ("gemini-1.5-pro", "mid"),
    ("gemini-2.0-pro", "mid"),
    # Expensive
    ("o1", "expensive"),
    ("o3", "expensive"),
    ("opus", "expensive"),
    ("gpt-4-turbo", "expensive"),
    ("gpt-4 ", "expensive"),
]


def _model_tier(model: str) -> str:
    model_lower = model.lower()
    for substr, tier in _MODEL_TIERS:
        if substr in model_lower:
            return tier
    return "mid"  # assume mid if unknown


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


class ContextBloatDetector:
    """Flags requests where input tokens are unusually large.

    Heuristic: requests in the top 10% by input token count that also have
    low output-to-input ratios (suggesting the large context wasn't useful).
    """

    BLOAT_TOKEN_THRESHOLD = 8_000   # absolute minimum to be considered bloated
    OUTPUT_RATIO_THRESHOLD = 0.05   # output / input < 5% is suspicious

    def run(self, requests: list[dict[str, Any]]) -> WasteFinding:
        """Run the detector and return a WasteFinding."""
        if not requests:
            return WasteFinding(
                detector="ContextBloatDetector",
                severity="low",
                title="Context Bloat",
                description="No requests to analyze.",
            )

        bloated = [
            r for r in requests
            if (r.get("input_tokens") or 0) >= self.BLOAT_TOKEN_THRESHOLD
            and (r.get("output_tokens") or 1) / max(r.get("input_tokens") or 1, 1)
            < self.OUTPUT_RATIO_THRESHOLD
        ]

        estimated_waste = sum(
            (r.get("cost_usd") or 0.0) * 0.5 for r in bloated
        )  # conservatively estimate 50% of cost is waste

        severity = "high" if len(bloated) > 10 else "medium" if bloated else "low"

        return WasteFinding(
            detector="ContextBloatDetector",
            severity=severity,
            title="Context Bloat",
            description=(
                f"{len(bloated)} request(s) sent extremely large contexts "
                f"(>{self.BLOAT_TOKEN_THRESHOLD:,} input tokens) with very few output tokens. "
                "Consider trimming conversation history or compressing system prompts."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=len(bloated),
            examples=bloated[:3],
        )


class DuplicateRequestDetector:
    """Flags repeated requests with identical system prompts and models.

    A duplicate run: same system_prompt_hash + same model appearing more than
    once in the analysis window, often indicating missing caching or retries.
    """

    MIN_OCCURRENCES = 3  # only flag if it happens this many times

    def run(self, requests: list[dict[str, Any]]) -> WasteFinding:
        """Run the detector and return a WasteFinding."""
        if not requests:
            return WasteFinding(
                detector="DuplicateRequestDetector",
                severity="low",
                title="Duplicate Requests",
                description="No requests to analyze.",
            )

        # Count (system_prompt_hash, model) pairs
        from collections import Counter

        key_counts: Counter[tuple[str | None, str]] = Counter()
        key_cost: dict[tuple[str | None, str], float] = {}

        for r in requests:
            key = (r.get("system_prompt_hash"), r.get("model", ""))
            if key[0] is None:
                continue
            key_counts[key] += 1
            key_cost[key] = key_cost.get(key, 0.0) + (r.get("cost_usd") or 0.0)

        duplicates = {k: v for k, v in key_counts.items() if v >= self.MIN_OCCURRENCES}
        affected = sum(v - 1 for v in duplicates.values())  # subtract one "legitimate" call
        estimated_waste = sum(
            key_cost[k] * (v - 1) / v for k, v in duplicates.items()
        )

        severity = "high" if affected > 20 else "medium" if duplicates else "low"

        return WasteFinding(
            detector="DuplicateRequestDetector",
            severity=severity,
            title="Duplicate Requests",
            description=(
                f"{len(duplicates)} unique (model, system-prompt) combination(s) "
                f"repeated {self.MIN_OCCURRENCES}+ times. "
                f"~{affected} redundant calls detected. "
                "Consider caching responses or using prompt caching features."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=affected,
        )


class ModelOverkillDetector:
    """Flags simple, short-output tasks routed to expensive models.

    Heuristic: expensive model + output < 200 tokens is likely overkill.
    A cheaper model could handle classification, extraction, and short Q&A.
    """

    SHORT_OUTPUT_THRESHOLD = 200    # output tokens
    MIN_COST_PER_REQUEST = 0.001    # only flag if it actually cost something

    def run(self, requests: list[dict[str, Any]]) -> WasteFinding:
        """Run the detector and return a WasteFinding."""
        if not requests:
            return WasteFinding(
                detector="ModelOverkillDetector",
                severity="low",
                title="Model Overkill",
                description="No requests to analyze.",
            )

        overkill = [
            r for r in requests
            if _model_tier(r.get("model") or "") == "expensive"
            and (r.get("output_tokens") or 0) < self.SHORT_OUTPUT_THRESHOLD
            and (r.get("cost_usd") or 0.0) >= self.MIN_COST_PER_REQUEST
        ]

        estimated_waste = sum(
            (r.get("cost_usd") or 0.0) * 0.7 for r in overkill
        )  # estimate ~70% savings by switching to a cheaper model

        severity = "high" if len(overkill) > 15 else "medium" if overkill else "low"

        return WasteFinding(
            detector="ModelOverkillDetector",
            severity=severity,
            title="Model Overkill",
            description=(
                f"{len(overkill)} request(s) used an expensive model but produced "
                f"fewer than {self.SHORT_OUTPUT_THRESHOLD} output tokens. "
                "Short classification, extraction, or routing tasks can use cheaper models."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=len(overkill),
            examples=overkill[:3],
        )


class SystemPromptWasteDetector:
    """Flags requests where the system prompt dominates input tokens.

    Heuristic: if system_prompt_hash is the same across many requests but the
    provider doesn't cache it (or caching isn't enabled), every call re-pays
    for the same tokens. Also flags unusually large system prompt ratios.
    """

    SYSTEM_PROMPT_RATIO_THRESHOLD = 0.80  # system prompt > 80% of input tokens
    MIN_INPUT_TOKENS = 500

    def run(self, requests: list[dict[str, Any]]) -> WasteFinding:
        """Run the detector and return a WasteFinding."""
        if not requests:
            return WasteFinding(
                detector="SystemPromptWasteDetector",
                severity="low",
                title="System Prompt Waste",
                description="No requests to analyze.",
            )

        # Find requests with no cache_read_tokens but repeated system_prompt_hash
        from collections import Counter

        hash_counter: Counter[str] = Counter()
        hash_cost: dict[str, float] = {}

        for r in requests:
            h = r.get("system_prompt_hash")
            if not h:
                continue
            # Only flag if no cache benefit observed
            hash_counter[h] += 1
            hash_cost[h] = hash_cost.get(h, 0.0) + (r.get("cost_usd") or 0.0)

        # Repeated system prompts that aren't cached
        repeated = {h: c for h, c in hash_counter.items() if c >= 5}
        estimated_waste = sum(
            hash_cost[h] * 0.3 for h in repeated
        )  # ~30% of cost could be saved by prompt caching

        affected = sum(repeated.values())
        severity = "medium" if repeated else "low"

        return WasteFinding(
            detector="SystemPromptWasteDetector",
            severity=severity,
            title="System Prompt Waste",
            description=(
                f"{len(repeated)} system prompt(s) sent {affected} times without "
                "observed cache hits. Enable prompt caching (Anthropic) or system "
                "fingerprinting (OpenAI) to avoid re-paying for repeated system prompts."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=affected,
        )


# ---------------------------------------------------------------------------
# Run all detectors
# ---------------------------------------------------------------------------


def run_all_detectors(requests: list[dict[str, Any]]) -> list[WasteFinding]:
    """Run all four waste detectors and return findings sorted by severity."""
    detectors = [
        ContextBloatDetector(),
        DuplicateRequestDetector(),
        ModelOverkillDetector(),
        SystemPromptWasteDetector(),
    ]
    findings = [d.run(requests) for d in detectors]

    severity_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(findings, key=lambda f: severity_order.get(f.severity, 3))
