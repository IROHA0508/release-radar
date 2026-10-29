"""Keep the API price table (data/prices.json) in line with the official pricing and deprecation pages.

Once a day (and whenever a newly announced model has no record yet) each company's pricing page is
read, Claude says which of our models are listed there and at what standard prices and which other
models the page prices, every value is checked against the page text, and prices.json is updated:

- listed and verified      -> prices refreshed, status "available" (or "deprecated" if the page says so)
- not listed               -> counted; after PRICE_MISSING_LIMIT checks in a row the model leaves the
                              table (status "unlisted"). A model never seen on the page is "unlisted" at once.
- on the page, not in ours -> added (discovery), so models no news item covered still reach the table
- not verifiable           -> nothing changes (a wrong extraction must never rewrite the table)

Then the company's deprecation page is read:

- shutdown date passed     -> status "retired" (kept in a separate list with the replacement). A retired
                              model is never checked against the pricing page again, because pricing
                              pages keep old models' prices after they stop working.
- shutdown date ahead      -> status "deprecated" with the date and the replacement
- retired in the last RETIRED_WINDOW_DAYS days but never in our table -> added as "retired", so someone
  whose code suddenly fails can look the model up
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta

from . import config, detect, guard

log = logging.getLogger(__name__)

STR = {"type": "string"}
CATEGORIES = ("text", "audio", "media", "other")
CAT = {"type": "string", "enum": list(CATEGORIES)}
_ROW = {"apiId": STR, "input": STR, "cached": STR, "output": STR, "perUnit": STR, "category": CAT, "desc": STR,
        "note": STR, "deprecated": {"type": "boolean"}, "evidence": STR}
PRICE_CHECK = {
    "type": "object", "additionalProperties": False, "required": ["models", "others"],
    "properties": {
        "models": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["key", "listed", *_ROW],
            "properties": {"key": STR, "listed": {"type": "boolean"}, **_ROW}}},
        "others": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", *_ROW],
            "properties": {"name": STR, **_ROW}}},
    },
}
DEPRECATION_CHECK = {
    "type": "object", "additionalProperties": False, "required": ["models"],
    "properties": {"models": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["apiId", "status", "shutdown", "replacement", "category", "evidence"],
        "properties": {"apiId": STR, "status": {"type": "string", "enum": ["retired", "deprecated"]},
                       "shutdown": STR, "replacement": STR, "category": CAT, "evidence": STR}}}},
}

RULES = """\
너는 AI 모델 API의 공식 가격 페이지를 읽고 우리 사이트의 가격표가 맞는지 확인하는 도우미다.
반드시 아래 페이지 내용에 있는 값만 쓴다. 기억이나 추측으로 채우지 않는다.

models에는 '확인할 후보 모델'마다(key 그대로) 한 줄씩 쓴다.
- listed: 이 페이지에 그 모델의 API 가격이 있으면 true. 없거나, 페이지가 API에서 쓸 수 없다고 하면 false.
  일부 조직에만 제공(limited availability 등)되더라도 가격이 실려 있으면 true로 하고 note에 '제한 제공'과 조건을 쓴다.
- apiId: 페이지에 적힌 모델 ID(예: gpt-6.1-sol, claude-opus-5-5, gemini-3.6-flash). 페이지에 ID가 없으면 빈 문자열.
- input / cached / output: 기본(standard) 등급의 토큰 가격, 100만 토큰당 USD. 페이지 표기 그대로 "$2.50"처럼.
  캐시 입력(cache read/cached input/context caching) 가격이 없으면 cached는 빈 문자열. Batch·Flex·Priority·Fast 가격은 쓰지 않는다.
  컨텍스트 길이별로 다르면 기본(짧은 쪽) 가격을 쓰고 note에 구간을 적는다. 이미지·오디오 전용 모델이면 그 모델의 대표
  토큰 가격(텍스트 또는 해당 모달리티)을 쓰고 note에 무엇의 가격인지 적는다. 토큰 가격이 없으면 빈 문자열.
