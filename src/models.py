"""Shared data types passed between pipeline stages."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class WordTiming:
    """One spoken word and when it is said, in seconds from audio start.

    `segment` groups words by the text block (paragraph) they came from, so captions
    never span a tease/story (paragraph) boundary and the audio can be paused between.
    """

    word: str
    start: float
    end: float
    segment: int = 0


@dataclass
class Story:
    """A story script. The `body` is the EXACT text spoken by TTS and is the
    source the word-synced subtitles are generated from (see claude.md)."""

    id: str
    title: str
    body: str
    theme: str = ""
    source: str = ""            # reddit | llm | hybrid
    source_url: str = ""
    background_category: str = ""
    voice: str = ""
    status: str = "draft"       # draft | voiced | rendered | uploaded
    created: str = ""
    # Upload metadata, precomputed alongside the story in ONE llm call so Stage 5
    # (sidecar) needs no extra Claude call. Empty for reddit/hybrid → sidecar fills in.
    description: str = ""
    tags: str = ""
    # An author/channel comment to pin under the video — a question that invites viewers
    # to reply, driving engagement. Precomputed with the story (llm) or filled by Stage 5.
    pinned_comment: str = ""
    # Quality gate (src/story/critic.py): the critic's harsh 0-10 score of the polished
    # script and its one-line notes. 0 = never judged (reddit faithful / --no-polish).
    quality: float = 0.0
    quality_notes: str = ""
    # Multi-part series. Standalone shorts use part=0, total_parts=1, series_id="".
    # A series of N parts shares one series_id; parts are numbered 1..N.
    series_id: str = ""
    part: int = 0
    total_parts: int = 1

    @property
    def is_series(self) -> bool:
        return self.total_parts > 1

    @property
    def has_next_part(self) -> bool:
        return self.is_series and 0 < self.part < self.total_parts

    def frontmatter(self) -> dict:
        d = asdict(self)
        d.pop("title")
        d.pop("body")
        return d
