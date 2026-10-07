"""Offline tests for the news pipeline. Run: python -m pytest tests -q"""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path

import pytest

from backend import config, detect, extract, feeds, guard, pipeline, store

REPO = Path(__file__).resolve().parent.parent

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>News</title>
<item><title>Introducing GPT-7 Nova</title><link>https://openai.com/index/introducing-gpt-7-nova</link>
<pubDate>Thu, 01 Oct 2026 17:00:00 GMT</pubDate><category>Product</category><description>A new model.</description></item>
<item><title>How Acme uses ChatGPT Work</title><link>https://openai.com/index/acme</link>
<pubDate>Thu, 01 Oct 2026 16:00:00 GMT</pubDate><category>Company</category></item>
<item><title>Introducing GPT-6.1 Sol</title><link>https://openai.com/index/introducing-gpt-6-1-sol</link>
<pubDate>Tue, 29 Sep 2026 17:00:00 GMT</pubDate></item>
<item><title>Our first GPT</title><link>https://openai.com/index/old-model</link>
<pubDate>Mon, 01 Jun 2020 17:00:00 GMT</pubDate></item>
</channel></rss>"""

LISTING = """<html><body>
<a href="/claude-sonnet-5-5"><h3>Introducing Claude Sonnet 5.5</h3><time datetime="2026-09-28">Sep 28, 2026</time></a>
<a href="/news/barclays-scales-claude"><h3>Barclays scales Claude</h3></a>
<a href="/careers">Careers</a>
<a href="https://www.anthropic.com/news/claude-haiku-5-5"><h3>Introducing Claude Haiku 5.5</h3></a>
</body></html>"""

ARTICLE = """<html><head><title>x</title><meta property="og:title" content="Introducing GPT-7 Nova">
<meta property="article:published_time" content="2026-10-01T17:00:00Z"></head><body>
<nav>menu</nav><article><h1>Introducing GPT-7 Nova</h1>
<p>GPT-7 Nova is available in the API as <code>gpt-7-nova</code> at $3 per 1M input tokens and $18 per 1M output tokens.
It has a 2M context window. Terminal-Bench 4.0 improved to 61.2%.</p>
<table><tr><th>Eval</th><th>GPT-7 Nova</th><th>GPT-6.1 Sol</th><th>Claude Opus 5.5</th></tr>
<tr><td>Terminal-Bench 4.0</td><td>61.2%</td><td>58.0%</td><td>66.4%</td></tr>
<tr><td>GDPval-AA</td><td>1,802 Elo</td><td>1,640 Elo</td><td>1,846 Elo</td></tr></table>
<p>Try it in <a href="https://platform.openai.com/docs/models/gpt-7-nova">the docs</a>.</p>
</article></body></html>""" + ("<p>filler text for length</p>" * 60)


@pytest.fixture()
def site(tmp_path, monkeypatch):
    """A throwaway copy of the repository's data, docs and validator."""
    for name in ("data", "docs", "scripts"):
        shutil.copytree(REPO / name, tmp_path / name)
    (tmp_path / "backend" / "state").mkdir(parents=True)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", tmp_path / "data")
    monkeypatch.setattr(config, "NEWS_DIR", tmp_path / "data" / "news")
    monkeypatch.setattr(config, "MANIFEST", tmp_path / "data" / "manifest.json")
    monkeypatch.setattr(config, "STATE_FILE", tmp_path / "backend" / "state" / "seen.json")
    monkeypatch.setattr(config, "PENDING_FILE", tmp_path / "backend" / "state" / "pending.json")
    monkeypatch.setattr(config, "SCHEMA_DOC", tmp_path / "docs" / "DATA_SCHEMA.md")
    monkeypatch.setattr(config, "STYLE_EXAMPLE", tmp_path / "data" / "news" / "claude-sonnet-5-5.json")
    monkeypatch.setattr(config, "TIP_EXAMPLE", tmp_path / "data" / "news" / "openai-retained-reasoning-compaction.json")
    monkeypatch.setattr(config, "VALIDATOR", tmp_path / "scripts" / "validate_data.py")
    monkeypatch.setattr(pipeline, "today_kst", lambda: date(2026, 10, 2))
    monkeypatch.setattr(pipeline, "now_kst", lambda: datetime(2026, 10, 2, 6, 3))
    return tmp_path


