"""营业时间文字的保守解析：只在能确定时给结论，否则返回 None（调用方显示“待核实”）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

_DAYS = "一二三四五六日天"
_IDX = {c: (i if c != "天" else 6) for i, c in enumerate(_DAYS)}
_SEG = re.compile(
    rf"周([{_DAYS}])(?:\s*[至到\-—~～]\s*周?([{_DAYS}]))?\s*[:：]?\s*([0-9:：\-—–~～、,，;；\s]*[0-9])"
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
        t = re.search(r"\d{1,2}:\d{2}\s*[-~～—–]\s*\d{1,2}:\d{2}", text)
        if t:
            return t.group(0)          # 没写星期，只有时段：每天适用
    return None


_RANGE_D = re.compile(r"(\d{1,2})月(\d{1,2})日?\s*[~～\-—–至到]\s*(\d{1,2})月(\d{1,2})日?")
_RANGE_S = re.compile(r"(?<![\d:：])(\d{1,2})/(\d{1,2})\s*[~～\-—–至到]\s*(\d{1,2})/(\d{1,2})(?![\d:：])")       # 09/25-09/30
_RANGE_DOT = re.compile(r"(?<![\d:：.])(\d{1,2})\.(\d{1,2})日\s*[~～\-—–至到]\s*(\d{1,2})\.(\d{1,2})日")   # 2.15日-2.23日
_FROM_D = re.compile(r"(\d{1,2})月(\d{1,2})日?\s*(?:起|开始)")
_RANGE_MM = re.compile(r"(\d{1,2})月\s*[~～\-—–至到]\s*(\d{1,2})月(?!\d|\s*\d+日)")      # 1月至7月
_RANGE_M = re.compile(r"(\d{1,2})\s*[~～\-—至到]\s*(\d{1,2})月")
_ONE_M = re.compile(r"(?<![\d~～\-—至到])(\d{1,2})月(?!\d|\s*\d+日)")


def _cond(clause: str):
    """返回 (None, None)=无季节条件；("bad", None)=条件复杂无法判断；否则 ([(起月日, 止月日), ...], None)，多项表示“或”。"""
    found = []
    for rx in (_RANGE_D, _RANGE_S, _RANGE_DOT):
        for m in rx.finditer(clause):
            a, b = (int(m.group(1)), int(m.group(2))), (int(m.group(3)), int(m.group(4)))
            if all(1 <= x[0] <= 12 and 1 <= x[1] <= 31 for x in (a, b)):
                found.append((a, b))
    stripped = _RANGE_DOT.sub(" ", _RANGE_S.sub(" ", _RANGE_D.sub(" ", clause)))
    for m in _FROM_D.finditer(stripped):
        found.append(((int(m.group(1)), int(m.group(2))), (12, 31)))
    stripped = _FROM_D.sub(" ", stripped)
    for m in _RANGE_MM.finditer(stripped):
        found.append(((int(m.group(1)), 1), (int(m.group(2)), 31)))
    stripped = _RANGE_MM.sub(" ", stripped)
    for m in _RANGE_M.finditer(stripped):
        found.append(((int(m.group(1)), 1), (int(m.group(2)), 31)))
    stripped = _RANGE_M.sub(" ", stripped)
    for m in _ONE_M.finditer(stripped):
        found.append(((int(m.group(1)), 1), (int(m.group(1)), 31)))
    if not found:
        return None, None
    if any(not (1 <= a[0] <= 12 and 1 <= b[0] <= 12) for a, b in found):
        return "bad", None
    if len(found) > 1 and not all(a[1] == 1 and b[1] == 31 for a, b in found):
        return "bad", None                         # 多个精确到日的条件：太复杂，不判断
    return found, None                             # 多个“月”范围（如“1月至7月,9月至12月”）按“或”处理


def _select(text: str, d: date) -> Optional[list[str]]:
    """d 当天适用的那几段文字（已考虑季节条件）；条件复杂或无法确定返回 None。"""
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
            for a, b in rng:
                if (a <= md <= b) if a <= b else (md >= a or md <= b):
                    cond.append((a, c))
                    break
    use = list(plain)
    if cond:
        use.append(max(cond, key=lambda x: x[0])[1])
    elif len(clauses) == 1 and _cond(clauses[0])[0] is not None:
        return None          # 唯一的一段，且条件不适用当天
    return use


def hours_for_date(text: str, d: date) -> Optional[str]:
    """考虑季节条件（如“10月11日起…”“3~10月…”“11月15日起周一闭馆”）后，d 当天的营业情况。
    条件复杂或无法确定时返回 None，不乱猜。"""
    use = _select(text, d)
    if use is None:
        return None
    results = [hours_for_weekday(c, d.weekday()) for c in use]
    if "闭馆" in results:
        return "闭馆"
    got = [r for r in results if r]
    return got[-1] if got else None        # 带季节条件的段排在最后，优先采用


_TIME_RANGE = re.compile(r"(\d{1,2})[:：](\d{2})\s*[-~～—–至到]\s*(\d{1,2})[:：](\d{2})")
_LAST_ENTRY = re.compile(r"(?:最晚|最后)\s*(?:进入|入园|入场|入馆|售票|检票|入内)\D{0,3}(\d{1,2})[:：](\d{2})")
_STOP_ENTRY = re.compile(r"(\d{1,2})[:：](\d{2})\s*(?:停止|截止|止)\s*(?:售票|检票|入场|入园|入馆|进入)")


@dataclass(frozen=True)
class Window:
    """某天的营业窗口。closed=整天不开；all_day=全天；ranges 是营业时段（一天中的第几分钟）；last_entry 是最晚进入/售票时间。"""
    closed: bool = False
    all_day: bool = False
    ranges: tuple = ()
    last_entry: Optional[int] = None


def hours_window(text: str, d: date) -> Optional[Window]:
    """把营业时间文字解析成 d 当天的营业窗口。只在能确定时给结论，否则返回 None（调用方不做检查、显示“待核实”）。"""
    use = _select(text, d)
    if use is None:
        return None
    best = None
    for c in use:
        r = hours_for_weekday(c, d.weekday())
        if r == "闭馆":
            return Window(closed=True)
        if r:
            best = (c, r)
    if best is None:
        return None
    clause, span = best
    last = None
    for rx in (_LAST_ENTRY, _STOP_ENTRY):
        m = rx.search(clause)
        if m:
            last = int(m.group(1)) * 60 + int(m.group(2))
            break
    if last is None:                                   # 没写在这一段里：全文只有一种说法时才采用
        vals = {int(m.group(1)) * 60 + int(m.group(2)) for rx in (_LAST_ENTRY, _STOP_ENTRY) for m in rx.finditer(text)}
        if len(vals) == 1:
            last = vals.pop()
    if span == "全天开放":
        return Window(all_day=True, last_entry=last)
    ranges = []
    for m in _TIME_RANGE.finditer(span):
        a, b = int(m.group(1)) * 60 + int(m.group(2)), int(m.group(3)) * 60 + int(m.group(4))
        if not (0 <= int(m.group(1)) <= 24 and 0 <= int(m.group(3)) <= 24 and int(m.group(2)) < 60 and int(m.group(4)) < 60):
            return None
        if b <= a:
            b += 24 * 60                               # 跨夜（如 18:00-02:00）
        ranges.append((a, b))
    if not ranges:
        return None
    if ranges[0][1] - ranges[0][0] >= 24 * 60 - 1 and len(ranges) == 1:
        return Window(all_day=True, last_entry=last)   # 00:00-24:00
    return Window(ranges=tuple(sorted(ranges)), last_entry=last)
