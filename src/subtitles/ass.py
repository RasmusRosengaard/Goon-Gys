"""Generate an .ass subtitle file from word timings.

One word is shown on screen at a time (the classic Shorts look): each word pops in at
its spoken moment, fills with the highlight colour over the time it is spoken (ASS
`\\kf` karaoke), then holds until the next word appears so there is no blank flicker in
the gaps. Because timings come from the same words TTS spoke, captions are exactly
synced and never paraphrased. Centered, large, high-contrast, safe-area aware for
1080x1920.
"""
from __future__ import annotations

from pathlib import Path

from .. import config
from ..models import WordTiming

# Colours are ASS BGR with alpha: &HAABBGGRR.
_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,96,&H0000FFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,3,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    cs = int(round((s - int(s)) * 100))
    return f"{int(h)}:{int(m):02d}:{int(s):02d}.{cs:02d}"


def _group(timings: list[WordTiming], max_words: int) -> list[list[WordTiming]]:
    """Chunk words into caption lines of up to max_words, starting a NEW line whenever
    the segment changes so a tease never shares a caption with the story."""
    groups: list[list[WordTiming]] = []
    cur: list[WordTiming] = []
    for t in timings:
        if cur and (len(cur) >= max_words or cur[-1].segment != t.segment):
            groups.append(cur)
            cur = []
        cur.append(t)
    if cur:
        groups.append(cur)
    return groups


def write_ass(
    timings: list[WordTiming],
    out_path: Path,
    *,
    max_words_per_line: int = 1,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    groups = _group(timings, max_words_per_line)
    lines = [_HEADER.format(w=config.VIDEO_WIDTH, h=config.VIDEO_HEIGHT)]
    for i, group in enumerate(groups):
        start = group[0].start
        # Hold the caption on screen until the next one pops in (so the small gaps
        # between words don't flash blank). Across a segment change (tease -> story)
        # let it clear at its own end instead, preserving that deliberate pause.
        end = group[-1].end
        if i + 1 < len(groups) and groups[i + 1][0].segment == group[-1].segment:
            end = max(end, groups[i + 1][0].start)
        chunks = []
        for w in group:
            dur_cs = max(1, int(round((w.end - w.start) * 100)))
            chunks.append(rf"{{\kf{dur_cs}}}{w.word.strip()}")
        text = " ".join(chunks)
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,{text}")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path
