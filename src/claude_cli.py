"""Text generation via the Claude Code CLI in headless mode — no API key.

The story writer (Stage 1) and sidecar metadata (Stage 5) call Claude through the
same `claude` CLI you use interactively, via `claude -p` (print/headless). This
keeps the project key-free: auth comes from the CLI's own login. See claude.md.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile

# Pinned to Sonnet 4.6: plenty strong for story/metadata writing and much cheaper per
# token than Opus. Set to None to fall back to the CLI's configured default, or pin
# another id (e.g. "claude-opus-4-8" for top quality, "claude-haiku-4-5" for cheapest).
DEFAULT_MODEL: str | None = "claude-sonnet-4-6"

# Empty MCP config + --strict-mcp-config makes the headless CLI ignore every
# user/project MCP server, so a tiny prompt no longer drags ~dozens of MCP tool
# definitions (Higgsfield, Vercel, …) along as input tokens on every call.
_EMPTY_MCP = '{"mcpServers":{}}'

# Run each call from an empty scratch dir, NOT the project root, so the CLI does not
# auto-load this project's claude.md / .claude settings / skills as extra context.
# Our prompts are fully self-contained, so they need none of it.
_SCRATCH = os.path.join(tempfile.gettempdir(), "goonandgys_claude_scratch")


def available() -> bool:
    return shutil.which("claude") is not None


def complete(
    user: str,
    system: str | None = None,
    *,
    model: str | None = DEFAULT_MODEL,
    timeout: int = 240,
) -> str:
    """Send a prompt to the Claude CLI and return its text response.

    The user prompt is piped over stdin to avoid shell-escaping/length limits;
    the system prompt is appended via --append-system-prompt.
    """
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("the `claude` CLI is not on PATH — install Claude Code")

    cmd = [exe, "-p", "--output-format", "text",
           "--mcp-config", _EMPTY_MCP, "--strict-mcp-config"]
    if system:
        cmd += ["--append-system-prompt", system]
    if model:
        cmd += ["--model", model]

    os.makedirs(_SCRATCH, exist_ok=True)
    # Force UTF-8 decoding: the CLI emits UTF-8, but text=True would otherwise decode
    # with the Windows locale (cp1252) and mangle smart quotes / em-dashes / ellipses.
    proc = subprocess.run(
        cmd, input=user, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, cwd=_SCRATCH,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude CLI failed (exit {proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout.strip()


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a CLI reply, tolerating code fences or stray
    prose around it. Raises a clear error (with a snippet) when there is no JSON at all,
    instead of a cryptic 'substring not found'."""
    s = text.strip()
    fenced = _FENCE.search(s)
    if fenced:
        s = fenced.group(1).strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end < start:
        snippet = (text.strip()[:300] or "(empty response)")
        raise ValueError(f"model returned no JSON object. Got: {snippet!r}")
    return json.loads(s[start : end + 1])


def complete_json(
    user: str,
    system: str | None = None,
    *,
    model: str | None = DEFAULT_MODEL,
    timeout: int = 240,
    retries: int = 1,
) -> dict:
    """Like complete(), but require a JSON object back — retrying once if the model
    happens to reply with prose instead of JSON."""
    last_err: Exception | None = None
    for _ in range(retries + 1):
        text = complete(user, system, model=model, timeout=timeout)
        try:
            return extract_json(text)
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
    raise RuntimeError(f"the model did not return valid JSON: {last_err}")
