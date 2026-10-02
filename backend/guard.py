"""Check the model's draft against the source text. Anything that cannot be found in the
original page (chart values, key numbers, model IDs, prices) is removed, never guessed."""
from __future__ import annotations

import re

NUM_RE = re.compile(
    r"(?<![0-9A-Za-z.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(k|m|b|thousand|million|billion|만|억)?(?![0-9A-Za-z])", re.I)
MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9, "만": 1e4, "억": 1e8}


def numbers_in(text: str) -> set[float]:
    """All numbers in a text, also expanded by their suffix (64K -> 64000, 100만 -> 1000000)."""
    out: set[float] = set()
    for m in NUM_RE.finditer(text):
        base = float((m.group(1) + (m.group(2) or "")).replace(",", ""))
        out.add(round(base, 6))
        suffix = (m.group(3) or "").lower()
        if suffix in MULT:
            out.add(round(base * MULT[suffix], 6))
    return out


def _has(value: float, pool: set[float]) -> bool:
    return any(abs(value - p) < 1e-6 for p in pool)


def check_item(item: dict, source_text: str, link_text: str = "") -> list[str]:
    """Mutate item in place and return a list of human-readable notes about what was removed."""
    notes: list[str] = []
    pool = numbers_in(source_text)
    haystack = source_text + "\n" + link_text

    # Charts: every row value must appear in the page; a chart needs 2+ rows incl. the highlighted one.
    kept = []
    for chart in item.get("charts") or []:
        rows = []
        for row in chart.get("rows", []):
            if isinstance(row.get("value"), (int, float)) and _has(float(row["value"]), pool):
                rows.append(row)
            else:
                notes.append(f"그래프 '{chart.get('title')}'의 '{row.get('label')}'={row.get('value')} 원문에서 확인 안 됨 → 제외")
        if len(rows) >= 2 and any(r.get("highlight") for r in rows):
            chart["rows"] = rows
            kept.append(chart)
        elif chart.get("rows"):
            notes.append(f"그래프 '{chart.get('title')}' 제외(확인된 행 부족)")
    if item.get("charts") and not kept:
        item["chartNote"] = item.get("chartNote") or "원문에서 텍스트로 확인할 수 있는 비교 수치가 부족해 그래프를 넣지 않았습니다."
        item.pop("chartSource", None)
    item["charts"] = kept
    if not kept:
        item.pop("chartSource", None)
        if not item.get("chartNote"):
            item["chartNote"] = "원문에 텍스트로 공개된 비교 수치가 없어 그래프를 넣지 않았습니다."

    # Key numbers: at least one number in the value must be in the page (labels like "1M" are expanded).
    nums = []
    for n in item.get("numbers") or []:
        values = numbers_in(str(n.get("value", "")))
        if not values or any(_has(v, pool) for v in values):
            nums.append(n)
        else:
            notes.append(f"핵심 수치 '{n.get('label')}: {n.get('value')}' 원문에서 확인 안 됨 → 제외")
    item["numbers"] = nums

    # Models: API IDs must appear verbatim (text or link URLs); prices must appear as numbers.
    for m in item.get("models") or []:
        api = m.get("apiId")
        if api and api not in haystack:
            notes.append(f"모델 ID '{api}' 원문에서 확인 안 됨 → 미공개로 표시")
            m["apiId"] = None
        for key in ("input", "output", "cached"):
            val = m.get(key)
            if not val:
                m[key] = None
                continue
            values = numbers_in(val)
            if values and not any(_has(v, pool) for v in values):
                notes.append(f"'{m.get('name')}' {key} 가격 '{val}' 원문에서 확인 안 됨 → 제외")
                m[key] = None
    return notes