OPENAI = config.SOURCES[0]
ANTHROPIC = config.SOURCES[1]


def test_normalize_url():
    assert feeds.normalize_url("https://www.openai.com/index/a/?x=1#y") == feeds.normalize_url("http://openai.com/index/a")


def test_parse_rss_and_listing():
    entries = feeds.parse_rss(RSS, OPENAI)
    assert [e.title for e in entries][0] == "Introducing GPT-7 Nova"
    assert entries[0].published == date(2026, 10, 1)
    listing = feeds.parse_listing(LISTING, ANTHROPIC)
    urls = [e.url for e in listing]
    assert urls == ["https://www.anthropic.com/claude-sonnet-5-5", "https://www.anthropic.com/news/barclays-scales-claude",
                    "https://www.anthropic.com/news/claude-haiku-5-5"]
    assert listing[0].published == date(2026, 9, 28) and listing[0].title == "Introducing Claude Sonnet 5.5"


def test_listing_with_own_article_pattern():
    blog = next(s for s in config.SOURCES if s.name == "Claude blog")
    html = """<a href="/blog/maximizing-the-value-of-your-claude-code-sessions">Maximizing the value</a>
    <a href="/blog/category/claude-code">Claude Code</a><a href="https://claude.com/blog/build-plugins-for-claude">Plugins</a>
    <a href="https://www.anthropic.com/news/x">elsewhere</a><a href="/pricing">Pricing</a>"""
    urls = [e.url for e in feeds.parse_listing(html, blog)]
    assert urls == ["https://claude.com/blog/maximizing-the-value-of-your-claude-code-sessions",
                    "https://claude.com/blog/build-plugins-for-claude"]
    assert all(e.company == "anthropic" for e in feeds.parse_listing(html, blog))


def test_text_date_from_byline():
    assert extract.text_date("Lydia Hallie | August 14, 2026 | 5 min read") == date(2026, 8, 14)
    assert extract.text_date("Edi Palencia\nJAN. 28, 2026\nHooks are scripts") == date(2026, 1, 28)
    assert extract.text_date("Posted 14 Aug 2026") == date(2026, 8, 14)
    assert extract.text_date("Plan a trip for September 2026.") is None


def test_undated_blog_post_is_skipped_not_dated_today(site, monkeypatch):
    blog = next(s for s in config.SOURCES if s.name == "Claude blog")
    undated = feeds.Entry("Old Claude tips", "https://claude.com/blog/old-claude-tips", "anthropic", blog.name, None, "", 1)
    newsroom = feeds.Entry("Introducing Claude Haiku 5.5", "https://www.anthropic.com/news/claude-haiku-5-5", "anthropic",
                           "Anthropic News", None, "", 2)
    page = "<html><body><article><p>" + "tips " * 300 + "</p></article></body></html>"
    monkeypatch.setattr(pipeline, "fetch_article", lambda url: extract.parse_html(page, url))
    state = {"urls": {}}
    out = pipeline._fill_dates([undated, newsroom], {}, date(2026, 9, 25), state, date(2026, 10, 2),
                               pipeline.RunReport("t", "update"))
    assert [e.url for e in out] == [newsroom.url]
    assert state["urls"][undated.key]["status"] == "nodate"


def test_tip_titles_pass_keyword_filter():
    for title in ("Shell + Skills + Compaction: Tips for long-running agents that do real work",
                  "Prompting fundamentals", "6 tips for prompting Lyria 3 in the Gemini app"):
        assert config.RELEVANT_RE.search(title), title


def test_parse_article_keeps_tables_and_links():
    art = extract.parse_html(ARTICLE, "https://openai.com/index/introducing-gpt-7-nova")
    assert art.published == date(2026, 10, 1)
    assert art.title == "Introducing GPT-7 Nova"
    assert "| Terminal-Bench 4.0 | 61.2% | 58.0% | 66.4% |" in art.tables[0]
    assert "menu" not in art.text
    assert "https://platform.openai.com/docs/models/gpt-7-nova" in art.links


