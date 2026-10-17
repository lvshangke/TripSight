"""统计与度量：一天有多满、交通多久、大概花多少钱。

调度器（scheduler）和校验器（validator）都用这里的函数，保证两边“算法一致”。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .geo import estimate_leg
from .models import DayPlan, Leg, Pace, Place, Trip


@dataclass(frozen=True)
class PaceLimits:
    max_places: int          # 一天最多几个地点
    max_total_minutes: int   # 一天“游览 + 交通”总分钟数上限

    @property
    def max_visit_minutes(self) -> int:
        """调度时用的游览时长上限（给交通留出约 20% 的余量）。"""
        return int(self.max_total_minutes * 0.8)


PACE_LIMITS: dict[Pace, PaceLimits] = {
    Pace.RELAXED: PaceLimits(max_places=2, max_total_minutes=300),
    Pace.NORMAL: PaceLimits(max_places=3, max_total_minutes=420),
    Pace.PACKED: PaceLimits(max_places=5, max_total_minutes=540),
}


def day_places(trip: Trip, day: DayPlan) -> list[Place]:
    """某一天里按顺序排好的景点对象。"""
    return [trip.place(it.place_id) for it in day.items]


def leg_key(a_id: str, a_lat: float, a_lon: float, b_id: str, b_lat: float, b_lon: float, mode: str) -> str:
    """路线缓存的键：包含两端坐标，所以景点坐标一改，旧缓存自然不再命中。"""
    return f"{a_id}@{a_lat:.5f},{a_lon:.5f}>{b_id}@{b_lat:.5f},{b_lon:.5f}|{mode}"


def _leg(trip: Trip, a_id, a_lat, a_lon, b_id, b_lat, b_lon) -> Leg:
    """优先用缓存的真实路线，没有就估算。"""
    mode = trip.meta.mode
    cached = trip.route_overrides.get(leg_key(a_id, a_lat, a_lon, b_id, b_lat, b_lon, mode))
    if cached is not None:
        return cached
    return estimate_leg(a_id, a_lat, a_lon, b_id, b_lat, b_lon, mode)


def legs_between_stops(trip: Trip, places: list[Place]) -> list[Leg]:
    """相邻景点之间的交通（有真实路线用真实的，否则估算）。"""
    return [_leg(trip, a.id, a.lat, a.lon, b.id, b.lat, b.lon) for a, b in zip(places, places[1:])]


def lodging_legs(trip: Trip, places: list[Place]) -> tuple[Optional[Leg], Optional[Leg]]:
    """住宿 → 当天第一个景点、当天最后一个景点 → 住宿。没选住宿或当天没景点则为 None。"""
    lodging = trip.chosen_lodging
    if lodging is None or not places:
        return None, None
    first, last = places[0], places[-1]
    out = _leg(trip, lodging.id, lodging.lat, lodging.lon, first.id, first.lat, first.lon)
    back = _leg(trip, last.id, last.lat, last.lon, lodging.id, lodging.lat, lodging.lon)
    return out, back


@dataclass
class DayStats:
    index: int
    places: list[Place]
    legs: list[Leg]
    lodging_out: Optional[Leg]
    lodging_back: Optional[Leg]
    visit_min: int = 0
    travel_min: int = 0          # 景点之间 + 往返住宿 的交通总分钟
    total_min: int = 0
    longest_leg_min: int = 0
    extra: dict = field(default_factory=dict)


def day_stats(trip: Trip, day: DayPlan) -> DayStats:
    places = day_places(trip, day)
    legs = legs_between_stops(trip, places)
    out, back = lodging_legs(trip, places)
    all_legs = legs + [x for x in (out, back) if x is not None]
    visit = sum(p.duration_min for p in places)
    travel = sum(l.minutes for l in all_legs)
    return DayStats(
        index=day.index,
        places=places,
        legs=legs,
        lodging_out=out,
        lodging_back=back,
        visit_min=visit,
        travel_min=travel,
        total_min=visit + travel,
        longest_leg_min=max((l.minutes for l in all_legs), default=0),
    )


@dataclass
class CostEstimate:
    tickets: float
    lodging: float
    nights: int

    @property
    def total(self) -> float:
        return self.tickets + self.lodging


def estimate_cost(trip: Trip) -> CostEstimate:
    """粗略费用：只含“已排入行程的景点门票 + 已选住宿 × 晚数”，不含餐饮和交通。"""
    tickets = 0.0
    if trip.plan:
        for day in trip.plan.days:
            for it in day.items:
                tickets += trip.place(it.place_id).ticket_price
    lodging = trip.chosen_lodging
    nights = max(trip.meta.num_days - 1, 0) if lodging else 0
    lodging_cost = lodging.price_mid * nights if lodging else 0.0
    return CostEstimate(tickets=tickets, lodging=lodging_cost, nights=nights)
