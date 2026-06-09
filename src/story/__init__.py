"""Stage 1 — story sourcing.

Providers share one signature: `generate(theme, **opts) -> Story`. Pick one with
`get_provider(name)`. See claude.md section 4, Stage 1.
"""
from __future__ import annotations

from ..models import Story
from . import llm, reddit, hybrid

_PROVIDERS = {
    "reddit": reddit.generate,
    "llm": llm.generate,
    "hybrid": hybrid.generate,
}


def get_provider(name: str):
    if name not in _PROVIDERS:
        raise ValueError(
            f"unknown story source '{name}'. options: {', '.join(_PROVIDERS)}"
        )
    return _PROVIDERS[name]


def generate(source: str, theme: str, **opts) -> Story:
    return get_provider(source)(theme, **opts)


def generate_series(source: str, theme: str, parts: int, **opts) -> list[Story]:
    """N linked cliffhanger parts (parts<=1 -> one standalone story)."""
    from . import series

    return series.generate_series(source, theme, parts, **opts)
