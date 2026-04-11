"""Provider signature matching — pure matching logic.

This module provides the core matching algorithm for identifying AI providers
from endpoint URLs using fnmatch patterns. The DB-dependent orchestration
(upsert_asset_from_detection, classify_new_assets) lives in the local package.
"""
from __future__ import annotations

import fnmatch
import logging

from burnlens_core.models.records import ProviderSignature

logger = logging.getLogger(__name__)


def match_provider_from_signatures(
    endpoint_url: str,
    signatures: list[ProviderSignature],
) -> str | None:
    """Return the provider name for a given endpoint URL, or None if unknown.

    Matching uses fnmatch glob patterns from provider signatures.
    The URL scheme (https://) is stripped before matching.
    Matching is case-insensitive.

    Args:
        endpoint_url: The AI API endpoint URL to identify.
        signatures: List of ProviderSignature records to match against.

    Returns:
        The provider name string (e.g. "openai") or None if no match found.
    """
    # Strip scheme (https:// or http://)
    url_host_path = endpoint_url.split("://", 1)[-1]
    url_lower = url_host_path.lower()

    for sig in signatures:
        if fnmatch.fnmatch(url_lower, sig.endpoint_pattern.lower()):
            return sig.provider

    return None
