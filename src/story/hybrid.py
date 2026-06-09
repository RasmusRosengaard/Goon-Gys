"""Hybrid sourcing: pull a real Reddit post as a SEED, then have Claude reshape and
expand it into a Shorts script (stronger hook, tighter pacing, punchier ending).

This is the transformative counterpart to `reddit` (which stays faithful to the post).
"""
from __future__ import annotations

import datetime

from .. import config
from ..claude_cli import available
from ..models import Story
from . import critic, ids, llm, reddit

_SEED_OPTS = ("subreddit", "min_chars", "max_chars")


def generate(theme: str, *, polish: bool = True, **opts) -> Story:
    title, body, url = reddit.fetch_seed(
        theme, **{k: v for k, v in opts.items() if k in _SEED_OPTS}
    )
    if available():
        body = llm.reshape(title, body, theme)
    story = Story(
        id=ids.make_id(theme, title),
        title=title,
        body=body,
        theme=theme,
        source="hybrid",
        source_url=url,
        background_category=config.DEFAULT_BACKGROUND_CATEGORY,
        voice=config.DEFAULT_VOICE,
        created=datetime.date.today().isoformat(),
    )
    if polish and available():
        # Quality gate: score + punch up the reshape. Also fills description/tags/
        # pinned_comment, so Stage 5 needs no Claude call for polished hybrids.
        critic.polish(story)
        story.id = ids.make_id(theme, story.title)
    return story
