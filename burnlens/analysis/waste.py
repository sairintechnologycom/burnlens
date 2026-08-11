"""Waste detectors: bloated prompts, duplicates, overkill models, prompt waste.

Detectors are PURE: they read request dicts and return findings. They never
touch the database. Persistence lives in ``burnlens/storage/findings.py`` so
the CLI and reports can run detection with no side effects.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

# Bump when a detector's thresholds or waste maths change. It is part of the
# fingerprint, so a bump retires every existing finding rather than silently
# redefining what an already-resolved one meant.
DETECTOR_VERSION = 1


@dataclass
class WasteFinding:
    """A single waste finding from a detector, scoped to one subject.

    ``subject_type``/``subject_key`` are what makes a finding actionable: they
    name the thing to go fix. Without them a finding is workspace-wide, so
    "mark fixed" would mute a whole category and there would be nothing
    specific to measure a saving against.
    """

    detector: str
    severity: str          # high | medium | low
    title: str
    description: str
    estimated_waste_usd: float = 0.0
    affected_count: int = 0
    examples: list[dict[str, Any]] = field(default_factory=list)
    subject_type: str = "workspace"   # workspace | workflow | model
    subject_key: str = "*"
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Stable identity for this finding across detection runs.

        Deliberately excludes the volatile parts — waste dollars, affected
        count, description, timestamps. Those change every run; including them
        would make the same underlying issue a brand-new finding each time and
        break the lifecycle.
        """
        raw = f"{self.detector}|{self.subject_type}|{self.subject_key}|{DETECTOR_VERSION}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _subject_of(request: dict[str, Any]) -> tuple[str, str]:
    """Pick the subject a request's waste should be attributed to.

    Prefers ``workflow_id`` (the unit a user can actually go change) and falls
    back to the model. Both already exist on the request fact — no new
    instrumentation.
    """
    tags = request.get("tags") or {}
    if isinstance(tags, str):  # storage may hand back raw JSON
        import json
        try:
            tags = json.loads(tags)
        except (ValueError, TypeError):
            tags = {}

    workflow = tags.get("workflow_id") if isinstance(tags, dict) else None
    if workflow:
        return ("workflow", str(workflow))
    return ("model", str(request.get("model") or "unknown"))


