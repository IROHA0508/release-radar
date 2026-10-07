"""Decide which feed entries are new compared with the site's data and the run history."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from difflib import SequenceMatcher

from . import config
from .feeds import Entry, normalize_url

log = logging.getLogger(__name__)


@dataclass
class SiteIndex:
    items: list[dict]                 # id, company, date, title, models
    known_urls: dict[str, str]        # normalized source URL -> news id
    newest: date | None

    def summary_lines(self) -> list[str]:
        return [f"{i['id']} | {i['company']} | {i['date']} | {i['title']}" for i in self.items]

    def add(self, item: dict) -> None:
        """Register an item written during this run, so later candidates in the same run see it."""
        self.items.insert(0, {"id": item["id"], "company": item["company"], "date": item["date"],
                              "title": item["title"], "kind": item.get("kind", ""),
                              "models": [m.get("name") for m in item.get("models", [])]})
        for s in item.get("sources", []):
            self.known_urls[normalize_url(s["url"])] = item["id"]
        day = date.fromisoformat(item["date"])
        self.newest = day if self.newest is None or day > self.newest else self.newest


def load_site() -> SiteIndex:
    items, known = [], {}
    newest = None
    for path in sorted(config.NEWS_DIR.glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        items.append({"id": d["id"], "company": d["company"], "date": d["date"], "title": d["title"],
                      "kind": d.get("kind", ""), "models": [m.get("name") for m in d.get("models", [])]})
        for s in d.get("sources", []):
            known[normalize_url(s["url"])] = d["id"]
        day = date.fromisoformat(d["date"])
        newest = day if newest is None or day > newest else newest
    items.sort(key=lambda x: x["date"], reverse=True)
    return SiteIndex(items, known, newest)


def load_state() -> dict:
    if config.STATE_FILE.exists():
        return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    return {"urls": {}}


def save_state(state: dict) -> None:
    urls = state.get("urls", {})
    # Keep the file small: the newest 3000 records are plenty for dedupe.
    if len(urls) > 3000:
        keep = sorted(urls.items(), key=lambda kv: kv[1].get("checkedAt", ""), reverse=True)[:3000]
        state["urls"] = dict(keep)
    config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9.]+", " ", t.lower()).strip()


def related_item(entry: Entry, site: SiteIndex) -> str | None:
    """Return the id of an existing item whose model name appears in the entry title."""
    title = _norm_title(entry.title)
    best = None
    for item in site.items:
        if item["company"] != entry.company:
            continue
        name = _norm_title(item["title"].split("(")[0].split("·")[0])
        if len(name) >= 6 and re.search(rf"(^| ){re.escape(name)}( |$)", title):
            if best is None or len(name) > len(best[1]):
                best = (item["id"], name)
    return best[0] if best else None


def slug_key(url: str) -> str:
    """host + last path segment, so /news/claude-x and /claude-x count as the same page."""
    norm = normalize_url(url)
    host = norm.split("/")[2]
    return host + "/" + norm.rstrip("/").rsplit("/", 1)[-1]


def same_item(entry: Entry, site: SiteIndex, exclude: set[str]) -> str | None:
    """An existing item about the same model published within a day of this entry."""
    rid = related_item(entry, site)
    if not rid or rid in exclude or entry.published is None:
        return None
    item = next(i for i in site.items if i["id"] == rid)
    return rid if abs((date.fromisoformat(item["date"]) - entry.published).days) <= 1 else None


def model_key(name: str | None) -> str:
    """'EmbeddingGemma 2', 'embeddinggemma-2', 'Gemini 3.1 Flash TTS (프리뷰)' -> comparable keys."""
    return re.sub(r"[^a-z0-9.]+", "", re.sub(r"\(.*?\)", "", (name or "").lower()))


def duplicate_launch(item: dict, site: SiteIndex, window_days: int = 14) -> str | None:
    """An existing item announcing the same model (or with the same title) as a freshly written one.

    A model is launched once: two "모델 출시" items from one company sharing a model name within
    two weeks are the same news. Tips and updates about a launched model stay separate items.
    """
    day = date.fromisoformat(item["date"])
    names = {model_key(m.get("name")) for m in item.get("models", [])} - {""}
    title = model_key(item.get("title"))
    for other in site.items:
        if other["company"] != item["company"] or other["id"] == item.get("id"):
            continue
        if abs((date.fromisoformat(other["date"]) - day).days) > window_days:
            continue
        same_kind = other.get("kind") == item.get("kind")
        if same_kind and title and model_key(other["title"]) == title:
            return other["id"]
        if item.get("kind") == "모델 출시" and other.get("kind") == "모델 출시" and \
                names & {model_key(n) for n in other.get("models", [])}:
            return other["id"]
    return None


def dedupe(entries: list[Entry]) -> list[Entry]:
    """Same article on two blogs (blog.google and deepmind.google): keep the higher-priority source."""
    def same_post(o: Entry, e: Entry) -> bool:
        if o.key == e.key:
            return True
        # Title match only across different sources, near-identical titles, and close dates:
        # "Introducing Claude Opus 5.5" and "Introducing Claude Sonnet 5.5" must stay separate.
        if o.source == e.source or o.company != e.company:
            return False
        if o.published and e.published and abs((o.published - e.published).days) > 1:
            return False
        return SequenceMatcher(None, _norm_title(o.title), _norm_title(e.title)).ratio() >= 0.95

    out: list[Entry] = []
    for e in sorted(entries, key=lambda x: -x.priority):
        dup = next((o for o in out if same_post(o, e)), None)
        if dup is None:
            out.append(e)
        else:
            dup.extra.setdefault("alsoAt", []).append(e.url)
    return out


def find_candidates(entries: list[Entry], site: SiteIndex, state: dict, today: date,
                    pretend_missing: set[str] = frozenset()) -> list[Entry]:
    """New = not a source of any news file, not handled in an earlier run, recent, and model-related.

    pretend_missing: news ids whose source URLs are ignored, used by the self-test to check that
    each source still finds an article we already know about.
    """
    known = {u: i for u, i in site.known_urls.items() if i not in pretend_missing}
    known_slugs = {slug_key(u) for u in known}
    seen = state.get("urls", {})
    base = site.newest or today
    if pretend_missing:
        dates = [date.fromisoformat(i["date"]) for i in site.items if i["id"] not in pretend_missing]
        base = max(dates) if dates else today
    cutoff = min(base, today) - timedelta(days=config.LOOKBACK_DAYS)
    out = []
    for e in dedupe(entries):
        urls = [e.url, *e.extra.get("alsoAt", [])]
        keys = [normalize_url(u) for u in urls]
        if any(k in known for k in keys) or any(slug_key(u) in known_slugs for u in urls):
            continue
        if not pretend_missing and any(k in seen for k in keys):
            continue
        if e.published and e.published < cutoff:
            continue
        lastmod = e.extra.get("lastmod")
        if e.published is None and lastmod and lastmod < cutoff:
            continue
        if not config.RELEVANT_RE.search(f"{e.title} {e.summary}"):
            continue
        if same_item(e, site, set(pretend_missing)):
            continue
        e.extra["relatedId"] = related_item(e, site)
        out.append(e)
    # Dated entries first (newest first), then undated ones from sitemaps.
    out.sort(key=lambda x: (x.published is not None, x.published or x.extra.get("lastmod") or today), reverse=True)
    return out


def mark(state: dict, entry: Entry, status: str, today: date, **info) -> None:
    rec = {"status": status, "title": entry.title, "company": entry.company,
           "date": entry.published.isoformat() if entry.published else None, "checkedAt": today.isoformat(), **info}
    for u in [entry.url, *entry.extra.get("alsoAt", [])]:
        state.setdefault("urls", {})[normalize_url(u)] = rec
