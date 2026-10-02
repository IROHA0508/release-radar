"""Write news files and the manifest, and run the repository's data validator."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from . import config

KEY_ORDER = ["id", "company", "date", "kind", "title", "headline", "tldr", "models", "numbers", "chartSource",
             "charts", "chartNote", "changes", "availability", "tips", "prompts", "cautions", "sources"]
RESERVED = {"guide", "prices"}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)[:60].strip("-") or "news"


def unique_id(wanted: str, title: str) -> str:
    base = slugify(wanted) or slugify(title)
    if base in RESERVED:
        base += "-news"
    nid, n = base, 2
    while (config.NEWS_DIR / f"{nid}.json").exists():
        nid, n = f"{base}-{n}", n + 1
    return nid


def _clean(value):
    """Empty strings become null inside models; empty strings/lists elsewhere are dropped by callers."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def normalize_item(raw: dict, *, company: str, day: date, url: str, title_hint: str) -> dict:
    item = _clean(dict(raw))
    item["company"] = company
    item["date"] = day.isoformat()
    item["id"] = unique_id(item.get("id") or "", item.get("title") or title_hint)
    for m in item.get("models", []):
        for k in ("apiId", "input", "output", "cached"):
            if not m.get(k):
                m[k] = None
    for chart in item.get("charts", []):
        for k in ("note", "source"):
            if not chart.get(k):
                chart.pop(k, None)
        for row in chart.get("rows", []):
            if not row.get("highlight"):
                row.pop("highlight", None)
    for key in ("chartSource", "chartNote"):
        if not item.get(key):
            item.pop(key, None)
    for n in item.get("numbers", []):
        n.setdefault("note", "")
    sources = [s for s in item.get("sources", []) if str(s.get("url", "")).startswith("https://")]
    if not any(s["url"].rstrip("/") == url.rstrip("/") for s in sources):
        sources.insert(0, {"title": f"{item.get('title') or title_hint} (공식 발표)", "url": url})
    item["sources"] = sources
    for p in item.get("prompts", []):
        p["type"] = p.get("type") if p.get("type") in ("prompt", "code") else "prompt"
    ordered = {k: item[k] for k in KEY_ORDER if k in item}
    return ordered


def write_news(item: dict) -> Path:
    path = config.NEWS_DIR / f"{item['id']}.json"
    path.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def apply_update(news_id: str, update: dict) -> bool:
    path = config.NEWS_DIR / f"{news_id}.json"
    if not path.exists():
        return False
    d = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    for key in ("changes", "availability"):
        for line in update.get(key) or []:
            if line and line not in d.get(key, []):
                d.setdefault(key, []).append(line)
                changed = True
    urls = {s["url"].rstrip("/") for s in d.get("sources", [])}
    for s in update.get("sources") or []:
        if str(s.get("url", "")).startswith("https://") and s["url"].rstrip("/") not in urls:
            d.setdefault("sources", []).append({"title": s.get("title") or s["url"], "url": s["url"]})
            changed = True
    if changed:
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def load_manifest() -> dict:
    return json.loads(config.MANIFEST.read_text(encoding="utf-8"))


def save_manifest(manifest: dict) -> None:
    config.MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_to_manifest(news_id: str) -> None:
    m = load_manifest()
    if news_id not in m["news"]:
        m["news"].insert(0, news_id)
    save_manifest(m)


def remove_from_manifest(news_id: str) -> None:
    m = load_manifest()
    m["news"] = [i for i in m["news"] if i != news_id]
    save_manifest(m)


def touch_last_checked(when: date | datetime) -> None:
    """Record when the sources were last checked: "YYYY-MM-DD HH:MM" in Korean time (the site shows it as Update)."""
    m = load_manifest()
    m["lastChecked"] = when.strftime("%Y-%m-%d %H:%M") if isinstance(when, datetime) else when.isoformat()
    save_manifest(m)


def validate() -> tuple[bool, str]:
    proc = subprocess.run([sys.executable, str(config.VALIDATOR)], capture_output=True, text=True, cwd=config.ROOT)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()