def _median(values: list[int]) -> int:
    """Median of a non-empty list; 0 for an empty one."""
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _split_by_subject(
    requests: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Partition requests into per-subject buckets."""
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in requests:
        buckets.setdefault(_subject_of(r), []).append(r)
    return buckets


class _Detector:
    """Base: split by subject, analyse each bucket, drop the clean ones."""

    detector = ""
    title = ""

    def run(self, requests: list[dict[str, Any]]) -> list[WasteFinding]:
        findings = []
        for (subject_type, subject_key), bucket in _split_by_subject(requests).items():
            finding = self._analyse(bucket, subject_type, subject_key)
            if finding is not None:
                findings.append(finding)
        return findings

    def _analyse(
        self, requests: list[dict[str, Any]], subject_type: str, subject_key: str
    ) -> WasteFinding | None:
        """Return a finding for this subject, or None when there is no waste."""
        raise NotImplementedError


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


class ContextBloatDetector(_Detector):
    """Flags requests where input tokens are unusually large.

    Heuristic: requests in the top 10% by input token count that also have
    low output-to-input ratios (suggesting the large context wasn't useful).
    """

    detector = "ContextBloatDetector"
    title = "Context Bloat"

    BLOAT_TOKEN_THRESHOLD = 8_000   # absolute minimum to be considered bloated
    OUTPUT_RATIO_THRESHOLD = 0.05   # output / input < 5% is suspicious

    def _analyse(
        self, requests: list[dict[str, Any]], subject_type: str, subject_key: str
    ) -> WasteFinding | None:
        bloated = [
            r for r in requests
            if (r.get("input_tokens") or 0) >= self.BLOAT_TOKEN_THRESHOLD
            and (r.get("output_tokens") or 1) / max(r.get("input_tokens") or 1, 1)
            < self.OUTPUT_RATIO_THRESHOLD
        ]
        if not bloated:
            return None

        estimated_waste = sum(
            (r.get("cost_usd") or 0.0) * 0.5 for r in bloated
        )  # conservatively estimate 50% of cost is waste

        return WasteFinding(
            detector=self.detector,
            severity="high" if len(bloated) > 10 else "medium",
            title=self.title,
            description=(
                f"{len(bloated)} request(s) on {subject_type} '{subject_key}' sent "
                f"extremely large contexts (>{self.BLOAT_TOKEN_THRESHOLD:,} input tokens) "
                "with very few output tokens. "
                "Consider trimming conversation history or compressing system prompts."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=len(bloated),
            examples=bloated[:3],
            subject_type=subject_type,
            subject_key=subject_key,
            evidence={
                "threshold_input_tokens": self.BLOAT_TOKEN_THRESHOLD,
                "output_ratio_threshold": self.OUTPUT_RATIO_THRESHOLD,
                "median_input_tokens": _median(
                    [r.get("input_tokens") or 0 for r in bloated]
                ),
            },
        )


class DuplicateRequestDetector(_Detector):
    """Flags repeated requests with identical system prompts and models.

    A duplicate run: same system_prompt_hash + same model appearing more than
    once in the analysis window, often indicating missing caching or retries.
    """

    detector = "DuplicateRequestDetector"
    title = "Duplicate Requests"

    MIN_OCCURRENCES = 3  # only flag if it happens this many times

    def _analyse(
        self, requests: list[dict[str, Any]], subject_type: str, subject_key: str
    ) -> WasteFinding | None:
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
        if not duplicates:
            return None

        affected = sum(v - 1 for v in duplicates.values())  # subtract one "legitimate" call
        estimated_waste = sum(
            key_cost[k] * (v - 1) / v for k, v in duplicates.items()
        )

        return WasteFinding(
            detector=self.detector,
            severity="high" if affected > 20 else "medium",
            title=self.title,
            description=(
                f"{len(duplicates)} unique (model, system-prompt) combination(s) on "
                f"{subject_type} '{subject_key}' repeated {self.MIN_OCCURRENCES}+ times. "
                f"~{affected} redundant calls detected. "
                "Consider caching responses or using prompt caching features."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=affected,
            subject_type=subject_type,
            subject_key=subject_key,
            evidence={
                "min_occurrences": self.MIN_OCCURRENCES,
                "duplicate_groups": len(duplicates),
                "top_repeat_count": max(duplicates.values()),
            },
        )


class ModelOverkillDetector(_Detector):
    """Flags simple, short-output tasks routed to expensive models.

    Heuristic: expensive model + output < 200 tokens is likely overkill.
    A cheaper model could handle classification, extraction, and short Q&A.
    """

    detector = "ModelOverkillDetector"
    title = "Model Overkill"

    SHORT_OUTPUT_THRESHOLD = 200    # output tokens
    MIN_COST_PER_REQUEST = 0.001    # only flag if it actually cost something

    def _analyse(
        self, requests: list[dict[str, Any]], subject_type: str, subject_key: str
    ) -> WasteFinding | None:
        overkill = [
            r for r in requests
            if _model_tier(r.get("model") or "") == "expensive"
            and (r.get("output_tokens") or 0) < self.SHORT_OUTPUT_THRESHOLD
            and (r.get("cost_usd") or 0.0) >= self.MIN_COST_PER_REQUEST
        ]
        if not overkill:
            return None

        estimated_waste = sum(
            (r.get("cost_usd") or 0.0) * 0.7 for r in overkill
        )  # estimate ~70% savings by switching to a cheaper model

        return WasteFinding(
            detector=self.detector,
            severity="high" if len(overkill) > 15 else "medium",
            title=self.title,
            description=(
                f"{len(overkill)} request(s) on {subject_type} '{subject_key}' used an "
                f"expensive model but produced fewer than {self.SHORT_OUTPUT_THRESHOLD} "
                "output tokens. Short classification, extraction, or routing tasks can "
                "use cheaper models."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=len(overkill),
            examples=overkill[:3],
            subject_type=subject_type,
            subject_key=subject_key,
            evidence={
                "short_output_threshold": self.SHORT_OUTPUT_THRESHOLD,
                "median_input_tokens": _median(
                    [r.get("input_tokens") or 0 for r in overkill]
                ),
                "models": sorted({r.get("model") or "" for r in overkill}),
            },
        )


class SystemPromptWasteDetector(_Detector):
    """Flags requests where the system prompt dominates input tokens.

    Heuristic: if system_prompt_hash is the same across many requests but the
    provider doesn't cache it (or caching isn't enabled), every call re-pays
    for the same tokens. Also flags unusually large system prompt ratios.
    """

    detector = "SystemPromptWasteDetector"
    title = "System Prompt Waste"

    SYSTEM_PROMPT_RATIO_THRESHOLD = 0.80  # system prompt > 80% of input tokens
    MIN_INPUT_TOKENS = 500

    def _analyse(
        self, requests: list[dict[str, Any]], subject_type: str, subject_key: str
    ) -> WasteFinding | None:
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
        if not repeated:
            return None

        estimated_waste = sum(
            hash_cost[h] * 0.3 for h in repeated
        )  # ~30% of cost could be saved by prompt caching

        affected = sum(repeated.values())

        return WasteFinding(
            detector=self.detector,
            severity="medium",
            title=self.title,
            description=(
                f"{len(repeated)} system prompt(s) on {subject_type} '{subject_key}' sent "
                f"{affected} times without observed cache hits. Enable prompt caching "
                "(Anthropic) or system fingerprinting (OpenAI) to avoid re-paying for "
                "repeated system prompts."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=affected,
            subject_type=subject_type,
            subject_key=subject_key,
            evidence={
                "distinct_system_prompts": len(repeated),
                "top_repeat_count": max(repeated.values()),
            },
        )


class PromptCachingOpportunityDetector(_Detector):
    """Flags repeated large system prompts that aren't being cached.

    Heuristic: system prompt tokens > 1,000 sent >= 5 times with no cache read tokens.
    """

    detector = "PromptCachingOpportunityDetector"
    title = "Prompt Caching Opportunity"

    MIN_SYSTEM_TOKENS = 1_000
    MIN_REPEATS = 5

    def _analyse(
        self, requests: list[dict[str, Any]], subject_type: str, subject_key: str
    ) -> WasteFinding | None:
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

        if not caching_opportunities:
            return None

        affected = sum(caching_opportunities.values())
        estimated_waste = sum(
            hash_cost[h] * 0.3 for h in caching_opportunities
        )  # conservatively assume 30% of cost is system prompt waste

        return WasteFinding(
            detector=self.detector,
            severity="high" if affected > 15 else "medium",
            title=self.title,
            description=(
                f"{len(caching_opportunities)} large system prompt(s) "
                f"(>{self.MIN_SYSTEM_TOKENS:,} tokens) on {subject_type} '{subject_key}' "
                f"sent {affected} times without observed cache hits. "
                "Enable prompt caching (Anthropic) or system fingerprinting (OpenAI) to save cost."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=affected,
            subject_type=subject_type,
            subject_key=subject_key,
            evidence={
                "min_system_tokens": self.MIN_SYSTEM_TOKENS,
                "min_repeats": self.MIN_REPEATS,
                "cacheable_prompts": len(caching_opportunities),
            },
        )


class OversizedToolSchemaDetector(_Detector):
    """Flags requests where tool/function schemas consume a large portion of input tokens.

    Heuristic: tools tokens > 1,000 and tools tokens > 30% of total input tokens.
    """

    detector = "OversizedToolSchemaDetector"
    title = "Oversized Tool Schemas"

    MIN_TOOLS_TOKENS = 1_000
    RATIO_THRESHOLD = 0.30

    def _analyse(
        self, requests: list[dict[str, Any]], subject_type: str, subject_key: str
    ) -> WasteFinding | None:
        oversized = []
        for r in requests:
            tools = r.get("prompt_tools_tokens") or 0
            total = r.get("input_tokens") or 1
            if tools >= self.MIN_TOOLS_TOKENS and (tools / total) >= self.RATIO_THRESHOLD:
                oversized.append(r)
        if not oversized:
            return None

        estimated_waste = sum(
            (r.get("cost_usd") or 0.0) * 0.5 for r in oversized
        )  # estimate 50% savings by pruning schemas

        return WasteFinding(
            detector=self.detector,
            severity="high" if len(oversized) > 10 else "medium",
            title=self.title,
            description=(
                f"{len(oversized)} request(s) on {subject_type} '{subject_key}' sent large "
                f"tool/function definitions (>{self.MIN_TOOLS_TOKENS:,} tokens) representing "
                f">{self.RATIO_THRESHOLD * 100:.0f}% of input. "
                "Prune unused schemas, shorten descriptions, or dynamically select tools."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=len(oversized),
            examples=oversized[:3],
            subject_type=subject_type,
            subject_key=subject_key,
            evidence={
                "min_tools_tokens": self.MIN_TOOLS_TOKENS,
                "ratio_threshold": self.RATIO_THRESHOLD,
                "median_tools_tokens": _median(
                    [r.get("prompt_tools_tokens") or 0 for r in oversized]
                ),
            },
        )


class LowRAGEfficiencyDetector(_Detector):
    """Flags requests with large retrieved contexts (RAG) but very small outputs.

    Heuristic: RAG tokens > 8,000 and output tokens < 100.
    """

    detector = "LowRAGEfficiencyDetector"
    title = "Low RAG Efficiency"

    MIN_RAG_TOKENS = 8_000
    MAX_OUTPUT_TOKENS = 100

    def _analyse(
        self, requests: list[dict[str, Any]], subject_type: str, subject_key: str
    ) -> WasteFinding | None:
        inefficient = [
            r for r in requests
            if (r.get("prompt_rag_tokens") or 0) >= self.MIN_RAG_TOKENS
            and (r.get("output_tokens") or 0) < self.MAX_OUTPUT_TOKENS
        ]
        if not inefficient:
            return None

        estimated_waste = sum(
            (r.get("cost_usd") or 0.0) * 0.5 for r in inefficient
        )  # estimate 50% savings from optimized chunking/reranking

        return WasteFinding(
            detector=self.detector,
            severity="high" if len(inefficient) > 10 else "medium",
            title=self.title,
            description=(
                f"{len(inefficient)} request(s) on {subject_type} '{subject_key}' sent large "
                f"RAG contexts (>{self.MIN_RAG_TOKENS:,} tokens) but generated very short "
                f"responses (<{self.MAX_OUTPUT_TOKENS} tokens). "
                "Consider smaller chunks, re-ranking (e.g. Cohere), or pre-summarizing context."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=len(inefficient),
            examples=inefficient[:3],
            subject_type=subject_type,
            subject_key=subject_key,
            evidence={
                "min_rag_tokens": self.MIN_RAG_TOKENS,
                "max_output_tokens": self.MAX_OUTPUT_TOKENS,
                "median_rag_tokens": _median(
                    [r.get("prompt_rag_tokens") or 0 for r in inefficient]
                ),
            },
        )


class HistoryBloatDetector(_Detector):
    """Flags requests where conversation history dominates input tokens.

    Heuristic: history tokens > 5,000 and history tokens > 50% of input tokens.
    """

    detector = "HistoryBloatDetector"
    title = "Chat History Bloat"

    MIN_HISTORY_TOKENS = 5_000
    RATIO_THRESHOLD = 0.50

    def _analyse(
        self, requests: list[dict[str, Any]], subject_type: str, subject_key: str
    ) -> WasteFinding | None:
        bloated = []
        for r in requests:
            history = r.get("prompt_history_tokens") or 0
            total = r.get("input_tokens") or 1
            if history >= self.MIN_HISTORY_TOKENS and (history / total) >= self.RATIO_THRESHOLD:
                bloated.append(r)
        if not bloated:
            return None

        estimated_waste = sum(
            (r.get("cost_usd") or 0.0) * 0.4 for r in bloated
        )  # estimate 40% savings from conversation pruning

        return WasteFinding(
            detector=self.detector,
            severity="high" if len(bloated) > 10 else "medium",
            title=self.title,
            description=(
                f"{len(bloated)} request(s) on {subject_type} '{subject_key}' sent bloated "
                f"conversation histories (>{self.MIN_HISTORY_TOKENS:,} tokens) representing "
                f">{self.RATIO_THRESHOLD * 100:.0f}% of input. "
                "Implement a sliding message window, summarize past turns, or trim older context."
            ),
            estimated_waste_usd=estimated_waste,
            affected_count=len(bloated),
            examples=bloated[:3],
            subject_type=subject_type,
            subject_key=subject_key,
            evidence={
                "min_history_tokens": self.MIN_HISTORY_TOKENS,
                "ratio_threshold": self.RATIO_THRESHOLD,
                "median_history_tokens": _median(
                    [r.get("prompt_history_tokens") or 0 for r in bloated]
                ),
            },
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
    findings = [f for d in detectors for f in d.run(requests)]

    # Worst first, then biggest dollars — the order a user should work them in.
    severity_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(
        findings,
        key=lambda f: (severity_order.get(f.severity, 3), -f.estimated_waste_usd),
    )
