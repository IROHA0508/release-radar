#!/usr/bin/env python3
"""사이트의 모든 공식 출처 링크(data/ 아래 JSON의 "url")가 아직 살아 있는지 점검한다.

  python3 scripts/check_links.py                  # 전체 점검, 결과 표 출력
  python3 scripts/check_links.py --out report.json
  python3 scripts/check_links.py --only-changed origin/main   # PR에서 바뀐 파일의 링크만

판정
  정상       2xx이고 주소가 그대로(스킴·www·끝 슬래시 차이는 무시)
  주소 바뀜   2xx지만 다른 주소로 넘어감 → 새 주소로 바꿀지 사람이 확인 (경고)
  끊김       404·410이거나 리더로 봐도 404 (실패)
  확인 불가   봇 차단(401·403·429 등)인데 리더로도 확인하지 못함 (경고)
  오류       연결 실패·시간 초과 (경고, 한 번 더 시도한 뒤)

봇을 막는 사이트(openai.com 등)는 backend와 같은 방식으로 r.jina.ai 리더를 거쳐 다시 확인한다.
끊긴 링크가 있으면 종료 코드 1을 돌려준다(GitHub Actions에서 실패로 표시돼 알림이 간다).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
READER = "https://r.jina.ai/"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 "
      "ReleaseRadarBot/1.0 (+https://release-radar-ten.vercel.app)")
BLOCKED = {401, 403, 405, 406, 429, 451, 503}
GONE = {404, 410}
LABEL = {"ok": "정상", "ok-reader": "정상(리더)", "moved": "주소 바뀜", "broken": "끊김", "unknown": "확인 불가",
         "error": "오류"}


# ---------- 링크 모으기 ----------
def collect(files: list[Path] | None = None) -> dict[str, list[str]]:
    """url → 쓰인 곳 목록 ("data/tech.json [rag]" 같은 형식)."""
    found: dict[str, list[str]] = {}

    def walk(obj, where: str, owner: str | None):
        if isinstance(obj, dict):
            owner = obj.get("id") if isinstance(obj.get("id"), str) else owner
            for k, v in obj.items():
                if k == "url" and isinstance(v, str) and v.startswith("http"):
                    found.setdefault(v, []).append(where + (f" [{owner}]" if owner else ""))
                else:
                    walk(v, where, owner)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, where, owner)

    for path in sorted(files if files is not None else DATA.rglob("*.json")):
        try:
            walk(json.loads(path.read_text(encoding="utf-8")), str(path.relative_to(ROOT)), None)
        except (OSError, ValueError):
            continue
    return found


def changed_files(base: str) -> list[Path]:
    out = subprocess.run(["git", "diff", "--name-only", base, "--", "data"], cwd=ROOT, capture_output=True, text=True)
    return [ROOT / p for p in out.stdout.split() if p.endswith(".json") and (ROOT / p).exists()]


# ---------- 점검 ----------
def same_page(a: str, b: str) -> bool:
    def norm(u: str) -> str:
        p = urlsplit(u.strip())
        return urlunsplit(("https", p.netloc.lower().removeprefix("www."), p.path.rstrip("/") or "/", "", ""))
    return norm(a) == norm(b)


def _get(session, url: str, timeout: int = 20):
    return session.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}, timeout=timeout,
                       allow_redirects=True)


def check_direct(session, url: str) -> dict:
    last = None
    for attempt in range(2):
        try:
            r = _get(session, url)
        except Exception as exc:  # noqa: BLE001 - reported, not fatal
            last = f"{type(exc).__name__}"
            time.sleep(2 * (attempt + 1))
            continue
        code = r.status_code
        if code in GONE:
            return {"status": "broken", "code": code}
        if 200 <= code < 300:
            if same_page(url, r.url):
                return {"status": "ok", "code": code}
            return {"status": "moved", "code": code, "final": r.url}
        if code in BLOCKED or code >= 500:
            return {"status": "blocked", "code": code}
        return {"status": "error", "code": code}
    return {"status": "error", "detail": last}


def check_reader(session, url: str) -> dict:
    try:
        r = _get(session, READER + url, timeout=40)
    except Exception as exc:  # noqa: BLE001
        return {"status": "unknown", "detail": f"리더 {type(exc).__name__}"}
    body = r.text[:3000]
    if r.status_code == 200 and "returned error 404" not in body and "returned error 410" not in body:
        return {"status": "ok-reader"}
    if "returned error 404" in body or "returned error 410" in body:
        return {"status": "broken", "detail": "리더로 확인한 결과 404"}
    return {"status": "unknown", "detail": f"리더 HTTP {r.status_code}"}


def run(urls: list[str], session=None, workers: int = 8, reader_limit: int = 150, pause: float = 3.0) -> dict[str, dict]:
    import requests

    session = session or requests.Session()
    with ThreadPoolExecutor(workers) as pool:
        results = dict(zip(urls, pool.map(lambda u: check_direct(session, u), urls)))
    blocked = [u for u, r in results.items() if r["status"] in ("blocked", "error")]
    for i, u in enumerate(blocked):
        if i >= reader_limit:
            results[u] = {**results[u], "status": "unknown", "detail": "리더 점검 한도 초과"}
            continue
        rr = check_reader(session, u)
        results[u] = {**results[u], **rr}
        time.sleep(pause)                    # the free reader allows only a few requests per minute
    for u, r in results.items():
        if r["status"] == "blocked":
            r["status"] = "unknown"
    return results


# ---------- 보고 ----------
def annotate(level: str, title: str, msg: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{level} title={title}::{msg.replace(chr(10), '%0A')}", flush=True)


def report(results: dict[str, dict], used: dict[str, list[str]]) -> str:
    counts: dict[str, int] = {}
    for r in results.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines = ["## 출처 링크 점검", "",
             "링크 " + str(len(results)) + "개: " + ", ".join(f"{LABEL.get(k, k)} {v}" for k, v in sorted(counts.items()))]
    for status, title in (("broken", "끊긴 링크"), ("moved", "주소가 바뀐 링크"), ("unknown", "확인하지 못한 링크"),
                          ("error", "연결 오류")):
        rows = [(u, r) for u, r in results.items() if r["status"] == status]
        if not rows:
            continue
        lines += ["", f"### {title} ({len(rows)})", "", "| 링크 | 결과 | 쓰인 곳 |", "|---|---|---|"]
        for u, r in sorted(rows):
            detail = r.get("final") or r.get("detail") or ""
            code = f"HTTP {r['code']} " if r.get("code") else ""
            lines.append(f"| {u} | {code}{detail} | {'<br>'.join(used.get(u, [])[:4])} |")
            level = "error" if status == "broken" else "warning"
            annotate(level, f"출처 링크 {LABEL[status]}", f"{u} {code}{detail} ← {', '.join(used.get(u, [])[:3])}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", help="결과 JSON 저장 경로")
    ap.add_argument("--only-changed", metavar="BASE", help="BASE와 비교해 바뀐 data/ 파일의 링크만 점검")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N개만 점검(시험용)")
    args = ap.parse_args()
    used = collect(changed_files(args.only_changed) if args.only_changed else None)
    urls = sorted(used)[: args.limit or None]
    print(f"점검할 링크 {len(urls)}개", flush=True)
    results = run(urls)
    md = report(results, used)
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md)
    if args.out:
        Path(args.out).write_text(json.dumps({"results": results, "usedIn": used}, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    return 1 if any(r["status"] == "broken" for r in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
