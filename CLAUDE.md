# GoonAndGys — YouTube Shorts Generator

> Read this top to bottom before touching anything. This file is the single source of
> truth for what the project is, how the pipeline fits together, and the conventions every
> stage must follow. If you change the architecture, update this file in the same commit.

## 1. What this project does

GoonAndGys is an automated pipeline that produces **vertical YouTube Shorts (1080×1920)**.
Each Short is a narrated "true story" voiced over muxed onto looping background gameplay,
with **word-synced subtitles** and a **sidecar** of upload metadata (title, description,
tags). Two content themes for now:

- **`horror`** — scary / unsettling true stories.
- **`goon`** — "goon-material" stories (suggestive storytime content).
- **`goonhorror`** — the two blended: suggestive + eerie/forbidden tension
  ("home alone with someone I shouldn't be", stepsibling-type setups) with a creeping
  edge. Innuendo and suspense only, never explicit (YouTube-safe).

Each Short can be **standalone** or one **part of a multi-part series** (Part 1, 2, 3…),
where every non-final part ends on a cliffhanger to pull viewers to the next one. See
section 4a.

The end-to-end flow for one video:

```
theme ──▶ [1] story ──▶ [2] voiceover ──▶ [3] subtitles ──▶ [4] assemble ──▶ [5] sidecar
          (script)      (TTS audio +      (word-level        (ffmpeg          (upload
                         word timings)     captions)          mux + burn)      metadata)
```

The defining constraint: **the on-screen captions must match the exact words spoken,
word-for-word, with correct timing.** The story script is the canonical text — TTS reads it
verbatim and subtitles are derived from the same words, so they can never drift.

## 2. Tech stack (decided)

- **Language/runtime:** Python 3.11+.
- **Video:** `ffmpeg` (must be on PATH). Driven via subprocess or `ffmpeg-python`.
- **TTS:** local/free first, pluggable. Default `edge-tts` (free, gives word boundaries).
  Optional providers: Piper (offline), ElevenLabs / OpenAI TTS (cloud, paid, higher quality).
- **Story sourcing:** hybrid — Reddit scraping (PRAW or read-only JSON) **and** LLM
  generation **via the Claude Code CLI** (`claude -p`, no API key — same login as this
  session). Both feed the same Story format.
- **No API keys / no cloud accounts required** for the default path: story + sidecar text
  come from the `claude` CLI, and the default voice (edge-tts) is free and keyless.
- **Subtitles:** prefer TTS-native word boundaries (edge-tts emits them); fall back to
  Whisper forced alignment when a provider gives no timings.

> Nothing is implemented yet — the repo is currently just the folder skeleton + templates
> described below. Sections 4–5 describe the *intended* design. Mark anything you build as
> done by checking it off in Section 7.

## 3. Repository layout

```
GoonAndGys/
├── claude.md                      # ← this file
├── background_videos/             # input: looping gameplay clips, grouped by category
│   └── minecraft_bhop/            #   one folder per visual style (e.g. subway_surfers, gta_ramps)
│       └── *.mp4                  #   raw clips; theme-agnostic, reused across stories
├── Stories/                       # generated story scripts (the canonical spoken text)
│   ├── template.md                #   the required format for every story file
│   └── <id>.md                    #   one file per story (see template)
└── Ready_for_upload/              # output: finished videos + metadata, ready to post
    └── <id>/                      #   one folder per finished Short
        ├── video_file.mp4         #   final 1080×1920 render with burned-in subtitles
        └── sidecar.txt            #   upload metadata (title/description/tags/...)
```

Conventions:
- **`<id>`** is a stable slug shared across `Stories/<id>.md` and `Ready_for_upload/<id>/`.
  Use `YYYYMMDD-<theme>-<short-slug>` (e.g. `20260608-horror-the-attic`).
- `background_videos/<category>/` clips are **inputs only** — never write there.
- A background category is chosen per story; categories are visual styles, not themes
  (any category can back either theme).

## 4. The pipeline, stage by stage

Each stage is a separate, independently runnable module under `src/`. A story can be
re-run from any stage. Suggested module map:

| Stage | Module | Input | Output |
|-------|--------|-------|--------|
| 1 Story | `src/story/` | theme | `Stories/<id>.md` |
| 2 Voice | `src/voice/` | `Stories/<id>.md` | audio file + word timings (JSON) |
| 3 Subs  | `src/subtitles/` | word timings | `.ass`/`.srt` caption file |
| 4 Assemble | `src/assemble/` | audio + subs + bg clip | `Ready_for_upload/<id>/video_file.mp4` |
| 5 Sidecar | `src/sidecar/` | `Stories/<id>.md` | `Ready_for_upload/<id>/sidecar.txt` |

