"""LLM story sourcing and cleanup via the Claude Code CLI (headless, no API key).

`generate` writes an original themed story in ONE Claude call that also returns the
title/description/tags (so Stage 5 needs no extra call); `rewrite`/`reshape` clean or
reshape a Reddit seed into spoken prose. All go through src/claude_cli.py (`claude -p`).
"""
from __future__ import annotations

import datetime

from .. import config
from ..claude_cli import complete, complete_json
from ..models import Story
from . import critic, ids, variety

# Shared craft rules. _SYSTEM (plain-text body) wraps these for rewrite()/reshape();
# _GEN_SYSTEM (JSON) wraps them for generate(), which returns story + metadata in one call.
_CRAFT = (
    "You write short first-person stories for narrated YouTube Shorts. The spoken story "
    "is clean prose: no markdown, no titles inside it, no stage directions, no emoji. "
    "Spell out numbers as they should be read. Keep it about 140-160 words "
    "(about a 60 SECOND read aloud).\n\n"
    "CRAFT — this is what stops the swipe, obey it:\n"
    "- SUBSTANCE (most important): something REAL and consequential must actually HAPPEN "
    "in the body of the story — a genuine event with stakes: a discovery, a confrontation, "
    "a decision that costs something, a turn that changes the situation. The story must be "
    "worth telling on its own, even if there were no tease or payoff wrapped around it. Do "
    "NOT let the middle become thin filler or mood-setting that just stalls until the "
    "ending — give the listener an actual story with a beginning, a real complication, and "
    "consequences.\n"
    "- THROUGH-LINE (the spine of the story): tell ONE clear, connected story. Every "
    "sentence must follow logically and causally from the one before it, every detail "
    "you introduce must matter and pay off, and the whole thing must make complete sense "
    "on a single listen. No non-sequiturs, no dropped threads, no jumps the listener "
    "can't follow, no details that appear only to vanish. If the ending depends on a "
    "fact, plant that fact earlier.\n"
    "- CLARITY (make sense above ALL): the listener must always understand exactly what is "
    "literally happening, who each person is, and why each action is taken. A story can be "
    "ridiculous, filthy, or terrifying — but it must NEVER be confusing. If it turns on a "
    "trick, plan, scheme, or loophole, make HOW that works unmistakably clear in plain "
    "terms as it happens, so the payoff actually lands; never leave the audience guessing "
    "at the mechanics. Before you finish, re-read it and confirm every step follows and "
    "nothing contradicts what came earlier.\n"
    "- POV: stay strictly in FIRST PERSON the whole way — 'I' and 'me', telling what "
    "happened to ME. Never narrate it from the outside as 'he'/'she'. Other people in "
    "the story can be 'he'/'she', but the narrator is always 'I'.\n"
    "- CADENCE (it is read aloud by a TTS voice, so punctuate for the EAR): write short, "
    "clear sentences, mostly one idea each. A period is a real pause; a comma is barely a "
    "breath. So do NOT chain things with commas — a comma-separated list or a long "
    "stacked-clause sentence gets slurred into one breathless run. If you would list "
    "three things, write them as three short sentences. Where you want the voice to "
    "stop, use a period.\n"
    "- HOOK: the first sentence drops the viewer straight into the sharpest moment "
    "with a concrete, specific detail and an unanswered question they need resolved. "
    "No throat-clearing, no 'so this one time', no scene-setting preamble. If that hook "
    "flashes forward to a moment the story then explains, it must be LITERALLY TRUE to the "
    "scene as it actually plays out — do not describe people as somewhere they aren't or "
    "doing something that contradicts what really happens at that moment.\n"
    "- ESCALATE: every sentence raises the stakes or tightens the tension. Use "
    "concrete sensory detail (a sound, a texture, a specific object) instead of vague "
    "adjectives like 'creepy' or 'weird'. No flat middle — keep ratcheting toward the "
    "end.\n"
    "- PAYOFF: the last line lands hard — a sharp, surprising, satisfying turn that the "
    "earlier beats actually set up, never a soft fade-out, a tidy moral, or a twist that "
    "comes from nowhere.\n"
    "- VARIETY: invent a fresh setting, cast, and voice every time; never reuse stock "
    "openings or pivots.\n"
    "- Be tight: no wasted words; every line earns its place.\n\n"
    "Do NOT add any call-to-action or meta lines such as 'follow for part two', "
    "'part 2', 'like and subscribe', or 'comment below' — this is a standalone story, "
    "so end on the story itself. Keep any suggestive ('goon') content as innuendo and "
    "tension only, never explicit, to stay within YouTube monetization rules."
)

