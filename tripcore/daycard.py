"""工作台每天的头部统计、景点卡片上的营业状态与类别标签。

只整理已有数据（路线、预算、校验结果、营业时间），不产生新的“事实”；拿不准的写“待核实”，不估算。
"""

from __future__ import annotations

from typing import Any

from .hours import hours_window
from .metrics import PACE_LIMITS, day_budgets, day_stats
from .models import Trip
from .validator import validate

_WEEK = "一二三四五六日"
_HOURS_CODES = ("OUTSIDE_HOURS", "ARRIVE_BEFORE_OPEN", "LEAVE_AFTER_CLOSE")


def _hm(m: int) -> str:
    m = int(m) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def category_label(category: str) -> str:
    """高德的类别文字如“风景名胜;公园广场;公园”，取最后一段（最具体）。"""
    parts = [x.strip() for x in (category or "").split(";") if x.strip()]
    if not parts:
        return ""
    return parts[-1]                                   # 最后一段最具体，如“公园”“步行街”


def hours_text(trip: Trip, place, day_index: int) -> str:
    d = trip.day_date(day_index)
    if not place.opening_hours:
        return ""
    if d is None:
        return place.opening_hours[:30]
    w = hours_window(place.opening_hours, d)
    if w is None:
        return place.opening_hours[:30]
    if w.closed:
        return "当天不开放"
    if w.all_day:
        return "全天开放" + (f"（最晚进入 {_hm(w.last_entry)}）" if w.last_entry is not None else "")
    span = "、".join(f"{_hm(a)}–{_hm(b)}" for a, b in w.ranges)
    return span + (f"（最晚进入 {_hm(w.last_entry)}）" if w.last_entry is not None else "")


def build(trip: Trip, timelines: dict[int, list[dict]]) -> dict[str, Any]:
    """返回 {"day_stats": {day_index: {...}}, "stop_info": {place_id: {...}}}。timelines 是地图数据里每天的时间线。"""
    if trip.plan is None:
        return {"day_stats": {}, "stop_info": {}}
    issues = validate(trip)
    budgets = {b.index: b for b in day_budgets(trip)}
    limit = PACE_LIMITS[trip.meta.pace].max_total_minutes
    stats: dict[str, Any] = {}
    info: dict[str, Any] = {}
    for day in trip.plan.days:
        i = day.index
        legs = [e for e in timelines.get(i, []) if e.get("type") == "leg"]
        km = round(sum(float(e.get("km") or 0) for e in legs), 1)
        ds = day_stats(trip, day)
        b = budgets.get(i)
        cost = (b.tickets + b.meals) if b else 0
        d = trip.day_date(i)
        stats[str(i)] = {
            "places": len(day.items),
            "km": km, "km_estimated": any(not e.get("real") for e in legs),
            "minutes": ds.total_min, "over": ds.total_min > limit,
            "cost": round(cost), "cost_known": cost > 0,
            "date": d.isoformat() if d else "", "weekday": f"周{_WEEK[d.weekday()]}" if d else "",
            "errors": sum(1 for x in issues if x.day_index == i and x.severity == "error"),
        }
        for it in day.items:
            p = trip.place(it.place_id)
            sev = {x.severity for x in issues if x.place_id == p.id and x.day_index == i and x.code in _HOURS_CODES}
            if not p.opening_hours:
                state = "unknown"
            elif "error" in sev:
                state = "bad"
            elif "warning" in sev:
                state = "warn"
            else:
                state = "ok"
            info[p.id] = {"state": state, "hours": hours_text(trip, p, i), "cat": category_label(p.category)}
    return {"day_stats": stats, "stop_info": info}
