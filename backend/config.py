"""Settings for the news pipeline. Everything can be overridden with environment variables."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(os.environ.get("RR_ROOT", Path(__file__).resolve().parent.parent))
DATA = ROOT / "data"
NEWS_DIR = DATA / "news"
MANIFEST = DATA / "manifest.json"
STATE_FILE = ROOT / "backend" / "state" / "seen.json"
PENDING_FILE = ROOT / "backend" / "state" / "pending.json"
SCHEMA_DOC = ROOT / "docs" / "DATA_SCHEMA.md"
STYLE_EXAMPLE = NEWS_DIR / "claude-sonnet-5-5.json"
TIP_EXAMPLE = NEWS_DIR / "openai-retained-reasoning-compaction.json"
VALIDATOR = ROOT / "scripts" / "validate_data.py"

TIMEZONE = "Asia/Seoul"

# Claude API models. The summary model writes the Korean article; the triage model only
# decides which feed entries are model news, so a small model is enough.
SUMMARY_MODEL = os.environ.get("RR_MODEL", "claude-sonnet-5-5")
TRIAGE_MODEL = os.environ.get("RR_TRIAGE_MODEL", "claude-haiku-4-5-20251001")

# Safety limits per run.
MAX_NEW_ITEMS = int(os.environ.get("RR_MAX_ITEMS", "5"))
LOOKBACK_DAYS = int(os.environ.get("RR_LOOKBACK_DAYS", "7"))
MAX_LISTING_FETCHES = int(os.environ.get("RR_MAX_LISTING_FETCHES", "30"))
PAGE_TEXT_LIMIT = 60_000

# When a page blocks scripted requests, retry through the Jina Reader proxy (r.jina.ai).
# Set RR_READER_FALLBACK=0 to turn it off.
READER_FALLBACK = os.environ.get("RR_READER_FALLBACK", "1") != "0"
READER_PREFIX = "https://r.jina.ai/"

USER_AGENT = os.environ.get(
    "RR_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 ReleaseRadarBot/1.0 (+https://release-radar-ten.vercel.app)",
)
HTTP_TIMEOUT = 30


@dataclass(frozen=True)
class Source:
    name: str
    company: str          # openai | anthropic | google
    kind: str             # rss | listing | sitemap
    url: str
    base: str = ""        # for listing pages: prefix for relative links
    priority: int = 0     # higher wins when two sources carry the same article
    pattern: str = ""     # listing pages: regex for article paths (default: ANTHROPIC_ARTICLE_RE)
    # If an article from this source has no readable date, treat it as published today. Only for the
    # Anthropic newsroom, whose new links appear at the top; elsewhere an undated post is skipped so
    # old blog posts are never mistaken for new ones.
    undated_is_new: bool = False


SOURCES = [
    Source("OpenAI News", "openai", "rss", "https://openai.com/news/rss.xml", priority=2),
    Source("Anthropic News", "anthropic", "listing", "https://www.anthropic.com/news",
           base="https://www.anthropic.com", priority=2, undated_is_new=True),
    Source("Anthropic sitemap", "anthropic", "sitemap", "https://www.anthropic.com/sitemap.xml",
           base="https://www.anthropic.com", priority=1, undated_is_new=True),
    Source("Google Gemini models blog", "google", "rss",
           "https://blog.google/innovation-and-ai/models-and-research/gemini-models/rss/", priority=2),
    Source("Google DeepMind blog", "google", "rss", "https://deepmind.google/blog/rss.xml", priority=1),
    # Official usage tips and prompting guides usually appear on these blogs, not the main newsrooms.
    Source("OpenAI Developers blog", "openai", "listing", "https://developers.openai.com/blog",
           base="https://developers.openai.com", priority=1, pattern=r"^/blog/(?!topic/|tag/|page/)[a-z0-9-]+/?$"),
    # The Claude blog moved from claude.com/blog to claude.com/resources/articles (Oct 2026); old /blog/
    # links still redirect, and the slug is the same, so posts already on the site are still recognized.
    Source("Claude blog", "anthropic", "listing", "https://claude.com/resources/articles", base="https://claude.com",
           priority=1, pattern=r"^/(?:resources/articles|blog)/(?!category/|tag/|page/)[a-z0-9-]+/?$"),
    Source("Google Gemini app blog", "google", "rss", "https://blog.google/products/gemini/rss/", priority=1),
    Source("Google Developers blog", "google", "rss", "https://developers.googleblog.com/feeds/posts/default"),
    Source("Google Cloud AI blog", "google", "rss", "https://cloudblog.withgoogle.com/products/ai-machine-learning/rss/"),
]

# Anthropic's newsroom links to article pages under /news/ and to launch pages at the top level
# (/claude-sonnet-5-5, /glasswing ...). Only these paths count as articles.
ANTHROPIC_ARTICLE_RE = re.compile(
    r"^/(news/[a-z0-9-]+|claude-[a-z0-9-]+|glasswing|[a-z0-9-]*(?:model|claude|opus|sonnet|haiku|fable|mythos)[a-z0-9-]*)/?$"
)

# Cheap first filter before any API call: the title or summary must mention something model-like.
RELEVANT_RE = re.compile(
    r"(?i)\b(gpt[-‑ ]?\d|o\d\b|codex|sora|chatgpt|gpt|claude|opus|sonnet|haiku|fable|mythos|gemini|[a-z]*gemma|veo|imagen|"
    r"lyria|nano banana|omni|models?|api|prompt(?:s|ing)?|realtime|tts|transcribe|reasoning|agents?|"
    r"tips?|guide|best practices|skills?|antigravity|ai studio)\b"
)
