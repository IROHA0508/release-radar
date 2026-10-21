"""Keep the API price table (data/prices.json) in line with the official pricing pages.

Once a day (and whenever a newly announced model has no record yet) each company's pricing page is
read, Claude says which of our models are listed there and at what standard text-token prices, every
value is checked against the page text, and prices.json is updated:

- listed and verified      -> prices refreshed, status "available" (or "deprecated" if the page says so)
- not listed               -> counted; after PRICE_MISSING_LIMIT checks in a row the model leaves the
                              table (status "unlisted"). A model never seen on the page is "unlisted" at once.
- not verifiable           -> nothing changes (a wrong extraction must never rewrite the table)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from . import config, detect, guard

log = logging.getLogger(__name__)

STR = {"type": "string"}
PRICE_CHECK = {
    "type": "object", "additionalProperties": False, "required": ["models"],
    "properties": {"models": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["key", "listed", "apiId", "input", "cached", "output", "note", "deprecated", "evidence"],
        "properties": {
            "key": STR, "listed": {"type": "boolean"}, "apiId": STR, "input": STR, "cached": STR, "output": STR,
            "note": STR, "deprecated": {"type": "boolean"}, "evidence": STR,
        }}}},
}

RULES = """\
너는 AI 모델 API의 공식 가격 페이지를 읽고, 우리 사이트의 가격표가 맞는지 확인하는 도우미다.
반드시 아래 페이지 내용에 있는 값만 쓴다. 기억이나 추측으로 채우지 않는다.

각 후보 모델(key)마다:
- listed: 이 페이지에 그 모델의 API 가격이 있으면 true. 없거나, 페이지가 API에서 쓸 수 없다고 하면 false.
  일부 조직에만 제공(limited availability 등)되더라도 가격이 실려 있으면 true로 하고 note에 '제한 제공'과 조건을 쓴다.
- apiId: 페이지에 적힌 모델 ID(예: gpt-6.1-sol, claude-opus-5-5, gemini-3.6-flash). 페이지에 ID가 없으면 빈 문자열.
- input / cached / output: 기본(standard) 등급의 텍스트 토큰 가격, 100만 토큰당 USD. 페이지 표기 그대로 "$2.50"처럼.
  캐시 입력(cache read/cached input/context caching) 가격이 없으면 cached는 빈 문자열. Batch·Priority·Flex 가격은 쓰지 않는다.
  컨텍스트 길이별로 다르면 기본(짧은 쪽) 가격을 쓰고 note에 구간을 적는다. 이미지·오디오 전용 모델이면 그 모델의 대표
  토큰 가격(텍스트 또는 해당 모달리티)을 쓰고 note에 무엇의 가격인지 적는다.
- note: 한국어로 짧게, 페이지에 적힌 사실만. 기한이 있는 가격과 그 날짜, 긴 컨텍스트 구간 가격, 지원 종료 예정일,
  fast mode 같은 별도 가격 등. 페이지에 없는 표현(예: 페이지가 쓰지 않은 '도입가', 권장 사항)은 쓰지 않는다. 없으면 빈 문자열.
- deprecated: 페이지에 지원 종료(deprecated/legacy, 종료 예정일) 표시가 있으면 true.
- evidence: 그 가격이 적힌 줄을 페이지에서 그대로 짧게 옮긴 것.
listed가 false면 가격 칸은 빈 문자열로 두고, 이유가 페이지에 있으면 note에 쓴다.
"""


PAGE_LIMIT = 200_000


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
    return {"checkedAt": "", "pages": {}, "models": []}


def load() -> dict:
    if config.PRICES_FILE.exists():
        return json.loads(config.PRICES_FILE.read_text(encoding="utf-8"))
    return _empty()


def save(data: dict) -> None:
    data["models"].sort(key=lambda m: (["openai", "anthropic", "google"].index(m["company"])
                                       if m["company"] in ("openai", "anthropic", "google") else 9,
                                       m.get("status") != "available", m.get("name", "")))
    config.PRICES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def model_key(apiId: str | None, name: str | None) -> str:
    return (apiId or "").strip().lower() or "name:" + detect.model_key(name)


def clean_name(name: str) -> str:
    """'Gemini 3.7 Flash (도입가, 12월 31일까지)' -> 'Gemini 3.7 Flash'."""
    return re.sub(r"\s*\(.*?\)\s*", " ", name or "").strip()


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
        if item.get("kind") == "활용 팁":
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
                continue
            out[key] = {"company": item["company"], "name": clean_name(m.get("name")), "apiId": m.get("apiId"),
                        "input": None, "cached": None, "output": None, "note": "", "status": "new",
                        "newsId": item["id"], "verifiedAt": None, "missing": 0}
    return out


def due(data: dict, company: str, today: date) -> bool:
    """Each company's page is read once a day."""
    page = (data.get("pages") or {}).get(company) or {}
    return (page.get("checkedAt") or "")[:10] < today.isoformat() or page.get("result") != "확인"