# rewrite()/reshape() return the spoken body as plain text.
_SYSTEM = _CRAFT + "\n\nOutput ONLY the spoken words of the story — nothing else."

# generate() returns the story AND its upload metadata in ONE call, so Stage 5
# (sidecar) reads story.description/story.tags instead of making its own Claude call.
_GEN_SYSTEM = _CRAFT + (
    "\n\nOutput ONLY valid JSON (no code fences, no commentary) with exactly these keys: "
    '"body" = the spoken story, following every rule above; '
    '"title" = a punchy YouTube Shorts title, max 70 characters, no quotes; '
    '"description" = a click-worthy 1-2 line YouTube description; '
    '"tags" = about 8 relevant tags as one comma-separated string; '
    '"pinned_comment" = a short, casual comment the channel pins under the video that '
    "asks viewers a specific question tied to THIS story so they reply (1-2 sentences, a "
    "couple of emoji, end with a prompt to comment)."
)

# Charged slow-burn for the goon theme: sustain real flirty/sexual TENSION the whole way
# (no innocent fake-out), pure innuendo, fades before anything explicit. YouTube-safe.
_GOON = (
    " STRUCTURE — charged slow-burn (stay FIRST PERSON throughout): (1) OPEN on the single "
    "most charged moment with one short, breathless line (a 2-5 second hook, about 8-14 "
    "words) dripping with suggestive tension and cut off right before the reveal, so the "
    "viewer's imagination fills the gap — e.g. 'He pinned me against the cooler and I "
    "forgot how to breathe...'. (2) Then tell the actual story as ONE connected through-"
    "line and keep ESCALATING genuine chemistry and tension between two people: charged "
    "proximity, lingering looks, a brushed touch, heat, the 'almost', the will-they-"
    "won't-they. Use concrete sensory detail (warmth, breath, a hand, closeness) and give "
    "it real stakes — something forbidden, risky, or unspoken that makes the tension "
    "matter. (3) END on a tantalizing, charged turn where the tension PEAKS and is left "
    "unresolved or pivots on a suggestive reveal (who it was, a confession, a text, a "
    "near-miss) — so the viewer is left wanting more. Do NOT defuse it into a mundane or "
    "innocent explanation, and do NOT resolve the tension cleanly. CRITICAL — keep it "
    "suggestive by IMPLICATION ONLY: imply, never describe; fade to black at the charged "
    "moment; no explicit sexual acts, no graphic anatomy, nothing crude or gross. Tasteful "
    "heat that stays within YouTube monetization rules. VARY everything each time — the "
    "opening moment, the setting, the cast, and the wording (do not always start 'And then "
    "I...' or reuse a stock line). The example above is an illustration only — invent your "
    "own."
)

# goonhorror = the goon slow-burn blended with creeping dread: sustain BOTH sexual tension
# and an eerie, forbidden, something-is-wrong edge. Suggestive by implication only.
_GOONHORROR = (
    " STRUCTURE — charged slow-burn with a creeping edge (stay FIRST PERSON throughout): "
    "(1) OPEN on the single most charged moment with one short, breathless line (a 2-5 "
    "second hook, about 8-14 words) that is at once suggestive AND faintly wrong, cut off "
    "right before the reveal so the viewer's imagination fills the gap — e.g. 'His hand "
    "slid up my back in the dark, but his car was still in the driveway...'. (2) Then tell "
    "the actual story as ONE connected through-line and ESCALATE TWO things at once: "
    "genuine chemistry and sexual tension (charged proximity, lingering looks, a brushed "
    "touch, heat, the 'almost') AND a creeping dread that something is forbidden or not "
    "right (you shouldn't be doing this, or he isn't who you think he is). Use concrete "
    "sensory detail and give it real stakes. (3) END on a turn that is BOTH tantalizing "
    "and unsettling — the heat peaks at the same instant the wrongness lands, left "
    "unresolved so it is equal parts seductive and spine-chilling. Do NOT defuse it into a "
    "mundane or innocent explanation, and do NOT resolve it cleanly. CRITICAL — keep it "
    "suggestive by IMPLICATION ONLY: imply, never describe; fade to black at the charged "
    "moment; no explicit sexual acts, no graphic anatomy, nothing crude or gross. Tasteful "
    "heat plus dread, within YouTube monetization rules. VARY everything each time — the "
    "opening moment, the setting, the cast, and the wording. The example above is an "
    "illustration only — invent your own."
)

