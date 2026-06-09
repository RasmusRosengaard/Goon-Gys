# GoonAndGys — YouTube Shorts Generator

Automated pipeline that turns a theme into a finished vertical **YouTube Short
(1080×1920)**: a narrated first-person story voiced over looping gameplay, with
word-synced karaoke captions and an upload-metadata sidecar.

Themes: `horror` (scary), `goon` (suggestive storytime), `goonhorror` (the two blended).
All suggestive content is innuendo/tension only — YouTube monetization-safe.

> Architecture and stage details live in `CLAUDE.md`. This file is just how to **set up
> and run** it.

---

## 1. Prerequisites (install once, system-wide)

| Tool | Why | Check |
|------|-----|-------|
| **Python 3.11+** | runs the pipeline | `python --version` |
| **ffmpeg** (on PATH) | builds/encodes the video | `ffmpeg -version` |
| **Claude Code CLI** (`claude` on PATH) | writes the stories — no API key, uses your Claude login | `claude --version` |

- Install Claude Code from https://claude.com/claude-code, then sign in once
  (`claude` interactively). The pipeline calls `claude -p` under the hood — **no API key
  needed**.
- The default voice (`edge-tts`) is free and keyless.

---

## 2. One-time project setup

```powershell
# from the project root: C:\Users\rasmu\Dev\GoonAndGys

# 1. create a virtual environment
python -m venv .venv

# 2. activate it
#    Windows PowerShell:
.\.venv\Scripts\Activate.ps1
#    (Windows cmd:            .venv\Scripts\activate.bat)
#    (macOS / Linux:          source .venv/bin/activate)

# 3. install Python dependencies
pip install -r requirements.txt

# 4. create your .env from the template (optional — only non-secret defaults)
copy .env.example .env       # PowerShell/cmd
#   cp .env.example .env      # macOS / Linux
```

If PowerShell blocks the activate script, allow it for your user once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

You'll know the venv is active when your prompt is prefixed with `(.venv)`.

### Add background gameplay clips
Drop one or more looping `.mp4` clips into a category folder under `background_videos/`,
e.g. `background_videos/minecraft_bhop/clip.mp4`. Categories are visual styles (any can
back any theme). These are **inputs only** — the pipeline never writes here.

---

## 3. Run the pipeline (start to end)

The normal flow is **two steps with you in the middle** — generate scripts, edit them by
hand, then render the videos.

```powershell
# (make sure the venv is active: prompt shows (.venv))

# STEP 1 — generate the story script(s). Nothing is rendered yet.
python run.py story --theme goonhorror --source llm

# -> writes Stories/<id>.md and prints each <id> + its path.

# STEP 2 — (optional) hand-edit the story in Stories/<id>.md
#    body (under the # Title)   = the exact spoken words (edit this for the story)
#    frontmatter (--- block)    = title / description / tags

# STEP 3 — render the video for that id (asks you to confirm first)
python run.py render <id>

# -> Ready_for_upload/<id>/video_file.mp4   (final 1080x1920 short)
#    Ready_for_upload/<id>/sidecar.txt      (title/description/tags for upload)
```

### Batch + series sizing
`--count` = how many **independent** stories; `--parts` = how many **connected**
cliffhanger parts each story is split into. Total shorts = `count × parts`.

```powershell
# 2 separate stories, each split into 2 connected parts = 4 shorts total
python run.py story --theme horror --source llm --count 2 --parts 2
```

### One-shot (generate + render with a confirm gate)
```powershell
python run.py all --theme goon --source llm           # pauses to confirm each script
python run.py all --theme goon --source llm -y         # skip the gate, render straight
```

### Command arguments (`story` / `all`)
| Argument | Values | Default | Meaning |
|----------|--------|---------|---------|
| `--theme` | `horror` / `goon` / `goonhorror` | *required* | content lane |
| `--source` | `llm` / `reddit` / `hybrid` | `reddit` | `llm` = original; `reddit` = faithful real post; `hybrid` = real post reshaped by Claude |
| `--count` | integer | `1` | number of independent stories |
| `--parts` | integer | `1` | connected cliffhanger parts per story |
| `--voice` | edge-tts voice id | `en-US-GuyNeural` | TTS voice |
| `--background` | folder in `background_videos/` | `minecraft_bhop` | gameplay style |
| `-y`, `--yes` | flag | off | (`all`) skip the per-video confirm gate |

### Run individual stages (advanced / debugging)
Stages are decoupled; each reads what the previous one wrote:
```powershell
python run.py voice    <id>      # stage 2: TTS audio + word timings
python run.py subs     <id>      # stage 3: karaoke .ass captions
python run.py assemble <id>      # stage 4: ffmpeg composite to 1080x1920
python run.py sidecar  <id>      # stage 5: upload metadata
```

`python run.py --help` lists everything.

---

## 4. Output

```
Ready_for_upload/<id>/
├── video_file.mp4   # final 1080x1920 short, burned-in captions
└── sidecar.txt      # title / description / tags / hashtags for upload
```

`build/<id>/` holds intermediate artifacts (voice.mp3, word_timings.json, subs.ass,
render.json) and is safe to delete between runs.

---

## 5. Notes
- **Cost:** story generation uses the `claude` CLI pinned to **Sonnet 4.6**, one call per
  short (title/description/tags come back in the same call). No other stage uses the LLM.
- The captions are derived from the exact spoken words, so they never drift from the audio.
- Channel identity lives in `niche.txt` (name + description) and `logo.svg` (channel logo).
- **Reddit sourcing** (`--source reddit` / `hybrid`) scrapes the public RSS feeds (the
  `.json` API is 403-blocked) — keyless, no Reddit account needed. `reddit` keeps the
  original post faithfully; `hybrid` has Claude reshape it into a punchier Short.
```
