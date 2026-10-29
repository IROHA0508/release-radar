"""Collect recent posts from each official source (RSS feeds and the Anthropic newsroom page)."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
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
        # A changelog entry shares its page URL with every other entry, so it carries its own key.
        return self.extra.get("key") or normalize_url(self.url)


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
    article_re = re.compile(source.pattern) if source.pattern else config.ANTHROPIC_ARTICLE_RE
    seen, entries = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("#")[0].split("?")[0]
        path = urlsplit(href).path if href.startswith("http") else href
        if href.startswith("http") and urlsplit(href).netloc.removeprefix("www.") != urlsplit(source.base).netloc.removeprefix("www."):
            continue
        if not article_re.match(path):
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
        if published is None and source.pattern:
            # Blog lists show "Oct 6, 2026" or just "Sep 23" next to each link.
            near = [a.get_text(" ", strip=True), a.parent.get_text(" ", strip=True)[:300]]
            published = next((d for d in (full_date(t) or month_day(t) for t in near) if d), None)
        entries.append(Entry(title[:200], url, source.company, source.name, published, "", source.priority))
    if not entries and source.pattern:
        # Lists drawn by the browser keep their links in the page's data, not in <a> tags.
        for path in re.findall(r"[\"'=](?:https?://(?:www\.)?" + re.escape(urlsplit(source.base).netloc.removeprefix("www."))
                               + r")?(/[a-z0-9/_-]+)", html):
            if not article_re.match(path):
                continue
            url = urljoin(source.base + "/", path.lstrip("/"))
            if normalize_url(url) in seen:
                continue
            seen.add(normalize_url(url))
            slug = path.rstrip("/").rsplit("/", 1)[-1]
            entries.append(Entry(slug.replace("-", " "), url, source.company, source.name, None, "", source.priority,
                                 {"titleFromSlug": True}))
    return entries


FULL_DATE_RE = re.compile(r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},\s*20\d\d\b")


def full_date(text: str) -> date | None:
    m = FULL_DATE_RE.search(text or "")
    return parse_date(re.sub(r"(?i)^sept", "Sep", m.group(0)).replace(".", "")) if m else None


MONTH_DAY_RE = re.compile(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b(?!,?\s*\d)")


def month_day(text: str, today: date | None = None) -> date | None:
    """'Sep 23' -> the most recent Sep 23 that is not in the future."""
    m = MONTH_DAY_RE.search(text or "")
    if not m:
        return None
    today = today or datetime.now(timezone.utc).date()
    month = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(m.group(1)[:3].lower()) + 1
    try:
        d = date(today.year, month, int(m.group(2)))
    except ValueError:
        return None
    return d if d <= today + timedelta(days=1) else d.replace(year=today.year - 1)


def parse_sitemap(xml: bytes | str, source: config.Source) -> list[Entry]:
    """Article URLs from a sitemap. The title is guessed from the slug; lastmod only bounds the date."""
    soup = BeautifulSoup(xml, "xml")
    article_re = re.compile(source.pattern) if source.pattern else config.ANTHROPIC_ARTICLE_RE
    entries = []
    for node in soup.find_all("url"):
        loc = node.find("loc")
        if not loc:
            continue
        url = loc.get_text(strip=True)
        path = urlsplit(url).path
        if not article_re.match(path):
            continue
        lastmod = node.find("lastmod")
        slug = path.rstrip("/").rsplit("/", 1)[-1]
        entries.append(Entry(slug.replace("-", " "), url, source.company, source.name, None, "", source.priority,
                             {"lastmod": parse_date(lastmod.get_text(strip=True)) if lastmod else None, "titleFromSlug": True}))
    return entries


def parse_reader_listing(markdown: str, source: config.Source) -> list[Entry]:
    """Article links from the Jina Reader's markdown of a listing page ([title](url) pairs)."""
    article_re = re.compile(source.pattern) if source.pattern else config.ANTHROPIC_ARTICLE_RE
    host = urlsplit(source.base).netloc.removeprefix("www.")
    seen, entries = set(), []
    for title, url in re.findall(r"\[([^\]]{3,300})\]\((https?://[^)\s]+)\)", markdown):
        parts = urlsplit(url)
        if parts.netloc.removeprefix("www.") != host or not article_re.match(parts.path):
            continue
        key = normalize_url(url)
        if key in seen:
            continue
        seen.add(key)
        title = re.sub(r"!\[[^\]]*\]\([^)]*\)|[#*_`]", "", title).strip()
        entries.append(Entry(title[:200], url.split("#")[0].split("?")[0], source.company, source.name, None, "",
                             source.priority, {"via": "reader"}))
    return entries


