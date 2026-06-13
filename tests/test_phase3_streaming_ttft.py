import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from burnlens.proxy.interceptor import handle_request
from burnlens.providers.base import Provider

@pytest.mark.asyncio
async def test_streaming_ttft_capture(tmp_path):
    db_path = str(tmp_path / "test.db")
    from burnlens.storage.database import init_db
    await init_db(db_path)

    # Mock provider
    provider = MagicMock(spec=Provider)
    provider.name = "openai"
    provider.upstream_base = "https://api.openai.com"
    provider.rewrite_path_for_routing.side_effect = lambda path, model: path

    # Mock client and response
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.build_request.side_effect = lambda method, url, headers, content: httpx.Request(
        method=method, url=url, headers=headers, content=content
    )
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.headers = httpx.Headers({"content-type": "text/event-stream"})
    
    # Simulated stream content yielding chunks with delay
    async def mock_aiter_bytes():
        await asyncio.sleep(0.05)  # Simulate 50ms network delay before first token
        yield b'data: {"id": "chatcmpl-123", "object": "chat.completion.chunk", "created": 1677652288, "model": "gpt-4o", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hello"}, "finish_reason": null}]}'
        yield b'\n\ndata: [DONE]\n\n'

    mock_response.aiter_bytes = mock_aiter_bytes
    mock_client.send.return_value = mock_response

    # Mock logging so we can inspect the generated RequestRecord
    records = []
    async def mock_log_record(db, record):
        records.append(record)

    with patch("burnlens.proxy.interceptor._log_record", mock_log_record):
        status, headers, body, stream = await handle_request(
            client=mock_client,
            provider=provider,
            path="/proxy/openai/v1/chat/completions",
            method="POST",
            headers={"Authorization": "Bearer sk-key"},
            body_bytes=b'{"model": "gpt-4o", "stream": true}',
            query_string="",
            db_path=db_path
        )
        
        # Consume the stream to trigger logging
        assert stream is not None
        async for _ in stream:
            pass
            
        await asyncio.sleep(0.05)

    # Verify that record was generated and ttft_ms is positive (> 40ms due to simulated sleep)
    assert len(records) == 1
    assert records[0].ttft_ms is not None
    assert records[0].ttft_ms >= 40.0
