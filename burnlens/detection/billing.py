"""Billing API parsers for OpenAI, Anthropic, and Google.

These parsers query provider admin/billing APIs to discover AI assets
(model/key combinations) that may not be routed through the BurnLens proxy.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from burnlens.config import BurnLensConfig
from burnlens.storage.database import insert_asset, insert_discovery_event
from burnlens.storage.models import AiAsset, DiscoveryEvent
from burnlens.storage.queries import get_assets

logger = logging.getLogger(__name__)


async def _paginate_usage(
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
    data_extractor: Any = None,
) -> list[dict]:
    """Follow has_more / next_page pagination, collecting all results.

    Args:
        url: API endpoint URL.
        headers: Request headers (auth, version, etc.).
        params: Initial query parameters.
        data_extractor: Optional callable(response_json) -> list[dict].
                        If None, uses response_json["data"] directly.

    Returns:
        Flat list of all result dicts across all pages.
    """
    all_results: list[dict] = []
    current_params = dict(params)

    async with httpx.AsyncClient() as client:
        while True:
            try:
                response = await client.get(url, headers=headers, params=current_params)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "HTTP error fetching billing data from %s: %s %s",
                    url,
                    exc.response.status_code,
                    exc.response.text,
                )
                break
            except httpx.RequestError as exc:
                logger.error("Request error fetching billing data from %s: %s", url, exc)
                break

            payload = response.json()

            if data_extractor:
                page_results = data_extractor(payload)
            else:
                page_results = payload.get("data", [])

            all_results.extend(page_results)

            if not payload.get("has_more"):
                break

            next_page = payload.get("next_page")
            if not next_page:
                break

            current_params["page"] = next_page

    return all_results


async def fetch_openai_usage(
    admin_key: str | None = None,
    since_hours: int = 24,
) -> list[dict]:
    """Fetch usage data from the OpenAI organization billing API.

    Calls POST /v1/organization/usage/completions with group_by model and
    api_key_id. Paginates via has_more + next_page.

    Args:
        admin_key: OpenAI admin API key (sk-... with org admin scope).
        since_hours: How many hours back to query.

    Returns:
        List of result dicts with model, api_key_id, input_tokens, output_tokens,
        num_model_requests fields. Empty list if admin_key is None.
    """
    if admin_key is None:
        logger.warning(
            "openai_admin_key not configured — skipping OpenAI billing API detection. "
            "Set openai_admin_key in config or OPENAI_ADMIN_KEY env var."
        )
        return []

    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    start_time = int(since.timestamp())

    headers = {"Authorization": f"Bearer {admin_key}", "Content-Type": "application/json"}
    params = {"start_time": start_time, "group_by[]": ("model", "api_key_id")}
    url = "https://api.openai.com/v1/organization/usage/completions"

    def _extract_openai(payload: dict) -> list[dict]:
        results: list[dict] = []
        for bucket in payload.get("data", []):
            results.extend(bucket.get("results", []))
        return results

    return await _paginate_usage(url, headers, params, data_extractor=_extract_openai)


async def fetch_anthropic_usage(
    admin_key: str | None = None,
    since_hours: int = 24,
) -> list[dict]:
    """Fetch usage data from the Anthropic organization billing API.

    Calls GET /v1/organizations/usage_report/messages with group_by model.
    Paginates via has_more + next_page.

    Args:
        admin_key: Anthropic admin API key (x-api-key header).
        since_hours: How many hours back to query.

    Returns:
        List of result dicts with model, input_tokens, output_tokens,
        num_model_requests. Empty list if admin_key is None.
    """
    if admin_key is None:
        logger.warning(
            "anthropic_admin_key not configured — skipping Anthropic billing API detection. "
            "Set anthropic_admin_key in config or ANTHROPIC_ADMIN_KEY env var."
        )
        return []

    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    start_time = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    headers = {
        "x-api-key": admin_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    params = {"start_time": start_time, "group_by[]": "model"}
    url = "https://api.anthropic.com/v1/organizations/usage_report/messages"

    return await _paginate_usage(url, headers, params)


async def fetch_google_usage(
    admin_key: str | None = None,
    since_hours: int = 24,
) -> list[dict]:
    """Google billing API detection stub (legacy interface).

    Retained for backwards compatibility. The real implementation is in
    GoogleBillingParser which uses the Cloud Billing v1 REST API.

    Returns:
        Always returns empty list.
    """
    logger.info("fetch_google_usage: proxy-only mode — use GoogleBillingParser for Google billing API detection")
    return []


class GoogleBillingParser:
    """Parses Google Cloud Billing API to discover Vertex AI and Generative AI usage.

    Supported auth modes:
      api_key: Simple API key — easiest setup, sufficient for billing read access
      service_account: Full OAuth2 — required for private billing accounts

    Falls back to proxy-only detection if billing config is missing or API fails.

    BigQuery billing export alternative (not implemented):
      SELECT service.description, sku.description, usage_start_time, cost, usage.amount
      FROM `{project}.{dataset}.gcp_billing_export_v1_{billing_account_id}`
      WHERE service.description LIKE '%AI%' OR service.description LIKE '%Vertex%'
      AND DATE(usage_start_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    """

    VERTEX_AI_SERVICE_IDS = {
        "aiplatform.googleapis.com",
        "generativelanguage.googleapis.com",
        "ml.googleapis.com",
    }

    GEMINI_MODEL_PREFIXES = [
        "gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro",
        "gemini-2.0-flash", "text-bison", "code-bison", "chat-bison",
    ]

    BASE_URL = "https://cloudbilling.googleapis.com/v1"

    async def fetch_usage(self, config: Any) -> list[dict]:
        """Fetch AI usage from Google Cloud Billing API.

        Args:
            config: GoogleBillingConfig instance.

        Returns:
            List of asset dicts compatible with ai_assets upsert.
            Returns [] on any error (fail-open, log warning).
        """
        if not config.enabled:
            return []

        if not config.billing_account_id:
            logger.warning(
                "google_billing.billing_account_id not configured — "
                "skipping Google billing API detection."
            )
            return []

        try:
            headers, key_param = self._build_auth(config)
        except _GoogleAuthUnavailable:
            return []

        try:
            skus = await self._fetch_skus(config.billing_account_id, headers, key_param)
        except Exception:
            logger.warning("Google billing API fetch failed", exc_info=True)
            return []

        assets: list[dict] = []
        key_for_hash = config.api_key or config.billing_account_id
        api_key_hash = hashlib.sha256(key_for_hash.encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat() + "Z"

        for sku in skus:
            model = self._extract_model(sku)
            if model is None:
                continue

            assets.append({
                "provider": "google",
                "model": model,
                "endpoint_url": (
                    f"https://generativelanguage.googleapis.com"
                    f"/v1beta/models/{model}:generateContent"
                ),
                "api_key_hash": api_key_hash,
                "first_seen_at": now,
                "last_seen_at": now,
                "monthly_spend_usd": 0.0,
                "request_count": 0,
                "status": "active",
                "source": "billing_api_google",
            })

        logger.info("Google billing parser found %d AI SKUs", len(assets))
        return assets

    def _build_auth(self, config: Any) -> tuple[dict[str, str], dict[str, str]]:
        """Build auth headers and query params based on config.auth_mode.

        Returns:
            (headers_dict, key_query_params_dict)

        Raises:
            _GoogleAuthUnavailable: when service_account mode is requested
                but google-auth is not installed.
        """
        if config.auth_mode == "service_account":
            try:
                from google.auth.transport.requests import Request as GoogleAuthRequest
                from google.oauth2 import service_account as sa_module
            except ImportError:
                logger.warning(
                    "Install google-auth for service account support: "
                    "pip install google-auth"
                )
                raise _GoogleAuthUnavailable()

            credentials = sa_module.Credentials.from_service_account_file(
                config.service_account_json_path,
                scopes=["https://www.googleapis.com/auth/cloud-billing.readonly"],
            )
            credentials.refresh(GoogleAuthRequest())
            return {"Authorization": f"Bearer {credentials.token}"}, {}

        # api_key mode (default)
        if not config.api_key:
            logger.warning(
                "google_billing.api_key not configured — "
                "skipping Google billing API detection."
            )
            return {}, {}

        return {}, {"key": config.api_key}

    async def _fetch_skus(
        self,
        billing_account_id: str,
        headers: dict[str, str],
        key_param: dict[str, str],
    ) -> list[dict]:
        """Fetch AI-related SKUs from Cloud Billing API with pagination.

        Args:
            billing_account_id: Google billing account ID.
            headers: Auth headers.
            key_param: Query params for API key auth.

        Returns:
            List of SKU dicts whose service matches known AI service IDs.
        """
        import asyncio

        url = f"{self.BASE_URL}/services/-/skus"
        params: dict[str, Any] = {
            **key_param,
            "pageSize": 500,
        }

        all_skus: list[dict] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                resp = await client.get(url, headers=headers, params=params)

                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", "5"))
                    logger.warning(
                        "Google Billing API rate limited, retrying after %.1fs",
                        retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                resp.raise_for_status()
                payload = resp.json()

                for sku in payload.get("skus", []):
                    service_id = (
                        sku.get("category", {}).get("serviceDisplayName", "")
                    )
                    sku_service_name = sku.get("serviceProviderName", "")
                    # Check if the SKU belongs to a known AI service
                    resource_family = sku.get("category", {}).get("resourceFamily", "")
                    service_display = sku.get("category", {}).get("serviceDisplayName", "")
                    description = sku.get("description", "").lower()

                    # Match prefixes with both hyphens and spaces
                    # (SKU descriptions use spaces: "Gemini 1.5 Pro")
                    desc_normalized = description.replace("-", " ")
                    is_ai_sku = (
                        any(svc_id in str(sku) for svc_id in self.VERTEX_AI_SERVICE_IDS)
                        or "vertex ai" in service_display.lower()
                        or "generative" in service_display.lower()
                        or "cloud ai" in service_display.lower()
                        or any(
                            prefix in description or prefix.replace("-", " ") in desc_normalized
                            for prefix in self.GEMINI_MODEL_PREFIXES
                        )
                    )

                    if is_ai_sku:
                        all_skus.append(sku)

                next_page = payload.get("nextPageToken")
                if not next_page:
                    break

                params["pageToken"] = next_page
                await asyncio.sleep(0.2)  # Rate limit: 5 req/s

        return all_skus

    def _extract_model(self, sku: dict) -> str | None:
        """Extract a model name from a SKU description.

        Scans the SKU description for known model prefixes.

        Args:
            sku: A single SKU dict from the Cloud Billing API.

        Returns:
            Model name string or None if no known model found.
        """
        description = sku.get("description", "").lower()
        desc_normalized = description.replace("-", " ")

        for prefix in self.GEMINI_MODEL_PREFIXES:
            if prefix in description or prefix.replace("-", " ") in desc_normalized:
                return prefix

        # Try to detect from Vertex AI generic SKU descriptions
        if "vertex ai" in description or "generative" in description:
            # Return a generic model name for unrecognized Vertex AI SKUs
            return None

        return None


class _GoogleAuthUnavailable(Exception):
    """Raised when google-auth library is not installed."""


async def run_all_parsers(db_path: str, config: BurnLensConfig) -> None:
    """Run all provider billing parsers and upsert discovered ai_asset records.

    For each result returned by a provider parser:
    - If the asset (provider + model + endpoint) already exists, update last_active_at.
    - If it is new, insert with status=shadow and write a new_asset_detected event.

    Args:
        db_path: Path to the SQLite database.
        config: BurnLensConfig with admin key fields populated.
    """
    provider_results: list[tuple[str, list[dict]]] = []

    openai_data = await fetch_openai_usage(config.openai_admin_key)
    for item in openai_data:
        provider_results.append(("openai", [item]))

    anthropic_data = await fetch_anthropic_usage(config.anthropic_admin_key)
    for item in anthropic_data:
        provider_results.append(("anthropic", [item]))

    google_data = await fetch_google_usage()
    for item in google_data:
        provider_results.append(("google", [item]))

    # Google Cloud Billing API parser (richer discovery via billing SKUs)
    try:
        google_billing_data = await GoogleBillingParser().fetch_usage(config.google_billing)
        for item in google_billing_data:
            provider_results.append(("google", [item]))
    except Exception:
        logger.warning("Google billing parser failed — continuing with other providers", exc_info=True)

    for provider, result in provider_results:
        for item in result:
            model = item.get("model", "unknown")
            endpoint_url = _endpoint_url(provider)

            api_key_id = item.get("api_key_id")
            api_key_hash = (
                hashlib.sha256(api_key_id.encode()).hexdigest() if api_key_id else None
            )

            existing = await get_assets(db_path, provider=provider)
            match = next(
                (a for a in existing if a.model_name == model and a.endpoint_url == endpoint_url),
                None,
            )

            if match is None:
                asset = AiAsset(
                    provider=provider,
                    model_name=model,
                    endpoint_url=endpoint_url,
                    api_key_hash=api_key_hash,
                    status="shadow",
                )
                asset_id = await insert_asset(db_path, asset)

                event = DiscoveryEvent(
                    event_type="new_asset_detected",
                    asset_id=asset_id,
                    details={"provider": provider, "model": model, "source": "billing_api"},
                )
                await insert_discovery_event(db_path, event)

                logger.info("New shadow asset detected via billing API: %s / %s", provider, model)
            else:
                import aiosqlite
                now = datetime.now(timezone.utc).isoformat()
                async with aiosqlite.connect(db_path) as db:
                    await db.execute(
                        "UPDATE ai_assets SET last_active_at = ?, updated_at = ? WHERE id = ?",
                        (now, now, match.id),
                    )
                    await db.commit()


def _endpoint_url(provider: str) -> str:
    """Return the canonical API endpoint URL for a provider."""
    _URLS = dict(
        openai="https://api.openai.com",
        anthropic="https://api.anthropic.com",
        google="https://generativelanguage.googleapis.com",
        azure_openai="https://openai.azure.com",
        bedrock="https://bedrock-runtime.amazonaws.com",
        cohere="https://api.cohere.com",
        mistral="https://api.mistral.ai",
    )
    return _URLS.get(provider, f"https://{provider}.api")
