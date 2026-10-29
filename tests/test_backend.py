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
<a href="https://www.anthropic.com/news/claude-haiku-9-9"><h3>Introducing Claude Haiku 5.5</h3></a>
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
    monkeypatch.setattr(config, "PRICES_FILE", tmp_path / "data" / "prices.json")
    monkeypatch.setattr(config, "GUIDES_FILE", tmp_path / "data" / "guides.json")
    monkeypatch.setattr(config, "MAINT_REPORT", tmp_path / "backend" / "state" / "maintenance-run.json")
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
                    "https://www.anthropic.com/news/claude-haiku-9-9"]
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
    newsroom = feeds.Entry("Introducing Claude Haiku 5.5", "https://www.anthropic.com/news/claude-haiku-9-9", "anthropic",
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


# ---- API changelogs (launches that never get a blog post) ----

GEMINI_CL = next(s for s in config.SOURCES if s.name == "Gemini API release notes")
OPENAI_CL = next(s for s in config.SOURCES if s.name == "OpenAI API changelog")
CLAUDE_CL = next(s for s in config.SOURCES if s.name == "Claude Platform release notes")

GEMINI_MD = """# Release notes

## October 8, 2026 {#10-08-2026}

- **Deprecation**: `gemini-3.7-flash` is deprecated. Requests are routed to [`gemini-3.8-flash`](/gemini-api/docs/models/gemini-3.8-flash).
- Deep Research agent `deep-research-pro-preview-12-2025` is deprecated.

## October 6, 2026

- Released Gemini Nano Banana 2.1 (`gemini-nano-banana-2.1`), our latest image model. See the [model page](/gemini-api/docs/models/gemini-nano-banana-2.1).
  - Better text rendering.
- Announced deprecation of `gemini-3.1-flash-image`.

## September 22, 2026

- Gemini 3.8 Flash TTS and Gemini 3.8 Flash-Lite TTS generally available (GA).
"""

OPENAI_CL_TEXT = """### October, 2026

Oct 28

Feature

Eligible ChatGPT Pro and Business subscribers can now claim free API credits.

Oct 6

Feature

gpt-6-luna

Released the Decisions API in beta for structured choices.

### December, 2025

Dec 30

Update

Released a year-end snapshot of the realtime models.
"""

CLAUDE_MD = """# Claude Platform release notes

### October 7, 2026

- We've launched [Claude Haiku 5.5](/docs/en/about-claude/models/overview), our fastest model.
- Lowered the cache read price for Claude Sonnet 5.5.
"""


def test_changelog_formats_split_into_dated_entries():
    g = feeds.parse_changelog(GEMINI_MD, GEMINI_CL, today=date(2026, 10, 29))
    assert [(e.published.isoformat(), e.title[:25]) for e in g] == [
        ("2026-10-08", "Deprecation: gemini-3.7-f"), ("2026-10-08", "Deep Research agent deep-"),
        ("2026-10-06", "Released Gemini Nano Bana"), ("2026-10-06", "Announced deprecation of "),
        ("2026-09-22", "Gemini 3.8 Flash TTS and ")]
    nano = g[2]
    assert nano.url == "https://ai.google.dev/gemini-api/docs/changelog#2026-10-06"
    assert "Better text rendering" in nano.extra["text"]                  # sub-bullet stays with its item
    assert "https://ai.google.dev/gemini-api/docs/models/gemini-nano-banana-2.1" in nano.extra["links"]
    assert len({e.key for e in g}) == 5 and nano.key != g[3].key         # same page, same day, separate entries
    # keys are stable, and editing one entry does not change the others
    again = feeds.parse_changelog(GEMINI_MD.replace("is deprecated.", "is now deprecated.", 1), GEMINI_CL, today=date(2026, 10, 29))
    assert [e.key for e in again][1:] == [e.key for e in g][1:] and again[0].key != g[0].key

    o = feeds.parse_changelog(OPENAI_CL_TEXT, OPENAI_CL, today=date(2026, 10, 29))
    assert [(e.published.isoformat(), e.title[:30], e.summary.split(":")[0]) for e in o] == [
        ("2026-10-28", "Eligible ChatGPT Pro and Busin", "Feature"),
        ("2026-10-06", "Released the Decisions API in ", "Feature"),      # the tag line is not the title
        ("2025-12-30", "Released a year-end snapshot o", "Update")]       # year from the month heading

    c = feeds.parse_changelog(CLAUDE_MD, CLAUDE_CL, today=date(2026, 10, 29))
    assert [e.title for e in c] == ["We've launched Claude Haiku 5.5, our fastest model.", "Lowered the cache read price for Claude Sonnet 5.5."]
    assert c[0].extra["links"] == ["https://platform.claude.com/docs/en/about-claude/models/overview"]


def test_changelog_entries_are_candidates_once(site):
    entries = feeds.parse_changelog(GEMINI_MD, GEMINI_CL, today=date(2026, 10, 8))
    idx = detect.load_site()
    idx.known_urls[feeds.normalize_url(GEMINI_CL.page)] = "some-item"          # a news item citing the changelog page
    cands = detect.find_candidates(entries, idx, {"urls": {}}, date(2026, 10, 8))
    assert [c.title[:20] for c in cands][:2] == ["Deprecation: gemini-", "Deep Research agent "]
    assert all(c.published >= date(2026, 9, 24) for c in cands)                 # Sep 22 is outside the look-back window
    state = {"urls": {}}
    nano = next(c for c in cands if "Nano Banana 2.1" in c.title)
    detect.mark(state, nano, "added", date(2026, 10, 8))
    left = detect.find_candidates(entries, idx, state, date(2026, 10, 8))
    assert nano.key not in {c.key for c in left} and len(left) == len(cands) - 1


def test_changelog_article_adds_the_linked_doc_page():
    nano = feeds.parse_changelog(GEMINI_MD, GEMINI_CL, today=date(2026, 10, 29))[2]
    read = []
    doc = extract.Article("https://ai.google.dev/gemini-api/docs/models/gemini-nano-banana-2.1", "Gemini Nano Banana 2.1",
                          None, "Model code gemini-nano-banana-2.1. Output $30.00 per 1M image tokens.", ["| a | b |"], [])
    art = extract.changelog_article(nano, fetch=lambda url: read.append(url) or doc)
    assert read == ["https://ai.google.dev/gemini-api/docs/models/gemini-nano-banana-2.1"]
    assert "Released Gemini Nano Banana 2.1" in art.text and "$30.00" in art.text and art.tables == ["| a | b |"]
    assert art.published == date(2026, 10, 6) and art.via == "changelog"
    broken = extract.changelog_article(nano, fetch=lambda url: (_ for _ in ()).throw(RuntimeError("404")))
    assert "Released Gemini Nano Banana 2.1" in broken.text                  # the entry alone still works


NOVA_CL = """### October, 2026

Oct 1

Feature

gpt-7-nova

Released GPT-7 Nova (gpt-7-nova), a new frontier model. See the [model page](/api/docs/models/gpt-7-nova).
"""


def run_changelog_update(site, monkeypatch, entries):
    import backend.summarize as summ

    seen_articles = []
    monkeypatch.setattr(feeds, "fetch_all", lambda sources=None: (entries, {}))
    monkeypatch.setattr(pipeline, "fetch_article", lambda url: extract.parse_html(ARTICLE, url))
    monkeypatch.setattr(extract, "fetch_article", lambda url: extract.parse_html(ARTICLE, url))   # the linked doc page
    monkeypatch.setattr(summ, "Claude", FakeClaude)
    monkeypatch.setattr(summ, "triage", lambda c, cands, lines: {i: ("Nova" in e.title, "고객 사례") for i, e in enumerate(cands)})

    def write(claude, entry, art, *a, **k):
        seen_articles.append((entry.url, art.via, art.text))
        return fake_draft()
    monkeypatch.setattr(summ, "write_item", write)
    return pipeline.run_update(api_key="test"), seen_articles


def test_launch_only_in_a_changelog_becomes_news(site, monkeypatch):
    entries = feeds.parse_changelog(NOVA_CL, OPENAI_CL, today=date(2026, 10, 2))
    report, arts = run_changelog_update(site, monkeypatch, entries)
    assert [a["id"] for a in report.added] == ["gpt-7-nova"]
    assert arts[0][1] == "changelog" and "Terminal-Bench" in arts[0][2]       # the entry plus its linked model page
    item = json.loads((site / "data/news/gpt-7-nova.json").read_text())
    assert item["date"] == "2026-10-01" and item["sources"][0]["url"] == "https://developers.openai.com/api/docs/changelog#2026-10-01"
    assert [n["label"] for n in item["numbers"]] == ["Terminal-Bench 4.0"]   # values still checked against the source
    assert store.validate()[0]
    report2, _ = run_changelog_update(site, monkeypatch, entries)
    assert report2.candidates == [] and report2.added == []


def test_blog_post_and_changelog_entry_on_the_same_day_make_one_item(site, monkeypatch):
    entries = feeds.parse_rss(RSS, OPENAI) + feeds.parse_changelog(NOVA_CL, OPENAI_CL, today=date(2026, 10, 2))
    report, arts = run_changelog_update(site, monkeypatch, entries)
    assert [a["id"] for a in report.added] == ["gpt-7-nova"] and arts[0][1] != "changelog"   # the blog post is written first
    assert [u["id"] for u in report.updated] == ["gpt-7-nova"]
    urls = [s["url"] for s in json.loads((site / "data/news/gpt-7-nova.json").read_text())["sources"]]
    assert "https://developers.openai.com/api/docs/changelog#2026-10-01" in urls
    assert len(list((site / "data/news").glob("gpt-7-nova*.json"))) == 1


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
<url><loc>https://www.anthropic.com/news/claude-haiku-9-9</loc><lastmod>2026-10-01T10:00:00.000Z</lastmod></url>
<url><loc>https://www.anthropic.com/news/100k-context-windows</loc><lastmod>2026-09-09T19:42:51.000Z</lastmod></url>
<url><loc>https://www.anthropic.com/careers</loc><lastmod>2026-10-01T10:00:00.000Z</lastmod></url>
</urlset>"""


def test_sitemap_and_slug_matching(site):
    entries = feeds.parse_sitemap(SITEMAP, config.SOURCES[2])
    assert [e.url for e in entries] == ["https://www.anthropic.com/news/claude-haiku-9-9",
                                        "https://www.anthropic.com/news/100k-context-windows"]
    assert entries[0].extra["lastmod"] == date(2026, 10, 1)
    idx = detect.load_site()
    # /news/claude-sonnet-5-5 is the same page as the known /claude-sonnet-5-5
    moved = feeds.Entry("Introducing Claude Sonnet 5.5", "https://www.anthropic.com/news/claude-sonnet-5-5", "anthropic", "x",
                        date(2026, 9, 28))
    cands = detect.find_candidates(entries + [moved], idx, {"urls": {}}, date(2026, 10, 2))
    assert [c.url for c in cands] == ["https://www.anthropic.com/news/claude-haiku-9-9"]   # old lastmod and known slug dropped


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


def test_blog_list_dates_without_year():
    assert feeds.month_day("Rethinking skills Sep 11", date(2026, 10, 7)) == date(2026, 9, 11)
    assert feeds.month_day("Year in review Dec 30", date(2026, 10, 7)) == date(2025, 12, 30)
    assert feeds.month_day("Sep 11, 2026") is None          # full dates are handled elsewhere
    dev = next(s for s in config.SOURCES if s.name == "OpenAI Developers blog")
    html = '<div><a href="/blog/rethinking-skills"><h3>Rethinking skills</h3><span>Sep 11</span></a></div>'
    assert feeds.parse_listing(html, dev)[0].published.month == 9


def test_listing_links_from_page_data():
    blog = next(s for s in config.SOURCES if s.name == "Claude blog")
    html = '<script>self.__next_f.push([1,"{\\"href\\":\\"/blog/cowork-is-now-claude\\"},{\\"href\\":\\"/blog/category/news\\"}"])</script><a href="https://example.com/blog/elsewhere">x</a>'
    got = feeds.parse_listing(html, blog)
    assert [e.url for e in got] == ["https://claude.com/blog/cowork-is-now-claude"]


def test_claude_articles_page_and_old_blog_links_are_same_post(site):
    blog = next(s for s in config.SOURCES if s.name == "Claude blog")
    html = ('<a href="/resources/articles/maximizing-the-value-of-your-claude-code-sessions"><h3>Maximizing</h3>'
            '<span>Aug 14, 2026</span></a><a href="/resources/articles/claude-code-mods"><h3>Customize Claude Code with mods</h3>'
            '<span>Oct 1, 2026</span></a>')
    got = feeds.parse_listing(html, blog)
    assert [e.published for e in got] == [date(2026, 8, 14), date(2026, 10, 1)]
    cands = detect.find_candidates(got, detect.load_site(), {"urls": {}}, date(2026, 10, 2))
    assert [c.url for c in cands] == ["https://claude.com/resources/articles/claude-code-mods"]  # the other is on the site as /blog/


# ---- price table upkeep ----

from backend import guides, prices  # noqa: E402

PRICE_PAGE = extract.Article(
    "https://developers.openai.com/api/docs/pricing", "Pricing", None,
    "Pricing per 1M tokens. " + "Standard tier. " * 200 +
    "GPT-6.1 Sol gpt-6.1-sol Input $2.00 Cached input $0.20 Output $12.00\n"
    "GPT-6 Luna gpt-6-luna Input $0.10 Cached input $0.01 Output $0.50\n", [], [])


class PriceClaude:
    """Answers the pricing-page call with rows (+ others) and the deprecation-page call with dep."""
    def __init__(self, rows, others=None, dep=None):
        self.rows, self.others, self.dep = rows, others or [], dep or []
        self.price_users = []

    def json_call(self, **kw):
        if kw.get("schema") is prices.DEPRECATION_CHECK:
            return {"models": self.dep}
        self.price_users.append(kw.get("user", ""))
        return {"models": self.rows, "others": self.others}


def price_row(key, listed=True, **kw):
    base = {"key": key, "listed": listed, "apiId": "", "input": "", "cached": "", "output": "", "perUnit": "",
            "category": "text", "desc": "", "note": "", "deprecated": False, "evidence": ""}
    base.update(kw)
    return base


def other_row(name, api, **kw):
    base = price_row("", apiId=api, **kw)
    del base["key"], base["listed"]
    base["name"] = name
    return base


def dep_row(api, shutdown, status="retired", replacement="", category="text"):
    return {"apiId": api, "status": status, "shutdown": shutdown, "replacement": replacement, "category": category, "evidence": ""}


def seed_prices(site, models):
    (site / "data/prices.json").write_text(json.dumps({"checkedAt": "", "pages": {}, "models": models}, ensure_ascii=False))


def entry(name, api, i, o, c=None, status="available", company="openai"):
    return {"company": company, "name": name, "apiId": api, "input": i, "cached": c, "output": o, "note": "",
            "status": status, "newsId": None, "verifiedAt": "2026-10-20", "missing": 0}


def only_openai(monkeypatch):
    monkeypatch.setattr(config, "PRICE_PAGES", {"openai": PRICE_PAGE.url})
    monkeypatch.setattr(config, "DEPRECATION_PAGES", {})
    monkeypatch.setattr(config, "NEWS_DIR", config.NEWS_DIR.parent / "no-news")
    config.NEWS_DIR.mkdir(exist_ok=True)


def test_price_change_is_applied_only_when_the_page_shows_it(site, monkeypatch):
    only_openai(monkeypatch)
    seed_prices(site, [entry("GPT-6.1 Sol", "gpt-6.1-sol", "$2", "$10", "$0.10"), entry("GPT-6 Luna", "gpt-6-luna", "$0.10", "$0.50", "$0.01")])
    claude = PriceClaude([price_row("gpt-6.1-sol", apiId="gpt-6.1-sol", input="$2.00", cached="$0.20", output="$12.00"),
                          price_row("gpt-6-luna", apiId="gpt-6-luna", input="$0.10", cached="$0.01", output="$0.70")])  # $0.70 not on page
    r = prices.run(claude, date(2026, 10, 21), "2026-10-21 06:05", fetch=lambda url: PRICE_PAGE)
    data = json.loads((site / "data/prices.json").read_text())
    sol = next(m for m in data["models"] if m["apiId"] == "gpt-6.1-sol")
    luna = next(m for m in data["models"] if m["apiId"] == "gpt-6-luna")
    assert (sol["output"], sol["cached"], sol["verifiedAt"]) == ("$12.00", "$0.20", "2026-10-21")
    assert luna["output"] == "$0.50"                                    # unverifiable value left alone
    assert any("출력 $10 → $12.00" in c for c in r["changes"]) and r["notes"]
    assert data["pages"]["openai"]["result"] == "확인"
    # the same day nothing is read again
    assert prices.run(claude, date(2026, 10, 21), "x", fetch=lambda url: pytest.fail("read twice"))["checked"] == []


def test_model_missing_twice_leaves_the_table(site, monkeypatch):
    only_openai(monkeypatch)
    seed_prices(site, [entry("GPT-6.1 Sol", "gpt-6.1-sol", "$2.00", "$12.00"), entry("GPT-6 Luna", "gpt-6-luna", "$0.10", "$0.50"),
                       entry("GPT-5.4 Pro", "gpt-5.4-pro", "$30", "$180")])
    claude = PriceClaude([price_row("gpt-6.1-sol", input="$2.00", output="$12.00"), price_row("gpt-6-luna", input="$0.10", output="$0.50"),
                          price_row("gpt-5.4-pro", listed=False)])
    prices.run(claude, date(2026, 10, 21), "2026-10-21 06:05", fetch=lambda url: PRICE_PAGE)
    pro = lambda: next(m for m in json.loads((site / "data/prices.json").read_text())["models"] if m["apiId"] == "gpt-5.4-pro")
    assert pro()["status"] == "available" and pro()["missing"] == 1
    r = prices.run(claude, date(2026, 10, 22), "2026-10-22 06:05", fetch=lambda url: PRICE_PAGE)
    assert pro()["status"] == "unlisted" and any("가격표에서 뺌: GPT-5.4 Pro" in c for c in r["changes"])


def test_half_the_table_vanishing_is_ignored(site, monkeypatch):
    only_openai(monkeypatch)
    seed_prices(site, [entry("GPT-6.1 Sol", "gpt-6.1-sol", "$2.00", "$12.00"), entry("GPT-6 Luna", "gpt-6-luna", "$0.10", "$0.50"),
                       entry("GPT-5.4 Pro", "gpt-5.4-pro", "$30", "$180")])
    claude = PriceClaude([price_row(k, listed=False) for k in ("gpt-6.1-sol", "gpt-6-luna", "gpt-5.4-pro")])
    r = prices.run(claude, date(2026, 10, 21), "2026-10-21 06:05", fetch=lambda url: PRICE_PAGE)
    assert all(m["missing"] == 0 for m in json.loads((site / "data/prices.json").read_text())["models"])
    assert "반영하지 않음" in r["changes"][0]


def test_newly_announced_model_is_checked_at_once(site, monkeypatch):
    monkeypatch.setattr(config, "PRICE_PAGES", {"openai": PRICE_PAGE.url})
    seed_prices(site, [])
    news = site / "data/news/gpt-6-1-sol.json"
    data = {"checkedAt": "", "pages": {"openai": {"url": "u", "checkedAt": "2026-10-21 00:05", "result": "확인"}}, "models": []}
    (site / "data/prices.json").write_text(json.dumps(data))
    rows = [price_row(k, input="$2.00", output="$12.00") if k == "gpt-6.1-sol" else price_row(k, listed=False)
            for k in prices.candidates(prices.load()) if k == "gpt-6.1-sol" or k.startswith("gpt") or k.startswith("name:gpt")]
    claude = PriceClaude(rows)
    r = prices.run(claude, date(2026, 10, 21), "2026-10-21 06:05", fetch=lambda url: PRICE_PAGE)
    assert "openai" in r["checked"]                                     # not due, but new models had no record
    models = json.loads((site / "data/prices.json").read_text())["models"]
    sol = next(m for m in models if m["apiId"] == "gpt-6.1-sol")
    assert sol["status"] == "available" and sol["newsId"] == "gpt-6-1-sol" and news.exists()
    assert all(m["status"] in ("available", "unlisted") for m in models)


# ---- new models found on the pricing page, shutdowns from the deprecation page ----

DEP_URL = "https://developers.openai.com/api/docs/deprecations.md"
DISCOVER_PAGE = extract.Article(PRICE_PAGE.url, "Pricing", None, PRICE_PAGE.text +
                                "GPT-7 Nova gpt-7-nova Input $3.00 Cached input $0.30 Output $15.00\n"
                                "GPT-Live 2 gpt-live-2 Price per minute $0.06\n", [], [])
LISTED = [price_row("gpt-6.1-sol", input="$2.00", cached="$0.20", output="$12.00"),
          price_row("gpt-6-luna", input="$0.10", cached="$0.01", output="$0.50")]


def table():
    return [entry("GPT-6.1 Sol", "gpt-6.1-sol", "$2.00", "$12.00", "$0.20"), entry("GPT-6 Luna", "gpt-6-luna", "$0.10", "$0.50", "$0.01")]


def dep_page(text):
    return extract.Article(DEP_URL, "Deprecations", None, "Deprecations. " + "Shutdown schedule. " * 80 + text, [], [])


def with_dep(monkeypatch, article):
    only_openai(monkeypatch)
    monkeypatch.setattr(config, "DEPRECATION_PAGES", {"openai": DEP_URL})
    return lambda url: article if url == DEP_URL else DISCOVER_PAGE


def models_by_id(site):
    return {m["apiId"]: m for m in json.loads((site / "data/prices.json").read_text())["models"]}


def test_new_model_on_the_pricing_page_is_added(site, monkeypatch):
    fetch = with_dep(monkeypatch, dep_page("No changes."))
    seed_prices(site, table())
    claude = PriceClaude(LISTED, others=[
        other_row("GPT-7 Nova", "gpt-7-nova", input="$3.00", cached="$0.30", output="$15.00", desc="새 플래그십 모델"),
        other_row("GPT-Live 2", "gpt-live-2", perUnit="$0.06 / 분", category="audio"),   # priced per minute only
        other_row("GPT-Ghost", "gpt-ghost", input="$1.00", output="$2.00"),             # not on the page
        other_row("GPT-7 Nova Max", "gpt-7-nova", input="$9.99", output="$15.00"),      # price not on the page
        other_row("GPT 6.1 Sol", "", input="$2.00", output="$12.00"),                   # ours, spelled differently
    ])
    r = prices.run(claude, date(2026, 10, 30), "2026-10-30 06:05", fetch=fetch)
    m = models_by_id(site)
    nova, live = m["gpt-7-nova"], m["gpt-live-2"]
    assert (nova["status"], nova["category"], nova["input"], nova["desc"], nova["addedAt"]) == \
        ("available", "text", "$3.00", "새 플래그십 모델", "2026-10-30")
    assert "since" not in nova      # found on the price page, not announced: no 'new model' alert on the 모델 추천 tab
    assert (live["category"], live["input"], live["output"], live["perUnit"]) == ("audio", None, None, "$0.06 / 분")
    assert sorted(m) == ["gpt-6-luna", "gpt-6.1-sol", "gpt-7-nova", "gpt-live-2"]
    assert sum("새 모델 추가" in c for c in r["changes"]) == 2
    assert any("GPT-Ghost" in n for n in r["notes"]) and any("GPT-7 Nova Max" in n for n in r["notes"])


def test_retired_model_moves_to_the_retired_list_and_stays_there(site, monkeypatch):
    fetch = with_dep(monkeypatch, dep_page("| 2026-10-28 | gpt-6-luna | gpt-6.1-terra |\n"
                                           "| 2026-03-01 | gpt-old-1 | gpt-6.1-sol |\n| 2024-01-01 | gpt-ancient | gpt-6.1-sol |"))
    seed_prices(site, table())
    claude = PriceClaude(LISTED, dep=[dep_row("gpt-6-luna", "2026-10-28", replacement="gpt-6.1-terra"),
                                      dep_row("gpt-old-1", "2026-03-01", replacement="gpt-6.1-sol"),
                                      dep_row("gpt-ancient", "2024-01-01")])
    r = prices.run(claude, date(2026, 10, 30), "2026-10-30 06:05", fetch=fetch)
    m = models_by_id(site)
    luna = m["gpt-6-luna"]
    assert (luna["status"], luna["shutdown"], luna["replacement"]) == ("retired", "2026-10-28", "gpt-6.1-terra")
    assert m["gpt-old-1"]["status"] == "retired"      # retired within a year: listed so old code can be looked up
    assert "gpt-ancient" not in m                     # older than a year and never in our table
    assert m["gpt-6.1-sol"]["status"] == "available"
    assert any(c.startswith("지원 종료로 옮김: GPT-6 Luna") for c in r["changes"])

    # The next day the pricing page still prices GPT-6 Luna (old prices stay up): it is neither checked nor re-added.
    claude = PriceClaude(LISTED, others=[other_row("GPT-6 Luna", "gpt-6-luna", input="$0.10", output="$0.50")])
    prices.run(claude, date(2026, 10, 31), "2026-10-31 06:05", fetch=fetch)
    models = json.loads((site / "data/prices.json").read_text())["models"]
    assert [x["status"] for x in models if x["apiId"] == "gpt-6-luna"] == ["retired"]
    assert "[gpt-6-luna]" not in claude.price_users[0] and "- GPT-6 Luna | gpt-6-luna" in claude.price_users[0]


def test_upcoming_shutdown_is_shown_then_retires_on_the_day(site, monkeypatch):
    fetch = with_dep(monkeypatch, dep_page("| 2026-11-15 | gpt-6-luna | gpt-6.1-terra |"))
    seed_prices(site, table())
    claude = PriceClaude(LISTED, dep=[dep_row("gpt-6-luna", "2026-11-15", status="deprecated", replacement="gpt-6.1-terra")])
    r = prices.run(claude, date(2026, 10, 30), "2026-10-30 06:05", fetch=fetch)
    luna = models_by_id(site)["gpt-6-luna"]
    assert (luna["status"], luna["shutdown"], luna["replacement"]) == ("deprecated", "2026-11-15", "gpt-6.1-terra")
    assert any("지원 종료 예정 표시: GPT-6 Luna" in c for c in r["changes"])

    # On the shutdown day the deprecation page cannot be read, but the known date still retires the model.
    def broken(url):
        if url == DEP_URL:
            raise RuntimeError("down")
        return DISCOVER_PAGE
    r = prices.run(PriceClaude(LISTED), date(2026, 11, 15), "2026-11-15 06:05", fetch=broken)
    assert models_by_id(site)["gpt-6-luna"]["status"] == "retired" and "openai 지원 종료" in r["errors"]


def test_earliest_possible_date_of_an_active_model_is_not_a_shutdown(site, monkeypatch):
    fetch = with_dep(monkeypatch, dep_page("| gpt-6-luna | Active | N/A | Not sooner than October 15, 2026 |"))
    seed_prices(site, table())
    r = prices.run(PriceClaude(LISTED, dep=[dep_row("gpt-6-luna", "2026-10-15")]), date(2026, 10, 30), "x", fetch=fetch)
    assert models_by_id(site)["gpt-6-luna"]["status"] == "available"
    assert any("gpt-6-luna" in n and "확인하지 못해" in n for n in r["notes"])


def test_half_the_table_retiring_at_once_is_ignored(site, monkeypatch):
    fetch = with_dep(monkeypatch, dep_page("| 2026-10-01 | gpt-6-luna |\n| 2026-10-01 | gpt-6.1-sol |"))
    seed_prices(site, table())
    claude = PriceClaude(LISTED, dep=[dep_row("gpt-6-luna", "2026-10-01"), dep_row("gpt-6.1-sol", "2026-10-01")])
    r = prices.run(claude, date(2026, 10, 30), "x", fetch=fetch)
    assert all(m["status"] == "available" for m in models_by_id(site).values())
    assert any("한꺼번에 지원 종료로 읽혀" in c for c in r["changes"])


def test_name_only_models_match_ids_without_mixing_versions():
    assert prices.name_matches_id("Claude Opus 4.1", "claude-opus-4-1-20250805")
    assert not prices.name_matches_id("Claude Opus 4", "claude-opus-4-1-20250805")
    assert prices.name_matches_id("gpt-5.4-nano", "gpt-5.4-nano-2026-03-17")
    assert [prices.guess_category(x) for x in ("gpt-live-1", "gemini-nano-banana-2.1", "gemini-embedding-2", "gpt-6.1-sol")] == \
        ["audio", "media", "other", "text"]


# ---- prompt guide upkeep ----

GUIDE = {"updatedAt": "2026-10-01", "common": [], "vendors": [{
    "company": "openai", "name": "OpenAI · GPT", "summary": "s",
    "methods": [{"id": "openai-criteria", "category": "기본 작성법", "title": "완료 기준을 먼저 쓰기", "body": "b",
                 "source": {"title": "t", "url": "https://developers.openai.com/api/docs/guides/prompting"}}],
    "templates": [], "watch": [{"title": "Prompting", "url": "https://developers.openai.com/api/docs/guides/prompting"}]}]}

GUIDE_PAGE = extract.Article("https://developers.openai.com/api/docs/guides/prompting", "Prompting", None,
                             "Use reasoning effort low first. It cut latency by 40% in our tests. " * 30, [], [])


class GuideClaude:
    def __init__(self, add=(), update=()):
        self.calls, self.add, self.update = 0, list(add), list(update)

    def json_call(self, **_):
        self.calls += 1
        return {"add": self.add, "update": self.update, "reason": ""}


def method(mid, title, body, **kw):
    return {"id": mid, "category": kw.get("category", "추론과 effort"), "title": title, "body": body,
            "before": kw.get("before", ""), "after": kw.get("after", ""), "code": "", "models": []}


def test_guide_page_change_adds_checked_methods(site):
    (site / "data/guides.json").write_text(json.dumps(GUIDE, ensure_ascii=False))
    claude = GuideClaude(add=[method("openai-effort-low", "추론은 낮게 시작", "지연이 40% 줄었습니다.", after="[작업]을 해 줘."),
                              method("openai-fake", "지어낸 수치", "정확도가 25% 올랐습니다."),
                              method("openai-dup", "완료 기준을 먼저 쓰기", "같은 카드")])
    page = GUIDE_PAGE
    first = guides.check_watch(claude, date(2026, 10, 21), "2026-10-21 06:05", fetch=lambda u: page)
    assert first["checked"] == 1 and claude.calls == 0                  # first look only remembers the page
    changed = extract.Article(page.url, page.title, None, page.text + " New section about effort.", [], [])
    r = guides.check_watch(claude, date(2026, 10, 22), "2026-10-22 06:05", fetch=lambda u: changed)
    data = json.loads((site / "data/guides.json").read_text())
    titles = [m["title"] for m in data["vendors"][0]["methods"]]
    assert titles == ["완료 기준을 먼저 쓰기", "추론은 낮게 시작"]
    added = data["vendors"][0]["methods"][1]
    assert added["addedAt"] == "2026-10-22" and added["source"]["url"] == page.url and added["after"]
    assert any("원문에 없는 수치" in c for c in r["changes"]) and claude.calls == 1
    # unchanged page next day: no Claude call
    guides.check_watch(claude, date(2026, 10, 23), "x", fetch=lambda u: changed)
    assert claude.calls == 1


def test_new_tip_item_feeds_the_guide(site):
    (site / "data/guides.json").write_text(json.dumps(GUIDE, ensure_ascii=False))
    claude = GuideClaude(add=[method("openai-skill-desc", "스킬 설명은 언제 쓰는지만", "설명이 짧을수록 고르기 쉽습니다.", category="에이전트와 코딩"),
                              method("openai-b", "둘째", "두 번째"), method("openai-c", "셋째", "세 번째")])
    item = {"id": "openai-tip", "company": "openai", "title": "팁", "sources": [{"title": "t", "url": "https://developers.openai.com/blog/x"}]}
    art = extract.Article("https://developers.openai.com/blog/x", "x", None, "skills " * 300, [], [])
    changes = guides.from_tip(claude, item, art, date(2026, 10, 21))
    methods = json.loads((site / "data/guides.json").read_text())["vendors"][0]["methods"]
    assert len(methods) == 3 and methods[1]["newsId"] == "openai-tip" and len(changes) == 2
    assert guides.from_tip(claude, item, art, date(2026, 10, 21)) == []   # same article never twice


def test_maintenance_rolls_back_invalid_changes(site, monkeypatch):
    (site / "data/guides.json").write_text(json.dumps(GUIDE, ensure_ascii=False))
    seed_prices(site, [entry("GPT-6.1 Sol", "gpt-6.1-sol", "$2", "$10")])
    before = (site / "data/prices.json").read_text()
    import backend.summarize as summ

    def broken_run(*a, **k):
        data = prices.load()
        data["models"][0]["status"] = "maybe"           # the validator rejects this
        prices.save(data)
        return {"checked": ["openai"], "changes": [], "notes": [], "errors": {}}

    monkeypatch.setattr(summ, "llm_available", lambda: "api")
    monkeypatch.setattr(summ, "make_llm", lambda: object())
    monkeypatch.setattr(prices, "run", broken_run)
    monkeypatch.setattr(guides, "check_watch", lambda *a, **k: {"checked": 0, "changed": [], "changes": [], "errors": {}})
    report = pipeline.run_maintenance()
    assert "되돌림" in report["note"] and (site / "data/prices.json").read_text() == before
    assert json.loads((site / "backend/state/maintenance-run.json").read_text())["note"] == report["note"]


class FeatureClaude:
    def __init__(self, update):
        self.calls, self.update = 0, update

    def json_call(self, **kw):
        self.calls += 1
        if kw.get("schema") is guides.FEATURE_UPDATE:
            return {"update": self.update, "reason": ""}
        return {"add": [], "update": [], "reason": ""}


def test_changed_help_page_rechecks_feature_map_cells(site):
    url = "https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt"
    data = json.loads(json.dumps(GUIDE))
    data["vendors"][0]["watch"] = [{"title": "Tasks", "url": url, "hash": "old"}]
    cell = {"name": "예약 작업", "note": "Plus는 5개까지.", "sources": [{"title": "t", "url": url}]}
    other = {"name": "x", "note": "y", "sources": [{"title": "t", "url": "https://example.com/other"}]}
    data["appFeatures"] = {"title": "대응표", "rows": [
        {"key": "schedule", "label": "예약", "cells": {"openai": cell}},
        {"key": "memory", "label": "기억", "cells": {"openai": other}}]}
    (site / "data/guides.json").write_text(json.dumps(data, ensure_ascii=False))
    page = extract.Article(url, "Tasks", None, "Plus: 8 active tasks. Pro: 15. " * 40, [], [])
    claude = FeatureClaude([{"key": "schedule", "name": "예약 작업", "note": "Plus는 8개까지."},
                            {"key": "memory", "name": "x", "note": "다른 페이지 칸은 못 고침"}])
    r = guides.check_watch(claude, date(2026, 10, 22), "2026-10-22 06:05", fetch=lambda u: page)
    saved = json.loads((site / "data/guides.json").read_text())["appFeatures"]
    assert saved["rows"][0]["cells"]["openai"]["note"] == "Plus는 8개까지."
    assert saved["rows"][0]["cells"]["openai"]["updatedAt"] == "2026-10-22"
    assert saved["rows"][1]["cells"]["openai"]["note"] == "y"
    assert any(c.startswith("대응표 수정") for c in r["changes"])
    # a number the page does not show is refused
    wrapped = {"appFeatures": saved}
    pairs = guides.feature_cells(wrapped, "openai", url)
    out = guides.apply_feature_updates(wrapped, "openai", pairs,
                                       {"update": [{"key": "schedule", "name": "예약 작업", "note": "Plus는 12개까지."}]},
                                       page.text, date(2026, 10, 23))
    assert out and out[0].startswith("제외") and pairs[0][1]["note"] == "Plus는 8개까지."


# ---- style rules (im-not-ai), product kind, technique links ----
def test_connective_comma_removed_but_noun_comma_kept():
    from backend.humanize import checker

    sc = checker()
    text = "모델을 고르고, 결과를 확인하며, 참고, 로고, 빠르지만, 비쌉니다."
    assert sc.fix_c11(text) == "모델을 고르고 결과를 확인하며 참고, 로고, 빠르지만 비쌉니다."
    assert sc.c11_spans("최고, 광고, 하고,") == ["하고,"]


class StyleClaude:
    def __init__(self, fields):
        self.fields, self.calls = fields, 0

    def json_call(self, **kw):
        self.calls += 1
        return {"fields": self.fields}


def test_polish_keeps_numbers_and_rejects_big_rewrites():
    from backend import humanize

    item = {"kind": "활용 팁", "title": "추론 유지: 점수 3배", "headline": "설정 두 개로 바뀝니다",
            "tldr": "핵심은 Responses API를 쓰는 것입니다. 점수가 13.3%에서 38.3%로 올랐고, 토큰은 줄었습니다.",
            "changes": ["A가 아니라 B입니다.", "C가 아니라 D입니다."], "availability": [], "cautions": [], "tips": []}
    claude = StyleClaude([
        {"path": "tldr", "text": "Responses API를 쓰면 됩니다. 점수가 13.3%에서 38.3%로 올랐고 토큰은 줄었습니다."},
        {"path": "title", "text": "추론 유지로 점수 3배"},
        {"path": "changes.0", "text": "B입니다(A 대신). 수치 99%"},          # adds a number: rejected
        {"path": "changes.1", "text": "완전히 다른 문장으로 바꿔 버린 아주 긴 설명입니다 D"},  # rewrites too much
    ])
    notes = humanize.polish(claude, item)
    assert claude.calls == 1
    assert item["tldr"].startswith("Responses API를 쓰면") and "올랐고 토큰" in item["tldr"]
    assert item["title"] == "추론 유지로 점수 3배"
    assert item["changes"] == ["A가 아니라 B입니다.", "C가 아니라 D입니다."]
    assert sum("거부" in n for n in notes) == 2


def test_polish_skips_clean_items_without_a_call():
    from backend import humanize

    item = {"kind": "모델 출시", "headline": "새 모델", "tldr": "빠르고, 쌉니다.", "changes": [], "tips": []}
    claude = StyleClaude([])
    assert humanize.polish(claude, item) == [] and claude.calls == 0
    assert item["tldr"] == "빠르고 쌉니다."           # the comma rule needs no Claude call


def test_product_launch_kind_is_valid(site):
    item = json.loads((site / "data/news/claude-sonnet-5-5.json").read_text())
    item.update(id="claude-duet-test", kind="제품·기능 출시", title="Claude Duet", models=[], charts=[])
    store.write_news(item)
    store.add_to_manifest(item["id"])
    ok, out = store.validate()
    assert ok, out


class LinkClaude:
    def __init__(self, out):
        self.out, self.calls = out, 0

    def json_call(self, **kw):
        self.calls += 1
        assert "AI 활용 기술 목록" in kw["user"] and kw["model"] == config.TRIAGE_MODEL
        return self.out


def test_new_tip_is_linked_to_techniques_and_new_names_are_queued(site):
    from backend import techlinks

    item = {"id": "openai-prompting-fundamentals", "company": "google", "kind": "활용 팁", "title": "t",
            "headline": "h", "tldr": "x", "changes": [], "tips": []}
    claude = LinkClaude({"links": [{"id": "compaction", "reason": "r"}, {"id": "no-such-tech", "reason": "r"},
                                   {"id": "tool-use", "reason": "r"}],
                         "candidates": [{"name": "목표 고정 실행", "en": "Goal mode", "oneLiner": "o"},
                                        {"name": "컴팩션", "en": "Compaction", "oneLiner": "이미 있음"}]})
    notes = techlinks.link_item(claude, item, date(2026, 10, 22))
    tech = {t["id"]: t for t in json.loads((site / "data/tech.json").read_text())["items"]}
    assert "google" in tech["compaction"]["companies"]                 # a radar item learns the company
    assert item["id"] in tech["tool-use"]["news"]
    queue = json.loads((site / "backend/state/tech-candidates.json").read_text())
    assert [q["name"] for q in queue] == ["목표 고정 실행"]               # known names are not queued
    assert any("새 기술 후보" in n for n in notes)
    ok, out = store.validate()
    assert ok, out
    # same item again: nothing new is linked or queued twice
    techlinks.link_item(claude, item, date(2026, 10, 22))
    queue = json.loads((site / "backend/state/tech-candidates.json").read_text())
    assert len(queue) == 1 and queue[0]["news"] == [item["id"]]


# ---- source link check ----
class _Resp:
    def __init__(self, url, code, text=""):
        self.url, self.status_code, self.text = url, code, text


class LinkSession:
    def __init__(self, table):
        self.table, self.calls = table, []

    def get(self, url, **kw):
        self.calls.append(url)
        code, final, text = self.table[url]
        return _Resp(final or url, code, text)


def test_link_check_classifies_and_uses_reader_for_blocked_sites():
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_links", REPO / "scripts" / "check_links.py")
    cl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cl)
    r = cl.READER
    table = {
        "https://a.com/ok/": (200, "https://www.a.com/ok", ""),           # only www/slash differ
        "https://a.com/old": (200, "https://a.com/new-place", ""),
        "https://a.com/gone": (404, None, ""),
        r + "https://a.com/gone": (200, None, "Warning: Target URL returned error 404: Not Found"),
        "https://help.example.com/a/1": (404, None, ""),                   # 404 only for CI requests
        r + "https://help.example.com/a/1": (200, None, "Title: Help\n\nbody"),
        "https://openai.com/index/x": (403, None, ""),
        r + "https://openai.com/index/x": (200, None, "Title: X\n\nbody"),
        "https://openai.com/index/dead": (403, None, ""),
        r + "https://openai.com/index/dead": (200, None, "Warning: Target URL returned error 404: Not Found"),
    }
    out = cl.run(["https://a.com/ok/", "https://a.com/old", "https://a.com/gone", "https://help.example.com/a/1",
                  "https://openai.com/index/x", "https://openai.com/index/dead"],
                 session=LinkSession(table), workers=2, pause=0)
    assert out["https://help.example.com/a/1"]["status"] == "ok-reader"
    assert out["https://a.com/ok/"]["status"] == "ok"
    assert out["https://a.com/old"]["status"] == "moved" and out["https://a.com/old"]["final"].endswith("new-place")
    assert out["https://a.com/old"]["sameArticle"] is False           # slug "old" is gone → a person checks
    kept = next(iter(cl.KEEP))
    kept_out = cl.run([kept], session=LinkSession({kept: (200, kept.rstrip("/") + "/2026-01-01/x", "")}),
                      workers=1, pause=0)
    assert kept_out[kept]["status"] == "ok"
    soft = next(iter(cl.SOFT_404))
    soft_out = cl.run([soft], session=LinkSession({soft: (404, None, ""), r + soft: (404, None, "")}), workers=1, pause=0)
    assert soft_out[soft]["status"] == "unknown"                       # warning, not a failure                                 # deliberate redirect is not reported
    assert out["https://a.com/gone"]["status"] == "broken"
    assert out["https://openai.com/index/x"]["status"] == "ok-reader"
    assert out["https://openai.com/index/dead"]["status"] == "broken"
    used = cl.collect()
    assert all(u.startswith("http") for u in used) and any("data/tech.json" in w for ws in used.values() for w in ws)


def test_link_check_applies_only_same_article_redirects(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_links", REPO / "scripts" / "check_links.py")
    cl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cl)
    assert cl.same_article("https://anthropic.com/engineering/claude-think-tool",
                           "https://www.anthropic.com/research/claude-think-tool")
    assert not cl.same_article("https://blog.example.com/posts/launch-notes", "https://blog.example.com/")
    data = tmp_path / "data"
    (data / "news").mkdir(parents=True)
    item = {"id": "x", "sources": [{"url": "https://anthropic.com/engineering/claude-think-tool"},
                                    {"url": "https://blog.example.com/posts/launch-notes"}]}
    (data / "news" / "x.json").write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"results": {
        "https://anthropic.com/engineering/claude-think-tool": {
            "status": "moved", "final": "https://www.anthropic.com/research/claude-think-tool", "sameArticle": True},
        "https://blog.example.com/posts/launch-notes": {
            "status": "moved", "final": "https://blog.example.com/", "sameArticle": False},
    }}), encoding="utf-8")
    monkeypatch.setattr(cl, "DATA", data)
    monkeypatch.setattr(cl, "ROOT", tmp_path)
    assert cl.apply_moved(str(report)) == 1
    urls = [s["url"] for s in json.loads((data / "news" / "x.json").read_text(encoding="utf-8"))["sources"]]
    assert urls == ["https://www.anthropic.com/research/claude-think-tool", "https://blog.example.com/posts/launch-notes"]


def test_moved_claude_blog_post_is_still_recognized():
    from backend import detect

    assert detect.slug_key("https://claude.com/blog/what-a-task-costs-on-opus-5-5") == \
        detect.slug_key("https://claude.dev/blog/what-a-task-costs-on-opus-5-5/")
    assert detect.slug_key("https://claude.com/resources/articles/web-search-api") == \
        detect.slug_key("https://claude.com/blog/web-search-api")