_THEME_PROMPT = {
    # horror: gripping cold open, no innocent payoff (dread shouldn't be defused).
    "horror": (
        "Write an unsettling, eerie 'this really happened to me' horror story. Open cold "
        "on the single most ominous, specific moment — one concrete image or sound that's "
        "already wrong — then unfold what led there while steadily tightening the dread. "
        "Build with sensory detail, not vague adjectives, and end on a final line that "
        "lands like a cold drop. Do NOT defuse the dread with a happy or innocent ending."
    ),
    "goon": (
        "Write a flirty, charged 'you won't believe what happened' storytime built on real "
        "slow-burn sexual tension between two people — chemistry, heat, and the 'almost' — "
        "kept tasteful and suggestive." + _GOON
    ),
    "goonhorror": (
        "Write a suggestive, tension-filled 'forbidden, home alone with someone I "
        "shouldn't be' storytime (e.g. a stepsibling-type setup) with real sexual "
        "chemistry AND a creeping, eerie, something-is-wrong edge." + _GOONHORROR
    ),
}


def _gen_json(user: str) -> dict:
    """One Claude call returning {body, title, description, tags, pinned_comment} as JSON."""
    return complete_json(user, _GEN_SYSTEM)


def _build_story(theme: str, data: dict) -> Story:
    title = (data.get("title") or "").strip().strip('"') or theme.title()
    return Story(
        id=ids.make_id(theme, title),
        title=title,
        body=(data.get("body") or "").strip(),
        theme=theme,
        source="llm",
        background_category=config.DEFAULT_BACKGROUND_CATEGORY,
        voice=config.DEFAULT_VOICE,
        created=datetime.date.today().isoformat(),
        description=(data.get("description") or "").strip(),
        tags=(data.get("tags") or "").strip(),
        pinned_comment=(data.get("pinned_comment") or "").strip(),
    )


def generate(
    theme: str, *, prompt: str | None = None, polish: bool = True, attempts: int = 2, **_
) -> Story:
    """Write an original story; with `polish` (default) every draft passes the
    quality gate (critic score + punch-up), and a draft that still scores below
    critic.MIN_SCORE is thrown away and regenerated — the editor's notes are fed
    back into the retry prompt — keeping the best attempt as a fallback."""
    if theme not in _THEME_PROMPT:
        raise ValueError(f"no llm prompt for theme '{theme}'")
    base = (prompt or _THEME_PROMPT[theme]) + variety.avoid_clause(theme)

    best: Story | None = None
    feedback = ""
    for _attempt in range(max(1, attempts) if polish else 1):
        story = _build_story(theme, _gen_json(base + feedback))
        if not story.body:
            continue  # malformed reply (e.g. JSON missing "body") — never save it
        if not polish:
            return story
        critic.polish(story)
        story.id = ids.make_id(theme, story.title)  # title may have been sharpened
        if story.quality <= 0 or story.quality >= critic.MIN_SCORE:
            return story  # accepted — or no CLI to judge with, so take the draft
        if best is None or story.quality > best.quality:
            best = story
        feedback = (
            "\n\nA previous draft was REJECTED by the channel's editor with these "
            f"notes: {story.quality_notes or 'flat, forgettable, weak payoff'}. "
            "Write a COMPLETELY different story — new premise, setting, and cast — "
            "that cannot fail the same way."
        )
    if best is None:
        raise RuntimeError("the model returned no usable story body")
    return best


def rewrite(title: str, body: str, theme: str) -> str:
    """Faithful clean of a sourced (Reddit) story into spoken prose; preserve the plot."""
    return complete(
        f"Rewrite this {theme} story as a tight first-person voiceover script. "
        f"Keep the events; fix grammar; remove usernames, edits, and asides.\n\n"
        f"Title: {title}\n\n{body}",
        _SYSTEM,
    )


def reshape(title: str, body: str, theme: str) -> str:
    """Transformative reshape of a seed post: keep the core idea but rebuild it as a
    punchy Short — open on the strongest hook, tighten pacing, sharpen the ending."""
    return complete(
        f"Use this {theme} post as inspiration. Keep its core premise but rebuild it as "
        f"a gripping first-person Shorts voiceover: open on the most gripping moment, "
        f"cut filler, heighten tension, and end on a punchy beat. Reshape freely.\n\n"
        f"Title: {title}\n\n{body}",
        _SYSTEM,
    )
