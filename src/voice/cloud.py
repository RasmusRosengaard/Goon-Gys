"""Optional cloud TTS providers (ElevenLabs, OpenAI).

Stubs to wire up when you want premium voices. These engines do NOT return word
boundaries, so after synthesizing you must run Stage-2 forced alignment
(src/voice/align.py) over the audio + known script to produce WordTimings.

To enable: implement synthesize(), then register it in src/voice/__init__.py:
    from . import cloud
    _PROVIDERS["elevenlabs"] = cloud.elevenlabs
    _PROVIDERS["openai"] = cloud.openai
"""
from __future__ import annotations

from pathlib import Path

from ..models import WordTiming


def elevenlabs(text: str, voice: str, out_path: Path) -> tuple[Path, list[WordTiming]]:
    raise NotImplementedError(
        "ElevenLabs provider not implemented yet. Synthesize audio, then call "
        "voice.align.align(out_path, text) for word timings."
    )


def openai(text: str, voice: str, out_path: Path) -> tuple[Path, list[WordTiming]]:
    raise NotImplementedError(
        "OpenAI TTS provider not implemented yet. Synthesize audio, then call "
        "voice.align.align(out_path, text) for word timings."
    )
