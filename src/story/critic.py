"""Stage 1.5 — quality gate: score a draft and punch it up before it is saved.

One extra Claude call per story (or per series): a harsh "script doctor" scores the
draft on the things that decide likes (hook, substance, escalation, payoff, clarity,
delivery), rewrites it to fix every weakness, and returns the revised script with an
honest 0-10 score. `llm.generate` regenerates from scratch when even the polished
result stays below MIN_SCORE, keeping the best attempt as a fallback. The score and
the critic's one-line notes land in the story frontmatter (`quality`,
`quality_notes`) so the review gate can triage. See claude.md section 4, Stage 1.
"""
from __future__ import annotations

from ..claude_cli import available, complete_json
from ..models import Story

# A polished story scoring below this is still "mid": llm.generate throws it away
# and writes a fresh one (up to its attempts budget), keeping the best as fallback.
MIN_SCORE = 7.5

# Sanity bounds for accepting a critic rewrite: a body outside this word range broke
# the ~60-second format, so the original body is kept (the score still applies).
_MIN_WORDS, _MAX_WORDS = 100, 220

_RUBRIC = (
    "You are a ruthless script doctor for narrated first-person YouTube Shorts. You "
    "judge a draft on ONE question: would it stop a stranger mid-scroll and earn a "
    "like and a share?\n\n"
    "Score the draft 0-10 against: HOOK (the first line alone stops the swipe), "
    "SUBSTANCE (something real and consequential actually happens, with stakes), "
    "ESCALATION (every line tightens; no flat middle), PAYOFF (the last line hits "
    "hard and is earned by what came before), CLARITY (fully understandable in one "
    "listen, no confusion), DELIVERY (short, clean, TTS-friendly sentences). Be "
    "harsh and honest: 5 = publishable but forgettable ('mid'), 7 = genuinely good, "
    "9+ = you would bet money on it going viral. Most first drafts deserve 4-6.\n\n"
    "Then REWRITE the script to fix every weakness you found — sharpen the hook, cut "
    "filler, raise the stakes, land the ending. Keep what already works; replace "
    "what is weak (especially the first and last lines). Constraints for the "
    "rewrite: about 140-160 words per part (a 60 second read), strict FIRST PERSON, "
    "clean spoken prose only (no markdown, no emoji, no stage directions, numbers "
    "spelled out), short period-separated sentences because a TTS voice reads it "
    "aloud, no call-to-action or meta lines, and any suggestive content stays "
    "implication-only within YouTube monetization rules. Never make the story "
    "confusing — clarity beats cleverness.\n\n"
)

_SYSTEM = _RUBRIC + (
    "Output ONLY valid JSON (no code fences, no commentary) with exactly these keys: "
    '"score" = your honest 0-10 overall for the REVISED version, same harsh scale; '
    '"title" = the most click-worthy YouTube Shorts title for the revised story, '
    "max 70 characters, no quotes; "
    '"body" = the revised script (spoken words only); '
    '"description" = a click-worthy 1-2 line YouTube description for the revised story; '
    '"tags" = about 8 relevant tags as one comma-separated string; '
    '"pinned_comment" = a short casual pinned comment asking viewers a specific '
    "question tied to THIS story (1-2 sentences, a couple of emoji, ends by asking "
    "them to comment); "
    '"notes" = one line: the draft\'s main weaknesses and what you changed.'
)

_SERIES_SYSTEM = _RUBRIC + (
    "The draft is a multi-part cliffhanger series; judge and rewrite it as ONE "
    "connected story. The rewrite must keep EXACTLY the same number of parts, each "
    "about 140-160 words, continuing seamlessly with a consistent timeline. Every "
    "non-final part must end mid-spike on a cliffhanger; the final part must resolve "
    "with a sharp, earned payoff. Do not add any 'follow for part two' line — that "
    "is appended automatically.\n\n"
    "Output ONLY valid JSON (no code fences, no commentary) with exactly these keys: "
    '"score" = your honest 0-10 overall for the REVISED series, same harsh scale; '
    '"series_title" = the most click-worthy series title; '
    '"parts" = the revised parts in order, as an array of strings; '
    '"notes" = one line: the draft\'s main weaknesses and what you changed.'
)


def _score(data: dict) -> float:
    try:
        return round(float(data.get("score") or 0), 1)
    except (TypeError, ValueError):
        return 0.0


def polish(story: Story) -> Story:
    """Score + punch up one Story in place (body, title, metadata, quality).
    No-op when the claude CLI is unavailable (quality stays 0 = unjudged)."""
    if not available():
        return story
    data = complete_json(
        f"Theme: {story.theme}. Here is the draft script for one Short.\n\n"
        f"Title: {story.title}\n\n{story.body}",
        _SYSTEM,
    )
    body = (data.get("body") or "").strip()
    if _MIN_WORDS <= len(body.split()) <= _MAX_WORDS:
        story.body = body
        story.title = (data.get("title") or "").strip().strip('"') or story.title
        for field in ("description", "tags", "pinned_comment"):
            val = (data.get(field) or "").strip()
            if val:
                setattr(story, field, val)
    story.quality = _score(data)
    story.quality_notes = (data.get("notes") or "").strip()
    return story


def polish_series(
    series_title: str, bodies: list[str], theme: str
) -> tuple[str, list[str], float, str]:
    """Score + punch up a whole series in one call, keeping the part count.
    Returns (series_title, bodies, score, notes); originals kept if the rewrite
    breaks the format."""
    if not available():
        return series_title, bodies, 0.0, ""
    parts_block = "\n\n".join(f"PART {i}:\n{b}" for i, b in enumerate(bodies, 1))
    data = complete_json(
        f"Theme: {theme}. Here is the draft of a {len(bodies)}-part series "
        f"titled '{series_title}'.\n\n{parts_block}",
        _SERIES_SYSTEM,
    )
    new = [b.strip() for b in (data.get("parts") or []) if b and b.strip()]
    if len(new) == len(bodies) and all(
        _MIN_WORDS <= len(b.split()) <= _MAX_WORDS for b in new
    ):
        bodies = new
        series_title = (data.get("series_title") or "").strip() or series_title
    return series_title, bodies, _score(data), (data.get("notes") or "").strip()
