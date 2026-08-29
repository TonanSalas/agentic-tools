"""Weekly-activity gathering, split by concern.

Submodules are imported for their side-effect-free namespaces so callers and
tests can reach them as `activity.gh`, `activity.collect`, and so on.
"""

from . import (
    assemble, cache, cli, collect, config, dates, discovery, gh, parsing, render,
)

__all__ = [
    "assemble", "cache", "cli", "collect", "config",
    "dates", "discovery", "gh", "parsing", "render",
]
