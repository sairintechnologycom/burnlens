"""Waste detectors — re-exported from burnlens_core."""
from burnlens_core.analysis.waste import (  # noqa: F401
    ContextBloatDetector,
    DuplicateRequestDetector,
    ModelOverkillDetector,
    SystemPromptWasteDetector,
    WasteFinding,
    run_all_detectors,
)
