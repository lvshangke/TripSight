"""营业时间文字的保守解析：只在能确定时给结论，否则返回 None（调用方显示“待核实”）。"""

from __future__ import annotations

import re
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
    return None
