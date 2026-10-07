"""Claude calls: (1) triage feed entries, (2) write one news item in the site's JSON format.

Two backends: the Claude Code CLI with a Pro/Max subscription token (no API billing), or the
Claude API with an API key (pay-as-you-go)."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date

from . import config
from .extract import Article
from .feeds import Entry

log = logging.getLogger(__name__)

STR = {"type": "string"}
STR_LIST = {"type": "array", "items": STR}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


CHART = _obj({
    "title": STR, "desc": STR,
    "type": {"type": "string", "enum": ["bar", "dot"]},
    "unit": {"type": "string", "enum": ["%", "$", "×", "Elo", ""]},
    "lowerIsBetter": {"type": "boolean"},
    "source": STR, "note": STR,
    "rows": {"type": "array", "items": _obj({"label": STR, "value": {"type": "number"}, "highlight": {"type": "boolean"}})},
})

ITEM = _obj({
    "id": STR,
    "kind": {"type": "string", "enum": ["모델 출시", "모델 업데이트", "활용 팁"]},
    "title": STR, "headline": STR, "tldr": STR,
    "models": {"type": "array", "items": _obj({"name": STR, "apiId": STR, "input": STR, "output": STR, "cached": STR})},
    "numbers": {"type": "array", "items": _obj({"label": STR, "value": STR, "note": STR})},
    "chartSource": STR, "charts": {"type": "array", "items": CHART}, "chartNote": STR,
    "changes": STR_LIST, "availability": STR_LIST,
    "tips": {"type": "array", "items": _obj({"title": STR, "body": STR})},
    "prompts": {"type": "array", "items": _obj({"title": STR, "when": STR,
                                                 "type": {"type": "string", "enum": ["prompt", "code"]}, "text": STR})},
    "cautions": STR_LIST,
    "sources": {"type": "array", "items": _obj({"title": STR, "url": STR})},
})

RESULT = _obj({
    "decision": {"type": "string", "enum": ["new", "update", "skip"]},
    "reason": STR,
    "updateId": STR,
    "item": ITEM,
    "update": _obj({"changes": STR_LIST, "availability": STR_LIST,
                    "sources": {"type": "array", "items": _obj({"title": STR, "url": STR})}}),
})

TRIAGE = _obj({"results": {"type": "array", "items": _obj({
    "index": {"type": "integer"},
    "relevant": {"type": "boolean"},
    "reason": STR,
})}})

RULES = """\
너는 '릴리스 레이더' 사이트의 편집자다. 이 사이트는 OpenAI(ChatGPT/GPT), Anthropic(Claude), Google(Gemini)의 공식 발표를
뉴스별로 한국어로 요약하고, 성능 그래프, 모델을 더 잘 쓰는 법, 추천 프롬프트를 정리한다.

판단 기준
- 포함(decision "new"): 새 모델 출시·발표, 모델 버전 업데이트, 가격이나 사용 가능 범위의 큰 변경, 그리고 공식 활용 팁
  (특정 모델이나 ChatGPT·Codex·Claude·Claude Code·Gemini 앱·Gemini API 같은 공식 도구를 더 잘 쓰는 법,
  프롬프트 가이드, 모범 사례처럼 독자가 바로 따라 할 수 있는 실전 조언이 중심인 글).
- 제외(decision "skip"): 기업 파트너십, 고객 사례, 정책·규제 글, 모델 출시와 무관한 연구·안전 보고서, 행사 홍보,
  모델과 무관한 제품·영업 공지(정부·기업 요금제 출시, 통합 발표 등), 실전 조언이 거의 없는 기능 소개.
- kind는 셋 중 하나: "모델 출시"(새 모델 출시·발표), "모델 업데이트"(기존 모델의 기능·가격·가용성 변경, 지원 종료),
  "활용 팁"(위의 공식 활용 팁).
- 이미 사이트에 있는 모델의 후속 소식(가용성 확대, 새 모드 등)은 decision "update", updateId에 기존 id를 쓰고
  update 필드에 덧붙일 changes/availability/sources만 쓴다. 이 경우 item은 빈 값으로 채워도 된다.

작성 원칙
- 반드시 아래 원문에 있는 내용만 근거로 쓴다. 원문에 없는 수치·가격·모델 ID는 지어내지 말고 빈 문자열로 둔다.
- 모델 ID(apiId)는 원문 본문이나 링크 URL에 글자 그대로 있는 것만 쓴다.
- 성능 그래프(charts)는 원문의 표(TABLES)나 본문 문장에 숫자로 직접 나온 비교 수치만 쓴다. 벤치마크마다 차트 하나,
  3~8개. 이 소식의 모델 행에 highlight true. Elo처럼 0이 의미 없는 점수는 type "dot", 낮을수록 좋은 지표는
  lowerIsBetter true. 수치가 이미지로만 있어 텍스트로 확인할 수 없으면 charts는 빈 배열, chartNote에 그 사실을 쓴다.
  charts를 쓰면 chartSource에 수치 출처를 쓴다. 각 수치가 무엇과 비교한 값인지(이전 모델 대비인지, 측정 기관) 원문대로 쓴다.
