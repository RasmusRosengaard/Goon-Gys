"""Composite the final Short with ffmpeg.

Loops a background clip to the voiceover length, scales+crops to 1080x1920, replaces
the gameplay audio with the voiceover, and burns in the subtitle file.

Background start offset (see claude.md 4b):
- standalone / first part: a RANDOM offset into the clip (`random_start=True`).
- later series parts: pass `start_offset` so the footage CONTINUES exactly where the
  previous part ended, keeping the gameplay seamless across the series.

`assemble` returns the clip + start + duration it used so the caller can chain parts.
Requires `ffmpeg` and `ffprobe` on PATH.
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

from .. import config


def _require(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise RuntimeError(f"{tool} not found on PATH — install ffmpeg")
    return path


def pick_background(category: str) -> Path:
    folder = config.BACKGROUND_DIR / category
    clips = sorted(p for p in folder.glob("*.mp4") if p.stat().st_size > 0)
    if not clips:
        raise RuntimeError(f"no usable .mp4 clips in {folder}")
    return random.choice(clips)


def media_duration(path: Path) -> float:
    """Container duration in seconds (works for audio and video)."""
    out = subprocess.run(
        [
            _require("ffprobe"), "-v", "error", "-show_entries",
            "format=duration", "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


# backwards-compatible alias
audio_duration = media_duration


def assemble(
    audio_path: Path,
    subtitles_path: Path,
    out_path: Path,
    *,
    background_category: str,
    background_clip: Path | None = None,
    start_offset: float | None = None,
    random_start: bool = False,
) -> dict:
    """Render the Short. Returns {clip, start, duration, clip_duration}.

    Offset resolution:
    - start_offset given      -> used as-is (wrapped within the clip length).
    - else random_start=True  -> random offset leaving room for the whole voiceover.
    - else                    -> 0.0.
    """
    ffmpeg = _require("ffmpeg")
    audio_path = Path(audio_path)
    subtitles_path = Path(subtitles_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bg = Path(background_clip) if background_clip else pick_background(background_category)
    clip_dur = media_duration(bg)
    duration = media_duration(audio_path)

    if start_offset is not None:
        start = start_offset % clip_dur if clip_dur > 0 else 0.0
    elif random_start:
        start = random.uniform(0.0, max(0.0, clip_dur - duration))
    else:
        start = 0.0

    # Run with cwd = subtitles folder so the ass filter takes a bare filename,
    # sidestepping Windows drive-colon escaping inside filtergraphs.
    subs_dir = subtitles_path.parent
    subs_name = subtitles_path.name
    vf = (
        f"scale={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT},"
        f"ass={subs_name}"
    )

    cmd = [ffmpeg, "-y", "-stream_loop", "-1"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]      # input seek, applied before the loop wraps
    cmd += [
        "-i", str(bg.resolve()),
        "-i", str(audio_path.resolve()),
        "-t", f"{duration:.3f}",
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        str(out_path.resolve()),
    ]
    subprocess.run(cmd, cwd=str(subs_dir), check=True)
    return {
        "clip": str(bg.resolve()),
        "start": round(start, 3),
        "duration": round(duration, 3),
        "clip_duration": round(clip_dur, 3),
    }
