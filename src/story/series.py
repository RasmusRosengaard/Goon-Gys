"""Multi-part series: split one story into Part 1..N, each ending on a cliffhanger
to pull the viewer to the next short ("edging" retention). Each part becomes its own
Story (and therefore its own video + sidecar), sharing a series_id.

Default path uses the Claude CLI to write N parts that each end on a hook. Without
the CLI it falls back to a naive sentence-based split (no synthesized cliffhangers).
See claude.md section 4a.
"""
from __future__ import annotations

import datetime
import re

from .. import config
from ..claude_cli import available, complete_json
from ..models import Story
from . import critic, ids, reddit, variety

# Spoken call-to-action appended to every non-final part so the voiceover literally
# says it and the subtitles show it (keeps captions == spoken words). {n} = next part.
CTA_TEMPLATE = "Follow for part {n}."

_SYSTEM = (
    "You write serialized first-person stories for narrated YouTube Shorts. Output "
    "ONLY valid JSON, no code fences, no commentary. Each part is clean spoken prose: "
    "no markdown, no emoji, no 'Part X' labels inside the body, numbers spelled out.\n\n"
    "CRAFT — this is what stops the swipe, obey it:\n"
    "- SUBSTANCE (most important): a REAL, consequential story must actually unfold across "
    "the parts — genuine events with stakes (a discovery, a confrontation, a decision that "
    "costs something), not mood-setting or stalling that just marks time until the ending. "
    "Each part should contain an actual beat that moves the story, so it is worth watching "
    "on its own.\n"
    "- THROUGH-LINE: it is ONE connected story across all parts. Every beat follows "
    "logically and causally from the last, details planted in earlier parts pay off "
    "later, and nothing is dropped or contradicted. It must make complete sense heard "
    "in order.\n"
    "- CLARITY & CONTINUITY (make sense above ALL): the listener must always understand "
    "exactly what is literally happening, who each person is, where they are, and why each "
    "action is taken. A story can be ridiculous, filthy, or terrifying — but it must NEVER "
    "be confusing. If it turns on a trick, plan, scheme, or loophole, make HOW that works "
    "unmistakably clear in plain terms, so the payoff lands. Each part must continue "
    "SEAMLESSLY from the exact moment the previous one ended, with no contradiction: do "
    "not place people somewhere they weren't, restate facts differently, or have a part's "
    "opening describe a moment in a way that conflicts with how it actually plays out. "
    "Read in order, the parts must be one coherent story with a consistent timeline.\n"
    "- POV: stay strictly in FIRST PERSON ('I'/'me') in every part — telling what "
    "happened to ME, never narrated from outside as 'he'/'she'.\n"
    "- CADENCE (read aloud by TTS, so punctuate for the EAR): short, clear sentences, "
    "one idea each. A period is a real pause; a comma is barely a breath. Do NOT chain "
    "things with commas — comma lists and long stacked-clause sentences get slurred into "
    "one breathless run. List three things as three short sentences. Use a period where "
    "the voice should stop.\n"
    "- HOOK: part 1's first sentence drops the viewer into the sharpest moment with a "
    "concrete, specific detail and an unanswered question. No preamble.\n"
    "- ESCALATE: every sentence raises stakes or tightens tension using concrete "
    "sensory detail, not vague adjectives. No flat stretches.\n"
    "- CLIFFHANGER: each non-final part ends mid-spike — right as something turns or a "
    "question cracks open — so stopping there feels unbearable. Do not resolve early.\n"
    "- PAYOFF: the final part's last line lands hard — sharp, surprising, and set up by "
    "the earlier parts, never a tidy fade-out or a twist from nowhere.\n"
    "- VARIETY: fresh setting, cast, and phrasing; never reuse stock openings or pivots.\n\n"
    "Do NOT write 'follow for part two' or any call-to-action — that line is added "
    "automatically afterward. Keep 'goon' content suggestive storytime, never explicit "
    "(YouTube-safe)."
)


def part_id(series_id: str, n: int) -> str:
    # e.g. 20260608-goonhorror-the-attic_part1  ->  Ready_for_upload/<id>_part1/
    return f"{series_id}_part{n}"


_GOON_SERIES = (
    " Build a charged slow-burn across the whole series (stay FIRST PERSON throughout): "
    "OPEN part 1 with one short, breathless suggestive line dropped into a charged moment "
    "that BELONGS TO PART 1's own scene (not a flash-forward to the finale, which only "
    "creates contradictions) — cut off right before the reveal so the viewer's imagination "
    "fills the gap. Across the parts keep ESCALATING genuine chemistry and tension between two "
    "people — charged proximity, lingering looks, a brushed touch, heat, the 'almost' — "
    "with concrete sensory detail and real stakes (something forbidden, risky, or "
    "unspoken). Each non-final part ends mid-spike with the tension cranked higher. END "
    "the FINAL part on a tantalizing, charged turn where the tension peaks or pivots on a "
    "suggestive reveal, leaving the viewer wanting — do NOT defuse it into something "
    "mundane or innocent, and do NOT resolve the tension cleanly. CRITICAL — suggestive by "
    "IMPLICATION ONLY: imply, never describe; fade to black at the charged moment; no "
    "explicit acts, no graphic anatomy, nothing crude. Tasteful, YouTube-safe. Vary the "
    "opening and phrasing each time."
)


