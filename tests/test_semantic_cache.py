"""Unit and integration tests for Phase 7 Semantic Cache MVP."""
from __future__ import annotations

import asyncio
import json
import httpx
import pytest
import respx

from burnlens.config import BurnLensConfig, CacheConfig, CacheEmbeddingConfig
from burnlens.cache.manager import (
    normalize_vector,
    extract_query_text,
    reconstruct_complete_response_from_chunks,
    reconstruct_streaming_chunks,
    SemanticCacheManager,
)
from burnlens.proxy.interceptor import handle_request, _request_is_cacheable
from burnlens.providers.openai import openai_provider
from burnlens.storage.database import init_db, insert_request
from burnlens.storage.models import RequestRecord
from burnlens.storage.queries import get_recent_requests, get_cache_savings


def test_normalize_vector():
    """Verify that normalize_vector correctly scales vectors to unit length."""
    assert normalize_vector([]) == []
    assert normalize_vector([0.0, 0.0]) == [0.0, 0.0]
    
    v = [3.0, 4.0]
    norm_v = normalize_vector(v)
    assert abs(norm_v[0] - 0.6) < 1e-6
    assert abs(norm_v[1] - 0.8) < 1e-6
    # Magnitude should be 1.0
    assert abs(sum(x * x for x in norm_v) - 1.0) < 1e-6


def test_extract_query_text():
    """Test user query extraction from different providers' formats."""
    # OpenAI format
    openai_body = json.dumps({
        "messages": [
            {"role": "system", "content": "You are a helper."},
            {"role": "user", "content": "What is 2+2?"}
        ]
    }).encode()
    assert extract_query_text(openai_body, "openai") == "What is 2+2?"

    # Google Gemini format
    google_body = json.dumps({
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Hello Gemini!"}]
            }
        ]
    }).encode()
    assert extract_query_text(google_body, "google") == "Hello Gemini!"


def test_reconstruct_complete_response_from_chunks():
    """Test aggregating streaming chunks to a complete JSON object."""
    # OpenAI chunks
    chunks = [
        'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant"}}]}\n\n',
        'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"Hello "}}]}\n\n',
        'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"world!"}}]}\n\n',
        "data: [DONE]\n\n",
    ]
    res_bytes = reconstruct_complete_response_from_chunks("openai", chunks)
    res = json.loads(res_bytes)
    assert res["choices"][0]["message"]["content"] == "Hello world!"


@pytest.mark.asyncio
async def test_reconstruct_streaming_chunks():
    """Test generating SSE stream chunks from complete JSON response."""
    cached_openai_res = json.dumps({
        "id": "chatcmpl-123",
        "model": "gpt-4o",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Cached Hello!"
                }
            }
        ]
    }).encode()

    chunks = []
    async for chunk in reconstruct_streaming_chunks("openai", cached_openai_res):
        chunks.append(chunk.decode())

    assert len(chunks) == 4
    assert "assistant" in chunks[0]
    assert "Cached Hello!" in chunks[1]
    assert "stop" in chunks[2]
    assert "[DONE]" in chunks[3]


@pytest.mark.asyncio
async def test_semantic_cache_manager_database_ops(tmp_path):
    """Verify SemanticCacheManager lookup and save database actions."""
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)

    cache_manager = SemanticCacheManager(db_path)
    
    # Check miss on empty DB
    exact_res = await cache_manager.lookup_exact("system_hash", "hi there")
    assert exact_res is None

    # Save cache entry
    response_body = b'{"result": "cached"}'
    embedding = [1.0, 0.0, 0.0]
    await cache_manager.save(
        system_prompt_hash="system_hash",
        query_text="hi there",
        provider="openai",
        model="gpt-4",
        response_body=response_body,
        embedding=embedding,
        customer_hash="cust_123",
        tags={"team": "dev"},
        ttl_seconds=100
    )

    # 1. Exact Match Lookup
    exact_res = await cache_manager.lookup_exact("system_hash", "hi there", "cust_123")
    assert exact_res is not None
    assert exact_res[0] == response_body
    assert exact_res[1] == "openai"
    assert exact_res[2] == "gpt-4"

    # Exact Match case-insensitive
    exact_res_upper = await cache_manager.lookup_exact("system_hash", "HI THERE", "cust_123")
    assert exact_res_upper is not None
    assert exact_res_upper[0] == response_body

    # Exact Match miss on wrong customer
    exact_res_wrong_cust = await cache_manager.lookup_exact("system_hash", "hi there", "other_cust")
    assert exact_res_wrong_cust is None

    # 2. Semantic Match Lookup
    # A vector close to [1.0, 0.0, 0.0]
    close_embedding = [0.99, 0.1, 0.0]
    sem_res = await cache_manager.lookup_semantic(
        system_prompt_hash="system_hash",
        query_text="hello there",
        query_embedding=close_embedding,
        customer_hash="cust_123",
        similarity_threshold=0.95,
    )
    assert sem_res is not None
    assert sem_res[0] == response_body

    # Semantic Match miss on low similarity
    far_embedding = [0.0, 1.0, 0.0]
    sem_res_miss = await cache_manager.lookup_semantic(
        system_prompt_hash="system_hash",
        query_text="far query",
        query_embedding=far_embedding,
        customer_hash="cust_123",
        similarity_threshold=0.95,
    )
    assert sem_res_miss is None


