"""Keep the prompt guide (data/guides.json) current.

Two ways new guidance gets in:
1. Every day the official prompting guide pages listed under each company's "watch" are read. When a
   page's text changed since the last check, Claude compares it with the methods we already show and
   proposes a few additions or corrections, which are checked and merged. If the page is the source of
   cells in the app feature map ("appFeatures": ChatGPT/Claude/Gemini features side by side), those cells
   are re-checked against the new text too; every number in a corrected cell must be on the page.
2. When the news pipeline adds a "활용 팁" item, Claude picks out up to two prompting methods from that
   article for the company's guide.
Every new or changed method keeps its source link and a date, so the page can mark it as new.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date

from . import config, guard

log = logging.getLogger(__name__)

CATEGORIES = ["기본 작성법", "구조와 형식", "앱 기능과 설정", "예시 활용", "추론과 effort", "긴 문서와 자료", "에이전트와 코딩",
              "도구와 API 설정", "이미지·영상·음성"]
MAX_ADD, MAX_UPDATE = 3, 3

STR = {"type": "string"}
METHOD = {
    "type": "object", "additionalProperties": False,
    "required": ["id", "category", "title", "body", "before", "after", "code", "models"],
    "properties": {
        "id": STR, "category": {"type": "string", "enum": CATEGORIES}, "title": STR, "body": STR,
        "before": STR, "after": STR, "code": STR, "models": {"type": "array", "items": STR},
    },
}
GUIDE_UPDATE = {
    "type": "object", "additionalProperties": False, "required": ["add", "update", "reason"],
    "properties": {
        "add": {"type": "array", "items": METHOD},
        "update": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "body", "before", "after"],
            "properties": {"id": STR, "body": STR, "before": STR, "after": STR}}},
        "reason": STR,
    },
}

FEATURE_UPDATE = {
    "type": "object", "additionalProperties": False, "required": ["update", "reason"],
    "properties": {
        "update": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["key", "name", "note"],
            "properties": {"key": STR, "name": STR, "note": STR}}},
        "reason": STR,
    },
}

FEATURE_RULES = """\
너는 '릴리스 레이더' 사이트의 '앱 기능 대응표'를 관리한다. 표의 칸마다 한 회사 앱 기능의 이름(name)과 1~2문장 설명(note)이 있다.
아래 공식 도움말 페이지가 바뀌었다. 이 페이지를 근거로 한 칸 중 원문과 맞지 않게 된 칸만 update에 넣어라(key는 그대로).
- 원문에 있는 사실만 쓴다. 수치·요금제·메뉴 이름을 지어내지 않는다. 기능 이름이 바뀌었으면 name도 고친다.
- 맞는 칸은 넣지 않는다. 고칠 것이 없으면 빈 배열. note는 자연스러운 한국어 존댓말 서술, 200자 이내.
"""

RULES = """\
너는 '릴리스 레이더' 사이트의 프롬프트 가이드 편집자다. 가이드는 회사별로 '방법(method)' 카드를 모아 둔다.
각 카드: category, title(짧은 행동 제목), body(2~4문장: 무엇을 어떻게, 왜 — 원문 근거, 언제), before(흔한 덜 좋은 프롬프트,
선택), after(개선한 프롬프트, 바로 복사해 쓰게 바꿀 곳은 [대괄호], 선택), code(API 예시가 핵심일 때만), models(해당 모델).

원칙
- 아래 원문에 있는 권고만 쓴다. 원문에 없는 조언, 수치, 파라미터 이름, 모델 ID를 지어내지 않는다.
- 이미 있는 카드와 같은 내용은 추가하지 않는다. 정말 새로운 방법만 add에, 원문이 바뀌어 기존 카드가 틀리게 된 경우만
  update에(바뀐 필드만 채우고 나머지는 빈 문자열) 넣는다. 바꿀 것이 없으면 둘 다 빈 배열로 둔다.
