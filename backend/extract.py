"""Read an article page: main text, tables copied cell by cell, links, title and publish date."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date

from bs4 import BeautifulSoup

from . import config
from .feeds import http_get, parse_date

log = logging.getLogger(__name__)

DROP_TAGS = ["script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "iframe"]


@dataclass
class Article:
    url: str
    title: str = ""
    published: date | None = None
    text: str = ""
    tables: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    via: str = "direct"          # direct | reader

    @property
    def full_text(self) -> str:
        """Everything a number or model ID may legitimately come from."""
        return "\n".join([self.title, self.text, *self.tables, *self.links])


def table_to_text(table) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def meta_date(soup: BeautifulSoup) -> date | None:
    for attrs in ({"property": "article:published_time"}, {"name": "article:published_time"},
                  {"name": "date"}, {"name": "publish-date"}, {"itemprop": "datePublished"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            d = parse_date(tag["content"])
            if d:
                return d
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in data if isinstance(data, list) else [data]:
            if isinstance(obj, dict) and obj.get("datePublished"):
                d = parse_date(obj["datePublished"])
                if d:
                    return d
    time_tag = soup.find("time")
    if time_tag:
        return parse_date(time_tag.get("datetime") or time_tag.get_text(strip=True))
    return None


MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
TEXT_DATE_RE = re.compile(
    rf"(?i)\b(?:({MONTHS})[a-z]*\.?\s+(\d{{1,2}}),?\s+(20\d\d)|(\d{{1,2}})\s+({MONTHS})[a-z]*\.?\s+(20\d\d)|(20\d\d)-(\d\d)-(\d\d))\b")


def text_date(text: str) -> date | None:
    """A date written near the top of the article ("August 14, 2026", "JAN. 28, 2026", "14 Aug 2026").
    Only the first part of the text is searched, where the byline usually is."""
    m = TEXT_DATE_RE.search(text[:2000])
    if not m:
        return None
    try:
        if m.group(1):
            month, day, year = m.group(1)[:3].lower(), int(m.group(2)), int(m.group(3))
        elif m.group(5):
            month, day, year = m.group(5)[:3].lower(), int(m.group(4)), int(m.group(6))
        else:
            return date(int(m.group(7)), int(m.group(8)), int(m.group(9)))
        return date(year, ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(month) + 1, day)
    except ValueError:
        return None


SITE_SUFFIX_RE = re.compile(
    r"\s*[-–—|]\s*(Google Developers Blog|Google Cloud Blog|Google DeepMind|Google Blog|The Keyword|"
    r"OpenAI( Developers)?|Anthropic|Claude)\s*$")


def clean_title(title: str) -> str:
    """'EmbeddingGemma 2: The Developer Guide- Google Developers Blog' -> 'EmbeddingGemma 2: The Developer Guide'."""
    return SITE_SUFFIX_RE.sub("", title or "").strip()


def parse_html(html: str, url: str) -> Article:
    soup = BeautifulSoup(html, "lxml")
    published = meta_date(soup)
    og = soup.find("meta", attrs={"property": "og:title"})
    title = clean_title((og.get("content") if og else None) or (soup.title.get_text(strip=True) if soup.title else ""))
    links = sorted({a["href"] for a in soup.find_all("a", href=True) if a["href"].startswith("http")})
    tables = [t for t in (table_to_text(tb) for tb in soup.find_all("table")) if t]
    # The byline date often sits in the article's <header>, which is dropped below with the menus.
    top = soup.find("article") or soup.find("main") or soup.body or soup
    byline_date = text_date(top.get_text("\n", strip=True))
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()
    for tb in soup.find_all("table"):
        tb.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    # Image alt text sometimes carries chart values, keep it.
    alts = [img.get("alt", "") for img in main.find_all("img") if len(img.get("alt", "")) > 20]
    text = main.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if alts:
        text += "\n\n[이미지 대체 텍스트]\n" + "\n".join(alts)
    published = published or byline_date or text_date(text)
    return Article(url, title, published, text[: config.PAGE_TEXT_LIMIT], tables, links)


def parse_reader(markdown: str, url: str) -> Article:
    """Parse the Jina Reader response (Title:/Published Time:/Markdown Content: header + markdown)."""
    title, published = "", None
    m = re.search(r"^Title:\s*(.+)$", markdown, re.M)
    if m:
        title = clean_title(m.group(1).strip())
    m = re.search(r"^Published Time:\s*(.+)$", markdown, re.M)
    if m:
        published = parse_date(m.group(1).strip())
    body = markdown.split("Markdown Content:", 1)[-1]
    published = published or text_date(body)
    tables = ["\n".join(block) for block in _markdown_tables(body)]
    links = sorted(set(re.findall(r"\((https?://[^)\s]+)\)", body)))
    return Article(url, title, published, body[: config.PAGE_TEXT_LIMIT], tables, links, via="reader")


def _markdown_tables(md: str):
    block = []
    for line in md.splitlines():
        if line.strip().startswith("|"):
            block.append(line.strip())
        elif block:
            if len(block) >= 2:
                yield block
            block = []
    if len(block) >= 2:
        yield block


def fetch_reader(url: str) -> Article:
    resp = http_get(config.READER_PREFIX + url, accept="text/plain,*/*")
    resp.raise_for_status()
    return parse_reader(resp.text, url)


def fetch_article(url: str) -> Article:
    """Read the page directly; use the reader when the page is blocked, too short, or has no
    HTML tables (some sites draw benchmark tables with divs, which the reader turns into tables)."""
    error, direct = None, None
    try:
        resp = http_get(url)
        if resp.status_code == 200:
            direct = parse_html(resp.text, url)
            if len(direct.text) < 800:
                error, direct = f"본문이 너무 짧음({len(direct.text)}자)", None
        else:
            error = f"HTTP {resp.status_code}"
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    if direct is not None and (direct.tables or not config.READER_FALLBACK):
        return direct
    if direct is None and not config.READER_FALLBACK:
        raise RuntimeError(f"원문을 읽지 못함: {url} ({error})")
    try:
        reader = fetch_reader(url)
    except Exception as exc:  # noqa: BLE001
        if direct is not None:
            return direct
        raise RuntimeError(f"원문을 읽지 못함: {url} ({error}; reader {exc})") from exc
    if direct is not None:
        # Keep the direct page (dates, links) and add the reader's tables.
        direct.tables = reader.tables
        direct.via = "direct+reader" if reader.tables else "direct"
        return direct
    if len(reader.text) < 800:
        raise RuntimeError(f"원문을 읽지 못함: {url} ({error}; reader {len(reader.text)}자)")
    return reader
