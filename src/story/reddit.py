"""Reddit story sourcing via the public RSS feeds (no API key required).

Reddit hard-blocks (403) the old `.json` endpoints for unauthenticated requests, but
the per-subreddit **RSS/Atom feeds** (`/r/<sub>/top/.rss`) are still served. We scrape
those: each feed entry carries the post title, permalink, and the full selftext (the
real story body is delimited by `<!-- SC_OFF --> ... <!-- SC_ON -->`). Posts are picked
by length and cleaned into natural spoken prose. Keyless — only a browser-like
User-Agent is needed (override with REDDIT_USER_AGENT in .env).
"""
from __future__ import annotations

import html
import random
import re

import requests

from .. import config
from ..models import Story
from . import ids

# Theme -> subreddits to draw from. goon/goonhorror = suggestive storytime, not explicit.
SUBREDDITS = {
    "horror": ["nosleep", "shortscarystories", "creepyencounters"],
    # goon = charged, flirty slow-burn storytime (tension over explicit) — favour
    # confession/tension-of-attraction subs, not the raw r/sex (too explicit / perv).
    "goon": ["confession", "TrueOffMyChest", "relationship_advice", "dating"],
    # blended: forbidden / "home alone with..." tension with an eerie edge
    "goonhorror": ["confession", "TrueOffMyChest", "creepyencounters", "nosleep"],
}

_HEADERS_KEY = "REDDIT_USER_AGENT"
# Reddit 403s the .json API for unauthenticated requests but still serves RSS to a
# browser-like client, so default to one (override with REDDIT_USER_AGENT in .env).
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_ENTRY = re.compile(r"<entry>(.*?)</entry>", re.S)
_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_LINK = re.compile(r'<link[^>]*href="([^"]+)"')
_CONTENT = re.compile(r"<content[^>]*>(.*?)</content>", re.S)
_CATEGORY = re.compile(r'<category[^>]*term="([^"]+)"')
# the real selftext sits between these comments; after SC_ON is just a "submitted by" footer
_BODY = re.compile(r"<!--\s*SC_OFF\s*-->(.*?)<!--\s*SC_ON\s*-->", re.S)
_TAG = re.compile(r"<[^>]+>")


def _strip_html(fragment: str) -> str:
    """RSS content is HTML; turn it into the plain markdown-ish text the cleaner expects."""
    text = html.unescape(fragment)
    text = re.sub(r"</p>\s*<p>", "\n\n", text)   # paragraph breaks -> blank lines
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = _TAG.sub("", text)                     # drop any remaining tags
    return html.unescape(text)


def _clean(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)   # [label](url) -> label
    text = re.sub(r"https?://\S+", "", text)            # bare urls
    text = re.sub(r"[*_`>#]+", "", text)                 # md emphasis/headers
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _parse_entry(entry: str) -> dict:
    """Turn one Atom <entry> into the post dict shape the rest of this module expects."""
    title = _TITLE.search(entry)
    link = _LINK.search(entry)
    content = _CONTENT.search(entry)
    raw = html.unescape(content.group(1)) if content else ""
    body = _BODY.search(raw)
    selftext = _strip_html(body.group(1) if body else raw).strip()
    terms = {t.lower() for t in _CATEGORY.findall(entry)}
    permalink = (link.group(1) if link else "").replace("https://www.reddit.com", "")
    return {
        "title": html.unescape(title.group(1)).strip() if title else "",
        "selftext": selftext,
        "permalink": permalink,
        "over_18": "nsfw" in terms,
        "stickied": False,  # RSS top feed doesn't surface stickies by score
    }


# Listings to draw from. Varying the sort/time window per run rotates the candidate pool
# so we aren't forever pulling this week's top — (sort, time) where time="" means none.
_LISTINGS = [("top", "week"), ("top", "month"), ("top", "year"), ("hot", "")]


def _fetch(subreddit: str, *, sort: str = "top", t: str = "week", limit: int = 50) -> list[dict]:
    ua = config.env(_HEADERS_KEY) or _DEFAULT_UA
    query = f"?limit={limit}" + (f"&t={t}" if t else "")
    url = f"https://www.reddit.com/r/{subreddit}/{sort}/.rss{query}"
    resp = requests.get(url, headers={"User-Agent": ua}, timeout=20)
    resp.raise_for_status()
    resp.encoding = "utf-8"  # Atom feed is UTF-8; don't let requests guess (mangles ’ “ ”)
    return [_parse_entry(e) for e in _ENTRY.findall(resp.text)]


_SOURCE_URL = re.compile(r"^source_url:\s*(.+?)\s*$", re.M)

