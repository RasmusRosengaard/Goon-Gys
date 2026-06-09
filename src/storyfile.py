"""Read/write Story scripts as `Stories/<id>.md` with YAML frontmatter.

Format matches Stories/template.md: a `---` YAML block, then `# Title`, then the
spoken body. The body is preserved verbatim because TTS reads it word-for-word.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from . import config
from .models import Story, WordTiming

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def story_path(story_id: str) -> Path:
    return config.STORIES_DIR / f"{story_id}.md"


def save_story(story: Story) -> Path:
    """Write a Story to Stories/<id>.md."""
    config.STORIES_DIR.mkdir(parents=True, exist_ok=True)
    fm = yaml.safe_dump(story.frontmatter(), sort_keys=False).strip()
    text = f"---\n{fm}\n---\n\n# {story.title}\n\n{story.body.strip()}\n"
    path = story_path(story.id)
    path.write_text(text, encoding="utf-8")
    return path


def load_story(story_id: str) -> Story:
    """Read Stories/<id>.md back into a Story."""
    path = story_path(story_id)
    raw = path.read_text(encoding="utf-8")
    m = _FRONTMATTER.match(raw)
    if not m:
        raise ValueError(f"{path} is missing a valid frontmatter block")
    meta = yaml.safe_load(m.group(1)) or {}
    rest = m.group(2).strip()

    title = ""
    body = rest
    if rest.startswith("#"):
        head, _, tail = rest.partition("\n")
        title = head.lstrip("#").strip()
        body = tail.strip()

    meta = {k: ("" if v is None else v) for k, v in meta.items()}
    meta["id"] = meta.get("id") or story_id
    return Story(title=title, body=body, **meta)


# --- intermediate artifact paths (in build/<id>/) ---

def save_word_timings(story_id: str, timings: list[WordTiming]) -> Path:
    path = config.build_dir(story_id) / "word_timings.json"
    path.write_text(
        json.dumps([t.__dict__ for t in timings], indent=2), encoding="utf-8"
    )
    return path


def load_word_timings(story_id: str) -> list[WordTiming]:
    path = config.build_dir(story_id) / "word_timings.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [WordTiming(**d) for d in data]
