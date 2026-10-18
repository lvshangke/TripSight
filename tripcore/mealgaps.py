"""哪几天“还缺几顿饭”：按当天游览时段是否覆盖午餐/晚餐时间，对比已选的用餐点数量。

只是提示（用餐点不占景点容量，也不参与排程）。午餐 11:30–13:30，晚餐 17:30–19:30，至少重叠 30 分钟才算。
"""

from __future__ import annotations

from .models import Trip
from .timeline import day_visits

WINDOWS = {"午餐": (11 * 60 + 30, 13 * 60 + 30), "晚餐": (17 * 60 + 30, 19 * 60 + 30)}
MIN_OVERLAP = 30


def meal_gaps(trip: Trip) -> dict[int, list[str]]:
    """{天序号（从 0 开始）: 还缺的餐名列表（午餐/晚餐）}，不缺的天不出现。"""
    out: dict[int, list[str]] = {}
    if trip.plan is None:
        return out
    for day in trip.plan.days:
        visits, _ = day_visits(trip, day)
        if not visits:
            continue
        start, end = visits[0].arrive, visits[-1].leave
        needs = [name for name, (a, b) in WINDOWS.items() if min(end, b) - max(start, a) >= MIN_OVERLAP]
        have = sum(1 for m in trip.meals if m.day == day.index)
        missing = needs[have:] if have < len(needs) else []
        if missing:
            out[day.index] = missing
    return out
