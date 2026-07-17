"""BurnLens — See where your LLM money goes."""

__version__ = "1.8.1"

from burnlens.detection.wrapper import wrap  # noqa: F401  re-exported for `import burnlens; burnlens.wrap(client)`

__all__ = ["wrap"]
