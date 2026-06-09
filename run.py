#!/usr/bin/env python
"""GoonAndGys CLI — run the Shorts pipeline stage by stage or end to end.

Examples:
    # generate stories, review/edit Stories/<id>.md, then render when happy:
    python run.py story  --theme goon --source llm        # writes Stories/<id>.md for review
    python run.py story  --theme goon --source llm --count 2 --parts 2   # 2 stories x 2 parts = 4 shorts
    python run.py render 20260608-goon-...                # confirm + render that story
    python run.py all    --theme horror --source llm      # story -> confirm gate -> render
    python run.py all    --theme horror --source llm -y   # skip the gate, render straight
    # individual stages (advanced):
    python run.py voice / subs / assemble / sidecar  <id>

Review gate: `story`/`all` write Stories/<id>.md — the body is the exact spoken text. Edit
it to change the story, then confirm (interactively, or via `render`). Loading the story
picks up your edits directly. Stages are decoupled: each reads what the previous one wrote
(see claude.md).
"""
from __future__ import annotations

import argparse
import json
import sys

# Print UTF-8 regardless of the Windows console code page, so a smart quote / em-dash /
# arrow in a title never crashes a run mid-pipeline.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from src import config, story as story_stage, voice, subtitles, assemble, sidecar
from src.story.critic import MIN_SCORE
from src.story.series import part_id
from src.storyfile import (
    load_story, save_story, load_word_timings, save_word_timings, story_path,
)


def _render_info_path(story_id: str):
    return config.build_dir(story_id) / "render.json"


def _id_taken(base: str, used: set[str]) -> bool:
    """True if this base id is already claimed in this batch or on disk (as a standalone
    Stories/<base>.md or as series parts Stories/<base>_part*.md)."""
    if base in used:
        return True
    sd = config.STORIES_DIR
    return (sd / f"{base}.md").exists() or any(sd.glob(f"{base}_part*.md"))


def _claim_id(base: str, used: set[str]) -> str:
    cand, i = base, 2
    while _id_taken(cand, used):
        cand, i = f"{base}-{i}", i + 1
    used.add(cand)
    return cand


def _ensure_unique(stories: list, used: set[str]) -> None:
    """Give a freshly generated story (or series) a collision-free id, renaming series
    parts off the same unique base so several --count stories never overwrite each other."""
    first = stories[0]
    if first.is_series:
        new_base = _claim_id(first.series_id, used)
        if new_base != first.series_id:
            for s in stories:
                s.series_id = new_base
                s.id = part_id(new_base, s.part)
    else:
        first.id = _claim_id(first.id, used)


def cmd_story(args) -> list[str]:
    parts = getattr(args, "parts", 1) or 1
    count = getattr(args, "count", 1) or 1
    used: set[str] = set()
    ids = []
    for _ in range(count):
        stories = story_stage.generate_series(
            args.source, args.theme, parts,
            polish=not getattr(args, "no_polish", False),
        )
        _ensure_unique(stories, used)
        for s in stories:
            if args.voice:
                s.voice = args.voice
            if args.background:
                s.background_category = args.background
            save_story(s)
            tag = f" [part {s.part}/{s.total_parts}]" if s.is_series else ""
            print(f"[story] {s.id}  ({s.source}/{s.theme}){tag}  \"{s.title}\"")
            if s.quality:
                flag = "" if s.quality >= MIN_SCORE else "  ⚠ below bar — consider re-running"
                print(f"        quality: {s.quality:g}/10{flag}")
                if s.quality_notes:
                    print(f"        editor: {s.quality_notes}")
            print(f"        edit: {story_path(s.id)}  (before rendering)")
            ids.append(s.id)
    return ids


def cmd_voice(args) -> str:
    s = load_story(args.id)
    audio = config.build_dir(s.id) / "voice.mp3"
    audio, timings = voice.synthesize(s.body, s.voice or config.DEFAULT_VOICE, audio)
    save_word_timings(s.id, timings)
    s.status = "voiced"
    save_story(s)
    print(f"[voice] {audio}  ({len(timings)} words)")
    return s.id


def cmd_subs(args) -> str:
    timings = load_word_timings(args.id)
    out = config.build_dir(args.id) / "subs.ass"
    subtitles.write_ass(timings, out)
    print(f"[subs]  {out}")
    return args.id


def cmd_assemble(args) -> str:
    s = load_story(args.id)
    audio = config.build_dir(s.id) / "voice.mp3"
    subs = config.build_dir(s.id) / "subs.ass"
    out = config.output_dir(s.id) / "video_file.mp4"

    # Background offset policy: standalone & part 1 start at a RANDOM interval;
    # later parts continue exactly where the previous part's footage ended.
    clip = None
    start_offset = None
    random_start = True
    if s.is_series and s.part > 1:
        prev = _render_info_path(part_id(s.series_id, s.part - 1))
        if not prev.exists():
            raise RuntimeError(
                f"render part {s.part - 1} before part {s.part} "
                "(needed to continue the background seamlessly)"
            )
        info = json.loads(prev.read_text(encoding="utf-8"))
        clip = info["clip"]                          # same clip as the series
        start_offset = info["start"] + info["duration"]  # resume where it left off
        random_start = False

    info = assemble.assemble(
        audio, subs, out,
        background_category=s.background_category or config.DEFAULT_BACKGROUND_CATEGORY,
        background_clip=clip,
        start_offset=start_offset,
        random_start=random_start,
    )
    _render_info_path(s.id).write_text(json.dumps(info, indent=2), encoding="utf-8")
    s.status = "rendered"
    save_story(s)
    print(f"[render] {out}  (bg start {info['start']}s of {info['clip_duration']}s)")
    return s.id