def test_reader_fallback_parsing():
    md = "Title: Hello\nPublished Time: 2026-10-01T10:00:00Z\nMarkdown Content:\n# Hello\n| a | b |\n|---|---|\n| 1 | 2 |\n" + "x" * 900
    art = extract.parse_reader(md, "https://example.com")
    assert art.title == "Hello" and art.published == date(2026, 10, 1) and art.tables and art.via == "reader"


def test_numbers_in_expands_suffixes():
    pool = guard.numbers_in("1,747.8 Elo, 64K output, 2M context, $0.75, 약 100만 토큰, GPT-5.6")
    for v in (1747.8, 64000, 2_000_000, 0.75, 1_000_000, 5.6):
        assert v in pool


def test_guard_removes_values_not_in_source():
    item = {
        "charts": [
            {"title": "TB", "rows": [{"label": "A", "value": 61.2, "highlight": True}, {"label": "B", "value": 58.0},
                                    {"label": "C", "value": 99.9}]},
            {"title": "Made up", "rows": [{"label": "A", "value": 12.3, "highlight": True}, {"label": "B", "value": 45.6}]},
        ],
        "chartSource": "src",
        "numbers": [{"label": "ctx", "value": "200만", "note": ""}, {"label": "fake", "value": "77.7%", "note": ""},
                    {"label": "text only", "value": "API 제공", "note": ""}],
        "models": [{"name": "Nova", "apiId": "gpt-7-nova", "input": "$3", "output": "$19", "cached": None},
                   {"name": "Other", "apiId": "gpt-7-imaginary", "input": None, "output": None, "cached": None}],
    }
    art = extract.parse_html(ARTICLE, "u")
    notes = guard.check_item(item, "\n".join([art.title, art.text, *art.tables]), "\n".join(art.links))
    assert [c["title"] for c in item["charts"]] == ["TB"]
    assert [r["label"] for r in item["charts"][0]["rows"]] == ["A", "B"]
    assert [n["label"] for n in item["numbers"]] == ["ctx", "text only"]
    assert item["models"][0]["apiId"] == "gpt-7-nova" and item["models"][0]["output"] is None
    assert item["models"][1]["apiId"] is None
    assert notes


def test_candidates_skip_known_old_and_irrelevant(site):
    idx = detect.load_site()
    entries = feeds.parse_rss(RSS, OPENAI)
    cands = detect.find_candidates(entries, idx, {"urls": {}}, date(2026, 10, 2))
    titles = [c.title for c in cands]
    assert "Introducing GPT-7 Nova" in titles          # new
    assert "Introducing GPT-6.1 Sol" not in titles     # already on the site
    assert "Our first GPT" not in titles               # too old
    # pretend the newest OpenAI item is missing: the detector must find it again
    again = detect.find_candidates(entries, idx, {"urls": {}}, date(2026, 10, 2), pretend_missing={"gpt-6-1-sol"})
    assert "Introducing GPT-6.1 Sol" in [c.title for c in again]


def test_dedupe_same_article_on_two_blogs():
    a = feeds.Entry("Gemini 4 Argon: our next era of frontier intelligence", "https://blog.google/a", "google", "g", priority=2)
    b = feeds.Entry("Gemini 4 Argon: our next era of frontier intelligence", "https://deepmind.google/b", "google", "d", priority=1)
    out = detect.dedupe([b, a])
    assert len(out) == 1 and out[0].url == "https://blog.google/a" and out[0].extra["alsoAt"] == ["https://deepmind.google/b"]


class FakeClaude:
    def __init__(self, *_):
        pass


