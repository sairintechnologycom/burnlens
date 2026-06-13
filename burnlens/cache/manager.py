"""Semantic cache manager for exact match and cosine similarity matching."""
from __future__ import annotations

import json
import logging
import hashlib
import time
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Tuple
import aiosqlite

from burnlens.config import BurnLensConfig

logger = logging.getLogger(__name__)

def normalize_vector(v: list[float]) -> list[float]:
    """Normalize a vector to unit length so cosine similarity is a simple dot product."""
    if not v:
        return []
    sq_sum = sum(x * x for x in v)
    norm = sq_sum ** 0.5
    if norm == 0.0:
        return v
    return [x / norm for x in v]

def extract_query_text(body_bytes: bytes, provider_name: str) -> str:
    """Robustly extract the user query text from the request body."""
    if not body_bytes:
        return ""
    try:
        data = json.loads(body_bytes)
        if provider_name == "google":
            contents = data.get("contents") or []
            if contents:
                last_content = contents[-1]
                parts = last_content.get("parts") or []
                text_parts = []
                for part in parts:
                    if isinstance(part, dict) and "text" in part:
                        text_parts.append(part["text"])
                if text_parts:
                    return "".join(text_parts)
        else:
            messages = data.get("messages") or []
            # Look for the last user message
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content")
                    if isinstance(content, str):
                        return content
                    elif isinstance(content, list):
                        text_parts = []
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                text_parts.append(part.get("text", ""))
                        return "".join(text_parts)
            # If no user message, return the last message content
            if messages:
                content = messages[-1].get("content")
                if isinstance(content, str):
                    return content
    except Exception as exc:
        logger.debug("Failed to extract query text: %s", exc)
    return ""

