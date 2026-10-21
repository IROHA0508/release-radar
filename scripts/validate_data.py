#!/usr/bin/env python3
"""Validate the site's data files before committing.

Usage: python3 scripts/validate_data.py
Exits with code 1 and prints every problem if anything is wrong.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

COMPANIES = {"openai", "anthropic", "google"}
KINDS = {"모델 출시", "모델 업데이트", "활용 팁"}
RESERVED_IDS = {"guide", "prices", "tech", "lab"}
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CHECKED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?$")
REQUIRED = ["id", "company", "date", "kind", "title", "headline", "tldr", "models", "numbers",
            "changes", "availability", "tips", "prompts", "cautions", "sources"]

errors = []


def err(where, msg):
    errors.append(f"{where}: {msg}")


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        err(path.relative_to(ROOT), f"JSON 파싱 실패 - {e}")
        return None


def check_chart(where, c):
    for key in ("title", "rows"):
        if key not in c:
            err(where, f"chart에 '{key}' 없음")
    if c.get("type", "bar") not in ("bar", "dot"):
        err(where, f"chart type은 bar 또는 dot: {c.get('type')}")
    rows = c.get("rows") or []
    if len(rows) < 2:
        err(where, f"chart '{c.get('title')}'는 비교 대상이 2개 이상이어야 함")
    for r in rows:
        if not isinstance(r.get("value"), (int, float)):
            err(where, f"chart '{c.get('title')}'의 '{r.get('label')}' 값이 숫자가 아님")
        if not r.get("label"):
            err(where, f"chart '{c.get('title')}'에 label 없는 행")


def check_news(path):
    d = load(path)
    if d is None:
        return None
    where = path.relative_to(ROOT)
    for key in REQUIRED:
        if key not in d:
            err(where, f"필수 필드 '{key}' 없음")
    nid = d.get("id", "")
    if nid != path.stem:
        err(where, f"id '{nid}'가 파일 이름 '{path.stem}'과 다름")
    if not ID_RE.match(nid) or nid in RESERVED_IDS:
        err(where, f"id 형식 오류 또는 예약어: '{nid}'")
    if d.get("company") not in COMPANIES:
        err(where, f"company는 {sorted(COMPANIES)} 중 하나: {d.get('company')}")
    if not DATE_RE.match(str(d.get("date", ""))):
        err(where, f"date는 YYYY-MM-DD: {d.get('date')}")
    if d.get("kind") not in KINDS:
        err(where, f"kind는 {sorted(KINDS)} 중 하나: {d.get('kind')}")
    for s in d.get("sources", []):
        if not str(s.get("url", "")).startswith("https://"):
            err(where, f"출처 URL은 https로 시작해야 함: {s.get('url')}")
    for p in d.get("prompts", []):
        if p.get("type", "prompt") not in ("prompt", "code"):
            err(where, f"prompt type은 prompt 또는 code: {p.get('type')}")
    for c in d.get("charts", []) or []:
        check_chart(where, c)
    return nid


GUIDE_CATEGORIES = {"기본 작성법", "구조와 형식", "앱 기능과 설정", "예시 활용", "추론과 effort", "긴 문서와 자료", "에이전트와 코딩",
                    "도구와 API 설정", "이미지·영상·음성"}
PRICE_STATUS = {"available", "deprecated", "unlisted"}


def check_guides(g, news_ids):
    where = "data/guides.json"
    if g is None:
        return
    for c in g.get("common", []):
        if not c.get("title") or not c.get("body"):
            err(where, "common 항목에 title/body 없음")
    seen = set()
    for v in g.get("vendors", []):
        co = v.get("company")
        if co not in COMPANIES:
            err(where, f"vendors.company 오류: {co}")
        for key in ("name", "summary", "methods", "templates", "watch"):
            if key not in v:
                err(where, f"{co}: '{key}' 없음")
        for m in v.get("methods", []):
            mid = m.get("id", "")
            if not ID_RE.match(mid) or mid in seen:
                err(where, f"{co}: method id 형식 오류 또는 중복: '{mid}'")
            seen.add(mid)
            if m.get("category") not in GUIDE_CATEGORIES:
                err(where, f"{mid}: category는 {sorted(GUIDE_CATEGORIES)} 중 하나: {m.get('category')}")
            if not m.get("title") or not m.get("body"):
                err(where, f"{mid}: title/body 없음")
            if not str((m.get("source") or {}).get("url", "")).startswith("https://"):
                err(where, f"{mid}: source.url은 https로 시작해야 함")
            if m.get("newsId") and m["newsId"] not in news_ids:
                err(where, f"{mid}: newsId '{m['newsId']}' 소식이 없음")
            for k in ("addedAt", "updatedAt"):
                if m.get(k) and not DATE_RE.match(m[k]):
                    err(where, f"{mid}: {k}는 YYYY-MM-DD")
        for t in v.get("templates", []):
            if not t.get("title") or not t.get("text"):
                err(where, f"{co}: template에 title/text 없음")
        for w in v.get("watch", []):
            if not str(w.get("url", "")).startswith("https://"):
                err(where, f"{co}: watch url은 https로 시작해야 함")
    af = g.get("appFeatures")
    if af is not None:
        if not af.get("title") or not af.get("rows"):
            err(where, "appFeatures에 title/rows 없음")
        keys = set()
        for r in af.get("rows", []):
            key = r.get("key", "")
            if not ID_RE.match(key) or key in keys:
                err(where, f"appFeatures key 형식 오류 또는 중복: '{key}'")
            keys.add(key)
            if not r.get("label"):
                err(where, f"appFeatures {key}: label 없음")
            cells = r.get("cells") or {}
            if set(cells) != COMPANIES:
                err(where, f"appFeatures {key}: cells는 openai/anthropic/google 세 칸이어야 함")
            for co, c in cells.items():
                if not c.get("name") or not c.get("note"):
                    err(where, f"appFeatures {key}.{co}: name/note 없음")
                if not c.get("sources") or not all(str(s_.get("url", "")).startswith("https://") for s_ in c["sources"]):
                    err(where, f"appFeatures {key}.{co}: 근거(sources) URL이 없거나 https가 아님")
                if c.get("methodId") and c["methodId"] not in seen:
                    err(where, f"appFeatures {key}.{co}: methodId '{c['methodId']}' 방법이 없음")
                if c.get("updatedAt") and not DATE_RE.match(c["updatedAt"]):
                    err(where, f"appFeatures {key}.{co}: updatedAt은 YYYY-MM-DD")
    st = g.get("structure")
    if st is not None:
        if not st.get("title") or not st.get("rows"):
            err(where, "structure에 title/rows 없음")
        for r in st.get("rows", []):
            if r.get("company") not in COMPANIES:
                err(where, f"structure.rows.company 오류: {r.get('company')}")
            for k in ("recommended", "inApp", "saveIn"):
                if not r.get(k):
                    err(where, f"structure {r.get('company')}: '{k}' 없음")
            for s_ in r.get("sources", []):
                if not str(s_.get("url", "")).startswith("https://"):
                    err(where, f"structure {r.get('company')}: 근거 URL은 https로 시작해야 함")


def check_prices(p, news_ids):
    where = "data/prices.json"
    if p is None:
        return
    seen = set()
    for m in p.get("models", []):
        name = m.get("name")
        if m.get("company") not in COMPANIES or not name:
            err(where, f"company/name 오류: {m}")
        if m.get("status") not in PRICE_STATUS:
            err(where, f"{name}: status는 {sorted(PRICE_STATUS)} 중 하나: {m.get('status')}")
        key = (m.get("apiId") or name or "").lower()
        if key in seen:
            err(where, f"{name}: 같은 모델이 두 번 있음({key})")
        seen.add(key)
        if m.get("status") in ("available", "deprecated"):
            if not (m.get("input") or m.get("output")):
                err(where, f"{name}: 가격표에 보이는 모델인데 가격이 없음")
            if not m.get("verifiedAt") or not DATE_RE.match(m["verifiedAt"]):
                err(where, f"{name}: verifiedAt(YYYY-MM-DD) 없음")
        if m.get("newsId") and m["newsId"] not in news_ids:
            err(where, f"{name}: newsId '{m['newsId']}' 소식이 없음")
    for co, page in (p.get("pages") or {}).items():
        if co not in COMPANIES or not str(page.get("url", "")).startswith("https://"):
            err(where, f"pages.{co} 오류")


TECH_GROUPS = {"path", "radar"}
TECH_LEVELS = {"기초", "중급", "심화"}
TECH_STAGES = {"관찰", "시도", "랩", "보관"}
TECH_EXAMPLE_TYPES = {"code", "prompt", "scene"}
TECH_REQUIRED = ["id", "group", "name", "en", "level", "definition", "why", "how", "effects", "example", "limits",
                 "prerequisites", "related", "sources", "news", "verifiedAt"]


def check_tech(t, news_ids):
    where = "data/tech.json"
    if t is None:
        return
    groups = {g.get("key"): g for g in t.get("groups") or []}
    if set(groups) != TECH_GROUPS:
        err(where, f"groups에는 {sorted(TECH_GROUPS)}가 하나씩 있어야 함")
    for k, g in groups.items():
        if not g.get("title") or not g.get("intro"):
            err(where, f"groups.{k}에 title과 intro가 필요함")
    items = t.get("items") or []
    ids = [i.get("id") for i in items]
    if len(ids) != len(set(ids)):
        err(where, "items에 중복 id가 있음")
    known = set(ids)
    orders = []
    for i in items:
        tid = i.get("id", "?")
        w = f"{where} [{tid}]"
        for key in TECH_REQUIRED:
            if key not in i:
                err(w, f"필수 필드 '{key}' 없음")
        if not ID_RE.match(str(tid)):
            err(w, "id는 소문자·숫자·하이픈만")
        if i.get("group") not in TECH_GROUPS:
            err(w, f"group은 {sorted(TECH_GROUPS)} 중 하나: {i.get('group')}")
        if i.get("level") not in TECH_LEVELS:
            err(w, f"level은 {sorted(TECH_LEVELS)} 중 하나: {i.get('level')}")
        for key in ("definition", "why"):
            if not str(i.get(key, "")).strip():
                err(w, f"{key}가 비어 있음")
        for key in ("how", "effects"):
            if not i.get(key):
                err(w, f"{key}는 항목이 하나 이상 있어야 함")
        if not i.get("sources"):
            err(w, "공식 출처(sources)가 하나 이상 있어야 함")
        for s in i.get("sources", []):
            if not s.get("title") or not str(s.get("url", "")).startswith("https://"):
                err(w, f"출처 형식 오류(title, https url): {s}")
        ex = i.get("example") or {}
        if ex.get("type") not in TECH_EXAMPLE_TYPES or not ex.get("title") or not ex.get("text"):
            err(w, f"example은 title, text와 type({sorted(TECH_EXAMPLE_TYPES)})이 필요함")
        for key in ("prerequisites", "related"):
            for r in i.get(key, []):
                if r not in known:
                    err(w, f"{key}의 '{r}' 기술이 없음")
        for n in i.get("news", []):
            if n not in news_ids:
                err(w, f"news의 '{n}' 소식이 없음")
        if not DATE_RE.match(str(i.get("verifiedAt", ""))):
            err(w, "verifiedAt은 YYYY-MM-DD")
        if i.get("group") == "path":
            if not isinstance(i.get("order"), int):
                err(w, "학습 경로 항목은 정수 order가 필요함")
            else:
                orders.append(i["order"])
        if i.get("group") == "radar":
            if i.get("status") not in TECH_STAGES:
                err(w, f"status는 {sorted(TECH_STAGES)} 중 하나: {i.get('status')}")
            if not i.get("companies") or any(c not in COMPANIES for c in i["companies"]):
                err(w, f"companies는 {sorted(COMPANIES)} 중 하나 이상")
            if i.get("status") == "랩" and i.get("lab") not in known:
                err(w, "status가 '랩'이면 lab에 학습 경로 항목 id가 필요함")
    if len(orders) != len(set(orders)):
        err(where, "학습 경로 order가 중복됨")


def main():
    manifest = load(DATA / "manifest.json")
    guides = load(DATA / "guides.json")
    prices = load(DATA / "prices.json") if (DATA / "prices.json").exists() else None
    files = sorted((DATA / "news").glob("*.json"))
    ids = [check_news(f) for f in files]
    ids = [i for i in ids if i]
    check_guides(guides, set(ids))
    check_prices(prices, set(ids))
    tech_path = DATA / "tech.json"
    tech = load(tech_path) if tech_path.exists() else None
    check_tech(tech, set(ids))
    if manifest is not None:
        listed = manifest.get("news", [])
        if not CHECKED_RE.match(str(manifest.get("lastChecked", ""))):
            err("data/manifest.json", "lastChecked는 'YYYY-MM-DD HH:MM'(한국 시간) 또는 YYYY-MM-DD")
        if len(listed) != len(set(listed)):
            err("data/manifest.json", "news에 중복 id가 있음")
        for i in listed:
            if i not in ids:
                err("data/manifest.json", f"'{i}'에 해당하는 data/news/{i}.json이 없음")
        for i in ids:
            if i not in listed:
                err("data/manifest.json", f"data/news/{i}.json이 manifest에 없음 (사이트에 안 보임)")
    if errors:
        print("데이터 검증 실패:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print(f"데이터 검증 통과: 소식 {len(ids)}건" + (f", 기술 {len(tech.get('items', []))}건" if tech else ""))


if __name__ == "__main__":
    main()