def fake_draft():
    return {
        "decision": "new", "reason": "", "updateId": "",
        "item": {
            "id": "gpt-7-nova", "kind": "모델 출시", "title": "GPT-7 Nova", "headline": "새 모델", "tldr": "요약입니다.",
            "models": [{"name": "GPT-7 Nova", "apiId": "gpt-7-nova", "input": "$3", "output": "$18", "cached": ""}],
            "numbers": [{"label": "Terminal-Bench 4.0", "value": "61.2%", "note": ""},
                        {"label": "지어낸 수치", "value": "88.8%", "note": ""}],
            "chartSource": "OpenAI 발표문 표",
            "charts": [{"title": "Terminal-Bench 4.0", "desc": "터미널", "type": "bar", "unit": "%", "lowerIsBetter": False,
                        "source": "", "note": "", "rows": [{"label": "GPT-7 Nova", "value": 61.2, "highlight": True},
                                                          {"label": "GPT-6.1 Sol", "value": 58.0, "highlight": False},
                                                          {"label": "Claude Opus 5.5", "value": 66.4, "highlight": False}]},
                       {"title": "GDPval-AA", "desc": "Elo", "type": "dot", "unit": "Elo", "lowerIsBetter": False,
                        "source": "", "note": "", "rows": [{"label": "GPT-7 Nova", "value": 1802, "highlight": True},
                                                          {"label": "GPT-6.1 Sol", "value": 1640, "highlight": False}]},
                       {"title": "Hallucinated", "desc": "", "type": "bar", "unit": "%", "lowerIsBetter": False,
                        "source": "", "note": "", "rows": [{"label": "GPT-7 Nova", "value": 91.1, "highlight": True},
                                                          {"label": "X", "value": 80.0, "highlight": False}]}],
            "chartNote": "",
            "changes": ["바뀐 점"], "availability": ["API"], "tips": [{"title": "팁", "body": "내용"}],
            "prompts": [{"title": "p", "when": "w", "type": "prompt", "text": "t"}],
            "cautions": ["주의"], "sources": [{"title": "원문", "url": "https://openai.com/index/introducing-gpt-7-nova/"}],
        },
        "update": {"changes": [], "availability": [], "sources": []},
    }


def test_full_update_writes_verified_item(site, monkeypatch):
    import backend.summarize as summ

    monkeypatch.setattr(feeds, "fetch_all", lambda sources=None: (feeds.parse_rss(RSS, OPENAI), {}))
    monkeypatch.setattr(pipeline, "fetch_article", lambda url: extract.parse_html(ARTICLE, url))
    monkeypatch.setattr(summ, "Claude", FakeClaude)
    monkeypatch.setattr(summ, "triage", lambda c, cands, lines: {i: ("Nova" in e.title, "고객 사례") for i, e in enumerate(cands)})
    monkeypatch.setattr(summ, "write_item", lambda *a, **k: fake_draft())

    report = pipeline.run_update(api_key="test")
    assert [a["id"] for a in report.added] == ["gpt-7-nova"]
    item = json.loads((site / "data/news/gpt-7-nova.json").read_text())
    assert item["date"] == "2026-10-01" and item["company"] == "openai"
    assert [c["title"] for c in item["charts"]] == ["Terminal-Bench 4.0", "GDPval-AA"]
    assert [n["label"] for n in item["numbers"]] == ["Terminal-Bench 4.0"]
    assert item["models"][0]["cached"] is None
    manifest = json.loads((site / "data/manifest.json").read_text())
    assert manifest["news"][0] == "gpt-7-nova" and manifest["lastChecked"] == "2026-10-02 06:03"
    ok, out = store.validate()
    assert ok, out
    state = json.loads((site / "backend/state/seen.json").read_text())
    statuses = {v["title"]: v["status"] for v in state["urls"].values()}
    assert statuses["Introducing GPT-7 Nova"] == "added" and statuses["How Acme uses ChatGPT Work"] == "skipped"

    # a second run finds nothing new and makes no API calls
    monkeypatch.setattr(summ, "write_item", lambda *a, **k: pytest.fail("should not be called"))
    monkeypatch.setattr(summ, "triage", lambda *a, **k: pytest.fail("should not be called"))
    report2 = pipeline.run_update(api_key="test")
    assert report2.candidates == [] and report2.added == []