class SemanticCacheManager:
    """Manages exact and semantic similarity cache lookup and persistence in SQLite."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def lookup_exact(
        self,
        system_prompt_hash: str,
        query_text: str,
        customer_hash: str | None = None,
    ) -> Tuple[bytes, str, str] | None:
        """Perform a fast exact case-insensitive match on the query text.

        Returns (response_body_bytes, provider, model) or None on miss.
        """
        sql = """
            SELECT response_body, provider, model FROM semantic_cache
            WHERE system_prompt_hash = ?
              AND LOWER(query_text) = LOWER(?)
              AND (customer_hash = ? OR (customer_hash IS NULL AND ? IS NULL))
              AND (expires_at IS NULL OR datetime(expires_at) > datetime('now'))
            LIMIT 1;
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(sql, (system_prompt_hash, query_text, customer_hash, customer_hash)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return row["response_body"], row["provider"], row["model"]
        except Exception as exc:
            logger.warning("Cache exact lookup failed (non-fatal): %s", exc)
        return None

    async def lookup_semantic(
        self,
        system_prompt_hash: str,
        query_text: str,
        query_embedding: list[float],
        customer_hash: str | None = None,
        similarity_threshold: float = 0.96,
    ) -> Tuple[bytes, str, str] | None:
        """Perform cosine similarity lookup over cached embeddings.

        Returns (response_body_bytes, provider, model) or None on miss.
        """
        sql = """
            SELECT response_body, embedding, provider, model FROM semantic_cache
            WHERE system_prompt_hash = ?
              AND (customer_hash = ? OR (customer_hash IS NULL AND ? IS NULL))
              AND (expires_at IS NULL OR datetime(expires_at) > datetime('now'));
        """
        try:
            query_norm = normalize_vector(query_embedding)
            if not query_norm:
                return None

            best_sim = -1.0
            best_row = None

            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(sql, (system_prompt_hash, customer_hash, customer_hash)) as cursor:
                    rows = await cursor.fetchall()

                    if rows:
                        try:
                            import numpy as np
                            embeddings_list = []
                            valid_rows = []
                            for row in rows:
                                try:
                                    embeddings_list.append(json.loads(row["embedding"]))
                                    valid_rows.append(row)
                                except Exception:
                                    continue
                            
                            if embeddings_list:
                                emb_matrix = np.array(embeddings_list, dtype=np.float32)
                                q_arr = np.array(query_norm, dtype=np.float32)
                                similarities = np.dot(emb_matrix, q_arr)
                                best_idx = np.argmax(similarities)
                                best_sim = float(similarities[best_idx])
                                best_row = valid_rows[best_idx]
                        except ImportError:
                            # Fallback to pure Python
                            for row in rows:
                                try:
                                    cached_emb = json.loads(row["embedding"])
                                    # Compute dot product (both vectors are normalized)
                                    sim = sum(q * c for q, c in zip(query_norm, cached_emb))
                                    if sim > best_sim:
                                        best_sim = sim
                                        best_row = row
                                except Exception:
                                    continue

            if best_sim >= similarity_threshold and best_row is not None:
                logger.info("Semantic cache hit! Similarity: %.4f (threshold: %.4f)", best_sim, similarity_threshold)
                return best_row["response_body"], best_row["provider"], best_row["model"]

        except Exception as exc:
            logger.warning("Cache semantic lookup failed (non-fatal): %s", exc)
        return None

    async def save(
        self,
        system_prompt_hash: str,
        query_text: str,
        provider: str,
        model: str,
        response_body: bytes,
        embedding: list[float],
        customer_hash: str | None = None,
        tags: dict[str, str] | None = None,
        ttl_seconds: int = 86400,
    ) -> None:
        """Save a new request-response pair and its normalized embedding to the cache."""
        sql = """
            INSERT OR REPLACE INTO semantic_cache (
                id, system_prompt_hash, query_text, provider, model,
                response_body, embedding, customer_hash, tags, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        try:
            # Generate stable ID from hash of inputs to ensure uniqueness
            inputs = f"{system_prompt_hash}:{customer_hash or ''}:{query_text.lower()}"
            cache_id = hashlib.sha256(inputs.encode()).hexdigest()

            # Normalize embedding before saving
            normalized_emb = normalize_vector(embedding)
            embedding_json = json.dumps(normalized_emb)

            expires_at = None
            if ttl_seconds:
                expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()

            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    sql,
                    (
                        cache_id,
                        system_prompt_hash,
                        query_text,
                        provider,
                        model,
                        response_body,
                        embedding_json,
                        customer_hash,
                        json.dumps(tags or {}),
                        expires_at,
                    ),
                )
                await db.commit()
        except Exception as exc:
            logger.warning("Failed to save to semantic cache (non-fatal): %s", exc)

async def reconstruct_streaming_chunks(
    provider_name: str,
    response_body: bytes,
) -> AsyncIterator[bytes]:
    """Reconstruct chunked Server-Sent Events (SSE) stream from cached complete JSON response."""
    try:
        data = json.loads(response_body)
    except Exception as exc:
        logger.warning("Failed to parse cached response for stream reconstruction: %s", exc)
        yield response_body
        return

    if provider_name == "openai":
        cid = data.get("id", "chatcmpl-cached")
        model = data.get("model", "cached-model")
        created = data.get("created", int(time.time()))
        
        choices = data.get("choices") or []
        content = ""
        if choices:
            content = choices[0].get("message", {}).get("content", "")

        # Yield role chunk
        chunk_role = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(chunk_role)}\n\n".encode()

        # Yield content chunk
        if content:
            chunk_content = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk_content)}\n\n".encode()

        # Yield finish_reason chunk
        chunk_stop = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(chunk_stop)}\n\n".encode()
        yield b"data: [DONE]\n\n"

    elif provider_name == "anthropic":
        msg_id = data.get("id", "msg_cached")
        model = data.get("model", "cached-model")
        
        content = ""
        contents = data.get("content") or []
        for part in contents:
            if isinstance(part, dict) and part.get("type") == "text":
                content = part.get("text", "")
                break

        # Yield message_start
        chunk_msg_start = {
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": model,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        }
        yield f"event: message_start\ndata: {json.dumps(chunk_msg_start)}\n\n".encode()

        # Yield content_block_start
        chunk_block_start = {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }
        yield f"event: content_block_start\ndata: {json.dumps(chunk_block_start)}\n\n".encode()

        # Yield content_block_delta
        if content:
            chunk_block_delta = {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": content},
            }
            yield f"event: content_block_delta\ndata: {json.dumps(chunk_block_delta)}\n\n".encode()

        # Yield content_block_stop
        chunk_block_stop = {
            "type": "content_block_stop",
            "index": 0,
        }
        yield f"event: content_block_stop\ndata: {json.dumps(chunk_block_stop)}\n\n".encode()

        # Yield message_delta
        chunk_msg_delta = {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": data.get("usage", {}).get("output_tokens", 0)},
        }
        yield f"event: message_delta\ndata: {json.dumps(chunk_msg_delta)}\n\n".encode()

        # Yield message_stop
        chunk_msg_stop = {
            "type": "message_stop",
        }
        yield f"event: message_stop\ndata: {json.dumps(chunk_msg_stop)}\n\n".encode()

    elif provider_name == "google":
        content = ""
        candidates = data.get("candidates") or []
        if candidates:
            parts = candidates[0].get("content", {}).get("parts") or []
            if parts:
                content = parts[0].get("text", "")

        chunk = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": content}]
                    },
                    "finishReason": "STOP",
                }
            ]
        }
        yield f"data: {json.dumps(chunk)}\n\n".encode()

    else:
        # Fallback for unknown provider
        yield response_body


def reconstruct_complete_response_from_chunks(provider_name: str, chunks: list[str]) -> bytes:
    """Aggregate SSE delta payloads to reconstruct a complete non-streaming response body."""
    full_content = ""
    for chunk_line in chunks:
        chunk_line = chunk_line.strip()
        if not chunk_line.startswith("data:"):
            continue
        payload = chunk_line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
            if provider_name == "openai":
                choices = data.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content", "")
                    if content:
                        full_content += content
            elif provider_name == "anthropic":
                # Anthropic streaming payload can be message_start, content_block_delta, content_block_stop, etc.
                # The text delta is in data["delta"]["text"] for content_block_delta type
                event_type = data.get("type")
                if event_type == "content_block_delta":
                    delta = data.get("delta") or {}
                    text = delta.get("text", "")
                    if text:
                        full_content += text
            elif provider_name == "google":
                candidates = data.get("candidates") or []
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts") or []
                    if parts:
                        text = parts[0].get("text", "")
                        if text:
                            full_content += text
        except Exception:
            pass

    # Now construct the complete response object
    if provider_name == "openai":
        res = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": full_content
                    }
                }
            ]
        }
        return json.dumps(res).encode()
    elif provider_name == "anthropic":
        res = {
            "content": [
                {
                    "type": "text",
                    "text": full_content
                }
            ]
        }
        return json.dumps(res).encode()
    elif provider_name == "google":
        res = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": full_content
                            }
                        ]
                    }
                }
            ]
        }
        return json.dumps(res).encode()
    
    return b""
