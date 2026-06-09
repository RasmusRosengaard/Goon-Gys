"""Stage 2 — voiceover.

Providers share one signature:
    synthesize(text, voice, out_path) -> (audio_path, list[WordTiming])

The word timings are what make subtitles exactly match the spoken words. edge-tts
emits them natively; providers that can't must run forced alignment (see align.py).
See claude.md section 4, Stage 2.
"""
from __future__ import annotations

from pathlib import Path

from ..models import WordTiming
from . import edge

_PROVIDERS = {
    "edge": edge.synthesize,
    "edge-tts": edge.synthesize,
}


def get_provider(name: str):
    # provider key is the part before the first '/', e.g. "edge" in "edge/en-US-GuyNeural"
    key = name.split("/", 1)[0] if "/" in name else name
    if key in _PROVIDERS:
        return _PROVIDERS[key]
    # Bare voice ids like "en-US-GuyNeural" default to edge.
    if key.startswith("en-") or key.startswith("edge"):
        return edge.synthesize
    raise ValueError(f"unknown voice provider '{name}'. installed: {sorted(_PROVIDERS)}")


def synthesize(text: str, voice: str, out_path: Path) -> tuple[Path, list[WordTiming]]:
    return get_provider(voice)(text, voice, out_path)
