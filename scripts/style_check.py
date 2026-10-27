#!/usr/bin/env python3
"""사이트 글에서 'AI 티' 문체 신호를 찾는다. (im-not-ai의 humanize-korean 규칙 중 이 사이트 장르에 맞는 것만)

규칙 원본: .claude/skills/humanize-korean-site/references/quick-rules.md (MIT, epoko77-ai/im-not-ai)
규칙 ID(C-11, D-8 …)는 원본 분류 체계를 그대로 따른다. 원본이 '기각'한 신호(A-2 '~를 통해', I-1 '~것이다',
H-1 문두 접속사, J-2 따옴표, D-4 hype 어휘)는 일부러 보지 않는다.

사용:
  python3 scripts/style_check.py              # data/ 전체 요약
  python3 scripts/style_check.py --spans      # 걸린 문장까지 출력
  python3 scripts/style_check.py --json out.json
판정은 경고용이다(실패 코드 없음). 자동 업데이트는 backend/humanize.py가 같은 함수를 쓴다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# C-11 연결어미 직후 쉼표. '고'로 끝나는 명사(참고·최고 …) 뒤 쉼표는 연결어미가 아니므로 제외한다.
GO_NOUNS = ("참고", "최고", "광고", "경고", "보고", "재고", "창고", "사고", "신고", "원고", "고고", "제고", "공고",
            "등고", "잔고", "상고", "고고학", "마고", "투고", "기고", "회고", "숙고", "중고", "선고", "로고")
_C11 = re.compile(r"([가-힣]*?)(고|며|지만|면서|아서|어서)\s*,")


def c11_spans(text: str) -> list[str]:
    out = []
    for m in _C11.finditer(text):
        word = m.group(1) + m.group(2)
        if m.group(2) == "고" and any(word.endswith(n) for n in GO_NOUNS):
            continue
        out.append(m.group(0))
    return out


def fix_c11(text: str) -> str:
    """연결어미 뒤 쉼표만 지운다(명사 '참고,' 등은 그대로). 다른 글자는 바꾸지 않는다."""
    def repl(m: re.Match) -> str:
        word = m.group(1) + m.group(2)
        if m.group(2) == "고" and any(word.endswith(n) for n in GO_NOUNS):
            return m.group(0)
        return word
    return _C11.sub(repl, text)


# (ID, 심각도, 설명, 정규식, 문서당 몇 번부터 신호로 볼지)
PATTERNS = [
    ("A-3", "S1", "'~에 있어(서)' 번역투", r"에\s?있어(?:서)?\b", 1),
    ("A-7", "S1", "'가지고 있다' 직역", r"가지고\s?있", 1),
    ("A-8", "S1", "이중 피동 '~되어지다'", r"되어지|어지게\s?되", 1),
    ("A-9", "S2", "'~에 의해' 피동", r"에\s?의해", 1),
    ("A-21", "S2", "'단순한 X를 넘어'", r"단순(?:한|히)\s?[^.]{0,20}넘어", 1),
    ("A-22", "S2", "'~은 명확하다/분명하다' 평가 술어", r"(?:명확|분명)(?:하다|합니다)", 1),
    ("A-24", "S2", "'더 이상' 반복", r"더\s?이상", 2),
    ("C-8", "S1", "'A가 아니라 B' 대구 반복", r"(?:가|이)\s?아니라|것이\s?아니라|이기보다", 2),
    ("D-1", "S1", "결산 접속어", r"결론적으로|요약하면|정리하자면|그러므로", 1),
    ("D-2", "S1", "의의 과장", r"시사하는\s?바|주목할\s?만하|매우\s?중요", 1),
    ("D-3", "S1", "열거 도입구", r"(?:두|세|네|다섯)\s?가지로\s?나눌|다음과\s?같(?:은|습니다|다)", 1),
    ("D-6", "S2", "결말 공식 '~할 때입니다'", r"할\s?때(?:입니다|이다)|시점(?:입니다|이다)", 1),
    ("D-8", "S2", "분열문 '핵심은/중요한 것은'", r"(?:핵심|관건|중요한\s?것|필요한\s?것|문제)은\s", 1),
    ("D-9", "S2", "'~로 이어진다' 결산", r"(?:로|으로)\s?이어(?:진다|집니다)|직결", 1),
    ("D-10", "S2", "도치 결산 '~하는 이유다'", r"이유(?:다|입니다)[.\s]", 1),
    ("D-12", "S2", "문패 문장 '과제도 남아 있다'", r"과제도\s?남|한계도\s?분명|아쉬운\s?점도", 1),
    ("D-14", "S2", "사전 은유", r"청사진|신호탄|잠식|적신호|경고등|뿌리내|움켜쥐|짓누르", 1),
    ("I-2", "S2", "형식명사 강조 '주목할 점은'", r"주목할\s?점은|점에\s?있다", 1),
    ("I-3", "S2", "'~다는 것이다/뜻이다' 결말", r"다는\s?(?:것이다|것입니다|뜻이다|뜻입니다)", 2),
    ("H-4", "S2", "'즉' 남발", r"(?:^|[\s.])즉[,\s]", 3),
    ("J-3", "S2", "대시(—) 부가 설명", r"—", 2),
    ("F-5", "S2", "'~적 N' 추상 체인", r"[가-힣]{1,4}적\s(?!으로)[가-힣]", 4),
    ("A-10", "S2", "'~할 수 있습니다' 반복", r"수\s?있(?:습니다|다)", 4),
]
_COMPILED = [(i, s, d, re.compile(p), n) for i, s, d, p, n in PATTERNS]


def check_title(title: str) -> dict[str, list[str]]:
    """C-10: 제목의 'X: Y' 콜론 부제."""
    return {"C-10": [title]} if re.search(r"[^\d]:\s", title or "") else {}


def check_text(text: str) -> dict[str, list[str]]:
    """문서 하나(소식 하나, 기술 하나)의 글을 받아 걸린 규칙과 일치 구간을 돌려준다."""
    hits: dict[str, list[str]] = {}
    c11 = c11_spans(text)
    if c11:
        hits["C-11"] = c11
    for pid, _sev, _desc, rx, at_least in _COMPILED:
        found = [m.group(0) for m in rx.finditer(text)]
        if len(found) >= at_least:
            hits[pid] = found
    return hits


def describe(pid: str) -> str:
    if pid == "C-11":
        return "연결어미(-고/-며/-지만/-면서/-아서/-어서) 뒤 쉼표"
    if pid == "C-10":
        return "제목의 'X: Y' 콜론 부제"
    return next(d for i, _s, d, _p, _n in PATTERNS if i == pid)


# ---------- 사이트 데이터에서 글 꺼내기 ----------
NEWS_FIELDS = ("title", "headline", "tldr", "changes", "availability", "cautions")


def _flat(v) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [x for e in v for x in _flat(e)]
    if isinstance(v, dict):
        return [x for e in v.values() for x in _flat(e)]
    return []


def news_text(d: dict) -> list[str]:
    parts = [p for f in NEWS_FIELDS for p in _flat(d.get(f))]
    parts += [x for t in d.get("tips", []) for x in (t.get("title", ""), t.get("body", ""))]
    parts += [x for p in d.get("prompts", []) if p.get("type") != "code" for x in (p.get("title", ""), p.get("when", ""))]
    parts += [x for n in d.get("numbers", []) for x in (n.get("label", ""), n.get("note", ""))]
    return [p for p in parts if p]


def tech_text(i: dict) -> list[str]:
    parts = [i.get("name", ""), i.get("definition", ""), i.get("why", "")]
    parts += i.get("how", []) + i.get("effects", []) + i.get("limits", [])
    if i.get("example", {}).get("type") != "code":
        parts.append(i.get("example", {}).get("text", ""))
    return [p for p in parts if p]


def guide_docs(g: dict) -> dict[str, list[str]]:
    """가이드는 카드(방법) 하나가 독립된 글이라 카드마다 따로 본다(반복 신호가 탭 전체로 합쳐지지 않게)."""
    docs = {f"guides/common/{i}": [c.get("title", ""), c.get("body", "")] for i, c in enumerate(g.get("common", []))}
    for v in g.get("vendors", []):
        docs[f"guides/{v['company']}/summary"] = [v.get("summary", "")]
        for m in v.get("methods", []):
            docs[f"guides/{v['company']}/{m.get('id')}"] = [m.get("title", ""), m.get("body", "")]
    st = g.get("structure") or {}
    docs["guides/structure"] = [st.get("answer", "")] + st.get("notes", []) + [
        x for r in st.get("rows", []) for x in (r.get("recommended", ""), r.get("inApp", ""), r.get("saveIn", ""))]
    af = g.get("appFeatures") or {}
    docs["guides/appFeatures"] = [af.get("intro", "")] + af.get("notes", []) + [
        x for r in af.get("rows", []) for x in [r.get("what", "")] + [c.get("note", "") for c in r.get("cells", {}).values()]]
    return {k: [p for p in v if p] for k, v in docs.items()}


def site_docs() -> dict[str, list[str]]:
    docs: dict[str, list[str]] = {}
    for f in sorted((DATA / "news").glob("*.json")):
        docs[f"news/{f.stem}"] = news_text(json.loads(f.read_text(encoding="utf-8")))
    tech = DATA / "tech.json"
    if tech.exists():
        for i in json.loads(tech.read_text(encoding="utf-8")).get("items", []):
            docs[f"tech/{i['id']}"] = tech_text(i)
    gl = DATA / "glossary.json"
    if gl.exists():
        for t in json.loads(gl.read_text(encoding="utf-8")).get("terms", []):
            docs[f"glossary/{t['id']}"] = [t.get("short", ""), t.get("body", "")]
    guides = DATA / "guides.json"
    if guides.exists():
        docs.update(guide_docs(json.loads(guides.read_text(encoding="utf-8"))))
    models = DATA / "models.json"
    if models.exists():
        docs.update(models_docs(json.loads(models.read_text(encoding="utf-8"))))
    return docs


def models_docs(m: dict) -> dict[str, list[str]]:
    """모델 추천 탭. 모델 카드와 상황 한 줄이 각각 독립된 글이라 따로 본다."""
    docs = {"models/intro": [m.get("intro", "")] + m.get("notes", [])}
    for x in m.get("models", []):
        docs[f"models/{x.get('apiId')}"] = [x.get("summary", ""), x.get("start", "")]
    for s in m.get("situations", []):
        docs[f"models/situation/{s.get('id')}"] = [s.get("title", "")] + [
            p.get("note", "") or p.get("missing", "") for p in s.get("picks", {}).values()]
    docs["models/levels"] = [c for lv in m.get("levels", []) for c in (lv.get("openai"), lv.get("anthropic"), lv.get("google")) if c]
    for i, p in enumerate(m.get("principles", [])):
        docs[f"models/principle/{i}"] = [p.get("title", ""), p.get("body", "")]
    return {k: [p for p in v if p] for k, v in docs.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spans", action="store_true", help="걸린 구간까지 출력")
    ap.add_argument("--json", help="결과를 JSON 파일로 저장")
    args = ap.parse_args()
    total, per_doc = Counter(), {}
    titles = {f"news/{f.stem}": json.loads(f.read_text(encoding="utf-8")).get("title", "")
              for f in (DATA / "news").glob("*.json")}
    for name, parts in site_docs().items():
        hits = check_text("\n".join(parts))
        hits.update(check_title(titles.get(name, "")))
        if hits:
            per_doc[name] = hits
            for pid, spans in hits.items():
                total[pid] += len(spans)
    print(f"문서 {len(site_docs())}개 중 신호가 있는 문서 {len(per_doc)}개")
    for pid, n in total.most_common():
        print(f"  {pid:5} {n:4}건  {describe(pid)}")
    if args.spans:
        for name, hits in per_doc.items():
            print(f"\n[{name}]")
            for pid, spans in hits.items():
                print(f"  {pid}: {' | '.join(spans[:8])}")
    if args.json:
        Path(args.json).write_text(json.dumps(per_doc, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
