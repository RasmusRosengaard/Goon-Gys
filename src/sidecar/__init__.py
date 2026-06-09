"""Stage 5 — upload metadata sidecar.

Produces Ready_for_upload/<id>/sidecar.txt matching the field layout in
Ready_for_upload/template_1/sidecar.txt. Uses the Claude CLI for catchy
title/description/tags when available; otherwise falls back to the story's own
title and a simple description. See claude.md section 4, Stage 5.
"""
from __future__ import annotations

from pathlib import Path

from .. import config
from ..claude_cli import available, complete_json
from ..models import Story

_FIELDS = ["title", "description", "pinned_comment", "tags", "theme", "series_id",
           "part", "story_id", "hashtags", "language", "visibility"]

_THEME_TAGS = {
    "horror": "horror, scarystory, storytime, creepy, shorts",
    "goon": "storytime, confession, relationship, drama, shorts",
    "goonhorror": "storytime, confession, forbidden, suspense, drama, shorts",
}
_THEME_HASHTAGS = {
    "horror": "#shorts #horror #scarystories #storytime #creepy",
    "goon": "#shorts #storytime #confession #drama #fyp",
    "goonhorror": "#shorts #storytime #forbidden #suspense #fyp",
}
# Fallback engagement comment to pin (used only when no LLM-written one is available).
_THEME_PINNED = {
    "horror": "Be honest — would YOU have stayed in that room? 😳 Tell me what you'd do 👇",
    "goon": "Okay be honest 👀 has something this awkward ever happened to YOU? Spill below 👇😅",
    "goonhorror": "Tell me I'm not the only one 👀 would you have stayed, or RUN? Drop it below 👇",
}


def _llm_meta(story: Story) -> dict | None:
    if not available():
        return None
    prompt = (
        "Return ONLY JSON with keys title, description, tags (comma-separated string), "
        "pinned_comment. "
        f"Theme: {story.theme}. Make a click-worthy YouTube Shorts title (<=90 chars), "
        "a 1-2 line description, and ~8 relevant tags. pinned_comment is a short, casual "
        "comment the channel pins under the video that asks viewers a specific question "
        "tied to THIS story to make them reply (1-2 sentences, a couple of emoji, end "
        "with a prompt to comment).\n\n"
        f"Story:\n{story.body}"
    )
    try:
        return complete_json(prompt, "Output only valid JSON, no code fences.")
    except RuntimeError:
        return None


def _part_suffix(story: Story) -> str:
    return f" (Part {story.part}/{story.total_parts})" if story.is_series else ""


def _part_tease(story: Story) -> str:
    if story.has_next_part:
        return f" Part {story.part + 1} drops next - follow so you don't miss it."
    if story.is_series:
        return " The finale. Watch parts 1 onward from the start."
    return ""


def generate(story: Story, out_path: Path | None = None) -> Path:
    out_path = Path(out_path) if out_path else config.output_dir(story.id) / "sidecar.txt"

    # Prefer metadata precomputed during story generation (Stage 1 returns it in the
    # same Claude call). Only fall back to a separate Claude call when it's absent —
    # e.g. reddit/hybrid stories, which don't precompute description/tags.
    meta = {} if (story.description and story.tags) else (_llm_meta(story) or {})
    title = (meta.get("title") or story.title) + _part_suffix(story)
    description = (
        story.description or meta.get("description") or story.body[:140]
    ).replace("\n", " ")
    tags = story.tags or meta.get("tags") or _THEME_TAGS.get(story.theme, "shorts")
    pinned_comment = (
        story.pinned_comment
        or meta.get("pinned_comment")
        or _THEME_PINNED.get(story.theme, "What would you have done? 👇")
    ).replace("\n", " ").strip()
    hashtags = _THEME_HASHTAGS.get(story.theme, "#shorts")
    if story.is_series:
        tags = f"{tags}, part{story.part}, series, storytimepart{story.part}"
        hashtags = f"{hashtags} #part{story.part}"
    values = {
        "title": title,
        "description": (description + _part_tease(story)).strip(),
        "pinned_comment": pinned_comment,
        "tags": tags,
        "theme": story.theme,
        "series_id": story.series_id,
        "part": f"{story.part}/{story.total_parts}" if story.is_series else "",
        "story_id": story.id,
        "hashtags": hashtags,
        "language": "en",
        "visibility": "public",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "\n".join(f"{k}: {values[k]}" for k in _FIELDS) + "\n", encoding="utf-8"
    )
    return out_path