def cmd_sidecar(args) -> str:
    s = load_story(args.id)
    out = sidecar.generate(s)
    print(f"[sidecar] {out}")
    return args.id


def _approve(sid: str) -> None:
    """Mark a story approved. Manual edits live in Stories/<id>.md directly, so loading
    the story already reflects them — there is nothing to sync."""
    s = load_story(sid)
    s.status = "approved"
    save_story(s)


def _confirm_render(sid: str, assume_yes: bool) -> bool:
    """Approval gate before a story becomes a video. Returns True to proceed."""
    if assume_yes:
        _approve(sid)
        return True
    path = story_path(sid)
    if not sys.stdin.isatty():
        # Non-interactive and not pre-approved: never auto-render. Leave it for review.
        print(f"[review] edit {path} if you like, then:  python run.py render {sid}")
        return False
    s = load_story(sid)
    q = f"  (quality {s.quality:g}/10)" if s.quality else ""
    print(f"\n--- script: {sid}{q} ---\n{s.body}\n--- file: {path} ---")
    resp = input("Edit that file if needed, then render this video? [y/N] ").strip().lower()
    if resp not in ("y", "yes"):
        print(f"[skip] {sid} (not rendered)")
        return False
    _approve(sid)
    return True


def _render_pipeline(sid: str) -> None:
    args = argparse.Namespace(id=sid)
    cmd_voice(args)
    cmd_subs(args)
    cmd_assemble(args)
    cmd_sidecar(args)
    print(f"  → {config.output_dir(sid)}")


def cmd_render(args) -> str | None:
    """Stages 2-5 for an already-generated story id, behind the confirm gate."""
    if not _confirm_render(args.id, getattr(args, "yes", False)):
        return None
    _render_pipeline(args.id)
    print(f"\nDone: {args.id}")
    return args.id


def cmd_all(args) -> list[str]:
    ids = cmd_story(args)
    rendered: list[str] = []
    for sid in ids:
        if not _confirm_render(sid, getattr(args, "yes", False)):
            continue
        _render_pipeline(sid)
        rendered.append(sid)
    if rendered:
        label = f"{len(rendered)} part(s)" if len(rendered) > 1 else rendered[0]
        print(f"\nDone: {label}")
    else:
        print("\nNo videos rendered — scripts are ready for review. "
              "Run `python run.py render <id>` when you're happy with them.")
    return rendered


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run.py",
        description="GoonAndGys — make YouTube Shorts in two steps.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "typical flow:\n"
            "  1. python run.py story  --theme horror --source llm     # write the script\n"
            "       (now edit Stories/<id>.md by hand if you want)\n"
            "  2. python run.py render <id>                            # make the video\n\n"
            "more:\n"
            "  --count N --parts M     N stories x M cliffhanger parts  (= N*M shorts)\n"
            "  run.py all ...          do both steps at once (confirms before each render)\n"
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True, metavar="{story,render}")

    def add_gen_flags(sp):
        sp.add_argument("--theme", choices=config.THEMES, required=True)
        sp.add_argument("--source", choices=["reddit", "llm", "hybrid"], default="reddit")
        sp.add_argument("--count", type=int, default=1,
                        help="how many independent stories to generate "
                             "(total shorts = count * parts)")
        sp.add_argument("--parts", type=int, default=1,
                        help="cliffhanger parts each story is split into (>=1); "
                             "the parts of one story are a connected series")
        sp.add_argument("--voice", default=None)
        sp.add_argument("--background", default=None)
        sp.add_argument("--no-polish", action="store_true",
                        help="skip the quality gate (critic score + punch-up); "
                             "faster and fewer Claude calls, but no score and more "
                             "'mid' scripts slip through")
        sp.add_argument("--yes", "-y", action="store_true",
                        help="skip the per-video review/confirm gate and render straight away")

    # STEP 1 — the two commands a user actually needs are shown in --help.
    sp = sub.add_parser("story", help="STEP 1: write story script(s) to Stories/ for review")
    add_gen_flags(sp); sp.set_defaults(func=cmd_story)

    # STEP 2
    sp = sub.add_parser("render", help="STEP 2: turn a reviewed story <id> into the video")
    sp.add_argument("id", help="story id printed by `story`")
    sp.add_argument("--yes", "-y", action="store_true", help="skip the confirm gate")
    sp.set_defaults(func=cmd_render)

    # Advanced / internal: still work if typed, but pass no `help=` so argparse leaves
    # them out of the --help listing (keeps it to the two commands users need).
    sp = sub.add_parser("all")
    add_gen_flags(sp); sp.set_defaults(func=cmd_all)

    for name, fn in [
        ("voice", cmd_voice),       # stage 2: voiceover + word timings
        ("subs", cmd_subs),         # stage 3: word-synced subtitles
        ("assemble", cmd_assemble), # stage 4: ffmpeg composite to 1080x1920
        ("sidecar", cmd_sidecar),   # stage 5: upload metadata
    ]:
        sp = sub.add_parser(name)
        sp.add_argument("id", help="story id")
        sp.set_defaults(func=fn)

    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except Exception as e:  # surface a clean message, full trace with --debug envs
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