def _values_ok(row: dict, pool: set[float]) -> bool:
    found = False
    for k in ("input", "cached", "output"):
        v = (row.get(k) or "").strip()
        if not v:
            continue
        nums = guard.numbers_in(v)
        if not nums or not all(any(abs(n - p) < 1e-6 for p in pool) for n in nums):
            return False
        found = found or k in ("input", "output")
    return found


def _identity_ok(row: dict, entry: dict, page_lower: str, page_keys: str) -> bool:
    for mid in (row.get("apiId"), entry.get("apiId")):
        if mid and mid.lower() in page_lower:
            return True
    return bool(entry.get("name")) and detect.model_key(entry["name"]) in page_keys


def check_company(claude, company: str, entries: list[tuple[str, dict]], article, today: date) -> tuple[dict, list[str]]:
    """Return (results by key, notes). A result is {"listed": bool, ...} only for verified rows."""
    page = "\n".join([article.text, *article.tables])
    lines = "\n".join(f"[{key}] {e.get('name')} | API ID: {e.get('apiId') or '모름'}" for key, e in entries)
    user = (f"회사: {company}\n가격 페이지: {article.url}\n\n# 확인할 후보 모델\n{lines}\n\n"
            f"# 가격 페이지 본문\n{article.text[:PAGE_LIMIT]}\n\n# 페이지의 표\n" + "\n\n".join(article.tables)[:30000])
    out = claude.json_call(model=config.SUMMARY_MODEL, system=RULES, user=user, schema=PRICE_CHECK, max_tokens=8000)
    pool = guard.numbers_in(page)
    page_lower = page.lower()
    page_keys = re.sub(r"[^a-z0-9.]+", "", page_lower)
    by_key = dict(entries)
    results, notes = {}, []
    for row in out.get("models", []):
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
    return results, notes


def apply(data: dict, cands: dict[str, dict], company: str, results: dict, today: date) -> list[str]:
    """Merge one company's verified results into data. Returns human-readable changes."""
    changes = []
    entries = [(k, e) for k, e in cands.items() if e["company"] == company]
    was_available = [k for k, e in entries if e.get("status") in ("available", "deprecated")]
    gone = [k for k in was_available if k in results and not results[k].get("listed")]
    if was_available and len(gone) > max(1, len(was_available) // 2):
        # Half the table vanishing at once is a reading problem, not news.
        return [f"{company}: 확인된 모델 {len(was_available)}개 중 {len(gone)}개가 안 보여 이번 결과는 반영하지 않음"]
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
            # A shutdown notice often lives on a separate deprecations page, so it is kept once known.
            status = "deprecated" if r.get("deprecated") or e.get("status") == "deprecated" else "available"
            if e.get("status") == "available" and status == "deprecated":
                changes.append(f"지원 종료 예정 표시: {name}")
            if status != e.get("status"):
                e["since"] = today.isoformat()
                moved = True
            e.update(new)
            e["apiId"] = e.get("apiId") or (r.get("apiId") or None)
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
            data["models"].append(e)
    return changes


def run(claude, today: date, now_text: str, force: bool = False, fetch=None) -> dict:
    """Check every company whose page is due (daily) or that has a model with no record yet."""
    fetch = fetch or fetch_page
    data = load()
    cands = candidates(data)
    report = {"checked": [], "changes": [], "notes": [], "errors": {}}
    for company, url in config.PRICE_PAGES.items():
        entries = [(k, e) for k, e in cands.items() if e["company"] == company]
        fresh = any(e.get("status") == "new" for _, e in entries)
        if not entries or not (force or fresh or due(data, company, today)):
            continue
        try:
            article = fetch(url)
            if len(article.text) < 2000:
                raise RuntimeError(f"가격 페이지 본문이 너무 짧음({len(article.text)}자)")
            results, notes = check_company(claude, company, entries, article, today)
        except Exception as exc:  # noqa: BLE001 - keep the table as it is
            from .summarize import is_auth_error

            if is_auth_error(exc):
                raise
            report["errors"][company] = f"{type(exc).__name__}: {exc}"[:500]
            data.setdefault("pages", {})[company] = {"url": url, "checkedAt": now_text, "result": "읽기 실패"}
            continue
        report["checked"].append(company)
        report["notes"] += notes
        report["changes"] += apply(data, cands, company, results, today)
        data.setdefault("pages", {})[company] = {"url": url, "checkedAt": now_text, "result": "확인"}
    if report["checked"]:
        data["checkedAt"] = now_text
        save(data)
    return report