**Review gate (human-in-the-loop).** The canonical, editable artifact is `Stories/<id>.md`
itself — its body (under `# Title`) is the exact spoken text. The pipeline is two steps
with the user in between:
1. **Generate** — `python run.py story ...` writes `Stories/<id>.md` (status `draft`).
   Nothing is rendered yet.
2. **Edit** — the user can hand-edit `Stories/<id>.md` directly: the body for the spoken
   words, the frontmatter for title/description/tags.
3. **Render** — `python run.py render <id>` re-reads `Stories/<id>.md` (picking up any
   edits), marks it `approved`, then runs Stages 2→5.

`python run.py all ...` chains both but **pauses at a confirm gate per video** before
rendering (so edits can be made); `-y/--yes` skips the gate. A non-interactive `all` with
no `--yes` stops after writing scripts (never auto-renders). See `run.py`.

### Stage 1 — Story sourcing (`src/story/`)
Pluggable providers behind a common interface, selected by `--source`:
- **`reddit`** — **faithful**: scrape a theme's subreddits, strip markdown, light cleanup;
  keep the redditor's story (`clean_with_llm=False` by default).
- **`hybrid`** — **transformative**: pull a Reddit post as a *seed*, then have Claude
  (`llm.reshape`) rebuild it as a punchy Short — stronger hook, tighter pacing, sharper end.
- **`llm`** — fully original from the theme prompt, no Reddit (`llm.generate`).

`llm.generate` makes **one** Claude call that returns the story **plus** its title,
description and tags as JSON (`_GEN_SYSTEM`); the metadata is stored on the `Story` and
reused by Stage 5. `rewrite`/`reshape` still return plain spoken text.

**Quality gate (`src/story/critic.py`) — default on, skip with `--no-polish`.** Raw
single-shot drafts were often "mid", so every transformative story (llm / hybrid /
series) now passes through a critic pass before it is saved:
- One extra Claude call: a harsh "script doctor" scores the draft 0–10 on hook,
  substance, escalation, payoff, clarity and delivery (5 = mid, 7 = good, 9+ = viral
  bet), **rewrites it to fix every weakness**, and re-syncs title/description/tags/
  pinned_comment to the revised script (so polished hybrids also need no Stage 5 call).
- The score + one-line notes land in frontmatter (`quality`, `quality_notes`) and are
  printed at the review gate, so weak scripts are visible before rendering.
- `llm.generate` enforces a bar: if even the polished script scores below
  `critic.MIN_SCORE` (7.5), it regenerates from scratch — feeding the editor's
  rejection notes into the retry prompt — up to `attempts` (2) times, keeping the
  best-scoring candidate. Series get one whole-series polish call (keeps part count
  and cliffhangers) but no regen loop.
- A rewrite that breaks the ~60s format (word-count sanity bounds) is discarded and
  the original body kept; without the `claude` CLI the gate is a no-op (`quality: 0`).
- Cost: a polished llm short = 2 Claude calls (up to 4 if a draft is rejected);
  `--no-polish` restores the old 1-call behavior. `reddit` (faithful) is never polished.

**Variety memory (`src/story/variety.py`).** Each CLI call is memoryless, so
generation used to drift back to the same stock premises. `llm.generate` and original
series prompts now append the titles + opening lines of the ~12 most recent same-theme
`Stories/*.md` with an instruction to differ from all of them in premise, setting,
cast, and opening.

All LLM work goes through the **Claude Code CLI** (`src/claude_cli.py` → `claude -p`); no key.
Each call is made with `--strict-mcp-config` + an empty MCP config and from an empty
scratch cwd, so the headless CLI does **not** load this project's `claude.md`, skills,
or any MCP servers as input-token overhead. Keep prompts self-contained so this holds.

> **CLI system-prompt bug (do not regress this):** on CLI 2.1.170/Windows, a
> multi-paragraph system prompt passed via `--system-prompt` /
> `--append-system-prompt` / `--system-prompt-file` is **truncated at the first
> blank line** — for months the model received only the first paragraph of the craft
> rules, which is where "mid" scripts came from. `claude_cli.complete` therefore
> sends the full multi-paragraph brief **inside the stdin user message** (a `BRIEF`
> block, stdin arrives intact) and passes only a single-line role via
> `--system-prompt` (survives the bug + replaces Claude Code's huge default agent
> prompt, saving thousands of input tokens per call). `complete_json` additionally
> re-anchors the JSON-only demand at the end of the user prompt on every attempt.