_MON = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
CL_FULL_RE = re.compile(rf"(?i)^(?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+)?({_MON})[a-z]*\.?\s+(\d{{1,2}}),?\s+(20\d\d)$")
CL_ISO_RE = re.compile(r"^(20\d\d)-(\d\d)-(\d\d)$")
CL_MONTH_DAY_RE = re.compile(rf"(?i)^({_MON})[a-z]*\.?\s+(\d{{1,2}})$")
CL_MONTH_YEAR_RE = re.compile(rf"(?i)^({_MON})[a-z]*,?\s+(20\d\d)$")
CL_LABEL_RE = re.compile(r"(?i)^(feature|update|fix|announcement|deprecation|new|changed|removed|improvement|breaking"
                         r"|beta|ga|launch|release)s?$")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _month(name: str) -> int:
    return ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(name[:3].lower()) + 1


def _clean_line(line: str, base: str, links: list[str]) -> str:
    """Markdown or page text -> plain text; link targets are collected."""
    def repl(m):
        links.append(urljoin(base, m.group(2)))
        return m.group(1)
    text = MD_LINK_RE.sub(repl, line)
    text = re.sub(r"\s*\{#[^}]*\}\s*$", "", text)                    # '## October 6, 2026 {#october-6}'
    text = re.sub(r"^\s*(?:#{1,6}\s*|>\s*)", "", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text)
    text = re.sub(r"<[^>]+>|\*\*|__|`", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _line_date(text: str, year: int | None, today: date) -> date | None:
    m = CL_FULL_RE.match(text)
    try:
        if m:
            return date(int(m.group(3)), _month(m.group(1)), int(m.group(2)))
        m = CL_ISO_RE.match(text)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = CL_MONTH_DAY_RE.match(text)
        if m:
            if year:
                return date(year, _month(m.group(1)), int(m.group(2)))
            return month_day(text, today)
    except ValueError:
        return None
    return None


def parse_changelog(text: str, source: config.Source, today: date | None = None) -> list[Entry]:
    """Split an API changelog into one entry per item.

    Handles '## October 6, 2026' + bullets (Gemini API, Claude release notes) and
    '### October, 2026' then 'Oct 28' / 'Feature' / body per item (OpenAI). Page text without
    bullet markers gives one entry per date."""
    import hashlib

    today = today or datetime.now(timezone.utc).date()
    page = source.page or source.url
    sections: list[tuple[date, list[str]]] = []
    year = None
    for raw in text.splitlines():
        plain = _clean_line(raw, page, [])
        if not plain:
            if sections:
                sections[-1][1].append("")
            continue
        m = CL_MONTH_YEAR_RE.match(plain)
        if m:
            year = int(m.group(2))
            continue
        d = _line_date(plain, year, today) if len(plain) <= 40 else None
        if d:
            sections.append((d, []))
        elif sections:
            sections[-1][1].append(raw)
    entries, seen = [], set()
    for d, lines in sections:
        items: list[list[str]] = []
        bulleted = any(re.match(r"^[-*+]\s+", ln) for ln in lines)
        for ln in lines:
            if bulleted and re.match(r"^[-*+]\s+", ln):
                items.append([ln])
            elif bulleted:
                if items:
                    items[-1].append(ln)
            else:
                items = items or [[]]
                items[0].append(ln)
        for item in items:
            links: list[str] = []
            cleaned = [c for c in (_clean_line(ln, page, links) for ln in item) if c]
            body = [c for c in cleaned if not CL_LABEL_RE.match(c)]
            label = next((c for c in cleaned if CL_LABEL_RE.match(c)), "")
            if not body:
                continue
            text_ = " ".join(body)
            title = next((c for c in body if len(c.split()) >= 4), body[0])
            title = re.split(r"(?<=[.!?])\s", title)[0][:200]
            digest = hashlib.sha1(re.sub(r"[^a-z0-9]+", "", text_.lower())[:200].encode()).hexdigest()[:8]
            key = f"{normalize_url(page)}#{d.isoformat()}-{digest}"
            if key in seen:
                continue
            seen.add(key)
            entries.append(Entry(title, f"{page}#{d.isoformat()}", source.company, source.name, d,
                                 ((label + ": ") if label else "") + text_[:500], source.priority,
                                 {"changelog": True, "key": key, "text": text_, "links": links, "page": page}))
    return entries


def fetch_changelog(source: config.Source) -> list[Entry]:
    """The markdown copy first (keeps bullets); the page itself (through the reader if blocked) if that fails."""
    errors = []
    try:
        resp = http_get(source.url, accept="text/markdown,text/plain,*/*")
        if resp.status_code == 200:
            entries = parse_changelog(resp.text, source)
            if entries:
                return entries
            errors.append(f"마크다운에서 날짜 항목 0개({len(resp.text)}자)")
        else:
            errors.append(f"마크다운 HTTP {resp.status_code}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"마크다운 {type(exc).__name__}: {exc}")
    if source.page and source.page != source.url:
        from .extract import fetch_article

        art = fetch_article(source.page)
        entries = parse_changelog(art.text, source)
        if entries:
            return entries
        errors.append(f"페이지에서 날짜 항목 0개({len(art.text)}자)")
    raise RuntimeError("변경 기록을 읽지 못함 — " + " / ".join(errors))


def fetch_source(source: config.Source) -> list[Entry]:
    if source.kind == "changelog":
        entries = fetch_changelog(source)
        log.info("%s: %d entries", source.name, len(entries))
        return entries
    resp = http_get(source.url, accept="text/html,*/*" if source.kind == "listing" else
                    "application/rss+xml,application/xml,text/xml,*/*")
    if source.kind == "listing" and resp.status_code != 200 and config.READER_FALLBACK:
        entries = []                       # blocked: try the reader below
    else:
        resp.raise_for_status()
        if source.kind == "rss":
            entries = parse_rss(resp.content, source)
        elif source.kind == "sitemap":
            entries = parse_sitemap(resp.content, source)
        else:
            entries = parse_listing(resp.text, source)
    if source.kind == "listing" and not entries and config.READER_FALLBACK:
        # Some blogs render the list in the browser or block scripted requests; the reader sees the links.
        reader = http_get(config.READER_PREFIX + source.url, accept="text/plain,*/*")
        if reader.status_code != 200:
            raise RuntimeError(f"목록에 글 링크 없음 — 직접: {describe(resp, source)} / 리더: HTTP {reader.status_code}")
        entries = parse_reader_listing(reader.text, source)
    if not entries and source.kind in ("listing", "sitemap"):
        raise RuntimeError("항목 0개 — " + describe(resp, source))
    log.info("%s: %d entries", source.name, len(entries))
    return entries


def describe(resp, source: config.Source) -> str:
    """What the server actually sent, for the run report when a source yields nothing."""
    body = resp.text or ""
    title = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    first = re.findall(r"<loc>([^<]+)</loc>|href=\"([^\"]+)\"", body)[:4]
    return (f"HTTP {resp.status_code}, {resp.headers.get('content-type', '?')}, {len(resp.content)}바이트, "
            f"최종 주소 {resp.url}, 제목 {title.group(1).strip()[:80] if title else '-'}, "
            f"'/blog/' {body.count('/blog/')}회, 첫 링크 {[a or b for a, b in first]}")


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
