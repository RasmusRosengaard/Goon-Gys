"""Project paths and environment configuration.

All filesystem locations are derived from PROJECT_ROOT so the pipeline works
regardless of where it is invoked from. See claude.md section 3 for the layout.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()  # load .env if present; no-op otherwise
except ImportError:  # dotenv is optional at runtime
    pass

# src/config.py -> project root is two levels up
PROJECT_ROOT = Path(__file__).resolve().parent.parent

BACKGROUND_DIR = PROJECT_ROOT / "background_videos"   # read-only input clips
STORIES_DIR = PROJECT_ROOT / "Stories"                # canonical story scripts
OUTPUT_DIR = PROJECT_ROOT / "Ready_for_upload"        # finished video + sidecar
BUILD_DIR = PROJECT_ROOT / "build"                    # intermediate artifacts

# Defaults (overridable via env / CLI flags)
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "en-US-GuyNeural")
DEFAULT_BACKGROUND_CATEGORY = os.getenv("DEFAULT_BACKGROUND_CATEGORY", "minecraft_bhop")

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920

# horror = scary; goon = suggestive storytime; goonhorror = the two blended
# (suggestive + eerie/forbidden tension, e.g. "my stepsister was home alone" type).
THEMES = ("horror", "goon", "goonhorror")


def build_dir(story_id: str) -> Path:
    """Working directory for a story's intermediate artifacts (audio, timings, subs)."""
    d = BUILD_DIR / story_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def output_dir(story_id: str) -> Path:
    """Final delivery directory: Ready_for_upload/<id>/."""
    d = OUTPUT_DIR / story_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def env(key: str) -> str | None:
    return os.getenv(key)
