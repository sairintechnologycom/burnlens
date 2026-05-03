"""BurnLens — See where your LLM money goes."""

__version__ = "1.1.0"

from burnlens.detection.wrapper import wrap  # noqa: F401  re-exported for `import burnlens; burnlens.wrap(client)`

__all__ = ["wrap"]