- 이 단계 뒤에 프로그램이 모든 그래프 값·핵심 수치·모델 ID·가격을 원문과 대조해, 원문에 없는 값은 지운다.
- 문체: 자연스럽고 간결한 한국어 존댓말 서술. 과장 금지. title은 모델 출시·업데이트면 공식 모델명 그대로,
  활용 팁이면 핵심을 담은 짧은 한국어 제목(예: "API 설정 두 개로 점수 3배: 추론 유지와 컴팩션").
- 활용 팁에서 changes는 원문의 핵심 내용, tips는 바로 따라 할 행동, prompts는 원문 예시를 옮긴 것 위주로 쓴다.
  성능 비교 수치가 없으면 charts는 빈 배열로 둔다.
- numbers는 핵심 수치 3~4개, changes 3~6개, tips 2~4개, prompts 2개(바로 붙여 쓸 수 있는 한국어, 바꿀 부분은 [대괄호],
  API 예시는 type "code"), cautions 1~3개, sources는 원문 URL을 첫 번째로.
- id는 소문자 영문·숫자·하이픈(예: claude-haiku-5-5). guide, prices는 쓰지 않는다.
- 빈 값은 빈 문자열/빈 배열로 둔다(null 금지).
"""


class Claude:
    def __init__(self, api_key: str | None = None):
        import anthropic  # imported lazily so detection-only runs don't need the key

        self.client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"], max_retries=3)
        self.bad_request = anthropic.BadRequestError

    def json_call(self, *, model: str, system: str, user: str, schema: dict, max_tokens: int) -> dict:
        """Ask for schema-shaped JSON. Falls back to plain JSON text if structured output is rejected."""
        try:
            msg = self.client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except self.bad_request as exc:  # model or schema not supported for structured output
            log.warning("structured output rejected (%s); retrying with plain JSON", exc)
            msg = self.client.messages.create(
                model=model, max_tokens=max_tokens, system=system + "\n\n출력은 JSON 객체 하나만, 다른 글 없이.",
                messages=[{"role": "user", "content": user + "\n\nJSON 스키마:\n" + json.dumps(schema, ensure_ascii=False)}],
            )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return parse_json(text)


class ClaudeCodeCLI:
    """Run the Claude Code CLI headless with a subscription token (CLAUDE_CODE_OAUTH_TOKEN).

    Usage counts against the Claude Pro/Max plan's limits instead of API billing. The API key is
    removed from the child environment on purpose: if it were set, Claude Code would bill the API.
    """

    def __init__(self, binary: str = "claude"):
        import shutil

        self.binary = shutil.which(binary) or binary
        self.env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        # A token copied from a terminal often picks up line breaks, spaces or box-drawing borders
        # (│). The real token only has letters, digits, "-" and "_", so drop everything else.
        if self.env.get("CLAUDE_CODE_OAUTH_TOKEN"):
            self.env["CLAUDE_CODE_OAUTH_TOKEN"] = re.sub(r"[^A-Za-z0-9_-]", "", self.env["CLAUDE_CODE_OAUTH_TOKEN"])

    def json_call(self, *, model: str, system: str, user: str, schema: dict, max_tokens: int) -> dict:
        import subprocess

        prompt = (f"# 작업 지시\n{system}\n\n# 입력\n{user}\n\n"
                  "결과는 주어진 JSON 스키마에 맞는 JSON 객체 하나로만 답해라.")
        cmd = [self.binary, "-p", "--output-format", "json", "--json-schema", json.dumps(schema, ensure_ascii=False),
               "--model", model, "--tools", "", "--no-session-persistence",
               "--system-prompt", "너는 JSON만 출력하는 편집 도우미다. 도구를 쓰지 않는다."]
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, env=self.env, timeout=900)
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI 실패({proc.returncode}): {(proc.stderr or proc.stdout)[-800:]}")
        envelope = json.loads(proc.stdout)
        if envelope.get("is_error"):
            raise RuntimeError(f"claude CLI 오류: {str(envelope.get('result'))[:800]}")
        if isinstance(envelope.get("structured_output"), dict):
            return envelope["structured_output"]
        return parse_json(envelope.get("result") or "")


class AuthError(RuntimeError):
    """The credential was rejected (bad, expired or revoked token / key)."""


def is_auth_error(exc: Exception) -> bool:
    text = str(exc)
    return isinstance(exc, AuthError) or "401" in text or "authenticate" in text.lower() or "authentication_error" in text


def make_llm():
    """Pick the model backend. RR_LLM=cli|api forces one; otherwise a subscription token wins over an
    API key so a Pro/Max plan is used before any pay-as-you-go API billing."""
    choice = os.environ.get("RR_LLM", "").lower()
    if choice == "cli" or (choice != "api" and os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")):
        return ClaudeCodeCLI()
    return Claude()


def llm_available() -> str | None:
    """Return which backend can run ("cli" or "api"), or None when neither credential is set."""
    choice = os.environ.get("RR_LLM", "").lower()
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") and choice != "api":
        return "cli"
    if os.environ.get("ANTHROPIC_API_KEY") and choice != "cli":
        return "api"
    return None


def parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def triage(claude, entries: list[Entry], site_lines: list[str]) -> dict[int, tuple[bool, str]]:
    listing = "\n".join(
        f"[{i}] {e.company} | {e.published or '날짜 미상'} | {e.title} | {e.summary[:200]} | {e.url}"
        for i, e in enumerate(entries))
    user = (f"사이트에 이미 있는 소식:\n" + "\n".join(site_lines[:60]) +
            f"\n\n새로 올라온 글 목록:\n{listing}\n\n각 글이 사이트에 실을 글(새 모델, 모델 업데이트, 가격·사용 범위 변경, "
            "공식 활용 팁·프롬프트 가이드·모범 사례, 또는 이미 있는 모델의 의미 있는 후속 소식)인지 위 판단 기준대로 "
            "판단해 results에 index별로 답해라.")
    out = claude.json_call(model=config.TRIAGE_MODEL, system=RULES, user=user, schema=TRIAGE, max_tokens=2000)
    return {r["index"]: (bool(r["relevant"]), r.get("reason", "")) for r in out.get("results", [])}


def write_item(claude, entry: Entry, article: Article, site_lines: list[str], today: date,
               update_of: dict | None = None) -> dict:
    """Draft one news item. With update_of (an existing item), only an update to that item is asked for:
    the article is another post about news the site already has."""
    schema_doc = config.SCHEMA_DOC.read_text(encoding="utf-8") if config.SCHEMA_DOC.exists() else ""
    example = config.STYLE_EXAMPLE.read_text(encoding="utf-8") if config.STYLE_EXAMPLE.exists() else ""
    tip_example = config.TIP_EXAMPLE.read_text(encoding="utf-8") if config.TIP_EXAMPLE.exists() else ""
    tables = "\n\n".join(article.tables) or "(텍스트로 된 표 없음)"
    links = "\n".join(l for l in article.links if re.search(r"model|api|docs|pricing|aistudio|platform", l, re.I))[:4000]
    system = (RULES + "\n\n# 데이터 형식\n" + schema_doc + "\n\n# 문체·구성 예시: 모델 출시 (다른 소식)\n" + example
              + "\n\n# 문체·구성 예시: 활용 팁 (다른 소식)\n" + tip_example)
    user = (
        f"오늘(Asia/Seoul): {today.isoformat()}\n회사: {entry.company}\n원문 제목: {article.title or entry.title}\n"
        f"원문 URL: {entry.url}\n발표일: {(article.published or entry.published or today).isoformat()}\n"
        f"관련 있어 보이는 기존 소식 id: {entry.extra.get('relatedId') or '없음'}\n\n"
        f"사이트에 이미 있는 소식:\n" + "\n".join(site_lines[:80]) +
        f"\n\n# 원문 본문\n{article.text}\n\n# TABLES (원문 표를 셀 그대로 옮김)\n{tables}\n\n# 원문 링크 일부\n{links}\n\n"
        "위 원문으로 decision과 item(또는 update)을 작성해라."
    )
    if update_of:
        existing = {k: update_of.get(k) for k in ("id", "title", "tldr", "numbers", "changes", "availability")}
        user += (
            "\n\n# 중요: 이미 사이트에 있는 소식\n"
            f"이 원문은 이미 사이트에 있는 소식 '{update_of['id']}'와 같은 모델·같은 발표를 다룬 다른 글이다. "
            "새 소식을 만들지 말고 decision은 반드시 \"update\", updateId는 "
            f"\"{update_of['id']}\"로 써라. update.changes와 update.availability에는 아래 기존 내용에 없는 "
            "새 사실만 짧게(각 0~3개) 쓰고, update.sources에는 이 원문 URL을 넣어라. item은 빈 값으로 둔다.\n"
            + json.dumps(existing, ensure_ascii=False, indent=1)
        )
    return claude.json_call(model=config.SUMMARY_MODEL, system=system, user=user, schema=RESULT, max_tokens=16000)
