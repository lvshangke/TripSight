"""住宿相关：推荐“住在哪一带”，并给候选酒店按通勤排序。

这里的“通勤”都是估算值（见 geo.py），只用来做相对比较。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .geo import estimate_leg, haversine_km
from .models import Lodging, Place, Trip, SCHEDULABLE_STATUSES


@dataclass
class StayAreaSuggestion:
    lat: float
    lon: float
    radius_km: float             # 覆盖约 80% 景点的半径
    avg_minutes_to_places: float  # 从这个中心到各景点的平均估算通勤
    place_count: int


def _planned_places(trip: Trip) -> list[Place]:
    if trip.plan:
        ids = [it.place_id for d in trip.plan.days for it in d.items]
        return [trip.place(i) for i in ids]
    return [p for p in trip.places if p.status in SCHEDULABLE_STATUSES]


def suggest_stay_area(trip: Trip) -> Optional[StayAreaSuggestion]:
    """按“游览时长加权”的重心，推荐一个住宿区域中心。没有景点时返回 None。"""
    places = _planned_places(trip)
    if not places:
        return None
    total_w = sum(p.duration_min for p in places)
    lat = sum(p.lat * p.duration_min for p in places) / total_w
    lon = sum(p.lon * p.duration_min for p in places) / total_w

    dists = sorted(haversine_km(lat, lon, p.lat, p.lon) for p in places)
    idx = max(int(len(dists) * 0.8) - 1, 0)
    radius = dists[idx]

    mins = [
        estimate_leg("c", lat, lon, p.id, p.lat, p.lon, trip.meta.mode).minutes for p in places
    ]
    return StayAreaSuggestion(
        lat=lat,
        lon=lon,
        radius_km=round(radius, 2),
        avg_minutes_to_places=round(sum(mins) / len(mins), 1),
        place_count=len(places),
    )


@dataclass
class LodgingScore:
    lodging: Lodging
    avg_commute_min: float   # 到各天首个景点、各天末个景点回来的平均单程分钟
    worst_commute_min: int
    price_mid: float


def rank_lodgings(trip: Trip) -> list[LodgingScore]:
    """给每个候选住宿算一个通勤分，按“通勤少 → 价格低”排序。

    有行程时：看每天第一个/最后一个景点；没有行程时：看所有入围景点。
    """
    if not trip.lodgings:
        return []

    targets: list[Place] = []
    if trip.plan:
        for d in trip.plan.days:
            if d.items:
                targets.append(trip.place(d.items[0].place_id))
                if len(d.items) > 1:
                    targets.append(trip.place(d.items[-1].place_id))
    if not targets:
        targets = _planned_places(trip)
    if not targets:
        return []

    out: list[LodgingScore] = []
    for l in trip.lodgings:
        mins = [
            estimate_leg(l.id, l.lat, l.lon, p.id, p.lat, p.lon, trip.meta.mode).minutes
            for p in targets
        ]
        out.append(
            LodgingScore(
                lodging=l,
                avg_commute_min=round(sum(mins) / len(mins), 1),
                worst_commute_min=max(mins),
                price_mid=l.price_mid,
            )
        )
    out.sort(key=lambda s: (s.avg_commute_min, s.price_mid, s.lodging.id))
    return out