- 일반 사용자와 개발자 모두 읽는다. 자연스럽고 간결한 한국어 존댓말 서술. before/after는 한국어로, 태그·파라미터·코드는 원문 그대로.
- id는 '<회사>-<짧은-영문-슬러그>' 형식(소문자·숫자·하이픈). 빈 값은 빈 문자열/빈 배열.
"""


def load() -> dict:
    return json.loads(config.GUIDES_FILE.read_text(encoding="utf-8"))


def save(data: dict) -> None:
    config.GUIDES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def page_hash(text: str) -> str:
    return hashlib.sha1(re.sub(r"\s+", " ", text).strip().encode("utf-8")).hexdigest()[:16]


def _norm(t: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", (t or "").lower())


def _numbers_ok(method: dict, pool: set[float]) -> bool:
    """Figures stated as facts (percentages, multiples, dollar amounts) must be in the source page."""
    text = " ".join(method.get(k, "") or "" for k in ("body", "title"))
    for m in re.finditer(r"(\$\s?\d[\d,.]*|\d[\d,.]*\s?(?:%|배|x\b|×))", text):
        nums = guard.numbers_in(m.group(0))
        if nums and not all(any(abs(n - p) < 1e-6 for p in pool) for n in nums):
            return False
    return True


def merge(vendor: dict, proposal: dict, source: dict, page_text: str, today: date, news_id: str | None = None) -> list[str]:
    """Apply checked additions/updates to one company's guide. Returns human-readable changes."""
    pool = guard.numbers_in(page_text)
    methods = vendor.setdefault("methods", [])
    ids = {m["id"] for m in methods}
    titles = {_norm(m["title"]) for m in methods}
    changes = []
    for m in (proposal.get("add") or [])[:MAX_ADD]:
        mid = re.sub(r"[^a-z0-9-]+", "-", (m.get("id") or "").lower()).strip("-")
        if not mid.startswith(vendor["company"] + "-"):
            mid = f"{vendor['company']}-{mid or 'method'}"
        if not m.get("title") or not m.get("body") or mid in ids or _norm(m["title"]) in titles:
            continue
        if not _numbers_ok(m, pool):
            changes.append(f"제외(원문에 없는 수치): {m.get('title')}")
            continue
        card = {"id": mid, "category": m["category"] if m.get("category") in CATEGORIES else CATEGORIES[0],
                "title": m["title"].strip(), "body": m["body"].strip()}
        for k in ("before", "after", "code"):
            if (m.get(k) or "").strip():
                card[k] = m[k].strip()
        if m.get("models"):
            card["models"] = [x for x in m["models"] if x][:4]
        card["source"] = source
        if news_id:
            card["newsId"] = news_id
        card["addedAt"] = today.isoformat()
        methods.append(card)
        ids.add(mid)
        titles.add(_norm(card["title"]))
        changes.append(f"가이드 추가: [{vendor['company']}] {card['title']}")
    by_id = {m["id"]: m for m in methods}
    for u in (proposal.get("update") or [])[:MAX_UPDATE]:
        card = by_id.get(u.get("id"))
        if card is None:
            continue
        fields = {k: u[k].strip() for k in ("body", "before", "after") if (u.get(k) or "").strip()}
        if not fields or not _numbers_ok({"body": fields.get("body", "")}, pool):
            continue
        card.update(fields)
        card["updatedAt"] = today.isoformat()
        if source.get("url") and (card.get("source") or {}).get("url") != source["url"]:
            card.setdefault("alsoSources", []).append(source)
        changes.append(f"가이드 수정: [{vendor['company']}] {card['title']}")
    return changes


def _ask(claude, vendor: dict, source: dict, page_text: str, intro: str) -> dict:
    existing = [{"id": m["id"], "title": m["title"], "body": m["body"][:300]} for m in vendor.get("methods", [])]
    user = (f"회사: {vendor['company']} ({vendor.get('name')})\n원문: {source.get('title')} {source.get('url')}\n{intro}\n\n"
            f"# 지금 가이드에 있는 카드\n{json.dumps(existing, ensure_ascii=False, indent=1)}\n\n"
            f"# 원문\n{page_text[:50000]}")
    from .humanize import checker, style_rules

    out = claude.json_call(model=config.SUMMARY_MODEL, system=RULES + "\n\n# 문체 규칙\n" + style_rules(), user=user,
                           schema=GUIDE_UPDATE, max_tokens=8000)
    for m in (out.get("add") or []) + (out.get("update") or []):
        for key in ("title", "body"):
            if isinstance(m.get(key), str):
                m[key] = checker().fix_c11(m[key])
    return out


