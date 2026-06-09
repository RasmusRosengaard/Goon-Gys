"""Forced-alignment fallback for TTS providers that don't emit word boundaries.

Uses Whisper word-level timestamps to align generated audio against the KNOWN
script, so subtitles still match the exact spoken words. Requires
`openai-whisper` (+ ffmpeg). Only needed for cloud.py providers; edge-tts already
gives boundaries directly.
"""
from __future__ import annotations

from pathlib import Path

from ..models import WordTiming


def align(audio_path: Path, script: str, model: str = "base") -> list[WordTiming]:
    try:
        import whisper
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("install openai-whisper to use forced alignment") from e

    result = whisper.load_model(model).transcribe(
        str(audio_path), word_timestamps=True
    )
    timings: list[WordTiming] = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            timings.append(
                WordTiming(w["word"].strip(), round(w["start"], 3), round(w["end"], 3))
            )
    return timings
