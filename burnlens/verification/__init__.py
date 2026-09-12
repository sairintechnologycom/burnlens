"""Phase 8: BL-AE-008 Verified Savings.

Proves whether executed recommendations produced real economic value and preserved outcome quality.
"""
from __future__ import annotations

from burnlens.verification.engine import SavingsVerificationEngine
from burnlens.verification.models import (
    BaselineSnapshot,
    SavingsVerificationRecord,
    VerificationVerdict,
)
from burnlens.verification.storage import VerificationStorage

__all__ = [
    "BaselineSnapshot",
    "SavingsVerificationEngine",
    "SavingsVerificationRecord",
    "VerificationStorage",
    "VerificationVerdict",
]
