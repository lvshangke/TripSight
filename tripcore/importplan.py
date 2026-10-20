"""游记里的分天行程 ↔ 我们的行程：对照（参考式）和照搬（照搬式）。

全部是确定性的代码，不经过模型：
- 分天由 candidates.day_markers 从原文里识别，记在景点的 source_name / source_day 上；
- compare：不改任何东西，只告诉你游记里同一天的景点在我们的行程里是否还在同一天，没在一起的原因是什么；
- follow：用户明确要求“按游记原样排”时，把游记第 N 天的景点放到我们的第 M 天（锁定），天内顺序仍由排程优化，
  放不进去、去不了（闭馆等）的不隐瞒，如实列出。整个操作是一个版本，可以撤销。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Optional

from .geo import haversine_km
from .models import DayItem, DayPlan, Place, PlaceStatus, Plan, Trip
from .scheduler import _blocked, _closed_on, build_plan
from .state import commit
from .validator import validate

FAR_KM = 30            # 同一天的景点最远相距超过这个距离，提示“一天可能走不完”
_WEEK = "一二三四五六日"
_USABLE = (PlaceStatus.SHORTLIST, PlaceStatus.PLANNED, PlaceStatus.CONFIRMED)


def source_names(trip: Trip) -> list[str]:
    seen: list[str] = []
    for p in trip.places:
        if p.source_name and p.source_day and p.source_name not in seen:
            seen.append(p.source_name)
    return seen


def groups(trip: Trip, source: str = "") -> dict[tuple[str, int], list[Place]]:
    """{(游记名, 游记第几天): [景点…]}，按游记天数、景点加入的先后排。没有分天信息的景点不在里面。"""
    out: dict[tuple[str, int], list[Place]] = defaultdict(list)
    for p in trip.places:
        if p.source_name and p.source_day and (not source or p.source_name == source) and p.status != PlaceStatus.EXCLUDED:
            out[(p.source_name, p.source_day)].append(p)
    return dict(sorted(out.items()))


def _our_days(trip: Trip) -> dict[str, int]:
    return {it.place_id: d.index for d in (trip.plan.days if trip.plan else []) for it in d.items}


def block_reason(trip: Trip, place: Place, day_index: int) -> str:
    """这个景点在我们的第 day_index+1 天去不了的原因；去得了返回空串。"""
    if not _blocked(trip, place, day_index):
        return ""
    d = trip.day_date(day_index)
    if d is not None and _closed_on(place, d):
        return f"周{_WEEK[d.weekday()]}闭馆"
    return "当天营业时间对不上（不开或太早打烊）"


def _far_note(places: list[Place]) -> str:
    far = max((haversine_km(a.lat, a.lon, b.lat, b.lon) for i, a in enumerate(places) for b in places[i + 1:]), default=0.0)
    return f"组内景点最远相距约 {far:.0f} 公里，一天可能走不完" if far > FAR_KM else ""


def compare(trip: Trip, source: str = "") -> list[dict]:
    """参考式：游记每一天的景点，在我们的行程里落在哪一天、有没有被拆开，拆开的原因。不修改任何东西。"""
    where = _our_days(trip)
    unsched = {u.place_id: u.reason for u in (trip.plan.unscheduled if trip.plan else [])}
    out = []
    for (src, sday), places in groups(trip, source).items():
        placed = [where[p.id] for p in places if p.id in where]
        notes: list[str] = []
        if not placed:
            status = "未安排"
        else:
            main = sorted(Counter(placed).items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            status = "在一起" if len(set(placed)) == 1 and len(placed) == len(places) else "被拆开"
            for p in places:
                if p.id in where and where[p.id] != main:
                    why = block_reason(trip, p, main)
                    notes.append(f"「{p.name}」在第 {where[p.id] + 1} 天，没和大家在第 {main + 1} 天："
                                 + (f"第 {main + 1} 天{why}" if why else "排程为了整体路程更顺，把它放到了别处"))
        for p in places:
            if p.id not in where:
                notes.append(f"「{p.name}」没排进任何一天" + (f"（{unsched[p.id]}）" if p.id in unsched else "（状态不是入围/已安排）"))
        far = _far_note(places)
        if far:
            notes.append(far)
        out.append({"source": src, "source_day": sday, "status": status,
                    "places": [{"id": p.id, "name": p.name, "our_day": None if p.id not in where else where[p.id] + 1} for p in places],
                    "notes": notes})
    return out


def follow(trip: Trip, source: str, day_map: Optional[dict[int, int]] = None) -> tuple[Trip, dict]:
    """照搬式：游记第 N 天 → 我们的第 day_map[N] 天（不给就同号，超出我们天数的不放）。返回 (新版本, 报告)。
    已被用户锁定在别的天的景点不动；不是入围/已安排状态的不放；去不了的照放但列在 conflicts 里让用户决定。"""
    gs = groups(trip, source)
    if not gs:
        raise ValueError(f"没有找到来自「{source}」且带分天信息的景点（要先从游记加入景点，且原文里要有“第N天/Day N”标记）。")
    n = trip.meta.num_days
    day_map = day_map or {}
    locked_day = {it.place_id: d.index for d in (trip.plan.days if trip.plan else []) for it in d.items if it.locked}

    target: dict[str, int] = {}                          # place_id → 我们的第几天（0 起）
    report: dict = {"placed": [], "skipped": [], "conflicts": [], "unmapped_days": []}
    for (src, sday), places in gs.items():
        dest = day_map.get(sday, sday)
        if not (1 <= dest <= n):
            report["unmapped_days"].append({"source_day": sday, "places": [p.name for p in places],
                                            "reason": f"游记第 {sday} 天对应我们的第 {dest} 天，超出了行程的 {n} 天；可以用 day_map 指定放到哪天"})
            continue
        for p in places:
            if p.id in locked_day:
                report["skipped"].append(f"「{p.name}」已被你锁定在第 {locked_day[p.id] + 1} 天，没有动")
            elif p.status not in _USABLE:
                report["skipped"].append(f"「{p.name}」状态是{p.status.value}，没有放")
            else:
                target[p.id] = dest - 1
                why = block_reason(trip, p, dest - 1)
                if why:
                    report["conflicts"].append(f"「{p.name}」放在第 {dest} 天：{why}")

    def mutate(t: Trip) -> None:
        days = [DayPlan(index=i, items=[]) for i in range(n)]
        for d in (t.plan.days if t.plan else []):
            if d.index < n:
                days[d.index].items = [DayItem(place_id=it.place_id, locked=True) for it in d.items if it.locked]
        for pid, di in target.items():
            days[di].items.append(DayItem(place_id=pid, locked=True))
        t.plan = Plan(days=days, unscheduled=[])
        t.plan = build_plan(t, keep_locked=True)
        scheduled = {it.place_id for d in t.plan.days for it in d.items}
        for p in t.places:
            if p.id in scheduled and p.status == PlaceStatus.SHORTLIST:
                p.status = PlaceStatus.PLANNED
            elif p.id not in scheduled and p.status == PlaceStatus.PLANNED:
                p.status = PlaceStatus.SHORTLIST

    new = commit(trip, mutate)
    by_id = {p.id: p for p in new.places}
    days_used = {di for di in target.values()}
    for pid, di in target.items():
        report["placed"].append(f"「{by_id[pid].name}」→ 第 {di + 1} 天")
    report["issues"] = [{"code": i.code, "severity": i.severity, "message": i.message,
                         "day": None if i.day_index is None else i.day_index + 1}
                        for i in validate(new) if i.day_index in days_used or i.place_id in target]
    return new, report