def check_watch(claude, today: date, now_text: str, force: bool = False, fetch=None) -> dict:
    """Read each watched official guide page once a day; ask for changes only when its text changed."""
    from .extract import fetch_article

    fetch = fetch or fetch_article
    data = load()
    report = {"checked": 0, "changed": [], "changes": [], "errors": {}}
    for vendor in data.get("vendors", []):
        for w in vendor.get("watch", []):
            if not force and (w.get("checkedAt") or "")[:10] >= today.isoformat():
                continue
            try:
                art = fetch(w["url"])
                if len(art.text) < 800:
                    raise RuntimeError(f"본문이 너무 짧음({len(art.text)}자)")
            except Exception as exc:  # noqa: BLE001
                report["errors"][w["url"]] = f"{type(exc).__name__}: {exc}"[:300]
                continue
            report["checked"] += 1
            text = "\n".join([art.text, *art.tables])
            h = page_hash(text)
            w["checkedAt"] = now_text
            if w.get("hash") in (None, ""):
                w["hash"] = h                      # first look: remember the page, nothing to compare yet
                continue
            if h == w["hash"]:
                continue
            source = {"title": w.get("title") or art.title, "url": w["url"]}
            proposal = _ask(claude, vendor, source, text,
                            "이 공식 가이드 페이지 내용이 지난 확인 이후 바뀌었다. 새로 생긴 권고나 바뀐 권고만 반영해라.")
            report["changed"].append(w["url"])
            report["changes"] += merge(vendor, proposal, source, text, today)
            report["changes"] += refresh_features(claude, data, vendor["company"], w["url"], text, today)
            w["hash"], w["changedAt"] = h, today.isoformat()
    if report["checked"]:
        data["updatedAt"] = today.isoformat() if report["changes"] else data.get("updatedAt", "")
        data["checkedAt"] = now_text
        save(data)
    return report


def feature_cells(data: dict, company: str, url: str) -> list[tuple[dict, dict]]:
    """(row, cell) pairs of the app feature map that cite this page for this company."""
    out = []
    for row in (data.get("appFeatures") or {}).get("rows", []):
        c = (row.get("cells") or {}).get(company)
        if c and any(s.get("url") == url for s in c.get("sources", [])):
            out.append((row, c))
    return out


def refresh_features(claude, data: dict, company: str, url: str, page_text: str, today: date) -> list[str]:
    """When a watched help page changed, re-check the feature map cells that cite it."""
    pairs = feature_cells(data, company, url)
    if not pairs:
        return []
    cells = [{"key": r["key"], "label": r.get("label", ""), "name": c["name"], "note": c["note"]} for r, c in pairs]
    user = (f"회사: {company}\n원문: {url}\n\n# 이 페이지를 근거로 한 칸\n{json.dumps(cells, ensure_ascii=False, indent=1)}\n\n"
            f"# 원문\n{page_text[:50000]}")
    proposal = claude.json_call(model=config.SUMMARY_MODEL, system=FEATURE_RULES, user=user, schema=FEATURE_UPDATE,
                                max_tokens=2000)
    return apply_feature_updates(data, company, pairs, proposal, page_text, today)


def apply_feature_updates(data: dict, company: str, pairs, proposal: dict, page_text: str, today: date) -> list[str]:
    pool = guard.numbers_in(page_text)
    by_key = {r["key"]: (r, c) for r, c in pairs}
    changes = []
    for u in (proposal.get("update") or [])[:len(pairs)]:
        hit = by_key.get(u.get("key"))
        name, note = (u.get("name") or "").strip(), (u.get("note") or "").strip()
        if hit is None or not name or not note or len(note) > 300:
            continue
        row, c = hit
        if (name, note) == (c["name"], c["note"]):
            continue
        # Limits and counts matter here (character limits, task counts), so every number must be on the page.
        if not all(any(abs(n - p) < 1e-6 for p in pool) for n in guard.numbers_in(f"{name} {note}")):
            changes.append(f"제외(원문에 없는 수치): 대응표 [{company}] {row.get('label')}")
            continue
        c.update(name=name, note=note, updatedAt=today.isoformat())
        data["appFeatures"]["updatedAt"] = today.isoformat()
        changes.append(f"대응표 수정: [{company}] {row.get('label')} → {name}")
    if pairs:
        data["appFeatures"]["checkedAt"] = today.isoformat()
    return changes


def from_tip(claude, item: dict, article, today: date) -> list[str]:
    """Add up to two prompting methods from a newly added '활용 팁' article."""
    data = load()
    vendor = next((v for v in data.get("vendors", []) if v.get("company") == item.get("company")), None)
    if vendor is None:
        return []
    url = (item.get("sources") or [{}])[0].get("url") or article.url
    source = {"title": item.get("title", ""), "url": url}
    if any((m.get("source") or {}).get("url") == url for m in vendor.get("methods", [])):
        return []
    text = "\n".join([article.title, article.text, *article.tables])
    proposal = _ask(claude, vendor, source, text,
                    "새로 올라온 공식 활용 팁 글이다. 프롬프트를 쓰는 방법으로 일반화할 수 있는 권고가 있으면 최대 2개만 add에 넣어라. "
                    "제품 기능 소개나 일회성 사례뿐이면 빈 배열로 둔다. update는 쓰지 않는다.")
    proposal["add"] = (proposal.get("add") or [])[:2]
    proposal["update"] = []
    changes = merge(vendor, proposal, source, text, today, news_id=item.get("id"))
    if any(c.startswith("가이드 추가") for c in changes):
        data["updatedAt"] = today.isoformat()
        save(data)
    return changes
