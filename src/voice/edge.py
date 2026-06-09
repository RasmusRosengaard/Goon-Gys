"""Default TTS: Microsoft Edge neural voices via `edge-tts` (free, no key).

Streams audio while collecting `WordBoundary` events, which give exact per-word
timings — so subtitles match the spoken words with zero extra alignment work.

The script is split on blank lines into segments (e.g. the suggestive tease vs. the
story). Each segment is synthesized separately, its edge-tts silence PADDING is trimmed
(otherwise the tease's trailing silence + the story's leading silence stack up into a
long dead gap), and the segments are joined with a small silence GAP so there is a tight
audible beat between the tease and the story and captions never span the boundary. Word
timings are offset cumulatively (accounting for the trim) and tagged with their segment.
Joining/trimming uses ffmpeg when available; otherwise it falls back to a gapless concat.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from pathlib import Path

from ..models import WordTiming

# Small audible beat inserted between segments (e.g. tease -> story), in milliseconds.
# Kept short because the bloated silence it used to fight is now trimmed away below.
GAP_MS = 150
# Hairs of silence kept around each trimmed segment so the first/last word isn't clipped.
LEAD_PAD = 0.04
TAIL_PAD = 0.08
_ANULLSRC_RATE = 24000  # edge-tts mp3 is 24 kHz mono


def _voice_name(voice: str) -> str:
    # accept "edge/en-US-GuyNeural" or a bare "en-US-GuyNeural"
    return voice.split("/", 1)[1] if voice.startswith("edge") and "/" in voice else voice


def _split_segments(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"\n\s*\n", text.strip()) if s.strip()]


async def _run(text: str, voice: str, out_path: Path) -> list[WordTiming]:
    import edge_tts

    # edge-tts >=7 defaults boundary to SentenceBoundary; we need per-WORD events.
    communicate = edge_tts.Communicate(text, _voice_name(voice), boundary="WordBoundary")
    timings: list[WordTiming] = []
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7          # 100ns units -> seconds
                end = start + chunk["duration"] / 1e7
                timings.append(WordTiming(chunk["text"], round(start, 3), round(end, 3)))
    return timings


def _probe_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def _join(
    seg_paths: list[Path],
    trims: list[tuple[float, float]],
    gap_ms: int,
    out_path: Path,
) -> None:
    """Concatenate segments, trimming each to its kept [start, end] window (which strips
    edge-tts's silence padding) and inserting gap_ms of real silence between them."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or len(seg_paths) == 1:
        # gapless fallback: mp3 frames concatenate fine for playback (no trim possible)
        with open(out_path, "wb") as o:
            for p in seg_paths:
                o.write(Path(p).read_bytes())
        return

    inputs: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    idx = 0
    for i, p in enumerate(seg_paths):
        inputs += ["-i", str(Path(p).resolve())]
        start, end = trims[i]
        filters.append(
            f"[{idx}:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{i}]"
        )
        labels.append(f"[a{i}]")
        idx += 1
        if gap_ms > 0 and i != len(seg_paths) - 1:  # silence between, not after the last
            inputs += ["-f", "lavfi", "-t", f"{gap_ms / 1000.0}",
                       "-i", f"anullsrc=r={_ANULLSRC_RATE}:cl=mono"]
            labels.append(f"[{idx}:a]")
            idx += 1
    filt = ";".join(filters) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]"
    cmd = [ffmpeg, "-y", *inputs, "-filter_complex", filt, "-map", "[out]",
           str(Path(out_path).resolve())]
    subprocess.run(cmd, check=True, capture_output=True)


def synthesize(
    text: str, voice: str, out_path: Path, *, gap_ms: int = GAP_MS
) -> tuple[Path, list[WordTiming]]:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    segments = _split_segments(text)

    if len(segments) <= 1:
        timings = asyncio.run(_run(text, voice, out_path))
        if not timings:
            raise RuntimeError("edge-tts returned no word boundaries — check the voice id")
        return out_path, timings

    # Trimming + real silence both need ffmpeg; without it keep the old gapless behaviour.
    have_ffmpeg = bool(shutil.which("ffmpeg"))
    effective_gap = gap_ms if have_ffmpeg else 0
    seg_paths: list[Path] = []
    trims: list[tuple[float, float]] = []
    all_timings: list[WordTiming] = []
    cumulative = 0.0
    for i, seg in enumerate(segments):
        seg_path = out_path.parent / f"_seg{i}.mp3"
        t = asyncio.run(_run(seg, voice, seg_path))
        if not t:
            raise RuntimeError("edge-tts returned no word boundaries — check the voice id")
        dur = _probe_duration(seg_path)
        if have_ffmpeg:
            # Drop edge-tts's silence padding, keeping only a hair around the speech.
            keep_start = max(0.0, t[0].start - LEAD_PAD)
            keep_end = t[-1].end + TAIL_PAD
            if dur is not None:
                keep_end = min(keep_end, dur)
        else:
            keep_start, keep_end = 0.0, (dur if dur is not None else t[-1].end)
        trims.append((keep_start, keep_end))
        for b in t:
            all_timings.append(
                WordTiming(b.word, round(b.start - keep_start + cumulative, 3),
                           round(b.end - keep_start + cumulative, 3), segment=i)
            )
        seg_paths.append(seg_path)
        cumulative += (keep_end - keep_start)
        if i != len(segments) - 1:
            cumulative += effective_gap / 1000.0

    _join(seg_paths, trims, effective_gap, out_path)
    for sp in seg_paths:
        try:
            sp.unlink()
        except OSError:
            pass
    return out_path, all_timings
