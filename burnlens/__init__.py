"""BurnLens — See where your LLM money goes."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    # Read from installed package metadata rather than a hand-maintained
    # literal — this had silently drifted three releases behind pyproject.
    __version__ = _pkg_version("burnlens")
except PackageNotFoundError:  # running from a source tree, not installed
    __version__ = "0.0.0+unknown"

from burnlens.detection.wrapper import wrap  # noqa: F401  re-exported for `import burnlens; burnlens.wrap(client)`

__all__ = ["wrap"]