- perUnit: 토큰이 아니라 분·초·이미지·요청 단위로 매긴 가격이 있으면 "$0.05 / 분"처럼 금액과 단위만 쓴다.
  페이지가 추정 비용(estimated cost)이라고 하면 끝에 " (추정)"을 붙인다. 없으면 빈 문자열.
- category: text(글을 읽고 쓰는 모델, 코딩·추론 포함), audio(음성 대화·실시간·TTS·전사·번역),
  media(이미지·영상·음악 생성), other(임베딩, 로보틱스, 리서치·코딩 에이전트, 검열(moderation) 등 나머지).
- desc: 페이지가 그 모델을 한 문장으로 소개하면 한국어로 짧게 옮긴다. 없으면 빈 문자열.
- note: 한국어로 짧게, 페이지에 적힌 사실만. 기한이 있는 가격과 그 날짜, 긴 컨텍스트 구간 가격, 지원 종료 예정일,
  fast mode 같은 별도 가격 등. 페이지에 없는 표현(예: 페이지가 쓰지 않은 '도입가', 권장 사항)은 쓰지 않는다. 없으면 빈 문자열.
- deprecated: 페이지에 지원 종료(deprecated/legacy, 종료 예정일) 표시가 있으면 true.
- evidence: 그 가격이 적힌 줄을 페이지에서 그대로 짧게 옮긴 것.
listed가 false면 가격 칸은 빈 문자열로 두고 이유가 페이지에 있으면 note에 쓴다.

others에는 이 페이지에 가격이 실렸지만 후보 목록에도, '지원이 끝나 뺀 모델' 목록에도 없는 모델을 빠짐없이 쓴다.
name은 페이지에 적힌 모델 이름(없으면 ID), 나머지 칸은 위와 같다. 후보와 같은 모델을 이름만 바꿔 다시 쓰지 않는다.
넣지 않는 것: 같은 모델의 Batch·Flex·Priority·Fast 등급 행, 파인튜닝 학습·파인튜닝 모델 가격, 도구(웹 검색, 코드 실행,
파일 검색, 컨테이너), 그라운딩, 저장 요금처럼 모델이 아닌 항목.
"""

DEP_RULES = """\
너는 AI 모델 API의 공식 지원 종료(deprecation) 페이지를 읽는 도우미다. 반드시 페이지에 있는 값만 쓴다.
models에 다음을 빠짐없이 쓴다.
1. 종료일이 {since} 이후로 정해진 모델. 이미 종료된 것과 앞으로 종료될 것 모두.
2. 아래 '우리 표의 모델' 가운데 페이지에 종료일이 적힌 모델(날짜가 {since}보다 이르더라도).
각 줄:
- apiId: 페이지에 적힌 모델 ID 그대로(스냅샷 날짜 포함). 한 줄에 ID가 여럿이면 ID마다 따로 쓴다.
- status: 이미 종료(retired, shut down)됐으면 "retired", 종료가 예정(deprecated)이면 "deprecated".
- shutdown: 종료일(예정일)을 YYYY-MM-DD로.
- replacement: 페이지가 권하는 대체 모델을 그대로. 없으면 빈 문자열.
- category: text, audio, media, other 중 하나(가격표와 같은 기준).
- evidence: 그 줄을 페이지에서 그대로 짧게 옮긴 것.
넣지 않는 것: 종료일이 정해지지 않은 모델('No shutdown date announced', 'To be announced', N/A, 자동 라우팅),
아직 사용 중(Active)인 모델의 가장 이른 종료 가능일(예: 'Not sooner than ...'), 모델이 아닌 API·엔드포인트·기능의 종료.
"""

PAGE_LIMIT = 200_000
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]


def fetch_page(url: str):
    """Pricing pages are read as plain markdown when the URL serves it; otherwise as an article."""
    from .extract import Article, fetch_article
    from .feeds import http_get

    if url.endswith((".md", ".md.txt", ".txt")):
        resp = http_get(url, accept="text/markdown,text/plain,*/*")
        resp.raise_for_status()
        text = resp.text
        title = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), url)
        return Article(url, title, None, text, [], [], via="markdown")
    return fetch_article(url)


def _empty() -> dict:
    return {"checkedAt": "", "pages": {}, "deprecationPages": {}, "models": []}


def load() -> dict:
    if config.PRICES_FILE.exists():
        return json.loads(config.PRICES_FILE.read_text(encoding="utf-8"))
    return _empty()


def save(data: dict) -> None:
    rank = {"available": 0, "deprecated": 1, "unlisted": 2, "retired": 3}
    data["models"].sort(key=lambda m: (["openai", "anthropic", "google"].index(m["company"])
                                       if m["company"] in ("openai", "anthropic", "google") else 9,
                                       rank.get(m.get("status"), 0), m.get("name", "")))
    config.PRICES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def model_key(apiId: str | None, name: str | None) -> str:
    return (apiId or "").strip().lower() or "name:" + detect.model_key(name)


def clean_name(name: str) -> str:
    """'Gemini 3.7 Flash (도입가, 12월 31일까지)' -> 'Gemini 3.7 Flash'."""
    return re.sub(r"\s*\(.*?\)\s*", " ", name or "").strip()


def guess_category(api_id: str | None, name: str | None = None) -> str:
    """Fallback when Claude gives no category: same split as the price table's four tables."""
    s = f"{api_id or ''} {name or ''}".lower()
    if re.search(r"embed|robotics|deep-research|deep research|antigravity|moderation|computer-use|search-preview", s):
        return "other"
    if re.search(r"realtime|live|tts|transcri|whisper|audio|speech|translate", s):
        return "audio"
    if re.search(r"image|banana|imagen|veo|omni|lyria|sora|dall-e|video|music", s):
        return "media"
    return "text"


