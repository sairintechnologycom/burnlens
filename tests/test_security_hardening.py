"""Verification tests for security hardening fixes (Phase 2 & 3)."""
import pytest

from burnlens.storage.database import init_db
from burnlens.cache.manager import SemanticCacheManager
from burnlens_cloud.telemetry.forwarder import OtelForwarder
from burnlens.proxy.interceptor import _extract_tags

@pytest.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "test_security.db")
    await init_db(db_path)
    return db_path

# 2. SSRF Protection in OTEL Forwarder
def test_otel_forwarder_ssrf_protection():
    forwarder = OtelForwarder()
    
    # Invalid schemes
    assert forwarder._validate_endpoint("http://example.com") is False
    assert forwarder._validate_endpoint("ftp://example.com") is False
    
    # Private IPs
    assert forwarder._validate_endpoint("https://127.0.0.1/v1/traces") is False
    assert forwarder._validate_endpoint("https://10.0.0.1/v1/traces") is False
    assert forwarder._validate_endpoint("https://192.168.1.1/v1/traces") is False
    assert forwarder._validate_endpoint("https://localhost/v1/traces") is False
    
    # Metadata services
    assert forwarder._validate_endpoint("https://169.254.169.254/v1/traces") is False
    assert forwarder._validate_endpoint("https://metadata.google.internal/v1/traces") is False
    
    # Valid endpoint
    assert forwarder._validate_endpoint("https://otel.datadoghq.com/v1/traces") is True

# 3. Tag Allowlisting
def test_tag_allowlisting():
    headers = {
        "x-burnlens-tag-team": "engineering",
        "x-burnlens-tag-feature": "chat",
        "x-burnlens-tag-malicious": "evil_payload",
        "x-burnlens-tag-budget-bypass": "true"
    }
    
    tags = _extract_tags(headers)
    
    assert tags["team"] == "engineering"
    assert tags["feature"] == "chat"
    assert "malicious" not in tags
    assert "budget-bypass" not in tags
    assert "budget_bypass" not in tags

# 4. Semantic Cache Integrity
@pytest.mark.asyncio
async def test_semantic_cache_integrity(db):
    secret = "cache_secret"
    manager = SemanticCacheManager(db, secret_key=secret)
    
    system_hash = "sys_hash"
    query = "Hello"
    provider = "openai"
    model = "gpt-4"
    body = b'{"response": "Hi"}'
    embedding = [0.1, 0.2, 0.3]
    
    # Save with valid signature
    await manager.save(system_hash, query, provider, model, body, embedding)
    
    # Lookup should succeed
    res = await manager.lookup_exact(system_hash, query)
    assert res is not None
    assert res[0] == body
    
    # Manually tamper with the DB
    import aiosqlite
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "UPDATE semantic_cache SET response_body = ? WHERE system_prompt_hash = ?",
            (b'{"response": "EVIL"}', system_hash)
        )
        await conn.commit()
    
    # Lookup should now fail due to hash mismatch
    res = await manager.lookup_exact(system_hash, query)
    assert res is None

@pytest.mark.asyncio
async def test_semantic_cache_no_secret_hash_only(db):
    # Test that it still works with just hashes if no secret is provided
    manager = SemanticCacheManager(db, secret_key=None)
    
    system_hash = "sys_hash_2"
    query = "Hello 2"
    body = b'{"response": "Hi 2"}'
    embedding = [0.1, 0.2, 0.3]
    
    await manager.save(system_hash, query, "openai", "gpt-4", body, embedding)
    
    res = await manager.lookup_exact(system_hash, query)
    assert res is not None
    assert res[0] == body
    
    # Tamper
    import aiosqlite
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "UPDATE semantic_cache SET response_body = ? WHERE system_prompt_hash = ?",
            (b'{"response": "EVIL 2"}', system_hash)
        )
        await conn.commit()
        
    res = await manager.lookup_exact(system_hash, query)
    assert res is None
