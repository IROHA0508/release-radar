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


MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]


def date_in(iso: str, text: str) -> bool:
    """Is this date (YYYY-MM-DD) written in the text? Accepts 2026-12-01, December 1(, 2026), Dec 1, 1 December,
    2026년 12월 1일, 12월 1일. A day without a year counts, because notices often omit the year."""
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        name = MONTHS[m - 1]
    except (ValueError, IndexError):
        return False
    low = text.lower()
    mon = rf"(?:{name}|{name[:3]}\.?)"
    pats = [rf"{y}-{m:02d}-{d:02d}", rf"{y}/{m:02d}/{d:02d}", rf"{y}\.\s?{m}\.\s?{d}(?!\d)",
            rf"\b{mon}\s+0?{d}(?:st|nd|rd|th)?\b", rf"\b0?{d}(?:st|nd|rd|th)?\s+(?:of\s+)?{mon}\b",
            rf"(?<!\d){m}월\s*{d}일"]
    return any(re.search(p, low) for p in pats)


def unknown_numbers(text: str, pool: set[float]) -> list[str]:
    """Numbers written in text that the page does not have. '100만' passes if the page has 100만, 1M or 1,000,000."""
    missing = []
    for m in NUM_RE.finditer(text or ""):
        base = float((m.group(1) + (m.group(2) or "")).replace(",", ""))
        suffix = (m.group(3) or "").lower()
        full = base * MULT[suffix] if suffix in MULT else base
        if not _has(round(full, 6), pool):
            missing.append(m.group(0).strip())
    return missing


def check_extras(item: dict, pool: set[float]) -> list[str]:
    """fit·figures·usage: a line, figure or usage entry that carries a number the page does not have is dropped.
    Step numbers the site adds itself are not in the data, and code/prompt examples are not checked (like prompts)."""
    notes: list[str] = []
    fit = item.get("fit")
    if fit:
        for key in ("good", "notFor"):
            kept = []
            for line in fit.get(key) or []:
                bad = unknown_numbers(line, pool)
                if bad:
                    notes.append(f"fit.{key} '{line[:30]}…'의 숫자 {bad} 원문에서 확인 안 됨 → 제외")
                else:
                    kept.append(line)
            fit[key] = kept
        for key in ("summary", "start"):
            bad = unknown_numbers(fit.get(key, ""), pool)
            if bad:
                notes.append(f"fit.{key}의 숫자 {bad} 원문에서 확인 안 됨 → 제외")
                fit[key] = ""
        if not fit.get("summary"):
            item.pop("fit", None)

    figures = []
    for f in item.get("figures") or []:
        texts = [f.get("title", ""), f.get("caption", ""), f.get("loop", "")] + list(f.get("columns") or [])
        texts += [x for st in f.get("steps") or [] for x in (st.get("label", ""), st.get("desc", ""), st.get("tag", ""))]
        texts += [x for r in f.get("rows") or [] for x in [r.get("label", "")] + list(r.get("cells") or [])]
        bad = [b for t in texts for b in unknown_numbers(t, pool)]
        if bad:
            notes.append(f"도식 '{f.get('title')}'의 숫자 {bad[:4]} 원문에서 확인 안 됨 → 도식 제외")
        else:
            figures.append(f)
    if "figures" in item:
        item["figures"] = figures

    usage = []
    for u in item.get("usage") or []:
        texts = [u.get("title", ""), u.get("when", ""), u.get("note", "")] + list(u.get("steps") or [])
        bad = [b for t in texts for b in unknown_numbers(t, pool)]
        if bad:
            notes.append(f"사용법 '{u.get('title')}'의 숫자 {bad[:4]} 원문에서 확인 안 됨 → 제외")
        else:
            usage.append(u)
    if "usage" in item:
        item["usage"] = usage
    return notes


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
    notes += check_extras(item, pool)
    # Shutdown date of a retirement notice: must be written in the page, otherwise it is dropped ('종료일 미정').
    sd = item.get("shutdown")
    if sd and not date_in(str(sd), haystack):
        notes.append(f"종료일 '{sd}' 원문에서 확인 안 됨 → 종료일 미정으로 표시")
        item.pop("shutdown", None)
    return notes