def test_without_api_key_only_detects(site, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(feeds, "fetch_all", lambda sources=None: (feeds.parse_rss(RSS, OPENAI), {}))
    before = sorted(p.name for p in (site / "data/news").glob("*.json"))
    report = pipeline.run_update()
    assert "ANTHROPIC_API_KEY" in report.note
    assert sorted(p.name for p in (site / "data/news").glob("*.json")) == before
    pending = json.loads((site / "backend/state/pending.json").read_text())
    assert any(p["title"] == "Introducing GPT-7 Nova" for p in pending)


def test_update_decision_appends_to_existing(site, monkeypatch):
    import backend.summarize as summ

    rss = RSS.replace("Introducing GPT-7 Nova", "GPT-6.1 Sol now available in the EU").replace("introducing-gpt-7-nova", "gpt-6-1-sol-eu")
    monkeypatch.setattr(feeds, "fetch_all", lambda sources=None: (feeds.parse_rss(rss, OPENAI), {}))
    monkeypatch.setattr(pipeline, "fetch_article", lambda url: extract.parse_html(ARTICLE, url))
    monkeypatch.setattr(summ, "Claude", FakeClaude)
    monkeypatch.setattr(summ, "triage", lambda c, cands, lines: {i: ("EU" in e.title, "") for i, e in enumerate(cands)})
    draft = {"decision": "update", "reason": "", "updateId": "gpt-6-1-sol", "item": fake_draft()["item"],
             "update": {"changes": ["EU에서도 쓸 수 있게 됐습니다."], "availability": [],
                        "sources": [{"title": "EU", "url": "https://openai.com/index/gpt-6-1-sol-eu"}]}}
    monkeypatch.setattr(summ, "write_item", lambda *a, **k: draft)
    report = pipeline.run_update(api_key="test")
    assert report.updated == [{"id": "gpt-6-1-sol", "url": "https://openai.com/index/gpt-6-1-sol-eu"}]
    d = json.loads((site / "data/news/gpt-6-1-sol.json").read_text())
    assert d["changes"][-1] == "EU에서도 쓸 수 있게 됐습니다."


SITEMAP = """<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.anthropic.com/news/claude-haiku-5-5</loc><lastmod>2026-10-01T10:00:00.000Z</lastmod></url>
<url><loc>https://www.anthropic.com/news/100k-context-windows</loc><lastmod>2026-09-09T19:42:51.000Z</lastmod></url>
<url><loc>https://www.anthropic.com/careers</loc><lastmod>2026-10-01T10:00:00.000Z</lastmod></url>
</urlset>"""


def test_sitemap_and_slug_matching(site):
    entries = feeds.parse_sitemap(SITEMAP, config.SOURCES[2])
    assert [e.url for e in entries] == ["https://www.anthropic.com/news/claude-haiku-5-5",
                                        "https://www.anthropic.com/news/100k-context-windows"]
    assert entries[0].extra["lastmod"] == date(2026, 10, 1)
    idx = detect.load_site()
    # /news/claude-sonnet-5-5 is the same page as the known /claude-sonnet-5-5
    moved = feeds.Entry("Introducing Claude Sonnet 5.5", "https://www.anthropic.com/news/claude-sonnet-5-5", "anthropic", "x",
                        date(2026, 9, 28))
    cands = detect.find_candidates(entries + [moved], idx, {"urls": {}}, date(2026, 10, 2))
    assert [c.url for c in cands] == ["https://www.anthropic.com/news/claude-haiku-5-5"]   # old lastmod and known slug dropped


def test_same_model_same_day_counts_as_known(site):
    idx = detect.load_site()
    dup = feeds.Entry("Gemini 4 Argon: our next era of frontier intelligence", "https://deepmind.google/blog/argon-x",
                      "google", "d", date(2026, 9, 30))
    assert detect.find_candidates([dup], idx, {"urls": {}}, date(2026, 10, 2)) == []


def test_similar_titles_from_one_source_stay_separate():
    a = feeds.Entry("Introducing Claude Opus 5.5", "https://www.anthropic.com/claude-opus-5-5", "anthropic", "n", date(2026, 9, 22), priority=2)
    b = feeds.Entry("Introducing Claude Sonnet 5.5", "https://www.anthropic.com/claude-sonnet-5-5", "anthropic", "n", date(2026, 9, 28), priority=2)
    assert len(detect.dedupe([a, b])) == 2


def test_cli_backend_uses_subscription_not_api(monkeypatch):
    import subprocess
    import backend.summarize as summ

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sub-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-leak")
    monkeypatch.delenv("RR_LLM", raising=False)
    assert summ.llm_available() == "cli"
    llm = summ.make_llm()
    assert isinstance(llm, summ.ClaudeCodeCLI)
    seen = {}

    def fake_run(cmd, input, capture_output, text, env, timeout):
        seen.update(cmd=cmd, env=env, input=input)
        out = json.dumps({"type": "result", "is_error": False, "result": "", "structured_output": {"results": []}})
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert llm.json_call(model="claude-sonnet-5-5", system="규칙", user="내용", schema=summ.TRIAGE, max_tokens=100) == {"results": []}
    assert "ANTHROPIC_API_KEY" not in seen["env"] and seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "sub-token"
    assert "--json-schema" in seen["cmd"] and seen["cmd"][seen["cmd"].index("--tools") + 1] == ""
    assert "규칙" in seen["input"] and "내용" in seen["input"]

    # text result without structured_output is parsed too
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(
        cmd, 0, json.dumps({"is_error": False, "result": "```json\n{\"results\": [1]}\n```"}), ""))
    assert llm.json_call(model="m", system="", user="", schema={}, max_tokens=1) == {"results": [1]}