# Topics to skip entirely regardless of theme: suicide / self-harm and the like — these
# are off-brand and demonetizing on YouTube. NOTE: goon is meant to be the suggestive /
# "perv" content, so nothing sexual is blocked here — only genuinely unsafe topics.
_BLOCKED = re.compile(
    r"(?:\bsuicid(?:e|al)\b"
    r"|\bkill(?:ing|ed)?\s+(?:myself|himself|herself|themselves|yourself)\b"
    r"|\b(?:end|ended|ending|take|took|taking)\s+(?:my|his|her|their)\s+(?:own\s+)?life\b"
    r"|\bself[\s-]?harm\b"
    r"|\bcut(?:ting)?\s+myself\b"
    r"|\bgave\s+myself\b"
    r"|\boverdos(?:e|ed|ing)?\b"
    r"|\bhang(?:ed|ing)?\s+(?:myself|himself|herself)\b)",
    re.I,
)


def _is_blocked(*texts: str) -> bool:
    return any(_BLOCKED.search(t or "") for t in texts)


def _norm_permalink(url: str) -> str:
    """Reduce a reddit URL to its bare permalink path so the same post compares equal
    however it was stored (with/without domain or trailing slash)."""
    return url.strip().strip("'\"").replace("https://www.reddit.com", "").rstrip("/")


def used_permalinks() -> set[str]:
    """Permalinks of Reddit posts already turned into stories — read from the
    `source_url` of every Stories/*.md so we never source the same post twice."""
    used: set[str] = set()
    for p in config.STORIES_DIR.glob("*.md"):
        if p.name == "template.md":
            continue
        try:
            m = _SOURCE_URL.search(p.read_text(encoding="utf-8"))
        except OSError:
            continue
        if not m:
            continue
        val = m.group(1).strip().strip("'\"")
        if val.startswith(("/r/", "http")):  # a real permalink, not blank or a comment
            used.add(_norm_permalink(val))
    return used


def choose_post(
    theme: str,
    *,
    subreddit: str | None = None,
    min_chars: int = 600,
    max_chars: int = 3500,
    exclude: set[str] | None = None,
) -> dict:
    """Return a RANDOM suitable raw Reddit post for a theme (no Story built yet). Gathers
    every eligible candidate across the subreddits and picks one at random, so re-running
    doesn't keep grabbing the top post — and if you delete a story, the next run is very
    unlikely to land on the same one again. Skips posts already used by an existing story
    (and anything in `exclude`) so it never produces a duplicate source."""
    if theme not in SUBREDDITS:
        raise ValueError(f"no subreddits configured for theme '{theme}'")
    subs = [subreddit] if subreddit else SUBREDDITS[theme]
    seen = used_permalinks() | {_norm_permalink(u) for u in (exclude or set())}

    candidates: list[dict] = []
    skipped_dupes = False
    for sub in subs:
        sort, t = random.choice(_LISTINGS)  # rotate the listing so the pool varies per run
        try:
            posts = _fetch(sub, sort=sort, t=t)
        except requests.RequestException:
            continue  # one subreddit failing shouldn't abort the whole pick
        for post in posts:
            body = (post.get("selftext") or "").strip()
            if post.get("over_18") and theme not in ("goon", "goonhorror"):
                continue
            if post.get("stickied") or not (min_chars <= len(body) <= max_chars):
                continue
            if _is_blocked(post.get("title", ""), body):  # suicide / self-harm etc.
                continue
            if _norm_permalink(post.get("permalink", "")) in seen:
                skipped_dupes = True
                continue
            candidates.append(post)

    if candidates:
        return random.choice(candidates)
    hint = (
        " (all candidates were already used — try again, or another subreddit)"
        if skipped_dupes else ""
    )
    raise RuntimeError(f"no suitable post found in r/{', r/'.join(subs)}{hint}")


def fetch_seed(theme: str, **opts) -> tuple[str, str, str]:
    """Pick a post and return (title, cleaned_body, permalink) — the raw seed a
    single short or a multi-part series is built from."""
    post = choose_post(theme, **opts)
    title = html.unescape(post["title"]).strip()
    return title, _clean(post["selftext"]), "https://www.reddit.com" + post.get("permalink", "")


def generate(
    theme: str,
    *,
    subreddit: str | None = None,
    min_chars: int = 600,
    max_chars: int = 3500,
    clean_with_llm: bool = False,   # faithful by default: light clean only, keep the post
    **_,
) -> Story:
    title, body, url = fetch_seed(
        theme, subreddit=subreddit, min_chars=min_chars, max_chars=max_chars
    )

    from ..claude_cli import available

    if clean_with_llm and available():
        from . import llm

        body = llm.rewrite(title, body, theme)

    return Story(
        id=ids.make_id(theme, title),
        title=title,
        body=body,
        theme=theme,
        source="reddit",
        source_url=url,
        background_category=config.DEFAULT_BACKGROUND_CATEGORY,
        voice=config.DEFAULT_VOICE,
        created=__import__("datetime").date.today().isoformat(),
    )
