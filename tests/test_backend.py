"""Offline tests for the news pipeline. Run: python -m pytest tests -q"""
from __future__ import annotations

import json
import shutil
from datetime import date
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
    monkeypatch.setattr(config, "VALIDATOR", tmp_path / "scripts" / "validate_data.py")
    monkeypatch.setattr(pipeline, "today_kst", lambda: date(2026, 10, 2))
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
    assert manifest["news"][0] == "gpt-7-nova" and manifest["lastChecked"] == "2026-10-02"
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
