"""Collect recent posts from each official source (RSS feeds and the Anthropic newsroom page)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import feedparser
import requests
from bs4 import BeautifulSoup

from . import config

log = logging.getLogger(__name__)


@dataclass
class Entry:
    title: str
    url: str
    company: str
    source: str
    published: date | None = None
    summary: str = ""
    priority: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return normalize_url(self.url)


def normalize_url(url: str) -> str:
    """Compare URLs without scheme, www., query, fragment or trailing slash."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, "", ""))


def http_get(url: str, *, accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8") -> requests.Response:
    return requests.get(
        url,
        headers={"User-Agent": config.USER_AGENT, "Accept": accept, "Accept-Language": "en-US,en;q=0.9"},
        timeout=config.HTTP_TIMEOUT,
    )


def parse_date(value) -> date | None:
    """Accept RFC 822, ISO 8601 or feedparser's struct_time; return the calendar date."""
    if not value:
        return None
    if hasattr(value, "tm_year"):
        return date(value.tm_year, value.tm_mon, value.tm_mday)
    text = str(value).strip()
    try:
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_rss(xml: bytes | str, source: config.Source) -> list[Entry]:
    feed = feedparser.parse(xml)
    entries = []
    for item in feed.entries:
        link = item.get("link") or ""
        title = (item.get("title") or "").strip()
        if not link or not title:
            continue
        published = parse_date(item.get("published_parsed") or item.get("updated_parsed") or item.get("published"))
        summary = BeautifulSoup(item.get("summary", ""), "lxml").get_text(" ", strip=True) if item.get("summary") else ""
        tags = [t.get("term", "") for t in item.get("tags", [])]
        entries.append(Entry(title, link, source.company, source.name, published, summary[:500],
                             source.priority, {"tags": tags}))
    return entries


def parse_listing(html: str, source: config.Source) -> list[Entry]:
    """Pull article links (in page order) from a newsroom page. Dates are read later from each article."""
    soup = BeautifulSoup(html, "lxml")
    seen, entries = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("#")[0].split("?")[0]
        path = urlsplit(href).path if href.startswith("http") else href
        if href.startswith("http") and urlsplit(href).netloc.removeprefix("www.") != urlsplit(source.base).netloc.removeprefix("www."):
            continue
        if not config.ANTHROPIC_ARTICLE_RE.match(path):
            continue
        url = urljoin(source.base + "/", path.lstrip("/"))
        if normalize_url(url) in seen:
            continue
        seen.add(normalize_url(url))
        title = a.get_text(" ", strip=True)
        heading = a.find(["h2", "h3", "h4"])
        if heading:
            title = heading.get_text(" ", strip=True)
        time_tag = a.find("time")
        published = parse_date(time_tag.get("datetime") or time_tag.get_text(strip=True)) if time_tag else None
        entries.append(Entry(title[:200], url, source.company, source.name, published, "", source.priority))
    return entries


def fetch_source(source: config.Source) -> list[Entry]:
    resp = http_get(source.url, accept="application/rss+xml,application/xml,text/xml,*/*" if source.kind == "rss" else
                    "text/html,*/*")
    resp.raise_for_status()
    if source.kind == "rss":
        entries = parse_rss(resp.content, source)
    else:
        entries = parse_listing(resp.text, source)
    log.info("%s: %d entries", source.name, len(entries))
    return entries


def fetch_all(sources=None) -> tuple[list[Entry], dict[str, str]]:
    """Return all entries plus a map of source name -> error message for sources that failed."""
    entries, errors = [], {}
    for source in sources or config.SOURCES:
        try:
            entries.extend(fetch_source(source))
        except Exception as exc:  # noqa: BLE001 - one broken source must not stop the others
            log.warning("source failed: %s (%s)", source.name, exc)
            errors[source.name] = f"{type(exc).__name__}: {exc}"
    return entries, errors


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
