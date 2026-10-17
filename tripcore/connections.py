"""大交通对第一天/最后一天可用时间的影响（确定性规则）。

到达日：可开始游玩 = 到达时间 + 取行李/出站时间 + 「机场或车站 → 酒店（没选酒店则第一个景点）」的路程时间。
离开日：最晚结束 = 起飞/发车时间 − 提前到场时间 − 「酒店（没选酒店则最后一个景点）→ 机场或车站」的路程时间。
路程时间优先用高德真实路线（refine_routes 缓存），没有就按距离估算；不知道机场/车站位置时，用固定经验值兜底。
每天默认 9:00–21:00。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .geo import estimate_leg
from .metrics import leg_key, leg_mode
from .models import Connection, DateMode, Leg, Trip

DAY_START_MIN = 9 * 60
DAY_END_MIN = 21 * 60
EXIT_BUFFER = {"flight": 45, "train": 15, "other": 10}          # 到达后取行李、出站
ARRIVE_BUFFER = EXIT_BUFFER                                      # 兼容旧名
LEAD_BUFFER = {"flight": 120, "train": 40, "other": 20}         # 离开前到场、安检/检票
FALLBACK_TRANSFER = {"arrival": {"flight": 45, "train": 30, "other": 20},
                     "departure": {"flight": 60, "train": 20, "other": 10}}   # 不知道位置时的路程兜底（分钟）


@dataclass
class Pt:
    """机场/车站的临时点（id 固定为 arrival / departure，不是景点）。"""
    id: str
    name: str
    lat: float
    lon: float


def terminal_point(trip: Trip, which: str) -> Optional[Pt]:
    c = getattr(trip, which)
    if c is None or c.terminal_lat is None or c.terminal_lon is None:
        return None
    return Pt(which, c.terminal_name or ("到达站" if which == "arrival" else "出发站"), c.terminal_lat, c.terminal_lon)


def day_index_of(trip: Trip, when: datetime, default: int) -> Optional[int]:
    """这个时间落在行程第几天（0 开始）。没有确定日期时用 default；日期不在行程内返回 None。"""
    if trip.meta.date_mode == DateMode.EXACT and trip.meta.start_date:
        idx = (when.date() - trip.meta.start_date).days
        return idx if 0 <= idx < trip.meta.num_days else None
    return default


def arrival_day(trip: Trip) -> Optional[int]:
    return day_index_of(trip, trip.arrival.arr_time, 0) if trip.arrival else None


def departure_day(trip: Trip) -> Optional[int]:
    return day_index_of(trip, trip.departure.dep_time, trip.meta.num_days - 1) if trip.departure else None


def transfer_target(trip: Trip, which: str):
    """机场/车站要往返的那一头：选了酒店就是酒店；否则到达日第一个景点 / 离开日最后一个景点。"""
    if trip.chosen_lodging:
        return trip.chosen_lodging
    idx = arrival_day(trip) if which == "arrival" else departure_day(trip)
    if trip.plan is None or idx is None or idx >= len(trip.plan.days) or not trip.plan.days[idx].items:
        return None
    items = trip.plan.days[idx].items
    return trip.place(items[0].place_id if which == "arrival" else items[-1].place_id)


def terminal_leg(trip: Trip, which: str) -> Optional[Leg]:
    """机场/车站 ↔ 酒店（或景点）这一段：有高德缓存用缓存，否则估算。位置未知返回 None。"""
    t, target = terminal_point(trip, which), transfer_target(trip, which)
    if t is None or target is None:
        return None
    a, b = (t, target) if which == "arrival" else (target, t)
    mode = leg_mode(trip, a.id, b.id)
    cached = trip.route_overrides.get(leg_key(a.id, a.lat, a.lon, b.id, b.lat, b.lon, mode))
    return cached if cached is not None else estimate_leg(a.id, a.lat, a.lon, b.id, b.lat, b.lon, mode)


def transfer_minutes(trip: Trip, which: str) -> tuple[int, str]:
    """(分钟, 来源说明)：来源是 高德路线 / 距离估算 / 经验值。"""
    c = getattr(trip, which)
    leg = terminal_leg(trip, which)
    if leg is None:
        return FALLBACK_TRANSFER[which][c.kind], "经验值（机场/车站位置未知）"
    return leg.minutes, ("高德路线" if leg.detail_level == "route" else "距离估算")


def ready_time(trip: Trip) -> datetime:
    """到达后可以开始游玩（人已在酒店）的时间。"""
    c = trip.arrival
    return c.arr_time + timedelta(minutes=EXIT_BUFFER[c.kind] + transfer_minutes(trip, "arrival")[0])


def leave_by(trip: Trip) -> datetime:
    """最晚要从酒店出发去机场/车站的时间。"""
    c = trip.departure
    return c.dep_time - timedelta(minutes=LEAD_BUFFER[c.kind] + transfer_minutes(trip, "departure")[0])


def _minute_of_day(t: datetime) -> int:
    return t.hour * 60 + t.minute


def day_window(trip: Trip, day_index: int) -> tuple[int, int, list[str]]:
    """这一天可以用来游玩的时间窗 (开始分钟, 结束分钟, 原因说明)，分钟是一天中的第几分钟。"""
    start, end, why = DAY_START_MIN, DAY_END_MIN, []
    if trip.arrival and arrival_day(trip) == day_index:
        r = ready_time(trip)
        mins, src = transfer_minutes(trip, "arrival")
        start = max(start, _minute_of_day(r) if r.date() == trip.arrival.arr_time.date() else 24 * 60)
        why.append(f"{trip.arrival.arr_time:%H:%M} 到达，出站约 {EXIT_BUFFER[trip.arrival.kind]} 分钟 + 到酒店路上约 {mins} 分钟（{src}），"
                   f"约 {_minute_of_day(r) // 60:02d}:{_minute_of_day(r) % 60:02d} 后才能开始")
    if trip.departure and departure_day(trip) == day_index:
        lv = leave_by(trip)
        mins, src = transfer_minutes(trip, "departure")
        end = min(end, _minute_of_day(lv) if lv.date() == trip.departure.dep_time.date() else 0)
        why.append(f"{trip.departure.dep_time:%H:%M} 离开，要提前 {LEAD_BUFFER[trip.departure.kind]} 分钟到场 + 去机场/车站路上约 {mins} 分钟（{src}），"
                   f"最晚 {_minute_of_day(lv) // 60:02d}:{_minute_of_day(lv) % 60:02d} 就要从酒店出发")
    return start, max(start, end), why


NIGHT_START_MIN = 23 * 60        # 经验规则：约 23:00–05:30 公共交通多已停运（不是真实末班车时间，会在说明里标注）
NIGHT_END_MIN = 5 * 60 + 30


def is_night(when: datetime) -> bool:
    m = when.hour * 60 + when.minute
    return m >= NIGHT_START_MIN or m < NIGHT_END_MIN


def terminal_depart_time(trip: Trip, which: str) -> Optional[datetime]:
    """机场/车站这一段预计从哪个时间出发：到达=出站后；离开=按目前估计的路程倒推。"""
    c = getattr(trip, which)
    if c is None:
        return None
    if which == "arrival":
        return c.arr_time + timedelta(minutes=EXIT_BUFFER[c.kind])
    return c.dep_time - timedelta(minutes=LEAD_BUFFER[c.kind] + transfer_minutes(trip, "departure")[0])
