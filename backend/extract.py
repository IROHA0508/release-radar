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


def parse_html(html: str, url: str) -> Article:
    soup = BeautifulSoup(html, "lxml")
    published = meta_date(soup)
    og = soup.find("meta", attrs={"property": "og:title"})
    title = (og.get("content") if og else None) or (soup.title.get_text(strip=True) if soup.title else "")
    links = sorted({a["href"] for a in soup.find_all("a", href=True) if a["href"].startswith("http")})
    tables = [t for t in (table_to_text(tb) for tb in soup.find_all("table")) if t]
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
    return Article(url, title, published, text[: config.PAGE_TEXT_LIMIT], tables, links)


def parse_reader(markdown: str, url: str) -> Article:
    """Parse the Jina Reader response (Title:/Published Time:/Markdown Content: header + markdown)."""
    title, published = "", None
    m = re.search(r"^Title:\s*(.+)$", markdown, re.M)
    if m:
        title = m.group(1).strip()
    m = re.search(r"^Published Time:\s*(.+)$", markdown, re.M)
    if m:
        published = parse_date(m.group(1).strip())
    body = markdown.split("Markdown Content:", 1)[-1]
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


def fetch_article(url: str) -> Article:
    error = None
    try:
        resp = http_get(url)
        if resp.status_code == 200:
            art = parse_html(resp.text, url)
            if len(art.text) >= 800:
                return art
            error = f"본문이 너무 짧음({len(art.text)}자)"
        else:
            error = f"HTTP {resp.status_code}"
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    if not config.READER_FALLBACK:
        raise RuntimeError(f"원문을 읽지 못함: {url} ({error})")
    log.info("direct fetch failed for %s (%s), trying reader", url, error)
    resp = http_get(config.READER_PREFIX + url, accept="text/plain,*/*")
    resp.raise_for_status()
    art = parse_reader(resp.text, url)
    if len(art.text) < 800:
        raise RuntimeError(f"원문을 읽지 못함: {url} ({error}; reader {len(art.text)}자)")
    return art
