"""BurnLens — See where your LLM money goes."""

__version__ = "0.3.1"

from burnlens.detection.wrapper import wrap  # noqa: F401  re-exported for `import burnlens; burnlens.wrap(client)`

__all__ = ["wrap"]
