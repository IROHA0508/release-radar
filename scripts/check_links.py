#!/usr/bin/env python3
"""사이트의 모든 공식 출처 링크(data/ 아래 JSON의 "url")가 아직 살아 있는지 점검한다.

  python3 scripts/check_links.py                  # 전체 점검, 결과 표 출력
  python3 scripts/check_links.py --out report.json
  python3 scripts/check_links.py --only-changed origin/main   # PR에서 바뀐 파일의 링크만
  python3 scripts/check_links.py --apply-moved report.json    # '같은 글'로 넘어간 주소를 data/에 반영

판정
  정상       2xx이고 주소가 그대로(스킴·www·끝 슬래시 차이는 무시)
  주소 바뀜   2xx지만 다른 주소로 넘어감 (경고). 원래 주소의 마지막 경로(slug)가 새 주소에도 있으면
             '같은 글'로 보고 --apply-moved로 바꿀 수 있다. 없으면 목록·홈으로 넘어갔을 수 있으니 사람이 확인한다.
  끊김       404·410이거나 리더로 봐도 404 (실패)
  확인 불가   봇 차단(401·403·429 등)인데 리더로도 확인하지 못함 (경고)
  오류       연결 실패·시간 초과 (경고, 한 번 더 시도한 뒤)

봇을 막는 사이트(openai.com 등)는 backend와 같은 방식으로 r.jina.ai 리더를 거쳐 다시 확인한다.
직접 요청이 404여도 리더로 한 번 더 본다. 일부 도움말 사이트는 GitHub Actions에서 보낸 요청에만 404를 주기 때문이다.
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
# 넘어가는 곳이 있어도 일부러 원래 주소를 쓰는 링크. 넘어가면 '정상'으로 보고 끊기면 그대로 '끊김'으로 알린다.
KEEP = {
    "https://modelcontextprotocol.io/docs/learn/architecture": "버전 없는 최신 문서 주소(날짜가 붙은 판으로 넘어감)",
    "https://deepmind.google/models/evals-methodology/gemini-3-8-live/": "공식 평가 방법 안내 주소(PDF로 넘어감)",
    "https://deepmind.google/models/evals-methodology/gemini-3-8-tts/": "공식 평가 방법 안내 주소(PDF로 넘어감)",
    "https://deepmind.google/blog/embeddinggemma-2-an-open-lightweight-multimodal-embedding-model/":
        "소식 원문 주소. 자동 업데이트가 같은 글인지 판단할 때 쓰므로 그대로 둔다",
}
# 브라우저로는 열리는데 자동 요청(GitHub Actions·리더)에만 404가 나오는 링크. 실패 대신 '확인 불가' 경고로 둔다.
# 사람이 브라우저로 열어 확인한 날짜를 함께 적고, 오래되면 다시 열어 본다.
SOFT_404 = {
    "https://support.claude.com/en/articles/10181068-styles-are-moving-to-skills":
        "Claude 도움말. 2026-10-22 브라우저로 열림(같은 글 de·it판도 열림)",
}
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


def slug(url: str) -> str:
    parts = [p for p in urlsplit(url).path.split("/") if p]
    return parts[-1].lower() if parts else ""


def same_article(url: str, final: str) -> bool:
    """리디렉션된 곳이 같은 글로 보이는지. 원래 slug가 새 주소의 경로에 그대로 들어 있으면 같은 글로 본다."""
    s = slug(url)
    return len(s) >= 6 and s in urlsplit(final).path.lower()


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
            return {"status": "moved", "code": code, "final": r.url, "sameArticle": same_article(url, r.url)}
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
    recheck = [u for u, r in results.items() if r["status"] in ("blocked", "error", "broken")]
    for i, u in enumerate(recheck):
        direct = results[u]
        if i >= reader_limit:
            if direct["status"] != "broken":
                results[u] = {**direct, "status": "unknown", "detail": "리더 점검 한도 초과"}
            continue
        rr = check_reader(session, u)
        if direct["status"] == "broken" and rr["status"] != "ok-reader":
            pass                             # the direct 404 stands unless the reader actually got the page
        elif direct["status"] == "broken":
            results[u] = {**direct, **rr, "detail": f"직접 요청은 HTTP {direct.get('code')}, 리더로는 열림"}
        else:
            results[u] = {**direct, **rr}
        time.sleep(pause)                    # the free reader allows only a few requests per minute
    for u, r in results.items():
        if r["status"] == "blocked":
            r["status"] = "unknown"
        if r["status"] == "moved" and u in KEEP:
            r.update(status="ok", detail="유지: " + KEEP[u])
        if r["status"] == "broken" and u in SOFT_404:
            r.update(status="unknown", detail="자동 요청에만 404: " + SOFT_404[u])
    return results


# ---------- 보고 ----------
def annotate(level: str, title: str, msg: str) -> None:
    # GitHub는 단계마다 경고·오류 표시를 10개까지만 보여 주므로 상태별로 한 줄씩 묶어서 낸다.
    if os.environ.get("GITHUB_ACTIONS") == "true":
        msg = msg.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        print(f"::{level} title={title}::{msg}", flush=True)


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
        notes = []
        for u, r in sorted(rows):
            detail = r.get("final") or r.get("detail") or ""
            code = f"HTTP {r['code']} " if r.get("code") else ""
            if status == "moved":
                detail += " (같은 글)" if r.get("sameArticle") else " (확인 필요: 다른 곳으로 넘어감)"
            lines.append(f"| {u} | {code}{detail} | {'<br>'.join(used.get(u, [])[:4])} |")
            notes.append(f"{u} {code}{detail} ← {', '.join(used.get(u, [])[:3])}")
        annotate("error" if status == "broken" else "warning", f"출처 링크 {LABEL[status]} {len(rows)}개",
                 "\n".join(notes[:40]) + (f"\n…외 {len(notes) - 40}개" if len(notes) > 40 else ""))
    if any(r["status"] == "moved" and r.get("sameArticle") for r in results.values()):
        lines += ["", "'같은 글'로 표시된 주소는 결과 JSON을 받아 `python3 scripts/check_links.py --apply-moved link-report.json`으로 한 번에 바꿀 수 있습니다."]
    return "\n".join(lines) + "\n"


def apply_moved(report_path: str) -> int:
    """결과 JSON에서 '같은 글'로 넘어간 주소를 data/ 아래 JSON에 새 주소로 바꿔 쓴다. 바꾼 개수를 돌려준다."""
    results = json.loads(Path(report_path).read_text(encoding="utf-8"))["results"]
    swap = {u: r["final"] for u, r in results.items() if r.get("status") == "moved" and r.get("sameArticle")}
    changed = 0
    for path in sorted(DATA.rglob("*.json")):
        text = path.read_text(encoding="utf-8")
        new = text
        for old, final in swap.items():
            new = new.replace(json.dumps(old, ensure_ascii=False), json.dumps(final, ensure_ascii=False))
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
            print(f"바꿈: {path.relative_to(ROOT)}")
    print(f"주소 {len(swap)}개, 파일 {changed}개를 고쳤습니다. scripts/validate_data.py로 검증하세요.")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", help="결과 JSON 저장 경로")
    ap.add_argument("--only-changed", metavar="BASE", help="BASE와 비교해 바뀐 data/ 파일의 링크만 점검")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N개만 점검(시험용)")
    ap.add_argument("--md", help="결과 표(마크다운) 저장 경로. PR 댓글에 쓴다")
    ap.add_argument("--apply-moved", metavar="REPORT", help="점검 결과 JSON의 '같은 글' 주소를 data/에 반영하고 끝낸다")
    args = ap.parse_args()
    if args.apply_moved:
        apply_moved(args.apply_moved)
        return 0
    used = collect(changed_files(args.only_changed) if args.only_changed else None)
    urls = sorted(used)[: args.limit or None]
    print(f"점검할 링크 {len(urls)}개", flush=True)
    results = run(urls)
    md = report(results, used)
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md)
    if args.md:
        Path(args.md).write_text(md, encoding="utf-8")
    if args.out:
        Path(args.out).write_text(json.dumps({"results": results, "usedIn": used}, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    return 1 if any(r["status"] == "broken" for r in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
