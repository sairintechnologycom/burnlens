"""Public pages must match the live CLI, registry, and policy defaults.

Mutation E: replacing the post-scan command ``repos`` with ``top`` on public
onboarding must fail. ``burnlens top`` remains a valid live-proxy viewer; it
is not the next step after ``burnlens scan``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

HOMEPAGE = ROOT / "frontend" / "src" / "app" / "page.tsx"
SCAN_ONBOARDING = [
    HOMEPAGE,
    ROOT / "frontend" / "src" / "app" / "scan" / "page.tsx",
    ROOT / "frontend" / "src" / "app" / "docs" / "scan" / "page.tsx",
    ROOT / "frontend" / "src" / "app" / "docs" / "page.tsx",
    ROOT / "frontend" / "src" / "app" / "docs" / "cli" / "page.tsx",
]

PROVIDER_DISPLAY = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "groq": "Groq",
    "together": "Together",
    "mistral": "Mistral",
    "xai": "xAI",
    "deepseek": "DeepSeek",
    "azure": "Azure OpenAI",
    "bedrock": "AWS Bedrock",
}

PROVIDER_PAGES = [
    HOMEPAGE,
    ROOT / "frontend" / "src" / "app" / "compare" / "burnlens-vs-litellm" / "page.tsx",
    ROOT / "frontend" / "src" / "app" / "compare" / "burnlens-vs-helicone" / "page.tsx",
    ROOT / "frontend" / "support-knowledge" / "faq.md",
    ROOT / "README.md",
]

ABSOLUTE_PAYLOAD_CLAIMS = (
    "zero payload rewrites",
    "zero payload modification",
    "None — transparent passthrough",
    "forwards your requests unmodified",
    "forwards requests unmodified",
    "request body pass through byte-for-byte",
    "body, and other headers pass through unchanged",
)


def test_homepage_scan_funnel_is_repos_not_top():
    """Mutation E: public onboarding after scan must be repos, not top."""
    text = HOMEPAGE.read_text()
    assert 'text: "burnlens repos"' in text
    assert 'text: "burnlens top"' not in text
    install = text[text.index("Up in 3 commands") :]
    assert "burnlens repos" in install
    assert "burnlens top" not in install


@pytest.mark.parametrize("page", SCAN_ONBOARDING, ids=lambda p: p.name)
def test_scan_onboarding_names_repos(page: Path):
    text = page.read_text()
    assert "burnlens repos" in text, (
        f"{page.relative_to(ROOT)} documents scan without the post-scan "
        "command burnlens repos"
    )


def test_registered_providers_appear_on_public_lists():
    from burnlens.providers import all_providers

    registered = set(all_providers())
    assert set(PROVIDER_DISPLAY) == registered, (
        f"Display map drifted from registry: {registered ^ set(PROVIDER_DISPLAY)}"
    )
    missing: list[str] = []
    for page in PROVIDER_PAGES:
        text = page.read_text()
        for name, label in PROVIDER_DISPLAY.items():
            if label not in text:
                missing.append(f"{page.relative_to(ROOT)} missing {label} ({name})")
    assert not missing, "Public provider lists disagree with the registry:\n" + "\n".join(
        missing
    )


def test_public_pages_do_not_claim_payloads_never_change():
    pages = [
        ROOT / "frontend" / "src" / "app" / "compare" / "burnlens-vs-litellm" / "page.tsx",
        ROOT / "frontend" / "src" / "app" / "security" / "page.tsx",
        HOMEPAGE,
        ROOT / "frontend" / "support-knowledge" / "faq.md",
    ]
    hits: list[str] = []
    for page in pages:
        text = page.read_text()
        for claim in ABSOLUTE_PAYLOAD_CLAIMS:
            if claim in text:
                hits.append(f"{page.relative_to(ROOT)}: {claim!r}")
    assert not hits, "Absolute passthrough claims contradict explicit policy:\n" + "\n".join(
        hits
    )


def test_security_qualifies_observation_vs_policy():
    text = (ROOT / "frontend" / "src" / "app" / "security" / "page.tsx").read_text()
    assert "observation mode" in text.lower() or "Observation mode" in text
    assert "budget_downgrade" in text


def test_docs_budgets_state_runtime_policies_are_explicit():
    text = (
        ROOT / "frontend" / "src" / "app" / "docs" / "budgets" / "page.tsx"
    ).read_text()
    assert "This policy can change the model sent upstream." in text
    assert "budget_downgrade: false" in text
    assert "cache.enabled: false" in text


def test_homepage_states_cache_and_routing_are_opt_in():
    text = HOMEPAGE.read_text()
    assert "cache.enabled: true" in text
    assert "Off by default" in text
    assert "Opt-in model routing" in text
    assert "Automatic model routing" not in text


_DEAD_SCAN_SYNTAX = re.compile(r"burnlens scan (claude|cursor|codex|gemini)\b")
_CURRENT_DOCS = [
    ROOT / "README.md",
    HOMEPAGE,
    ROOT / "frontend" / "src" / "app" / "scan" / "page.tsx",
    ROOT / "frontend" / "src" / "app" / "security" / "page.tsx",
    ROOT / "frontend" / "src" / "app" / "docs" / "scan" / "page.tsx",
    ROOT / "frontend" / "src" / "app" / "docs" / "cli" / "page.tsx",
    ROOT / "frontend" / "src" / "app" / "docs" / "page.tsx",
]


def test_current_docs_use_scan_provider_flag():
    """Live CLI is ``burnlens scan --provider claude``, not positional."""
    hits: list[str] = []
    for page in _CURRENT_DOCS:
        for i, line in enumerate(page.read_text().splitlines(), 1):
            if _DEAD_SCAN_SYNTAX.search(line):
                hits.append(f"{page.relative_to(ROOT)}:{i}: {line.strip()}")
    assert not hits, "Dead scan syntax in current docs:\n" + "\n".join(hits)


def test_scan_page_unpriced_is_unknown_not_zero():
    text = (ROOT / "frontend" / "src" / "app" / "scan" / "page.tsx").read_text()
    assert "$ unknown" in text
    assert "imported with a $0" not in text
    assert "imported with cost = $0" not in text
    assert "cost = $0" not in text


def test_codex_scan_path_is_jsonl_not_sqlite():
    pages = [
        ROOT / "frontend" / "src" / "app" / "scan" / "page.tsx",
        ROOT / "frontend" / "src" / "app" / "security" / "page.tsx",
    ]
    for page in pages:
        text = page.read_text()
        assert "Codex" in text
        assert "~/.codex/sessions" in text or "JSONL" in text
        assert "Codex CLI SQLite" not in text
        assert "Codex SQLite" not in text


def test_homepage_scan_attribution_is_per_repo_not_per_pr():
    text = HOMEPAGE.read_text()
    assert "per-repo, per-dev attribution" in text
    assert "per-PR, per-dev attribution" not in text