def test_api_key_alone_selects_api(monkeypatch):
    import backend.summarize as summ

    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert summ.llm_available() == "api"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert summ.llm_available() is None


def test_auth_failure_stops_early_and_is_reported(site, monkeypatch):
    import backend.summarize as summ

    monkeypatch.setattr(feeds, "fetch_all", lambda sources=None: (feeds.parse_rss(RSS, OPENAI), {}))
    monkeypatch.setattr(summ, "Claude", FakeClaude)

    def bad_triage(*a, **k):
        raise RuntimeError('claude CLI 실패(1): "api_error_status":401,"result":"Failed to authenticate. API Error: 401 Invalid bearer token"')

    monkeypatch.setattr(summ, "triage", bad_triage)
    monkeypatch.setattr(summ, "write_item", lambda *a, **k: pytest.fail("should not be called after an auth error"))
    report = pipeline.run_update(api_key="test")
    assert report.authError and "인증 실패" in report.note
    saved = json.loads((site / "backend/state/last-run.json").read_text())
    assert saved["authError"] is True
    state = json.loads((site / "backend/state/seen.json").read_text())
    assert state.get("urls", {}) == {} and not state.get("attempts")   # nothing burned, retried next run


def test_cli_token_whitespace_is_removed(monkeypatch):
    import backend.summarize as summ

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "  sk-ant-oat01-abc\r\ndef ghi \n")
    assert summ.ClaudeCodeCLI().env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-abcdefghi"
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "│ sk-ant-oat01-ab_C-d │\n│ ef9 │")
    assert summ.ClaudeCodeCLI().env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-ab_C-def9"


# ---- two posts about one launch in the same run (EmbeddingGemma 2, 2026-10-06) ----

