"""Helpers for the shared `<id>` slug used across Stories/ and Ready_for_upload/."""
from __future__ import annotations

import re
from datetime import date


def slugify(text: str, max_words: int = 4) -> str:
    words = re.sub(r"[^a-z0-9\s-]", "", text.lower()).split()
    return "-".join(words[:max_words]) or "untitled"


def make_id(theme: str, title: str, on: date | None = None) -> str:
    """YYYYMMDD-<theme>-<slug>, e.g. 20260608-horror-the-attic."""
    day = (on or date.today()).strftime("%Y%m%d")
    return f"{day}-{theme}-{slugify(title)}"