> **Reddit access:** the public `.json` endpoints are **403 / hard-blocked** for
> unauthenticated requests, so `src/story/reddit.py` instead scrapes the still-served
> **RSS/Atom feeds** (`/r/<sub>/top/.rss`). Each entry carries the title, permalink, and
> full selftext (the body is delimited by `<!-- SC_OFF -->…<!-- SC_ON -->`). This is
> keyless — it only needs a browser-like `User-Agent` (override via `REDDIT_USER_AGENT`).
> Both `reddit` (faithful) and `hybrid` (reshaped) funnel through `reddit._fetch`, so the
> single RSS path serves both, including multi-part series. `choose_post` gathers every
> eligible post across the theme's subreddits (rotating the sort/time window per run) and
> picks one **at random**, so re-runs don't keep grabbing the top post. It also **de-dupes
> by source**: it skips any post whose permalink already appears as the `source_url` of an
> existing `Stories/*.md` (via `reddit.used_permalinks()`), so re-running reddit/hybrid
> never sources the same Reddit post twice. (Delete a story and its post becomes eligible
> again — but the random pick makes re-landing on it unlikely.) It also drops posts on **off-brand /
> demonetizing topics** (suicide, self-harm, overdose, etc.) via the `_BLOCKED` regex on
> title+body — `goon`'s suggestive content is intentionally *not* filtered.

Output is always a `Stories/<id>.md` file matching `Stories/template.md`. The body is the
**exact text to be spoken** — write it clean (no markdown, no stage directions inside the
prose) so TTS reads only real words.

### Stage 2 — Voiceover (`src/voice/`)
Pluggable TTS providers behind one interface so voices are swappable:
- **`edge-tts`** (default) — free; **emits `WordBoundary` events → use these directly as
  word-level timings.** This is the cheapest path to perfectly-synced subtitles.
- **`piper`** — offline/local fallback.
- **`elevenlabs`** / **`openai`** — paid, higher quality; opt-in via env keys.

Outputs: an audio file (wav/mp3) **and** a `word_timings.json` — a list of
`{word, start, end}` (seconds). If a provider can't emit boundaries, run Whisper forced
alignment over the generated audio + known script to produce the same JSON.

### Stage 3 — Subtitles (`src/subtitles/`)
Turn `word_timings.json` into a caption file. Requirements:
- **One or few words on screen at a time**, highlighted as spoken (karaoke style) — typical
  Shorts look. `.ass` is preferred (styling + per-word karaoke); `.srt` acceptable as a
  simpler fallback.
- Captions must use the **same words** as the script — no paraphrasing, no autocaption guess.
- Centered, large, high-contrast, safe-area aware for 1080×1920.

### Stage 4 — Assemble (`src/assemble/`)
`ffmpeg` composites the final video:
1. Pick a clip from `background_videos/<category>/`; loop/trim to the voiceover length.
2. Scale + center-crop to exactly **1080×1920**.
3. **Replace** the gameplay audio with the voiceover (do not mix in original game sound
   unless intentionally ducked).
4. Burn in the subtitle file from Stage 3.
5. Write to `Ready_for_upload/<id>/video_file.mp4` (H.264 + AAC, faststart).

### Stage 5 — Sidecar (`src/sidecar/`)
Generate `Ready_for_upload/<id>/sidecar.txt` from the story. Format defined in
`Ready_for_upload/template_1/sidecar.txt`. For series parts the title gets a
`(Part X/N)` suffix and the description teases the next part.

**Token note:** for `--source llm`, the description/tags are produced *in the same
single Claude call as the story* (Stage 1 — see below) and stored on the `Story`
(`description`/`tags` frontmatter). Stage 5 reuses them and makes **no** Claude call.
It only falls back to its own `_llm_meta` call when those fields are empty (reddit
stories, un-polished hybrids, and series parts — the critic pass fills them for
polished standalone llm/hybrid stories).

## 4a. Multi-part series (`src/story/series.py`)
A **series** is one story split into N parts, each rendered as its own Short to "edge"
viewers into watching the next.

