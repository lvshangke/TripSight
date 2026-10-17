"""大交通对第一天/最后一天可用时间的影响（确定性规则）。

- 到达后需要一段时间才能开始玩：飞机 90 分钟（取行李、进城），火车 45 分钟，其他 30 分钟。
- 离开前要提前出发：飞机 180 分钟（赶到机场、安检），火车 60 分钟，其他 30 分钟。
- 每天默认 9:00 开始、21:00 结束。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from .models import Connection, DateMode, Trip

DAY_START_MIN = 9 * 60
DAY_END_MIN = 21 * 60
ARRIVE_BUFFER = {"flight": 90, "train": 45, "other": 30}
DEPART_BUFFER = {"flight": 180, "train": 60, "other": 30}


def ready_time(c: Connection) -> datetime:
    """到达后可以开始游玩的时间。"""
    return c.arr_time + timedelta(minutes=ARRIVE_BUFFER[c.kind])


def leave_by(c: Connection) -> datetime:
    """最晚要从最后一个景点/酒店出发去车站机场的时间。"""
    return c.dep_time - timedelta(minutes=DEPART_BUFFER[c.kind])


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


def _minute_of_day(t: datetime) -> int:
    return t.hour * 60 + t.minute


def day_window(trip: Trip, day_index: int) -> tuple[int, int, list[str]]:
    """这一天可以用来游玩的时间窗 (开始分钟, 结束分钟, 原因说明)，分钟是一天中的第几分钟。"""
    start, end, why = DAY_START_MIN, DAY_END_MIN, []
    if trip.arrival and arrival_day(trip) == day_index:
        r = ready_time(trip.arrival)
        start = max(start, _minute_of_day(r) if r.date() == trip.arrival.arr_time.date() else 24 * 60)
        why.append(f"{trip.arrival.arr_time:%H:%M} 到达，约 {_minute_of_day(r) // 60:02d}:{_minute_of_day(r) % 60:02d} 后才能开始")
    if trip.departure and departure_day(trip) == day_index:
        lv = leave_by(trip.departure)
        end = min(end, _minute_of_day(lv) if lv.date() == trip.departure.dep_time.date() else 0)
        why.append(f"{trip.departure.dep_time:%H:%M} 离开，最晚 {_minute_of_day(lv) // 60:02d}:{_minute_of_day(lv) % 60:02d} 就要出发")
    return start, max(start, end), why
