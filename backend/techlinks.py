"""Link new news items to the techniques on the site (data/tech.json) and queue new technique names.

When the pipeline adds a '활용 팁' or '제품·기능 출시' item, Claude (the small triage model) picks the
techniques the item really covers. The item id is added to those techniques' "news" lists (the site shows
them as related news, and a technique mentioned by several companies or news items gets a "시도 추천"
badge). Technique names the item is about but the site does not have yet are only written to
backend/state/tech-candidates.json for a person to review: a new technique page needs an official source
and a checked definition first (docs/GUIDELINES.md 9.2).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from . import config, store

log = logging.getLogger(__name__)



def tech_file():
    return config.DATA / "tech.json"


def candidates_file():
    return config.ROOT / "backend" / "state" / "tech-candidates.json"

MAX_LINKS = 4
MAX_CANDIDATES = 2

STR = {"type": "string"}
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["links", "candidates"],
    "properties": {
        "links": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                             "required": ["id", "reason"], "properties": {"id": STR, "reason": STR}}},
        "candidates": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                  "required": ["name", "en", "oneLiner"],
                                                  "properties": {"name": STR, "en": STR, "oneLiner": STR}}},
    },
}

RULES = """\
너는 '릴리스 레이더' 사이트의 편집자다. 새로 올라온 공식 소식 하나가 사이트의 'AI 활용 기술' 목록 중 어떤 기술을
다루는지 고른다.
- links: 소식의 핵심 내용이 그 기술을 직접 설명하거나, 그 기술의 새 기능·권고·사례를 보탤 때만 고른다.
  단어만 겹치거나 지나가며 언급하는 정도면 고르지 않는다. 0~4개. id는 목록에 있는 것만 쓴다.
- candidates: 소식의 중심 주제인데 목록 어디에도 해당하지 않는 새 활용 기술이 있으면 0~2개.
  모델·제품 이름 자체는 기술이 아니다(예: 'Gemini 4'는 아니고 '목표 고정 장시간 실행'은 기술이다).
  name은 짧은 한국어 이름, en은 영어 이름, oneLiner는 한 문장 설명(합쇼체, 원문에 있는 내용만).
- reason은 왜 연결했는지 한 문장.
"""


def load() -> dict:
    return json.loads(tech_file().read_text(encoding="utf-8"))


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", (s or "").lower())


def apply_links(data: dict, item: dict, ids: list[str]) -> list[str]:
    """Add the item to each technique's news list. Returns the ids that actually changed."""
    by_id = {t["id"]: t for t in data.get("items", [])}
    changed = []
    for tid in ids:
        t = by_id.get(tid)
        if not t or item["id"] in t.setdefault("news", []):
            continue
        t["news"].append(item["id"])
        if t.get("group") == "radar" and item.get("company") and item["company"] not in t.setdefault("companies", []):
            t["companies"].append(item["company"])
        changed.append(tid)
    return changed


def queue_candidates(cands: list[dict], item: dict, data: dict, today: date) -> list[dict]:
    """Keep technique names the site does not have yet, for a person to review."""
    known = {_norm(t.get("name")) for t in data.get("items", [])} | {_norm(t.get("en")) for t in data.get("items", [])}
    path = candidates_file()
    queue = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    seen = {_norm(c.get("name")) for c in queue} | {_norm(c.get("en")) for c in queue}
    added = []
    for c in cands[:MAX_CANDIDATES]:
        keys = {_norm(c.get("name")), _norm(c.get("en"))} - {""}
        if not keys or keys & known:
            continue
        if keys & seen:
            for q in queue:                     # same name again: just add this news as more evidence
                if {_norm(q.get("name")), _norm(q.get("en"))} & keys and item["id"] not in q["news"]:
                    q["news"].append(item["id"])
            continue
        entry = {"name": c["name"].strip(), "en": c.get("en", "").strip(), "oneLiner": c.get("oneLiner", "").strip(),
                 "news": [item["id"]], "company": item.get("company"), "addedAt": today.isoformat()}
        queue.append(entry)
        seen |= keys
        added.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return added


def ask(claude, item: dict, data: dict) -> dict:
    listing = "\n".join(f"- {t['id']} | {t['name']} ({t.get('en', '')}) | {t.get('definition', '')[:150]}"
                        for t in data.get("items", []))
    news = {k: item.get(k) for k in ("id", "company", "kind", "title", "headline", "tldr", "changes")}
    news["tips"] = [t.get("title") for t in item.get("tips", [])]
    user = (f"# AI 활용 기술 목록 (id | 이름 | 정의)\n{listing}\n\n# 새 소식\n"
            + json.dumps(news, ensure_ascii=False, indent=1))
    return claude.json_call(model=config.TRIAGE_MODEL, system=RULES, user=user, schema=SCHEMA, max_tokens=2000)


def link_item(claude, item: dict, today: date) -> list[str]:
    path = tech_file()
    if not path.exists():
        return []
    data = load()
    before = path.read_text(encoding="utf-8")
    out = ask(claude, item, data)
    valid = {t["id"] for t in data.get("items", [])}
    ids = [link["id"] for link in out.get("links") or [] if link.get("id") in valid][:MAX_LINKS]
    changed = apply_links(data, item, ids)
    notes = []
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ok, msg = store.validate()
        if not ok:
            path.write_text(before, encoding="utf-8")
            return [f"기술 연결 되돌림(검증 실패): {msg[-200:]}"]
        notes.append(f"{item['id']} → " + ", ".join(changed))
    for c in queue_candidates(out.get("candidates") or [], item, data, today):
        notes.append(f"새 기술 후보: {c['name']} ({c['en']}) ← {item['id']}")
    return notes