_GOONHORROR_SERIES = (
    " Build a charged slow-burn with a creeping edge across the whole series (stay FIRST "
    "PERSON throughout): OPEN part 1 with one short, breathless line that is at once "
    "suggestive AND faintly wrong, dropped into a charged moment that BELONGS TO PART 1's "
    "own scene (not a flash-forward to the finale, which only creates contradictions) — "
    "cut off before the reveal so the viewer's imagination fills the gap. Across the parts "
    "ESCALATE TWO things at once — "
    "genuine sexual chemistry (charged proximity, lingering looks, a brushed touch, the "
    "'almost') AND a creeping dread that something is forbidden or not right (you shouldn't "
    "be doing this, or he isn't who you think) — with concrete sensory detail and real "
    "stakes. Each non-final part ends mid-spike with both the heat and the wrongness "
    "cranked higher. END the FINAL part on a turn that is BOTH tantalizing and unsettling "
    "— the heat peaks at the same instant the wrongness lands, left equal parts seductive "
    "and spine-chilling. Do NOT defuse it into something mundane or innocent. CRITICAL — "
    "suggestive by IMPLICATION ONLY: imply, never describe; fade to black at the charged "
    "moment; no explicit acts, no graphic anatomy, nothing crude. Tasteful, YouTube-safe. "
    "Vary the opening and phrasing each time."
)


def _prompt(parts: int, theme: str, seed: str | None) -> str:
    source_line = (
        f"Base it on this true story, keeping the events:\n\n{seed}\n\n"
        if seed
        else f"Invent an original {theme} story.{variety.avoid_clause(theme)}\n\n"
    )
    tease = {"goon": _GOON_SERIES, "goonhorror": _GOONHORROR_SERIES}.get(theme, "")
    return (
        f"{source_line}"
        f"Split it into exactly {parts} parts of about 140-160 words each (each part "
        f"about a 60 SECOND read aloud). Every part except the last MUST end mid-spike on "
        f"a cliffhanger — cut at the instant something turns or a question cracks open, so "
        f"stopping there feels unbearable and the viewer needs the next part. The final "
        f"part resolves the story with a sharp, surprising payoff.{tease} Return JSON of the form: "
        f'{{"series_title": "...", "parts": ["body of part 1", "body of part 2", ...]}} '
        f"with exactly {parts} strings in 'parts'."
    )


def _parts_from(data: dict) -> tuple[str, list[str]]:
    bodies = [b.strip() for b in data.get("parts", []) if b and b.strip()]
    if not bodies:
        raise RuntimeError("model returned no story parts")
    return (data.get("series_title") or "").strip(), bodies


def _naive_split(title: str, body: str, parts: int) -> tuple[str, list[str]]:
    sentences = re.split(r"(?<=[.!?])\s+", body.strip())
    if len(sentences) < parts:
        raise RuntimeError("story too short to split into the requested parts")
    size = -(-len(sentences) // parts)  # ceil
    chunks = [
        " ".join(sentences[i : i + size]).strip()
        for i in range(0, len(sentences), size)
    ][:parts]
    return title, chunks


def _series_bodies(
    source: str, theme: str, parts: int, opts: dict
) -> tuple[str, list[str]]:
    seed = None
    if source in ("reddit", "hybrid"):
        s_title, s_body, opts["_source_url"] = reddit.fetch_seed(theme, **{
            k: v for k, v in opts.items() if k in ("subreddit", "min_chars", "max_chars")
        })
        seed = f"{s_title}\n\n{s_body}"
        if not available():  # no CLI -> naive split of the raw post
            return _naive_split(s_title, s_body, parts)

    if not available():
        raise RuntimeError("multi-part llm source needs the `claude` CLI on PATH")
    return _parts_from(complete_json(_prompt(parts, theme, seed), _SYSTEM))


def generate_series(source: str, theme: str, parts: int, **opts) -> list[Story]:
    """Produce N linked Story parts. parts<=1 returns a single standalone story."""
    if parts <= 1:
        from . import generate as gen_single

        return [gen_single(source, theme, **opts)]

    series_title, bodies = _series_bodies(source, theme, parts, opts)
    if len(bodies) != parts:
        # tolerate the model returning a slightly different count
        parts = len(bodies)

    # Quality gate: one critic call scores + punches up the whole series at once
    # (keeping the part count and cliffhangers). No-op without the CLI.
    quality, quality_notes = 0.0, ""
    if opts.get("polish", True):
        series_title, bodies, quality, quality_notes = critic.polish_series(
            series_title, bodies, theme
        )
    series_id = ids.make_id(theme, series_title or f"{theme} series")
    today = datetime.date.today().isoformat()
    source_url = opts.get("_source_url", "")

    stories: list[Story] = []
    for i, body in enumerate(bodies, start=1):
        if i < parts:  # append spoken CTA to every non-final part
            body = f"{body.rstrip()} {CTA_TEMPLATE.format(n=_spell(i + 1))}"
        stories.append(
            Story(
                id=part_id(series_id, i),
                title=f"{series_title or theme.title()} (Part {i})",
                body=body,
                theme=theme,
                source=source,
                source_url=source_url,
                background_category=config.DEFAULT_BACKGROUND_CATEGORY,
                voice=config.DEFAULT_VOICE,
                created=today,
                series_id=series_id,
                part=i,
                total_parts=parts,
                quality=quality,
                quality_notes=quality_notes,
            )
        )
    return stories


_NUMBERS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
            "nine", "ten"]


def _spell(n: int) -> str:
    return _NUMBERS[n] if 0 <= n < len(_NUMBERS) else str(n)
