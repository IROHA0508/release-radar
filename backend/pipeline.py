"""Run the whole update: detect -> triage -> read article -> write -> check -> save."""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import config, detect, feeds, guard, store
from .extract import Article, fetch_article

log = logging.getLogger(__name__)


def today_kst() -> date:
    return datetime.now(ZoneInfo(config.TIMEZONE)).date()


def now_kst() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def annotate(level: str, title: str, message: str) -> None:
    """Print a GitHub Actions annotation (shown on the run page and readable through the API)."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        msg = message.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        print(f"::{level} title={title}::{msg}", flush=True)


@dataclass
class RunReport:
    startedAt: str
    mode: str
    sourceErrors: dict = field(default_factory=dict)
    entries: int = 0
    candidates: list = field(default_factory=list)
    added: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    guardNotes: dict = field(default_factory=dict)
    note: str = ""
    authError: bool = False

    def save(self) -> None:
        path = config.STATE_FILE.parent / "last-run.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fail(state: dict, e: feeds.Entry, today: date, report: RunReport, error: str) -> None:
    """Record a failure; after 3 failed runs the article is given up on so it is not retried forever."""
    report.failed.append({"url": e.url, "error": error})
    attempts = state.setdefault("attempts", {})
    attempts[e.key] = attempts.get(e.key, 0) + 1
    if attempts[e.key] >= 3:
        detect.mark(state, e, "failed", today, error=error[:300])
        attempts.pop(e.key, None)


def _load_item(news_id: str | None) -> dict | None:
    path = config.NEWS_DIR / f"{news_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if news_id and path.exists() else None


def _fill_dates(cands: list[feeds.Entry], cache: dict[str, Article], cutoff: date, state: dict, today: date,
                report: RunReport) -> list[feeds.Entry]:
    """Listing pages have no dates: read up to N article pages to get them and drop old ones."""
    out, fetched = [], 0
    for e in cands:
        if e.published is None:
            if fetched >= config.MAX_LISTING_FETCHES:
                continue
            fetched += 1
            try:
                art = fetch_article(e.url)
            except Exception as exc:  # noqa: BLE001 - counted, given up after 3 runs
                _fail(state, e, today, report, f"원문 읽기 실패: {exc}")
                continue
            cache[e.key] = art
            # A page without a date: fall back to the sitemap's lastmod, or today, for the Anthropic
            # newsroom only. Blogs have many old posts (and their lastmod changes on every site
            # rebuild), so an undated post there is skipped instead of being taken as new.
            src = next((s for s in config.SOURCES if s.name == e.source), None)
            trusted = src is None or src.undated_is_new
            e.published = art.published or ((e.extra.get("lastmod") or today) if trusted else None)
            if e.published is None:
                detect.mark(state, e, "nodate", today)
                continue
            if art.title and (e.extra.get("titleFromSlug") or len(art.title) > len(e.title)):
                e.title = art.title
        if e.published < cutoff:
            detect.mark(state, e, "old", today)
            continue
        out.append(e)
    return out


def run_update(*, dry_run: bool = False, api_key: str | None = None) -> RunReport:
    today = today_kst()
    report = RunReport(datetime.now(ZoneInfo(config.TIMEZONE)).isoformat(timespec="seconds"),
                       "dry-run" if dry_run else "update")
    site = detect.load_site()
    state = detect.load_state()
    entries, report.sourceErrors = feeds.fetch_all()
    report.entries = len(entries)
    for name, err in report.sourceErrors.items():
        annotate("warning", f"소스 실패: {name}", err)

    cutoff = min(site.newest or today, today) - timedelta(days=config.LOOKBACK_DAYS)
    cache: dict[str, Article] = {}
    cands = detect.find_candidates(entries, site, state, today)
    cands = _fill_dates(cands, cache, cutoff, state, today, report)
    report.candidates = [{"title": e.title, "url": e.url, "company": e.company,
                          "date": e.published.isoformat() if e.published else None,
                          "relatedId": e.extra.get("relatedId")} for e in cands]
    for c in report.candidates:
        annotate("notice", "새 글 후보", f"{c['company']} {c['date']} {c['title']} {c['url']}")

    from . import summarize

    backend = "api" if api_key else summarize.llm_available()
    if dry_run or not backend:
        report.note = "dry-run" if dry_run else (
            "CLAUDE_CODE_OAUTH_TOKEN(구독 토큰)이나 ANTHROPIC_API_KEY가 없어 감지만 하고 요약은 하지 않았습니다.")
        if not dry_run:
            config.PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
            config.PENDING_FILE.write_text(json.dumps(report.candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            store.touch_last_checked(now_kst())
            detect.save_state(state)
            report.save()
        return report

    from .summarize import Claude, is_auth_error, make_llm, triage, write_item

    claude = Claude(api_key) if api_key else make_llm()
    report.note = f"요약 엔진: {'Claude Code CLI(구독)' if backend == 'cli' else 'Claude API'}"
    site_lines = site.summary_lines()
    if cands:
        try:
            verdicts = triage(claude, cands, site_lines)
        except Exception as exc:  # noqa: BLE001 - the writing step can still skip non-model posts
            if is_auth_error(exc):
                # Every later call would fail the same way: stop here, keep candidates for the next run.
                report.authError = True
                report.note += " | Claude 인증 실패: 토큰(또는 API 키)이 잘못됐거나 만료됨. 새로 만들어 GitHub Secret을 바꿔 주세요."
                annotate("error", "Claude 인증 실패", str(exc)[-400:])
                store.touch_last_checked(now_kst())
                detect.save_state(state)
                report.save()
                return report
            log.warning("triage failed (%s); sending every candidate to the writing step", exc)
            annotate("warning", "분류 단계 실패", str(exc)[:500])
            verdicts = {}
        keep = []
        for i, e in enumerate(cands):
            ok, why = verdicts.get(i, (True, "판단 없음"))
            if ok:
                keep.append(e)
            else:
                detect.mark(state, e, "skipped", today, reason=why)
                report.skipped.append({"title": e.title, "url": e.url, "reason": why})
        cands = keep

    for e in cands[: config.MAX_NEW_ITEMS]:
        # Another post about news the site already has, including an item added earlier in this run
        # (e.g. two blog posts about one launch on the same day): only add its new details there.
        same = detect.same_item(e, site, set())
        try:
            art = cache.get(e.key) or fetch_article(e.url)
            draft = write_item(claude, e, art, site_lines, today, update_of=_load_item(same) if same else None)
            if draft.get("decision") == "new" and not same:
                probe = {**(draft.get("item") or {}), "company": e.company,
                         "date": (e.published or art.published or today).isoformat()}
                probe.pop("id", None)
                dup = detect.duplicate_launch(probe, site)
                if dup:
                    same = dup
                    annotate("notice", "중복 소식 방지", f"{e.url} → 기존 '{dup}'에 덧붙임")
                    draft = write_item(claude, e, art, site_lines, today, update_of=_load_item(dup))
        except Exception as exc:  # noqa: BLE001 - try again next run
            log.exception("failed: %s", e.url)
            if is_auth_error(exc):
                report.authError = True
                report.note += " | Claude 인증 실패: 토큰(또는 API 키)을 새로 만들어 GitHub Secret을 바꿔 주세요."
                annotate("error", "Claude 인증 실패", str(exc)[-400:])
                break
            _fail(state, e, today, report, f"{type(exc).__name__}: {exc}")
            annotate("warning", "요약 실패", f"{e.url} {exc}")
            continue
        decision = draft.get("decision")
        if same:
            # Never a second item for the same news: whatever the draft says, this post is at least
            # another official source of the existing item.
            upd = (draft.get("update") or {}) if decision == "update" else {}
            draft = {"decision": "update", "updateId": same, "update": {
                "changes": upd.get("changes") or [], "availability": upd.get("availability") or [],
                "sources": [{"title": art.title or e.title, "url": e.url}, *(upd.get("sources") or [])]}}
            decision = "update"
        if decision == "skip":
            detect.mark(state, e, "skipped", today, reason=draft.get("reason", ""))
            report.skipped.append({"title": e.title, "url": e.url, "reason": draft.get("reason", "")})
            continue
        if decision == "update":
            target = store.slugify(draft.get("updateId") or e.extra.get("relatedId") or "")
            target_path = config.NEWS_DIR / f"{target}.json"
            before = target_path.read_text(encoding="utf-8") if target_path.exists() else None
            if before is not None and store.apply_update(target, draft.get("update") or {}):
                ok, out = store.validate()
                if ok:
                    detect.mark(state, e, "updated", today, id=target)
                    report.updated.append({"id": target, "url": e.url})
                    site.known_urls[feeds.normalize_url(e.url)] = target
                    annotate("notice", "기존 소식 보강", f"{target} ← {e.url}")
                    continue
                target_path.write_text(before, encoding="utf-8")
                _fail(state, e, today, report, "검증 실패: " + out)
            else:
                detect.mark(state, e, "skipped", today, reason="보강할 내용 없음", id=target)
            continue

        day = e.published or art.published or today
        item = store.normalize_item(draft.get("item") or {}, company=e.company, day=day, url=e.url, title_hint=e.title)
        source_text = "\n".join([art.title, art.text, *art.tables])
        notes = guard.check_item(item, source_text, "\n".join(art.links))
        item = store.normalize_item(item, company=e.company, day=day, url=e.url, title_hint=e.title)
        if notes:
            report.guardNotes[item["id"]] = notes
        path = store.write_news(item)
        store.add_to_manifest(item["id"])
        ok, out = store.validate()
        if not ok:
            path.unlink(missing_ok=True)
            store.remove_from_manifest(item["id"])
            _fail(state, e, today, report, "검증 실패: " + out)
            annotate("warning", "검증 실패", f"{e.url}\n{out}")
            continue
        detect.mark(state, e, "added", today, id=item["id"])
        site.add(item)                      # later candidates in this run must see it
        site_lines = site.summary_lines()
        report.added.append({"id": item["id"], "title": item["title"], "url": e.url, "charts": len(item.get("charts", []))})
        annotate("notice", "새 소식 추가", f"{item['id']} | {item['title']} | 그래프 {len(item.get('charts', []))}개")

    store.touch_last_checked(now_kst())
    detect.save_state(state)
    report.save()
    return report


def run_selftest() -> tuple[bool, list[str]]:
    """No API calls. For each company, hide the newest known article and check the detector finds it."""
    lines, ok = [], True
    today = today_kst()
    site = detect.load_site()
    entries, errors = feeds.fetch_all()
    for src in config.SOURCES:
        got = [e for e in entries if e.source == src.name]
        dated = [e for e in got if e.published]
        if src.name in errors or not got:
            ok = False
            lines.append(f"FAIL {src.name}: {errors.get(src.name, '항목 0개')}")
        else:
            via = " · 리더 경유" if any(e.extra.get("via") == "reader" for e in got) else ""
            lines.append(f"OK   {src.name}: {len(got)}개 (날짜 있음 {len(dated)}개, "
                         f"최신 {max((e.published for e in dated), default=None)}{via})")
    for company in ("openai", "anthropic", "google"):
        newest = next((i for i in site.items if i["company"] == company), None)
        if not newest:
            continue
        cands = detect.find_candidates(entries, site, {"urls": {}}, today, pretend_missing={newest["id"]})
        own = {u for u, i in site.known_urls.items() if i == newest["id"]}
        own_slugs = {detect.slug_key(u) for u in own}
        hit = next((c for c in cands
                    if any(feeds.normalize_url(u) in own or detect.slug_key(u) in own_slugs
                           for u in [c.url, *c.extra.get("alsoAt", [])])
                    or c.extra.get("relatedId") == newest["id"]), None)
        if hit:
            lines.append(f"OK   감지 시험 {company}: '{newest['id']}'을 지웠다고 가정 → '{hit.title}' 감지 ({hit.url})")
            try:
                art = fetch_article(hit.url)
                lines.append(f"OK   원문 읽기 {company}: {art.via}, 본문 {len(art.text)}자, 표 {len(art.tables)}개, "
                             f"링크 {len(art.links)}개, 페이지 발표일 {art.published}")
                if art.tables:
                    lines.append(f"INFO 첫 표 앞부분: {art.tables[0][:160]}")
            except Exception as exc:  # noqa: BLE001
                ok = False
                lines.append(f"FAIL 원문 읽기 {company}: {hit.url} ({exc})")
        else:
            ok = False
            lines.append(f"FAIL 감지 시험 {company}: '{newest['id']}'을 찾지 못함 (후보 {len(cands)}개)")
            for e in [e for e in entries if e.company == company][:12]:
                lines.append(f"INFO {e.source} | {e.published} | {e.title[:80]} | {e.url}")
    # Tip blogs: can an article page we already link to still be read from here? (warning only)
    for src in config.SOURCES:
        host = feeds.urlsplit(src.base or src.url).netloc.removeprefix("www.")
        if src.name in ("OpenAI News", "Anthropic News", "Anthropic sitemap", "Google Gemini models blog"):
            continue
        known = [u for u in site.known_urls if feeds.urlsplit(u).netloc.removeprefix("www.") == host
                 and (not src.pattern or re.match(src.pattern, feeds.urlsplit(u).path))]
        if not known:
            continue
        try:
            known.sort(key=lambda u: ("/blog/" in u or "/index/" in u, u))
            art = fetch_article(known[-1])
            lines.append(f"OK   원문 읽기 {src.name}: {art.via}, 본문 {len(art.text)}자, 발표일 {art.published}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"WARN 원문 읽기 {src.name}: {exc}")
    for line in lines:
        print(line, flush=True)
        if line.startswith("FAIL"):
            annotate("error", "자가 시험 실패", line)
    # One annotation with every line: GitHub shows at most 10 notices per step.
    annotate("notice", "자가 시험 결과", "\n".join(lines))
    return ok, lines