def _flat(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def name_matches_id(name: str | None, api_id: str | None) -> bool:
    """'Claude Opus 4.1' ~ 'claude-opus-4-1-20250805', 'gpt-5.4-nano' ~ 'gpt-5.4-nano-2026-03-17'.
    Only an exact match or an 8-digit snapshot date may follow, so 'Claude Opus 4' never matches Opus 4.1."""
    n, i = _flat(name), _flat(api_id)
    return bool(n and i) and (i == n or (i.startswith(n) and re.fullmatch(r"\d{8}", i[len(n):]) is not None))


def find_same(models: list[dict], company: str, api: str | None, name: str | None) -> dict | None:
    """An entry (any status) that is the same model under another spelling, ID or snapshot."""
    for m in models:
        if m.get("company") != company:
            continue
        mid = m.get("apiId")
        if api and mid and (api.lower() == mid.lower() or name_matches_id(mid, api) or name_matches_id(api, mid)):
            return m
        if api and name_matches_id(m.get("name"), api):
            return m
        if mid and name_matches_id(name, mid):
            return m
        if name and detect.model_key(clean_name(name)) == detect.model_key(m.get("name")):
            return m
    return None


def candidates(data: dict) -> dict[str, dict]:
    """Every model the price table should account for: what prices.json already tracks plus every model
    announced with API prices in a launch or update item on the site."""
    out: dict[str, dict] = {}
    by_name: dict[str, str] = {}
    for m in data.get("models", []):
        key = model_key(m.get("apiId"), m.get("name"))
        out[key] = m
        by_name[detect.model_key(m.get("name"))] = key
    for path in sorted(config.NEWS_DIR.glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        if item.get("kind") in ("활용 팁", "제품·기능 출시") and not any(m.get("input") or m.get("output") for m in item.get("models", [])):
            continue
        for m in item.get("models", []):
            if not (m.get("input") or m.get("output")):
                continue
            key = model_key(m.get("apiId"), clean_name(m.get("name")))
            if key not in out and detect.model_key(clean_name(m.get("name"))) in by_name:
                key = by_name[detect.model_key(clean_name(m.get("name")))]   # same model, ID added later
            if key in out:
                if not out[key].get("newsId"):
                    out[key]["newsId"] = item["id"]
                    # a model added from the pricing page that a launch item now covers: its launch date
                    if not out[key].get("since") and out[key].get("status") in ("available", "deprecated") and item.get("date"):
                        out[key]["since"] = item["date"]
                continue
            out[key] = {"company": item["company"], "name": clean_name(m.get("name")), "apiId": m.get("apiId"),
                        "category": guess_category(m.get("apiId"), m.get("name")),
                        "input": None, "cached": None, "output": None, "note": "", "status": "new",
                        "newsId": item["id"], "verifiedAt": None, "missing": 0}
    return out


def due(data: dict, company: str, today: date) -> bool:
    """Each company's page is read once a day."""
    page = (data.get("pages") or {}).get(company) or {}
    return (page.get("checkedAt") or "")[:10] < today.isoformat() or page.get("result") != "확인"


def _values_ok(row: dict, pool: set[float]) -> bool:
    found = False
    for k in ("input", "cached", "output", "perUnit"):
        v = (row.get(k) or "").strip()
        if not v:
            continue
        nums = guard.numbers_in(v)
        if not nums or not all(any(abs(n - p) < 1e-6 for p in pool) for n in nums):
            return False
        found = found or k in ("input", "output", "perUnit")
    return found


def _identity_ok(row: dict, entry: dict, page_lower: str, page_keys: str) -> bool:
    for mid in (row.get("apiId"), entry.get("apiId")):
        if mid and mid.lower() in page_lower:
            return True
    return bool(entry.get("name")) and detect.model_key(entry["name"]) in page_keys


def _category(row: dict, api: str | None, name: str | None) -> str:
    return row.get("category") if row.get("category") in CATEGORIES else guess_category(api, name)


def check_company(claude, company: str, entries: list[tuple[str, dict]], article, today: date,
                  retired: list[dict] | None = None) -> tuple[dict, list[dict], list[str]]:
    """Return (results by key, newly found models, notes). Only verified rows are returned."""
    page = "\n".join([article.text, *article.tables])
    lines = "\n".join(f"[{key}] {e.get('name')} | API ID: {e.get('apiId') or '모름'}" for key, e in entries)
    gone = "\n".join(f"- {m.get('name')} | {m.get('apiId') or ''}" for m in retired or []) or "(없음)"
    user = (f"회사: {company}\n가격 페이지: {article.url}\n\n# 확인할 후보 모델\n{lines or '(없음)'}\n\n"
            f"# 지원이 끝나 뺀 모델 (others에 넣지 말 것)\n{gone}\n\n"
            f"# 가격 페이지 본문\n{article.text[:PAGE_LIMIT]}\n\n# 페이지의 표\n" + "\n\n".join(article.tables)[:30000])
    out = claude.json_call(model=config.SUMMARY_MODEL, system=RULES, user=user, schema=PRICE_CHECK, max_tokens=24000)
    pool = guard.numbers_in(page)
    page_lower = page.lower()
    page_keys = re.sub(r"[^a-z0-9.]+", "", page_lower)
    by_key = dict(entries)
    results, found, notes = {}, [], []
    for row in out.get("models", []) or []:
        key = row.get("key", "")
        entry = by_key.get(key)
        if entry is None:
            continue
        if row.get("listed"):
            if _values_ok(row, pool) and _identity_ok(row, entry, page_lower, page_keys):
                results[key] = row
            else:
                notes.append(f"{entry.get('name')}: 가격을 원문에서 확인하지 못해 그대로 둠")
        else:
            results[key] = {"listed": False, "note": row.get("note", "")}
    for row in out.get("others", []) or []:
        api, name = (row.get("apiId") or "").strip(), clean_name(row.get("name") or "")
        label = name or api
        if not label:
            continue
        on_page = (api.lower() in page_lower) if api else (detect.model_key(name) in page_keys)
        if not on_page:
            notes.append(f"새 모델 후보 {label}: 이름이나 ID가 원문에 없어 넣지 않음")
        elif not _values_ok(row, pool):
            notes.append(f"새 모델 후보 {label}: 가격을 원문에서 확인하지 못해 넣지 않음")
        else:
            found.append(row)
    return results, found, notes


def _vanishing(entries: list[tuple[str, dict]], results: dict) -> str | None:
    was_available = [k for k, e in entries if e.get("status") in ("available", "deprecated")]
    gone = [k for k in was_available if k in results and not results[k].get("listed")]
    if was_available and len(gone) > max(1, len(was_available) // 2):
        return f"확인된 모델 {len(was_available)}개 중 {len(gone)}개가 안 보여 이번 결과는 반영하지 않음"
    return None


def apply(data: dict, cands: dict[str, dict], company: str, results: dict, today: date) -> list[str]:
    """Merge one company's verified results into data. Returns human-readable changes."""
    changes = []
    entries = [(k, e) for k, e in cands.items() if e["company"] == company and e.get("status") != "retired"]
    why = _vanishing(entries, results)
    if why:
        # Half the table vanishing at once is a reading problem, not news.
        return [f"{company}: {why}"]
    for key, e in entries:
        r = results.get(key)
        if r is None:
            if e.get("status") != "new":
                continue
            r = {"listed": False, "note": ""}       # a new model the page says nothing about
        name = e.get("name")
        if r.get("listed"):
            new = {k: (r.get(k) or "").strip() or None for k in ("input", "cached", "output")}
            moved = False
            if e.get("status") in ("available", "deprecated"):
                for k, label in (("input", "입력"), ("cached", "캐시 입력"), ("output", "출력")):
                    if (e.get(k) or None) != new[k]:
                        changes.append(f"가격 변경: {name} {label} {e.get(k) or '—'} → {new[k] or '—'}")
                        moved = True
            else:
                changes.append(f"가격표에 추가: {name} (입력 {new['input'] or '—'} / 출력 {new['output'] or '—'})")
                moved = True
            # Per-minute or per-image prices are worded freely, so only a change in the numbers counts.
            unit = (r.get("perUnit") or "").strip()
            if unit and guard.numbers_in(unit) != guard.numbers_in(e.get("perUnit") or ""):
                if e.get("perUnit") and e.get("status") in ("available", "deprecated"):
                    changes.append(f"가격 변경: {name} 그 밖의 단가 {e['perUnit']} → {unit}")
                e["perUnit"] = unit
            # A shutdown notice often lives on a separate deprecations page, so it is kept once known.
            status = "deprecated" if r.get("deprecated") or e.get("status") == "deprecated" else "available"
            if e.get("status") == "available" and status == "deprecated":
                changes.append(f"지원 종료 예정 표시: {name}")
            if status != e.get("status"):
                e["since"] = today.isoformat()
                moved = True
            e.update(new)
            e["apiId"] = e.get("apiId") or (r.get("apiId") or None)
            if not e.get("category"):
                e["category"] = _category(r, e.get("apiId"), name)
            if not e.get("desc") and not e.get("newsId") and (r.get("desc") or "").strip():
                e["desc"] = r["desc"].strip()
            # Keep the wording stable from day to day; rewrite the note only when something changed.
            if moved or not e.get("note"):
                e["note"] = (r.get("note") or "").strip() or e.get("note") or ""
            e["status"], e["verifiedAt"], e["missing"] = status, today.isoformat(), 0
        else:
            e["missing"] = int(e.get("missing") or 0) + 1
            if e.get("status") in ("available", "deprecated"):
                if e["missing"] >= config.PRICE_MISSING_LIMIT:
                    e["status"], e["since"] = "unlisted", today.isoformat()
                    e["note"] = (r.get("note") or "").strip() or "공식 가격 페이지에서 확인되지 않음"
                    changes.append(f"가격표에서 뺌: {name} (공식 가격 페이지에 {e['missing']}번 연속 없음)")
            elif e.get("status") == "new":
                e["status"], e["since"] = "unlisted", today.isoformat()
                e["note"] = (r.get("note") or "").strip() or "공식 가격 페이지에 아직 없음"
    known = {model_key(m.get("apiId"), m.get("name")) for m in data["models"]}
    for key, e in entries:
        if key not in known and e.get("status") != "new":
            e.setdefault("category", guess_category(e.get("apiId"), e.get("name")))
            data["models"].append(e)
    return changes


def add_found(data: dict, company: str, found: list[dict], today: date) -> list[str]:
    """Add models the pricing page lists but the table did not have yet."""
    fresh = []
    for r in found:
        api = (r.get("apiId") or "").strip() or None
        name = clean_name(r.get("name") or "") or api
        if find_same(data["models"], company, api, name) or find_same(fresh, company, api, name):
            continue
        fresh.append({
            "company": company, "name": name, "apiId": api, "category": _category(r, api, name),
            "desc": (r.get("desc") or "").strip(),
            **{k: (r.get(k) or "").strip() or None for k in ("input", "cached", "output", "perUnit")},
            "note": (r.get("note") or "").strip(), "status": "deprecated" if r.get("deprecated") else "available",
            "newsId": None, "verifiedAt": today.isoformat(), "missing": 0, "addedAt": today.isoformat()})
    if len(fresh) > config.PRICE_DISCOVER_LIMIT:
        return [f"{company}: 새 모델 후보가 {len(fresh)}개라 읽기 오류로 보고 이번에는 추가하지 않음"]
    data["models"].extend(fresh)
    return [f"새 모델 추가: {e['name']} [{e['category']}] (입력 {e['input'] or '-'} / 출력 {e['output'] or '-'}"
            + (f" / {e['perUnit']}" if e.get("perUnit") else "") + ")" for e in fresh]


# ---- deprecation pages ----

def _norm_page(text: str) -> str:
    text = re.sub(r"[‐-–−]", "-", text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).lower()


def _date_forms(d: str) -> list[str]:
    y, m, dd = (int(x) for x in d.split("-"))
    mon = MONTHS[m - 1]
    return [d, f"{mon} {dd}, {y}", f"{mon[:3]} {dd}, {y}", f"{mon[:3]}. {dd}, {y}", f"{dd} {mon} {y}",
            f"{y}/{m:02d}/{dd:02d}", f"{y}.{m:02d}.{dd:02d}"]


def date_near(page: str, api: str, d: str, span: int = 1500) -> bool:
    """The date appears near the model ID, and not as an 'earliest possible' date of a model still in use."""
    forms = _date_forms(d)
    api = api.lower()
    start = 0
    while (i := page.find(api, start)) >= 0:
        window = page[max(0, i - span):i + len(api) + span]
        for f in forms:
            j = window.find(f)
            while j >= 0:
                if not re.search(r"(sooner than|at earliest|earliest)\W*$", window[max(0, j - 30):j]):
                    return True
                j = window.find(f, j + 1)
        start = i + 1
    return False


def check_deprecations(claude, company: str, data: dict, article, today: date) -> tuple[list[dict], list[str]]:
    page = "\n".join([article.text, *article.tables])
    norm = _norm_page(page)
    since = (today - timedelta(days=config.RETIRED_WINDOW_DAYS)).isoformat()
    ours = "\n".join(f"- {m.get('apiId') or m.get('name')} ({m.get('status')})" for m in data.get("models", [])
                     if m.get("company") == company and m.get("status") != "retired") or "(없음)"
    user = (f"회사: {company}\n지원 종료 페이지: {article.url}\n오늘: {today.isoformat()}\n\n# 우리 표의 모델\n{ours}\n\n"
            f"# 페이지 본문\n{article.text[:PAGE_LIMIT]}\n\n# 페이지의 표\n" + "\n\n".join(article.tables)[:30000])
    out = claude.json_call(model=config.SUMMARY_MODEL, system=DEP_RULES.format(since=since), user=user,
                           schema=DEPRECATION_CHECK, max_tokens=24000)
    rows, notes = [], []
    for r in out.get("models", []) or []:
        api, d = (r.get("apiId") or "").strip(), (r.get("shutdown") or "").strip()
        if not api or not DATE_RE.match(d):
            continue
        try:
            date.fromisoformat(d)
        except ValueError:
            continue
        if api.lower() not in norm:
            notes.append(f"지원 종료 {api}: 모델 ID가 원문에 없어 넣지 않음")
        elif not date_near(norm, api, d):
            notes.append(f"지원 종료 {api}: 종료일 {d}를 원문에서 확인하지 못해 넣지 않음")
        else:
            rows.append(r)
    return rows, notes


def _dep_match(models: list[dict], company: str, api: str) -> dict | None:
    """Deprecation rows name exact IDs (a snapshot can retire before its alias), so match IDs exactly;
    an entry known only by name (Anthropic's pricing page has no IDs) matches by name."""
    for m in models:
        if m.get("company") != company:
            continue
        if m.get("apiId") and m["apiId"].lower() == api.lower():
            return m
    for m in models:
        if m.get("company") == company and not m.get("apiId") and name_matches_id(m.get("name"), api):
            return m
    return None


def _retire(e: dict, d: str, repl: str | None, today: date) -> None:
    e.update(status="retired", since=today.isoformat(), shutdown=d, replacement=repl or e.get("replacement"),
             verifiedAt=today.isoformat(), missing=0)


def retire_due(data: dict, company: str, today: date) -> list[str]:
    """A model already marked with a shutdown date retires on that date even if the page could not be read."""
    changes = []
    for e in data["models"]:
        if (e.get("company") == company and e.get("status") in ("available", "deprecated", "unlisted")
                and e.get("shutdown") and e["shutdown"] <= today.isoformat()):
            _retire(e, e["shutdown"], e.get("replacement"), today)
            changes.append(f"지원 종료로 옮김: {e['name']} ({e['shutdown']} 종료일 지남)")
    return changes


def apply_deprecations(data: dict, company: str, rows: list[dict], today: date) -> list[str]:
    window = (today - timedelta(days=config.RETIRED_WINDOW_DAYS)).isoformat()
    t = today.isoformat()
    live = [m for m in data["models"] if m.get("company") == company and m.get("status") in ("available", "deprecated")]
    plan, seen = [], set()
    for r in rows:
        api = r["apiId"].strip()
        if api.lower() in seen:
            continue
        seen.add(api.lower())
        plan.append((r, api, r["shutdown"], (r.get("replacement") or "").strip() or None, _dep_match(data["models"], company, api)))
    retiring = {id(e) for _, _, d, _, e in plan if e is not None and d <= t and e.get("status") in ("available", "deprecated")}
    if live and len(retiring) > max(1, len(live) // 2):
        return [f"{company}: 표의 모델 {len(live)}개 중 {len(retiring)}개가 한꺼번에 지원 종료로 읽혀 이번 결과는 반영하지 않음"]
    changes = []
    for r, api, d, repl, e in plan:
        if e is not None and not e.get("apiId"):
            e["apiId"] = api
        if d <= t:
            if e is None:
                if d >= window:
                    data["models"].append({
                        "company": company, "name": api, "apiId": api, "category": _category(r, api, None),
                        "input": None, "cached": None, "output": None, "note": "", "status": "retired",
                        "newsId": None, "verifiedAt": t, "missing": 0, "since": t, "shutdown": d, "replacement": repl})
                    changes.append(f"지원 종료 모델 추가: {api} ({d} 종료)")
            elif e.get("status") != "retired":
                _retire(e, d, repl, today)
                changes.append(f"지원 종료로 옮김: {e['name']} ({d} 종료" + (f", 대체 {repl})" if repl else ")"))
            else:
                e.setdefault("shutdown", d)
                if repl and not e.get("replacement"):
                    e["replacement"] = repl
        elif e is not None and e.get("status") in ("available", "deprecated"):
            if e["status"] == "available":
                e["status"], e["since"] = "deprecated", t
                changes.append(f"지원 종료 예정 표시: {e['name']} ({d} 종료 예정" + (f", 대체 {repl})" if repl else ")"))
            elif e.get("shutdown") and e["shutdown"] != d:
                changes.append(f"종료 예정일 변경: {e['name']} {e['shutdown']} → {d}")
            e["shutdown"] = d
            if repl:
                e["replacement"] = repl
    return changes


def run(claude, today: date, now_text: str, force: bool = False, fetch=None) -> dict:
    """Check every company whose page is due (daily) or that has a model with no record yet."""
    from .summarize import is_auth_error

    fetch = fetch or fetch_page
    data = load()
    cands = candidates(data)
    report = {"checked": [], "changes": [], "notes": [], "errors": {}}
    for company, url in config.PRICE_PAGES.items():
        entries = [(k, e) for k, e in cands.items() if e["company"] == company and e.get("status") != "retired"]
        fresh = any(e.get("status") == "new" for _, e in entries)
        if not (force or fresh or due(data, company, today)):
            continue
        retired = [m for m in data["models"] if m.get("company") == company and m.get("status") == "retired"]
        try:
            article = fetch(url)
            if len(article.text) < 2000:
                raise RuntimeError(f"가격 페이지 본문이 너무 짧음({len(article.text)}자)")
            results, found, notes = check_company(claude, company, entries, article, today, retired)
        except Exception as exc:  # noqa: BLE001 - keep the table as it is
            if is_auth_error(exc):
                raise
            report["errors"][company] = f"{type(exc).__name__}: {exc}"[:500]
            data.setdefault("pages", {})[company] = {"url": url, "checkedAt": now_text, "result": "읽기 실패"}
            continue
        report["checked"].append(company)
        report["notes"] += notes
        changed = apply(data, cands, company, results, today)
        report["changes"] += changed
        if not _vanishing(entries, results):
            report["changes"] += add_found(data, company, found, today)
        data.setdefault("pages", {})[company] = {"url": url, "checkedAt": now_text, "result": "확인"}

        dep_url = config.DEPRECATION_PAGES.get(company)
        if dep_url:
            try:
                dep = fetch(dep_url)
                if len(dep.text) < 1000:
                    raise RuntimeError(f"지원 종료 페이지 본문이 너무 짧음({len(dep.text)}자)")
                rows, dnotes = check_deprecations(claude, company, data, dep, today)
                report["notes"] += dnotes
                report["changes"] += apply_deprecations(data, company, rows, today)
                result = "확인"
            except Exception as exc:  # noqa: BLE001 - the price check above still counts
                if is_auth_error(exc):
                    raise
                report["errors"][f"{company} 지원 종료"] = f"{type(exc).__name__}: {exc}"[:500]
                result = "읽기 실패"
            data.setdefault("deprecationPages", {})[company] = {"url": dep_url, "checkedAt": now_text, "result": result}
        report["changes"] += retire_due(data, company, today)
    if report["checked"]:
        data["checkedAt"] = now_text
        save(data)
    return report
