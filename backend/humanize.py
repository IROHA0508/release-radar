"""Korean style rules from im-not-ai (humanize-korean) for the automatic writers.

- style_rules(): the rule text added to writing prompts (site scope + the vendored quick-rules.md).
- fix_item(): deterministic fixes that cannot change meaning (comma after a connective ending, C-11).
- polish(): when other AI-tell signals remain in a new news item, ask Claude once more to rewrite only the
  flagged prose fields. Every rewritten field must keep the same numbers, Latin words (model names, IDs)
  and URLs, and change at most half of its text; otherwise the original field is kept.
"""
from __future__ import annotations

import difflib
import importlib.util
import json
import logging
import re
from collections import Counter
from functools import lru_cache

from . import config

log = logging.getLogger(__name__)

SKILL_DIR = config.ROOT / ".claude" / "skills" / "humanize-korean-site"
QUICK_RULES = SKILL_DIR / "references" / "quick-rules.md"

SITE_SCOPE = """\
- 이 사이트 글은 리포트 장르다. 목록 항목(changes, tips, cautions …)은 목록 그대로 두고 문장만 다듬는다.
- 존댓말(합쇼체 "~합니다/~입니다")을 유지한다.
- 수치·날짜·가격·모델명·API ID·제품명·URL·원문 인용·프롬프트 예시는 한 글자도 바꾸지 않는다.
- 특히 피할 것: 연결어미(-고/-며/-지만/-면서/-아서/-어서) 바로 뒤 쉼표(C-11), 제목의 "X: Y" 콜론 부제(C-10),
  한 글에 "A가 아니라 B" 대구 2번 이상(C-8), "핵심은/중요한 것은 ~" 분열문(D-8), "~로 이어집니다" 결산(D-9),
  "~할 수 있습니다" 4번 이상 반복(A-10, 단정으로 바꾸지 말고 표현만 분산).
"""

POLISH_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["fields"],
    "properties": {"fields": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["path", "text"],
        "properties": {"path": {"type": "string"}, "text": {"type": "string"}}}}},
}


@lru_cache(maxsize=1)
def checker():
    """scripts/style_check.py (the same checks the repo uses by hand)."""
    spec = importlib.util.spec_from_file_location("style_check", config.ROOT / "scripts" / "style_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@lru_cache(maxsize=1)
def style_rules() -> str:
    rules = QUICK_RULES.read_text(encoding="utf-8") if QUICK_RULES.exists() else ""
    return ("이 사이트의 글은 im-not-ai(humanize-korean)의 'AI 티' 규칙을 따른다.\n" + SITE_SCOPE
            + ("\n## im-not-ai quick-rules (원문)\n" + rules if rules else ""))


# ---------- the prose fields of a news item ----------
def prose_fields(item: dict) -> dict[str, str]:
    out = {"headline": item.get("headline", ""), "tldr": item.get("tldr", "")}
    if item.get("kind") == "활용 팁":
        out["title"] = item.get("title", "")
    for key in ("changes", "availability", "cautions"):
        for i, s in enumerate(item.get(key) or []):
            out[f"{key}.{i}"] = s
    for i, t in enumerate(item.get("tips") or []):
        out[f"tips.{i}.title"] = t.get("title", "")
        out[f"tips.{i}.body"] = t.get("body", "")
    return {k: v for k, v in out.items() if v}


def _set(item: dict, path: str, text: str) -> None:
    parts = path.split(".")
    if len(parts) == 1:
        item[parts[0]] = text
    elif len(parts) == 2:
        item[parts[0]][int(parts[1])] = text
    else:
        item[parts[0]][int(parts[1])][parts[2]] = text


def fix_item(item: dict) -> int:
    """Remove commas after connective endings in every prose field. Returns how many fields changed."""
    fix = checker().fix_c11
    n = 0
    for path, text in prose_fields(item).items():
        new = fix(text)
        if new != text:
            _set(item, path, new)
            n += 1
    return n


# ---------- gates for a rewritten field ----------
_TOKEN = re.compile(r"https?://\S+|\$?\d[\d,.]*(?:%|×|x)?|[A-Za-z][A-Za-z0-9._/+-]*")


def anchors(text: str) -> Counter:
    """Numbers, Latin words (model names, API IDs, product names) and URLs: must survive a rewrite."""
    return Counter(t.rstrip(".,") for t in _TOKEN.findall(text))


def change_rate(a: str, b: str) -> float:
    return 1 - difflib.SequenceMatcher(None, a, b).ratio()


def accept(old: str, new: str) -> tuple[bool, str]:
    if not new.strip():
        return False, "빈 문장"
    if anchors(old) != anchors(new):
        return False, "수치·영문 표기가 달라짐"
    if change_rate(old, new) > 0.5:
        return False, "50% 넘게 바뀜"
    return True, ""


def signals(item: dict) -> dict[str, list[str]]:
    sc = checker()
    hits = sc.check_text("\n".join(prose_fields(item).values()))
    if item.get("kind") == "활용 팁":
        hits.update(sc.check_title(item.get("title", "")))
    hits.pop("C-11", None)            # fixed without Claude
    return hits


def polish(claude, item: dict) -> list[str]:
    """Rewrite flagged fields once. Returns notes for the run report (what changed or was rejected)."""
    fix_item(item)
    hits = signals(item)
    if not hits:
        return []
    sc = checker()
    fields = prose_fields(item)
    flagged = {p: t for p, t in fields.items()
               if sc.check_text(t) or (p == "title" and sc.check_title(t))}
    # Repetition signals (C-8, A-10 …) are counted over the whole item, so offer every field then.
    if not flagged or any(k in hits for k in ("C-8", "A-10", "A-24", "I-3", "H-4", "J-3", "F-5")):
        flagged = fields
    user = ("아래는 사이트 소식 하나의 문장들이다. 점검에서 걸린 신호: "
            + ", ".join(f"{k}({sc.describe(k)}) {len(v)}건" for k, v in hits.items())
            + "\n걸린 문장만 문체 규칙대로 고쳐 path별로 돌려줘라. 고칠 필요가 없는 문장은 그대로 돌려준다. "
              "수치·모델명·ID·URL·영문 표기는 글자 그대로 둔다. 내용을 더하거나 빼지 않는다.\n\n"
            + json.dumps([{"path": p, "text": t} for p, t in flagged.items()], ensure_ascii=False, indent=1))
    try:
        out = claude.json_call(model=config.SUMMARY_MODEL, system=style_rules(), user=user,
                               schema=POLISH_SCHEMA, max_tokens=8000)
    except Exception as exc:  # noqa: BLE001 - the unpolished item is still fine to publish
        log.warning("polish failed: %s", exc)
        return [f"문체 다듬기 실패: {type(exc).__name__}"]
    notes = []
    for f in out.get("fields") or []:
        path, new = f.get("path"), sc.fix_c11(f.get("text") or "")
        if path not in flagged or new == flagged[path]:
            continue
        ok, why = accept(flagged[path], new)
        if ok:
            _set(item, path, new)
            notes.append(f"문체 수정: {path}")
        else:
            notes.append(f"문체 수정 거부({why}): {path}")
    return notes
