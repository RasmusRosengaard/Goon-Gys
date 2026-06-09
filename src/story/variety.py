"""Cross-run variety: feed recently used premises back into generation.

Each Claude CLI call is memoryless, so without this the generator slowly converges
on the same stock setups ("the babysitter", "the lake house") no matter how hard
the prompt asks for variety. We read the titles + opening lines of recent
Stories/<id>.md files for the same theme and tell the model to stay clearly away
from all of them.
"""
from __future__ import annotations

from .. import config
from ..storyfile import load_story


def recent_premises(theme: str, limit: int = 12) -> list[str]:
    """Title + opening words of the most recent stories of this theme."""
    try:
        paths = sorted(
            config.STORIES_DIR.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return []
    out: list[str] = []
    for path in paths:
        if path.name == "template.md":
            continue
        try:
            s = load_story(path.stem)
        except Exception:
            continue  # hand-made or malformed file; not worth failing generation over
        if s.theme != theme or s.part > 1:  # later parts repeat part 1's premise
            continue
        opening = " ".join(s.body.split()[:14])
        out.append(f'"{s.title}" (opens: {opening}…)')
        if len(out) >= limit:
            break
    return out


def avoid_clause(theme: str) -> str:
    """Prompt fragment listing premises the new story must not resemble."""
    premises = recent_premises(theme)
    if not premises:
        return ""
    return (
        "\n\nALREADY POSTED — the channel has already used these stories. Yours must "
        "be clearly different from EVERY one of them in premise, setting, cast, and "
        "opening line:\n- " + "\n- ".join(premises)
    )
