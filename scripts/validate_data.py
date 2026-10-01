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
KINDS = {"모델 출시", "모델 업데이트", "모델 발표", "활용 팁"}
RESERVED_IDS = {"guide", "prices"}
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
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


def main():
    manifest = load(DATA / "manifest.json")
    load(DATA / "guides.json")
    files = sorted((DATA / "news").glob("*.json"))
    ids = [check_news(f) for f in files]
    ids = [i for i in ids if i]
    if manifest is not None:
        listed = manifest.get("news", [])
        if not DATE_RE.match(str(manifest.get("lastChecked", ""))):
            err("data/manifest.json", "lastChecked는 YYYY-MM-DD")
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
    print(f"데이터 검증 통과: 소식 {len(ids)}건")


if __name__ == "__main__":
    main()
