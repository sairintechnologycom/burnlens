"""Alert payload dataclasses for BurnLens Phase 4 alert system."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from burnlens.storage.models import AiAsset, DiscoveryEvent


@dataclass
class DiscoveryAlert:
    """Alert payload for shadow AI detection and discovery events.

    Used for real-time alerts when a new shadow asset, provider change,
    or model change is detected.
    """

    alert_type: str
    asset: AiAsset
    event: DiscoveryEvent
    message: str


@dataclass
class SpendSpikeAlert:
    """Alert payload for unusual spend spikes on an AI asset.

    Fired when current spend significantly exceeds historical average.
    """

    asset: AiAsset
    current_spend: float
    avg_spend: float
    spike_ratio: float
    period_days: int = 30


@dataclass
class DigestPayload:
    """Payload for periodic digest emails summarising AI asset activity.

    Aggregates multiple alert items into a single email digest.
    """

    subject: str
    items: list[dict] = field(default_factory=list)
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
