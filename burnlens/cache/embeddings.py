"""Pluggable embedding service for generating query vectors."""
from __future__ import annotations

import logging
import os
import urllib.parse
import httpx

from burnlens.config import BurnLensConfig

logger = logging.getLogger(__name__)

async def get_embedding(
    text: str,
    config: BurnLensConfig,
    request_provider: str | None = None,
    request_headers: dict[str, str] | None = None,
    request_query: str | None = None,
) -> list[float]:
    """Generate embedding vector for text using the configured or auto-detected provider.

    Returns a list of floats representing the embedding vector.
    Raises ValueError or httpx.HTTPError if embedding fails.
    """
    # 1. Determine provider and model
    provider = config.cache.embedding.provider.lower()
    model = config.cache.embedding.model

    if provider == "auto":
        # Auto-detect based on incoming request provider first
        if request_provider in ("openai", "google", "ollama"):
            provider = request_provider
        elif os.environ.get("OPENAI_API_KEY") or config.openai_admin_key:
            provider = "openai"
        elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            provider = "google"
        else:
            # Fallback to local Ollama by default if environment variables are not set
            provider = "ollama"

    if provider == "openai":
        return await _get_openai_embedding(text, model, config, request_headers)
    elif provider == "google":
        return await _get_google_embedding(text, model, config, request_headers, request_query)
    elif provider == "ollama":
        return await _get_ollama_embedding(text, model)
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")

async def _get_openai_embedding(
    text: str,
    model: str,
    config: BurnLensConfig,
    request_headers: dict[str, str] | None = None,
) -> list[float]:
    # Resolve API Key
    api_key = None
    if request_headers:
        auth = request_headers.get("authorization") or request_headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            api_key = auth[7:].strip()
    
    if not api_key:
        api_key = config.openai_admin_key or os.environ.get("OPENAI_API_KEY")

    if not api_key:
        raise ValueError("OpenAI API Key is missing for embedding generation.")

    base_url = config.openai_upstream or "https://api.openai.com"
    url = f"{base_url.rstrip('/')}/v1/embeddings"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "input": text,
        "model": model,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=payload, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]

async def _get_google_embedding(
    text: str,
    model: str,
    config: BurnLensConfig,
    request_headers: dict[str, str] | None = None,
    request_query: str | None = None,
) -> list[float]:
    # Resolve API Key
    api_key = None
    if request_headers:
        api_key = request_headers.get("x-goog-api-key")
    
    if not api_key and request_query:
        # Parse query string to extract key
        params = urllib.parse.parse_qs(request_query)
        keys = params.get("key")
        if keys:
            api_key = keys[0]

    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    if not api_key:
        raise ValueError("Google Gemini API Key is missing for embedding generation.")

    # Google embedding uses text-embedding-004 model by default
    if model == "text-embedding-3-small":
        model = "text-embedding-004"

    base_url = config.google_upstream or "https://generativelanguage.googleapis.com"
    # Format model path: /v1beta/models/{model}:embedContent
    url = f"{base_url.rstrip('/')}/v1beta/models/{model}:embedContent"

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "content": {
            "parts": [{"text": text}]
        }
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=payload, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        return data["embedding"]["values"]

async def _get_ollama_embedding(
    text: str,
    model: str,
) -> list[float]:
    # Use standard local ollama url
    url = "http://localhost:11434/api/embeddings"
    
    # default local model if standard openai default is present
    if model == "text-embedding-3-small":
        model = "nomic-embed-text"

    payload = {
        "prompt": text,
        "model": model,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        return data["embedding"]