**Batch sizing — `--count` × `--parts`.** `--count M` generates M *independent* stories;
`--parts N` splits each into N connected cliffhanger parts. Total shorts = `M * N`. E.g.
`--count 2 --parts 2` = 4 shorts: story A (part 1→2, connected) and story B (part 1→2,
connected); A and B are unrelated. `run.py` gives each story a collision-free `<id>` (it
bumps a `-2`, `-3` suffix on the base/series id) so several stories never overwrite each
other. Mechanics of a single series:

- `--parts N` on `story`/`all` triggers it. `src/story/series.py` produces N linked
  `Story` objects; each then flows through Stages 2→5 **unchanged** (a part is just a
  Story). The decoupled stages are what make this free.
- The Claude CLI writes N parts where every non-final part **ends on a cliffhanger**;
  the final part resolves. Without the CLI, a naive sentence-split fallback is used
  (no synthesized cliffhangers).
- All parts share a **`series_id`**; part ids are `<series_id>_part1`, `_part2`, … and
  each gets its own `Stories/<id>.md` and `Ready_for_upload/<id>_partN/`.
- Story frontmatter carries `series_id`, `part`, `total_parts` (standalone = part 0,
  total_parts 1).
- A spoken CTA ("Follow for part two.") is appended to every non-final part's body, so
  it is voiced **and** captioned — preserving the captions==spoken-words rule.

## 4b. Background start offset (`src/assemble/`)
Where in the background clip each Short begins:
- **Standalone short, or part 1 of a series** → a **random offset** into the clip
  (`random_start=True`), so repeated videos don't reuse the same footage.
- **Later series parts** → **continue exactly where the previous part ended**
  (`start_offset = prev.start + prev.duration`, same clip), so the gameplay flows
  seamlessly across the whole series.

The orchestrator records what each render used in `build/<id>/render.json`
(`clip`, `start`, `duration`, `clip_duration`); part N reads part N-1's file to chain.
Therefore series parts must be assembled in order (1 before 2 …). ffmpeg seeks with
`-ss` before a looped input, so offsets beyond the clip length wrap around safely.

## 5. Configuration & secrets
- **No API keys required for the default path.** LLM text (story + sidecar) is generated by
  the `claude` CLI via `src/claude_cli.py`; the default voice (edge-tts) is keyless.
- `.env` only holds non-secret defaults (`REDDIT_USER_AGENT`, `DEFAULT_VOICE`,
  `DEFAULT_BACKGROUND_CATEGORY`) — see `.env.example`. Never commit `.env`.
- The `claude` CLI and `ffmpeg` must both be installed and on PATH.
- Optional paid providers (ElevenLabs/OpenAI voices in `src/voice/cloud.py`) are opt-in
  stubs and would need their own keys — not used by default.
- Python deps are pinned in `requirements.txt`.

## 6. Conventions for agents
- Keep the five stages decoupled and individually runnable — debugging one stage should not
  require re-running the others.
- The **story script is canonical**: TTS and subtitles both derive from it; never let
  captions come from re-transcribing the audio when exact text is already known.
- Reuse `<id>` across `Stories/` and `Ready_for_upload/`.
- Treat `background_videos/` as read-only input.
- `goon` and `goonhorror` content is suggestive storytime, not explicit material — keep
  scripts within YouTube's monetization-safe bounds (innuendo/tension only).
- Update this file whenever the architecture or folder conventions change.

## 7. Build status (check off as implemented)
- [x] Stage 1 — Story sourcing (reddit / llm / hybrid) via Claude CLI
- [x] Stage 2 — Voiceover TTS + word timings (edge-tts)
- [x] Stage 3 — Word-synced subtitles (.ass karaoke)
- [x] Stage 4 — ffmpeg assemble to 1080×1920
- [x] Stage 5 — Sidecar metadata
- [x] Multi-part series (`--parts N`, cliffhangers)
- [x] Quality gate — critic score + punch-up + regen-below-bar (`src/story/critic.py`)
- [x] Variety memory — recent premises fed back to avoid repeats (`src/story/variety.py`)
- [x] Orchestrator / CLI tying stages 1→5 together (`run.py`)
- [x] `requirements.txt` + `.env.example`

Still TODO / not yet wired: Piper + cloud TTS providers, Whisper alignment fallback,
auto-upload to YouTube. ffmpeg path is implemented but only smoke-tested without real
background clips (the `background_videos/` folders are empty placeholders).
