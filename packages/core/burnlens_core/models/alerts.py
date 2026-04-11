"""Alert payload dataclasses for the BurnLens alert system."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from burnlens_core.models.records import AiAsset, DiscoveryEvent


@dataclass
class DiscoveryAlert:
    """Alert payload for shadow AI detection and discovery events."""

    alert_type: str          # e.g. "shadow_detected", "new_provider", "model_changed"
    asset: AiAsset           # The AI asset that triggered the alert
    event: DiscoveryEvent    # The discovery event that triggered the alert
    message: str             # Human-readable alert message


@dataclass
class SpendSpikeAlert:
    """Alert payload for unusual spend spikes on an AI asset."""

    asset: AiAsset           # The AI asset experiencing the spike
    current_spend: float     # Spend in the current period (USD)
    avg_spend: float         # Historical average spend (USD)
    spike_ratio: float       # current_spend / avg_spend
    period_days: int = 30    # Period length used to calculate spend


@dataclass
class DigestPayload:
    """Payload for periodic digest emails summarising AI asset activity."""

    subject: str                             # Email subject line
    items: list[dict]                        # List of digest items (arbitrary dicts)
    generated_at: datetime = field(default_factory=datetime.utcnow)
