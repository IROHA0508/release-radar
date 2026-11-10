"""Write news files and the manifest, and run the repository's data validator."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from . import config

KEY_ORDER = ["id", "company", "date", "kind", "shutdown", "title", "headline", "tldr", "fit", "models", "numbers", "figures",
             "chartSource", "charts", "chartNote", "changes", "availability", "usage", "tips", "prompts", "cautions", "sources"]
RESERVED = {"guide", "prices", "models", "tech", "lab", "glossary", "migrate"}
RETIRE_SOON, RETIRED = "지원 종료 예정", "지원 종료"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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


def _strs(values) -> list[str]:
    return [str(v).strip() for v in values or [] if str(v or "").strip()]


def normalize_extras(item: dict, source: dict) -> None:
    """fit·figures·usage(선택 필드)를 검증 스크립트가 받는 모양으로 다듬는다. 모양이 맞지 않으면 그 항목만 버린다.
    도식과 사용법의 출처는 모델이 쓰지 않고 이 소식의 원문으로 채운다."""
    fit = item.get("fit") or {}
    fit = {"summary": str(fit.get("summary") or "").strip(), "good": _strs(fit.get("good")),
           "notFor": _strs(fit.get("notFor")), "start": str(fit.get("start") or "").strip()}
    if item.get("kind") in (RETIRE_SOON, RETIRED) or not fit["summary"] or not (fit["good"] or fit["notFor"]):
        item.pop("fit", None)
    else:
        item["fit"] = {k: v for k, v in fit.items() if v}

    figures = []
    for f in item.get("figures") or []:
        kind, title = f.get("type"), str(f.get("title") or "").strip()
        out = {"type": kind, "title": title}
        if f.get("caption"):
            out["caption"] = f["caption"]
        if kind in ("flow", "scale"):
            steps = []
            for st in f.get("steps") or []:
                if not str(st.get("label") or "").strip():
                    continue
                step = {"label": st["label"].strip()}
                for k in ("desc", "tag"):
                    if st.get(k):
                        step[k] = st[k]
                if st.get("highlight"):
                    step["highlight"] = True
                steps.append(step)
            if not title or len(steps) < 2:
                continue
            out["steps"] = steps
            if kind == "flow" and f.get("loop"):
                out["loop"] = f["loop"]
        elif kind == "compare":
            cols = _strs(f.get("columns"))
            rows = []
            for r in f.get("rows") or []:
                cells = [str(c or "").strip() for c in r.get("cells") or []]
                if not str(r.get("label") or "").strip() or len(cells) != len(cols):
                    continue
                row = {"label": r["label"].strip(), "cells": cells}
                if r.get("highlight"):
                    row["highlight"] = True
                rows.append(row)
            if not title or not cols or len(rows) < 2:
                continue
            out["columns"], out["rows"] = cols, rows
        else:
            continue
        out["source"] = source
        figures.append(out)
    if figures:
        item["figures"] = figures[:3]
    else:
        item.pop("figures", None)

    usage = []
    for u in item.get("usage") or []:
        title, steps = str(u.get("title") or "").strip(), _strs(u.get("steps"))
        ex = u.get("example") or {}
        has_ex = ex.get("type") in ("prompt", "code") and str(ex.get("text") or "").strip()
        if not title or not (steps or has_ex):
            continue
        out = {"title": title}
        if u.get("when"):
            out["when"] = u["when"]
        if steps:
            out["steps"] = steps
        if u.get("note"):
            out["note"] = u["note"]
        if has_ex:
            out["example"] = {"type": ex["type"], "text": ex["text"]}
        out["source"] = source
        usage.append(out)
    if usage:
        item["usage"] = usage[:5]
    else:
        item.pop("usage", None)


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
    # 종료일은 지원 종료 소식에만, YYYY-MM-DD일 때만 남긴다(모르면 빼 둔다 → 화면에 '종료일 미정')
    if item.get("kind") not in (RETIRE_SOON, RETIRED) or not DATE_RE.match(str(item.get("shutdown") or "")):
        item.pop("shutdown", None)
    elif item["kind"] == RETIRED and item["shutdown"] > item["date"]:
        item["kind"] = RETIRE_SOON              # 발표일 뒤에 끝나는 일은 아직 '예정'
    for n in item.get("numbers", []):
        n.setdefault("note", "")
    sources = [s for s in item.get("sources", []) if str(s.get("url", "")).startswith("https://")]
    if not any(s["url"].rstrip("/") == url.rstrip("/") for s in sources):
        sources.insert(0, {"title": f"{item.get('title') or title_hint} (공식 발표)", "url": url})
    item["sources"] = sources
    normalize_extras(item, dict(sources[0]))
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


def retire_due(today: date) -> list[dict]:
    """종료일이 된 '지원 종료 예정' 소식을 '지원 종료'로 바꾼다. 바꾼 소식의 id·title을 돌려준다."""
    done = []
    for path in sorted(config.NEWS_DIR.glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        sd = str(d.get("shutdown") or "")
        if d.get("kind") == RETIRE_SOON and DATE_RE.match(sd) and sd <= today.isoformat():
            d["kind"] = RETIRED
            path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            done.append({"id": d["id"], "title": d.get("title", ""), "shutdown": sd})
    return done


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
