"""营业时间文字的保守解析：只在能确定时给结论，否则返回 None（调用方显示“待核实”）。"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

_DAYS = "一二三四五六日天"
_IDX = {c: (i if c != "天" else 6) for i, c in enumerate(_DAYS)}
_SEG = re.compile(
    rf"周([{_DAYS}])(?:\s*[至到\-—~～]\s*周?([{_DAYS}]))?\s*[:：]?\s*([0-9:：\-—~～、,，;；\s]*[0-9])"
)
_CLOSED = re.compile(rf"周([{_DAYS}])\s*(?:闭馆|休息|休馆|不开放|关闭)")


def hours_for_weekday(text: str, weekday: int) -> Optional[str]:
    """weekday：0=周一。返回当天营业时段（如 "08:30-17:00"）、"闭馆"，无法确定返回 None。"""
    if not text:
        return None
    for m in _CLOSED.finditer(text):
        if _IDX[m.group(1)] == weekday:
            return "闭馆"
    found = None
    for m in _SEG.finditer(text):
        a = _IDX[m.group(1)]
        b = _IDX[m.group(2)] if m.group(2) else a
        days = range(a, b + 1) if a <= b else list(range(a, 7)) + list(range(0, b + 1))
        if weekday in days:
            found = m.group(3).strip()
    if found:
        return found
    if re.search(r"24\s*小时|全天", text) and not _SEG.search(text):
        return "全天开放"
    if not _SEG.search(text):
        t = re.search(r"\d{1,2}:\d{2}\s*[-~～—]\s*\d{1,2}:\d{2}", text)
        if t:
            return t.group(0)          # 没写星期，只有时段：每天适用
    return None


_RANGE_D = re.compile(r"(\d{1,2})月(\d{1,2})日?\s*[~～\-—至到]\s*(\d{1,2})月(\d{1,2})日?")
_FROM_D = re.compile(r"(\d{1,2})月(\d{1,2})日?\s*(?:起|开始)")
_RANGE_M = re.compile(r"(\d{1,2})\s*[~～\-—至到]\s*(\d{1,2})月")
_ONE_M = re.compile(r"(?<![\d~～\-—至到])(\d{1,2})月(?!\d|\s*\d+日)")


def _cond(clause: str):
    """返回 (None, None)=无季节条件；("bad", None)=条件复杂无法判断；否则 (起止月日元组, 起点 key)。"""
    found = []
    for m in _RANGE_D.finditer(clause):
        found.append(((int(m.group(1)), int(m.group(2))), (int(m.group(3)), int(m.group(4)))))
    stripped = _RANGE_D.sub(" ", clause)
    for m in _FROM_D.finditer(stripped):
        found.append(((int(m.group(1)), int(m.group(2))), (12, 31)))
    stripped = _FROM_D.sub(" ", stripped)
    for m in _RANGE_M.finditer(stripped):
        found.append(((int(m.group(1)), 1), (int(m.group(2)), 31)))
    stripped = _RANGE_M.sub(" ", stripped)
    for m in _ONE_M.finditer(stripped):
        found.append(((int(m.group(1)), 1), (int(m.group(1)), 31)))
    if not found:
        return None, None
    if len(found) > 1:
        return "bad", None
    return found[0], found[0][0]


def hours_for_date(text: str, d: date) -> Optional[str]:
    """考虑季节条件（如“10月11日起…”“3~10月…”“11月15日起周一闭馆”）后，d 当天的营业情况。
    条件复杂或无法确定时返回 None，不乱猜。"""
    if not text:
        return None
    clauses = [c for c in re.split(r"[;；\n。]", text) if c.strip()]
    md = (d.month, d.day)
    plain, cond = [], []
    for c in clauses:
        rng, start = _cond(c)
        if rng is None:
            plain.append(c)
        elif rng == "bad":
            return None
        else:
            a, b = rng
            ok = (a <= md <= b) if a <= b else (md >= a or md <= b)
            if ok:
                cond.append((start, c))
    use = list(plain)
    if cond:
        use.append(max(cond, key=lambda x: x[0])[1])
    elif len(clauses) == 1 and _cond(clauses[0])[0] is not None:
        return None          # 唯一的一段，且条件不适用当天
    results = [hours_for_weekday(c, d.weekday()) for c in use]
    if "闭馆" in results:
        return "闭馆"
    got = [r for r in results if r]
    return got[-1] if got else None        # 带季节条件的段排在最后，优先采用
