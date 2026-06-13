import json
import logging
import asyncio
from typing import Any, Optional

try:
    from aiokafka import AIOKafkaProducer
except ImportError:
    AIOKafkaProducer = None

from .config import settings

logger = logging.getLogger(__name__)

_producer: Optional[Any] = None
_producer_lock = asyncio.Lock()


async def get_streaming_producer() -> Optional[Any]:
    """Get or create the async Kafka/Redpanda producer (thread/task-safe)."""
    global _producer
    if AIOKafkaProducer is None:
        logger.warning("aiokafka is not installed. Streaming is disabled.")
        return None

    if _producer is None:
        async with _producer_lock:
            if _producer is None:
                try:
                    logger.info("Initializing AIOKafkaProducer connecting to %s...", settings.kafka_bootstrap_servers)
                    _producer = AIOKafkaProducer(
                        bootstrap_servers=settings.kafka_bootstrap_servers,
                        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                        retry_backoff_ms=500,
                        request_timeout_ms=5000,
                    )
                    await _producer.start()
                    logger.info("AIOKafkaProducer started successfully.")
                except Exception as e:
                    logger.error("Failed to start AIOKafkaProducer: %s", e)
                    _producer = None
                    raise
    return _producer


async def close_streaming_producer() -> None:
    """Close the streaming producer client."""
    global _producer
    async with _producer_lock:
        if _producer is not None:
            try:
                await _producer.stop()
                logger.info("AIOKafkaProducer stopped.")
            except Exception as e:
                logger.warning("Error stopping AIOKafkaProducer: %s", e)
            finally:
                _producer = None


async def send_records_to_stream(workspace_id: str, records: list[dict[str, Any]]) -> None:
    """Publish a batch of request records to Kafka/Redpanda topic."""
    if not records:
        return

    producer = await get_streaming_producer()
    if producer is None:
        logger.warning("Streaming producer is unavailable. Skipping stream write.")
        return

    # Ingest API receives records in the schema format:
    # timestamp, provider, model, input_tokens, output_tokens, etc.
    # We enrich them with workspace_id and serialize date/times to strings.
    tasks = []
    for record in records:
        # Format datetimes
        payload = {**record}
        payload["workspace_id"] = workspace_id
        
        # Serialize datetime keys to ISO strings if needed
        for k, v in payload.items():
            if hasattr(v, "isoformat"):
                payload[k] = v.isoformat()

        # Produce message to topic
        # Partitioning by workspace_id ensures all events for the same workspace land on the same partition,
        # preserving temporal order for window aggregations in downstream consumers.
        key_bytes = workspace_id.encode("utf-8") if workspace_id else None
        tasks.append(
            producer.send(
                settings.kafka_topic,
                value=payload,
                key=key_bytes,
            )
        )

    try:
        # Await the send futures in parallel to ensure they are queued
        await asyncio.gather(*tasks)
        logger.info("Successfully produced %d records to topic '%s' for workspace %s", len(records), settings.kafka_topic, workspace_id)
    except Exception as e:
        logger.error("Failed to produce records to stream: %s", e)
        raise
