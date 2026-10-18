"""每天各景点的预计到达/离开时间（和地图时间线用同一套算法：从可用时间窗的开始算起，累加酒店出发路程、停留和景点间通勤）。

用餐点只是标记，不占用时间（和地图时间线一致）。分钟数是“一天中的第几分钟”（9:00 = 540）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .connections import day_window
from .metrics import day_stats
from .models import DayPlan, Place, Trip


@dataclass(frozen=True)
class Visit:
    place: Place
    arrive: int
    leave: int


def day_visits(trip: Trip, day: DayPlan) -> tuple[list[Visit], int]:
    """返回 (各景点的到达/离开分钟, 当天结束分钟)。结束 = 最后一个景点离开 + 回酒店路程（没有酒店就是最后离开）。"""
    st = day_stats(trip, day)
    t = day_window(trip, day.index)[0]
    if st.places and trip.morning_lodging(day.index) and st.lodging_out:
        t += st.lodging_out.minutes
    visits: list[Visit] = []
    for i, p in enumerate(st.places):
        visits.append(Visit(p, t, t + p.duration_min))
        t += p.duration_min
        if i < len(st.legs):
            t += st.legs[i].minutes
    if st.places and trip.lodging_for_day(day.index) and st.lodging_back:
        t += st.lodging_back.minutes
    return visits, t
