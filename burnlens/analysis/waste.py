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
    # Expensive
    ("gpt-5.6-sol", "expensive"),
    ("gpt-5.2-pro", "expensive"),
    ("o1", "expensive"),
    ("o3", "expensive"),
    ("opus", "expensive"),
    ("gpt-4-turbo", "expensive"),
    ("gpt-4 ", "expensive"),
    # Cheap / small
    ("gpt-4o-mini", "cheap"),
    ("gpt-5-mini", "cheap"),
    ("gpt-5-nano", "cheap"),
    ("gpt-5.6-luna", "cheap"),
    ("gpt-3.5", "cheap"),
    ("haiku", "cheap"),
    ("flash", "cheap"),
    ("gemini-1.5-flash", "cheap"),
    ("gemini-2.0-flash", "cheap"),
    ("gemini-3.1-flash-lite", "cheap"),
    # Mid
    ("gpt-4o", "mid"),
    ("gpt-5", "mid"),
    ("sonnet", "mid"),
    ("gemini-1.5-pro", "mid"),
    ("gemini-2.0-pro", "mid"),
    ("gemini-3.1-pro", "mid"),
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


class PromptCachingOpportunityDetector:
    """Flags repeated large system prompts that aren't being cached.

    Heuristic: system prompt tokens > 1,000 sent >= 5 times with no cache read tokens.
    """

    MIN_SYSTEM_TOKENS = 1_000
    MIN_REPEATS = 5

    def run(self, requests: list[dict[str, Any]]) -> WasteFinding:
        if not requests:
            return WasteFinding(
                detector="PromptCachingOpportunityDetector",
                severity="low",
                title="Prompt Caching Opportunity",
                description="No requests to analyze.",
            )

        from collections import Counter

        hash_counter: Counter[str] = Counter()
        hash_cost: dict[str, float] = {}
        hash_tokens: dict[str, int] = {}

        for r in requests:
            h = r.get("system_prompt_hash")
            if not h:
                continue
            # Only flag if no cache read benefit observed
            if (r.get("cache_read_tokens") or 0) == 0:
                hash_counter[h] += 1
                hash_cost[h] = hash_cost.get(h, 0.0) + (r.get("cost_usd") or 0.0)
                hash_tokens[h] = max(hash_tokens.get(h, 0), r.get("prompt_system_tokens") or 0)

        caching_opportunities = {
            h: count for h, count in hash_counter.items()
            if count >= self.MIN_REPEATS and hash_tokens[h] >= self.MIN_SYSTEM_TOKENS
        }

        affected = sum(caching_opportunities.values())
        estimated_waste = sum(
            hash_cost[h] * 0.3 for h in caching_opportunities
        )  # conservatively assume 30% of cost is system prompt waste

        severity = "high" if affected > 15 else "medium" if caching_opportunities else "low"

        return WasteFinding(
            detector="PromptCachingOpportunityDetector",
            severity=severity,
            title="Prompt Caching Opportunity",
            description=(
                f"{len(caching_opportunities)} large system prompt(s) (>{self.MIN_SYSTEM_TOKENS:,} tokens) "
                f"sent {affected} times without observed cache hits. "
                "Enable prompt caching (Anthropic) or system fingerprinting (OpenAI) to save cost."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=affected,
        )


class OversizedToolSchemaDetector:
    """Flags requests where tool/function schemas consume a large portion of input tokens.

    Heuristic: tools tokens > 1,000 and tools tokens > 30% of total input tokens.
    """

    MIN_TOOLS_TOKENS = 1_000
    RATIO_THRESHOLD = 0.30

    def run(self, requests: list[dict[str, Any]]) -> WasteFinding:
        if not requests:
            return WasteFinding(
                detector="OversizedToolSchemaDetector",
                severity="low",
                title="Oversized Tool Schemas",
                description="No requests to analyze.",
            )

        oversized = []
        for r in requests:
            tools = r.get("prompt_tools_tokens") or 0
            total = r.get("input_tokens") or 1
            if tools >= self.MIN_TOOLS_TOKENS and (tools / total) >= self.RATIO_THRESHOLD:
                oversized.append(r)

        estimated_waste = sum(
            (r.get("cost_usd") or 0.0) * 0.5 for r in oversized
        )  # estimate 50% savings by pruning schemas

        severity = "high" if len(oversized) > 10 else "medium" if oversized else "low"

        return WasteFinding(
            detector="OversizedToolSchemaDetector",
            severity=severity,
            title="Oversized Tool Schemas",
            description=(
                f"{len(oversized)} request(s) sent large tool/function definitions "
                f"(>{self.MIN_TOOLS_TOKENS:,} tokens) representing >{self.RATIO_THRESHOLD * 100:.0f}% of input. "
                "Prune unused schemas, shorten descriptions, or dynamically select tools."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=len(oversized),
            examples=oversized[:3],
        )


class LowRAGEfficiencyDetector:
    """Flags requests with large retrieved contexts (RAG) but very small outputs.

    Heuristic: RAG tokens > 8,000 and output tokens < 100.
    """

    MIN_RAG_TOKENS = 8_000
    MAX_OUTPUT_TOKENS = 100

    def run(self, requests: list[dict[str, Any]]) -> WasteFinding:
        if not requests:
            return WasteFinding(
                detector="LowRAGEfficiencyDetector",
                severity="low",
                title="Low RAG Efficiency",
                description="No requests to analyze.",
            )

        inefficient = [
            r for r in requests
            if (r.get("prompt_rag_tokens") or 0) >= self.MIN_RAG_TOKENS
            and (r.get("output_tokens") or 0) < self.MAX_OUTPUT_TOKENS
        ]

        estimated_waste = sum(
            (r.get("cost_usd") or 0.0) * 0.5 for r in inefficient
        )  # estimate 50% savings from optimized chunking/reranking

        severity = "high" if len(inefficient) > 10 else "medium" if inefficient else "low"

        return WasteFinding(
            detector="LowRAGEfficiencyDetector",
            severity=severity,
            title="Low RAG Efficiency",
            description=(
                f"{len(inefficient)} request(s) sent large RAG contexts (>{self.MIN_RAG_TOKENS:,} tokens) "
                f"but generated very short responses (<{self.MAX_OUTPUT_TOKENS} tokens). "
                "Consider smaller chunks, re-ranking (e.g. Cohere), or pre-summarizing context."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=len(inefficient),
            examples=inefficient[:3],
        )


class HistoryBloatDetector:
    """Flags requests where conversation history dominates input tokens.

    Heuristic: history tokens > 5,000 and history tokens > 50% of input tokens.
    """

    MIN_HISTORY_TOKENS = 5_000
    RATIO_THRESHOLD = 0.50

    def run(self, requests: list[dict[str, Any]]) -> WasteFinding:
        if not requests:
            return WasteFinding(
                detector="HistoryBloatDetector",
                severity="low",
                title="Chat History Bloat",
                description="No requests to analyze.",
            )

        bloated = []
        for r in requests:
            history = r.get("prompt_history_tokens") or 0
            total = r.get("input_tokens") or 1
            if history >= self.MIN_HISTORY_TOKENS and (history / total) >= self.RATIO_THRESHOLD:
                bloated.append(r)

        estimated_waste = sum(
            (r.get("cost_usd") or 0.0) * 0.4 for r in bloated
        )  # estimate 40% savings from conversation pruning

        severity = "high" if len(bloated) > 10 else "medium" if bloated else "low"

        return WasteFinding(
            detector="HistoryBloatDetector",
            severity=severity,
            title="Chat History Bloat",
            description=(
                f"{len(bloated)} request(s) sent bloated conversation histories "
                f"(>{self.MIN_HISTORY_TOKENS:,} tokens) representing >{self.RATIO_THRESHOLD * 100:.0f}% of input. "
                "Implement a sliding message window, summarize past turns, or trim older context."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=len(bloated),
            examples=bloated[:3],
        )


# ---------------------------------------------------------------------------
# Run all detectors
# ---------------------------------------------------------------------------


def run_all_detectors(requests: list[dict[str, Any]]) -> list[WasteFinding]:
    """Run all waste detectors and return findings sorted by severity."""
    detectors = [
        ContextBloatDetector(),
        DuplicateRequestDetector(),
        ModelOverkillDetector(),
        SystemPromptWasteDetector(),
        PromptCachingOpportunityDetector(),
        OversizedToolSchemaDetector(),
        LowRAGEfficiencyDetector(),
        HistoryBloatDetector(),
    ]
    findings = [d.run(requests) for d in detectors]

    severity_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(findings, key=lambda f: severity_order.get(f.severity, 3))