GOOGLE_RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Dev</title>
<item><title>Bring multimodal semantic search to the edge with VectorGemma 9</title>
<link>https://developers.googleblog.com/edge-with-vectorgemma-9/</link><pubDate>Fri, 02 Oct 2026 16:00:00 GMT</pubDate></item>
<item><title>VectorGemma 9: The Developer Guide</title>
<link>https://developers.googleblog.com/vectorgemma-9-developer-guide/</link><pubDate>Fri, 02 Oct 2026 16:00:00 GMT</pubDate></item>
</channel></rss>"""

GOOGLE = next(s for s in config.SOURCES if s.name == "Google Developers blog")
VG_PAGE = ("<html><body><article><h1>VectorGemma 9</h1><p>VectorGemma 9 is a 740M embedding model.</p>"
           + "<p>more text</p>" * 200 + "</article></body></html>")


def vg_draft(url, kind="모델 출시", title="VectorGemma 9", model="VectorGemma 9"):
    return {"decision": "new", "reason": "", "updateId": "", "update": {"changes": [], "availability": [], "sources": []},
            "item": {"id": "vectorgemma-9", "kind": kind, "title": title, "headline": "h", "tldr": "t",
                     "models": [{"name": model, "apiId": "", "input": "", "output": "", "cached": ""}],
                     "numbers": [], "charts": [], "chartNote": "n", "chartSource": "", "changes": ["c"],
                     "availability": ["a"], "tips": [{"title": "x", "body": "y"}],
                     "prompts": [{"title": "p", "when": "w", "type": "prompt", "text": "t"}],
                     "cautions": ["z"], "sources": [{"title": "s", "url": url}]}}


def run_two_posts(site, monkeypatch, rss, draft_for):
    import backend.summarize as summ

    calls = []
    def fake_write(claude, entry, art, site_lines, today, update_of=None):
        calls.append((entry.url, update_of["id"] if update_of else None))
        if update_of:
            return {"decision": "update", "updateId": update_of["id"], "reason": "",
                    "update": {"changes": ["개발자 가이드의 새 내용"], "availability": [], "sources": []}}
        return draft_for(entry.url)

    monkeypatch.setattr(feeds, "fetch_all", lambda sources=None: (feeds.parse_rss(rss, GOOGLE), {}))
    monkeypatch.setattr(pipeline, "fetch_article", lambda url: extract.parse_html(VG_PAGE, url))
    monkeypatch.setattr(summ, "Claude", FakeClaude)
    monkeypatch.setattr(summ, "triage", lambda c, cands, lines: {i: (True, "") for i, _ in enumerate(cands)})
    monkeypatch.setattr(summ, "write_item", fake_write)
    return pipeline.run_update(api_key="test"), calls


def test_second_post_about_same_launch_updates_instead_of_duplicating(site, monkeypatch):
    report, calls = run_two_posts(site, monkeypatch, GOOGLE_RSS, vg_draft)
    assert [a["id"] for a in report.added] == ["vectorgemma-9"]
    assert [u["id"] for u in report.updated] == ["vectorgemma-9"]
    assert calls[1][1] == "vectorgemma-9"                 # the second post was written as an update
    assert not (site / "data/news/vectorgemma-9-2.json").exists()
    item = json.loads((site / "data/news/vectorgemma-9.json").read_text())
    urls = [s["url"] for s in item["sources"]]
    assert "https://developers.googleblog.com/vectorgemma-9-developer-guide/" in urls
    assert "개발자 가이드의 새 내용" in item["changes"]
    manifest = json.loads((site / "data/manifest.json").read_text())
    assert manifest["news"].count("vectorgemma-9") == 1 and "vectorgemma-9-2" not in manifest["news"]


def test_duplicate_launch_caught_even_when_title_hides_model_name(site, monkeypatch):
    rss = GOOGLE_RSS.replace("VectorGemma 9: The Developer Guide", "A new open embedding model for developers")
    report, calls = run_two_posts(site, monkeypatch, rss, vg_draft)
    assert len(report.added) == 1 and len(report.updated) == 1
    assert calls[1][1] is None and calls[2][1] == "vectorgemma-9"   # drafted as new, caught, rewritten as update


def test_writer_ignoring_update_request_still_adds_no_second_item(site, monkeypatch):
    import backend.summarize as summ

    rss = GOOGLE_RSS.replace("VectorGemma 9: The Developer Guide", "A new open embedding model for developers")
    report, _ = run_two_posts(site, monkeypatch, rss, vg_draft)  # warm-up run adds the item
    assert len(report.added) == 1
    # a stubborn writer that always answers "new"
    monkeypatch.setattr(summ, "write_item", lambda *a, **k: vg_draft(a[1].url))
    state = json.loads((site / "backend/state/seen.json").read_text())
    state["urls"].clear()
    (site / "backend/state/seen.json").write_text(json.dumps(state))
    item_path = site / "data/news/vectorgemma-9.json"
    item = json.loads(item_path.read_text())
    item["sources"] = item["sources"][:1]
    item_path.write_text(json.dumps(item, ensure_ascii=False))
    report2 = pipeline.run_update(api_key="test")
    assert report2.added == [] and [u["id"] for u in report2.updated] == ["vectorgemma-9"]
    assert not (site / "data/news/vectorgemma-9-2.json").exists()
    urls = [s["url"] for s in json.loads(item_path.read_text())["sources"]]
    assert "https://developers.googleblog.com/vectorgemma-9-developer-guide/" in urls   # kept as a source


def test_tip_about_launched_model_stays_separate(site):
    idx = detect.load_site()
    idx.add({"id": "vectorgemma-9", "company": "google", "date": "2026-10-02", "kind": "모델 출시",
             "title": "VectorGemma 9", "models": [{"name": "VectorGemma 9"}], "sources": []})
    tip = {"company": "google", "date": "2026-10-03", "kind": "활용 팁", "title": "VectorGemma 9 검색 팁",
           "models": [{"name": "VectorGemma 9"}]}
    assert detect.duplicate_launch(tip, idx) is None
    launch = {**tip, "kind": "모델 출시", "title": "VectorGemma 9 (preview)"}
    assert detect.duplicate_launch(launch, idx) == "vectorgemma-9"


def test_site_name_suffix_removed_from_titles():
    assert extract.clean_title("EmbeddingGemma 2: The Developer Guide- Google Developers Blog") == \
        "EmbeddingGemma 2: The Developer Guide"
    assert extract.clean_title("Gemini 3.5 Flash - our fastest model") == "Gemini 3.5 Flash - our fastest model"


def test_listing_falls_back_to_reader_links():
    blog = next(s for s in config.SOURCES if s.name == "Claude blog")
    md = ("Title: Blog\nMarkdown Content:\n[Cowork is now Claude](https://claude.com/blog/cowork-is-now-claude) "
          "[All posts](https://claude.com/blog/category/news) [Docs](https://code.claude.com/docs/en/overview)\n"
          "[**Artifacts in Claude Code**](https://claude.com/blog/artifacts-in-claude-code?x=1)")
    got = feeds.parse_reader_listing(md, blog)
    assert [e.url for e in got] == ["https://claude.com/blog/cowork-is-now-claude",
                                    "https://claude.com/blog/artifacts-in-claude-code"]
    assert got[1].title == "Artifacts in Claude Code" and got[0].extra["via"] == "reader"


def test_selftest_window_follows_hidden_item(site):
    idx = detect.load_site()
    old = feeds.Entry("Introducing Claude Vector 1", "https://www.anthropic.com/vectorclaude-1", "anthropic",
                      "Anthropic News", date(2026, 9, 1), "", 2)
    idx.items.insert(0, {"id": "vectorclaude-1", "company": "anthropic", "date": "2026-09-01",
                         "title": "VectorClaude 1", "kind": "모델 출시", "models": []})
    idx.known_urls[feeds.normalize_url(old.url)] = "vectorclaude-1"
    cands = detect.find_candidates([old], idx, {"urls": {}}, date(2026, 10, 7), pretend_missing={"vectorclaude-1"})
    assert [c.url for c in cands] == [old.url]


def test_claude_blog_sitemap_keeps_only_posts():
    blog = next(s for s in config.SOURCES if s.name == "Claude blog")
    xml = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://claude.com/blog/cowork-is-now-claude</loc><lastmod>2026-10-06T10:00:00Z</lastmod></url>
    <url><loc>https://claude.com/blog/category/news</loc><lastmod>2026-10-06T10:00:00Z</lastmod></url>
    <url><loc>https://claude.com/pricing</loc></url></urlset>"""
    got = feeds.parse_sitemap(xml, blog)
    assert [e.url for e in got] == ["https://claude.com/blog/cowork-is-now-claude"]
    assert got[0].extra["lastmod"] == date(2026, 10, 6) and got[0].company == "anthropic"


def test_blog_lastmod_is_not_taken_as_publish_date(site, monkeypatch):
    blog = next(s for s in config.SOURCES if s.name == "Claude blog")
    e = feeds.Entry("old tips", "https://claude.com/blog/old-tips", "anthropic", blog.name, None, "", 1,
                    {"lastmod": date(2026, 10, 6), "titleFromSlug": True})
    page = "<html><body><article><p>" + "tips " * 300 + "</p></article></body></html>"
    monkeypatch.setattr(pipeline, "fetch_article", lambda url: extract.parse_html(page, url))
    state = {"urls": {}}
    out = pipeline._fill_dates([e], {}, date(2026, 9, 29), state, date(2026, 10, 7), pipeline.RunReport("t", "update"))
    assert out == [] and state["urls"][e.key]["status"] == "nodate"


def test_byline_date_in_article_header():
    html = ("<html><body><article><header><h1>Rethinking skills</h1><p>Sep 11, 2026</p></header>"
            "<p>Coding agents have come a long way.</p>" + "<p>more</p>" * 100 + "</article></body></html>")
    assert extract.parse_html(html, "u").published == date(2026, 9, 11)
