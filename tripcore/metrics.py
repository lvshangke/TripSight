"""统计与度量：一天有多满、交通多久、大概花多少钱。

调度器（scheduler）和校验器（validator）都用这里的函数，保证两边“算法一致”。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .geo import estimate_leg
from .models import DayPlan, Leg, Pace, Place, Trip
from .routeplace import entry, exit_


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


INTERCITY_KM = 80      # 单段超过这个距离，按“跨城路段”处理（高德公交方案可能是普速慢车，应改看高铁或驾车）


def intercity_hint(distance_km: float, mode: str = "") -> str:
    """跨城路段的提示文字；不是跨城返回空串。"""
    if distance_km <= INTERCITY_KM or mode == "drive":      # 已经是驾车的不用提示
        return ""
    return (f"跨城路段（约 {distance_km:g} km）：高德的公交方案可能是普速慢车，不一定是最合适的；"
            "建议用 flyai 的 search-train 查高铁车次，或改成驾车/打车（set_leg_mode），请和用户确认")


def day_places(trip: Trip, day: DayPlan) -> list[Place]:
    """某一天里按顺序排好的景点对象。"""
    return [trip.place(it.place_id) for it in day.items]


def leg_key(a_id: str, a_lat: float, a_lon: float, b_id: str, b_lat: float, b_lon: float, mode: str) -> str:
    """路线缓存的键：包含两端坐标，所以景点坐标一改，旧缓存自然不再命中。"""
    return f"{a_id}@{a_lat:.5f},{a_lon:.5f}>{b_id}@{b_lat:.5f},{b_lon:.5f}|{mode}"


def leg_mode(trip: Trip, a_id: str, b_id: str) -> str:
    """这一段用哪种出行方式：用户单独指定的优先，否则用行程的默认偏好。"""
    return trip.leg_modes.get(f"{a_id}>{b_id}", trip.meta.mode)


def _leg(trip: Trip, a_id, a_lat, a_lon, b_id, b_lat, b_lon) -> Leg:
    """优先用缓存的真实路线，没有就估算。"""
    mode = leg_mode(trip, a_id, b_id)
    cached = trip.route_overrides.get(leg_key(a_id, a_lat, a_lon, b_id, b_lat, b_lon, mode))
    if cached is not None:
        return cached
    return estimate_leg(a_id, a_lat, a_lon, b_id, b_lat, b_lon, mode)


def legs_between_stops(trip: Trip, places: list[Place]) -> list[Leg]:
    """相邻景点之间的交通（有真实路线用真实的，否则估算）。"""
    out = []
    for a, b in zip(places, places[1:]):
        x, e = exit_(a), entry(b)
        out.append(_leg(trip, x.id, x.lat, x.lon, e.id, e.lat, e.lon))
    return out


def lodging_legs(trip: Trip, places: list[Place], day_index: Optional[int] = None) -> tuple[Optional[Leg], Optional[Leg]]:
    """住宿 → 当天第一个景点、当天最后一个景点 → 住宿。没选住宿或当天没景点则为 None。
    给了 day_index 且设置了分段住宿时：早上从前一晚的酒店出发，晚上回今晚的酒店。"""
    if day_index is None:
        morning = night = trip.chosen_lodging
    else:
        morning, night = trip.morning_lodging(day_index), trip.lodging_for_day(day_index)
    if morning is None or night is None or not places:
        return None, None
    first, last = places[0], places[-1]
    e, x = entry(first), exit_(last)
    out = _leg(trip, morning.id, morning.lat, morning.lon, e.id, e.lat, e.lon)
    back = _leg(trip, x.id, x.lat, x.lon, night.id, night.lat, night.lon)
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
    out, back = lodging_legs(trip, places, day.index)
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
    """粗略费用：只含“已排入行程的景点门票 + 每晚所住酒店的价格之和”，不含餐饮和交通。"""
    tickets = 0.0
    if trip.plan:
        for day in trip.plan.days:
            for it in day.items:
                tickets += trip.place(it.place_id).ticket_price
    nights, lodging_cost = 0, 0.0
    for n in range(max(trip.meta.num_days - 1, 0)):     # 第 n 晚住 lodging_for_day(n)
        lod = trip.lodging_for_day(n)
        if lod is not None:
            nights += 1
            lodging_cost += lod.price_mid
    return CostEstimate(tickets=tickets, lodging=lodging_cost, nights=nights)


@dataclass
class DayBudget:
    index: int
    tickets: float        # 当天景点门票（按人数）
    meals: float          # 当天已选餐厅的人均参考（按人数）；没选餐厅就是 0
    meals_chosen: int


def day_budgets(trip: Trip) -> list[DayBudget]:
    """按天的费用明细（门票 + 已选餐厅，均按 trip.meta.travelers 乘人数）。住宿和大交通按整个行程算，不分到天。
    没选的餐食、市内交通不在里面（没有可靠数据，不估）。"""
    n = trip.meta.travelers
    out: list[DayBudget] = []
    if trip.plan is None:
        return out
    for day in trip.plan.days:
        tickets = sum(trip.place(it.place_id).ticket_price for it in day.items) * n
        chosen = [m for m in trip.meals if m.day == day.index]
        meals = sum(m.cost_per_person or 0 for m in chosen) * n
        out.append(DayBudget(day.index, tickets, meals, len(chosen)))
    return out