def test_request_is_cacheable_temperature():
    """Sampled requests (explicit temperature > 0) must not be cached."""
    base = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
    # No temperature → cacheable (deterministic-by-default assumption)
    assert _request_is_cacheable(json.dumps(base).encode()) is True
    # temperature 0 → cacheable
    assert _request_is_cacheable(json.dumps({**base, "temperature": 0}).encode()) is True
    # temperature > 0 → NOT cacheable
    assert _request_is_cacheable(json.dumps({**base, "temperature": 0.7}).encode()) is False
    assert _request_is_cacheable(json.dumps({**base, "temperature": 1}).encode()) is False
    # bool is not a temperature
    assert _request_is_cacheable(json.dumps({**base, "temperature": True}).encode()) is True
    # Garbage / empty body → cacheable (fail-open, matches other cache guards)
    assert _request_is_cacheable(b"not json") is True
    assert _request_is_cacheable(None) is True


@pytest.mark.asyncio
async def test_get_cache_savings(tmp_path):
    """get_cache_savings sums cache_saved_usd and counts cache hits."""
    db_path = str(tmp_path / "savings.db")
    await init_db(db_path)

    # Empty DB
    assert await get_cache_savings(db_path) == (0.0, 0)

    # A normal (non-hit) request contributes nothing
    await insert_request(db_path, RequestRecord(
        provider="openai", model="gpt-4o", request_path="/x", cost_usd=0.5,
    ))
    # Two cache hits with savings
    for saved in (0.10, 0.25):
        await insert_request(db_path, RequestRecord(
            provider="openai", model="gpt-4o", request_path="/x",
            cost_usd=0.0, cache_hit=1, cache_saved_usd=saved,
        ))

    total, hits = await get_cache_savings(db_path)
    assert hits == 2
    assert abs(total - 0.35) < 1e-9


@pytest.mark.asyncio
@respx.mock
async def test_semantic_cache_proxy_integration(tmp_path):
    """End-to-end integration test for the proxy semantic cache pipeline."""
    db_path = str(tmp_path / "test_proxy.db")
    await init_db(db_path)

    # Setup configuration with cache enabled
    config = BurnLensConfig(
        db_path=db_path,
        cache=CacheConfig(
            enabled=True,
            similarity_threshold=0.95,
            ttl_seconds=3600,
            embedding=CacheEmbeddingConfig(
                provider="openai",
                model="text-embedding-3-small"
            )
        )
    )

    # Mock OpenAI embeddings call
    embed_route = respx.post("https://api.openai.com/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.6, 0.8, 0.0]}]})
    )

    # Mock OpenAI Chat completions call
    openai_res = {
        "id": "chatcmpl-upstream",
        "object": "chat.completion",
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Upstream response!"},
                "finish_reason": "stop"
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25}
    }
    chat_route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=openai_res)
    )

    client = httpx.AsyncClient()
    headers = {
        "Authorization": "Bearer sk-proj-12345",
        "Content-Type": "application/json",
        "x-burnlens-tag-customer": "test-client",
    }
    body = json.dumps({
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "What is the capital of France?"}
        ]
    }).encode()

    # --- 1. Cache Miss ---
    status, resp_headers, resp_body, stream_iter = await handle_request(
        client=client,
        provider=openai_provider,
        path="/proxy/openai/v1/chat/completions",
        method="POST",
        headers=headers,
        body_bytes=body,
        query_string="",
        db_path=db_path,
        config=config,
    )

    assert status == 200
    assert json.loads(resp_body)["choices"][0]["message"]["content"] == "Upstream response!"
    assert chat_route.call_count == 1
    
    # Flush background tasks to allow embedding call and cache save
    for _ in range(10):
        await asyncio.sleep(0.05)

    assert embed_route.call_count == 2

    # Check database: first request record has cache_hit = 0
    records = await get_recent_requests(db_path, limit=5)
    assert len(records) == 1
    assert records[0]["cache_hit"] == 0

    # --- 2. Cache Hit (Exact Match) ---
    chat_route.reset()  # Reset upstream mock to confirm no request is sent
    embed_route.reset()

    status2, resp_headers2, resp_body2, stream_iter2 = await handle_request(
        client=client,
        provider=openai_provider,
        path="/proxy/openai/v1/chat/completions",
        method="POST",
        headers=headers,
        body_bytes=body,
        query_string="",
        db_path=db_path,
        config=config,
    )

    assert status2 == 200
    assert json.loads(resp_body2)["choices"][0]["message"]["content"] == "Upstream response!"
    assert chat_route.call_count == 0  # Bypassed upstream!
    assert embed_route.call_count == 0  # Stage 1 exact match (no embedding call!)

    for _ in range(10):
        await asyncio.sleep(0.05)

    # Verify requests database log for cache hit
    records = await get_recent_requests(db_path, limit=5)
    assert len(records) == 2
    # The most recent record (index 0) should be the cache hit
    assert records[0]["cache_hit"] == 1
    assert records[0]["cost_usd"] == 0.0
    assert records[0]["cache_saved_usd"] > 0.0

    # --- 3. Cache Bypass (Cache-Control: no-cache) ---
    chat_route.reset()
    embed_route.reset()
    bypass_headers = headers.copy()
    bypass_headers["Cache-Control"] = "no-cache"

    status3, resp_headers3, resp_body3, stream_iter3 = await handle_request(
        client=client,
        provider=openai_provider,
        path="/proxy/openai/v1/chat/completions",
        method="POST",
        headers=bypass_headers,
        body_bytes=body,
        query_string="",
        db_path=db_path,
        config=config,
    )

    assert status3 == 200
    assert chat_route.call_count == 1  # Upstream hit since cache bypassed!
