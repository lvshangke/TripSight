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


# ---------------------------------------------------------------------------
# 按每晚 / 每段推荐住在哪一带（跨城市也适用）
# ---------------------------------------------------------------------------

SAME_AREA_KM = 8.0       # 相邻两晚的推荐中心相距不超过这个距离，就合并成“连住一段”


@dataclass
class StaySegment:
    from_night: int            # 第几晚开始（从 0 开始；第 0 晚 = 第 1 天晚上）
    to_night: int              # 第几晚结束（含）
    lat: float
    lon: float
    radius_km: float           # 覆盖这一段相关景点的半径
    near_place: str            # 离中心最近的景点名，搜酒店时可以用“某某附近”
    place_names: list[str]     # 这一段相关的景点（每晚前一天的最后一个、后一天的第一个）
    avg_minutes_to_places: float


SAME_DAY_AREA_KM = 40.0      # 相邻两天的景点重心相距不超过这个距离，算同一片区域
DAY_TRIP_MAX_KM = 150.0      # 孤立的一天离主区域不超过这个距离，按“一日游”处理（酒店仍住主区域）


def _centroid(ps: list[Place]) -> tuple[float, float]:
    return sum(p.lat for p in ps) / len(ps), sum(p.lon for p in ps) / len(ps)


def day_trips(trip: Trip) -> dict[int, tuple[list[str], float]]:
    """找出“一日游”的那几天：这一天的景点自成一片区域（离相邻几天都远）、不是景点最多的主区域，
    且离主区域不超过 DAY_TRIP_MAX_KM。返回 {天序号: (景点名, 离主区域的公里数)}。
    这些天晚上通常回主区域住，所以推荐住宿区域时不把它当成落脚点。"""
    days = trip.plan.days if trip.plan else []
    members = [(d.index, [trip.place(it.place_id) for it in d.items]) for d in days if d.items]
    if len(members) < 2:
        return {}
    groups: list[list[tuple[int, list[Place]]]] = []
    for idx, ps in members:                         # 每天归入最近的、重心在 40 km 内的区域；没有就自成一片
        ca, co = _centroid(ps)
        best, best_km = None, SAME_DAY_AREA_KM + 1
        for g in groups:
            la, lo = _centroid([p for _, q in g for p in q])
            km = haversine_km(la, lo, ca, co)
            if km <= SAME_DAY_AREA_KM and km < best_km:
                best, best_km = g, km
        if best is None:
            groups.append([(idx, ps)])
        else:
            best.append((idx, ps))
    if len(groups) < 2:
        return {}
    main = max(groups, key=lambda g: sum(len(q) for _, q in g))
    ma, mo = _centroid([p for _, q in main for p in q])
    out: dict[int, tuple[list[str], float]] = {}
    for g in groups:
        if g is main or len(g) != 1:
            continue
        idx, ps = g[0]
        ca, co = _centroid(ps)
        km = haversine_km(ma, mo, ca, co)
        if km <= DAY_TRIP_MAX_KM:
            out[idx] = ([p.name for p in ps], round(km, 1))
    return out


def _night_targets(trip: Trip, n: int, skip: frozenset[int] = frozenset()) -> list[Place]:
    """第 n 晚（第 n 天晚上到第 n+1 天早上）最相关的景点：往前最近一个有景点的天的最后一个、往后最近一个有景点的天的第一个。
    一日游的天（skip）不算。"""
    out: list[Place] = []
    days = trip.plan.days if trip.plan else []
    for i in range(min(n, len(days) - 1), -1, -1):
        if i not in skip and days[i].items:
            out.append(trip.place(days[i].items[-1].place_id))
            break
    for i in range(n + 1, len(days)):
        if i not in skip and days[i].items:
            out.append(trip.place(days[i].items[0].place_id))
            break
    return out


def suggest_stay_segments(trip: Trip) -> list[StaySegment]:
    """每晚算一个推荐中心（当晚最相关景点的重心），相邻几晚中心靠得近就合并成一段连住。
    景点分布在不同城市/区域时，会自然分成多段，提示你中途换酒店。没有分天或没有景点时返回空列表。"""
    if trip.plan is None:
        return []
    skip = frozenset(day_trips(trip))
    nights: list[tuple[int, float, float, list[Place]]] = []
    for n in range(max(trip.meta.num_days - 1, 0)):
        pts = _night_targets(trip, n, skip)
        if not pts:
            continue
        nights.append((n, sum(p.lat for p in pts) / len(pts), sum(p.lon for p in pts) / len(pts), pts))
    if not nights:
        return []

    groups: list[list[tuple[int, float, float, list[Place]]]] = []
    for item in nights:
        if groups:
            last = groups[-1][-1]
            contiguous = item[0] == last[0] + 1
            if contiguous and haversine_km(last[1], last[2], item[1], item[2]) <= SAME_AREA_KM:
                groups[-1].append(item)
                continue
        groups.append([item])

    out: list[StaySegment] = []
    for g in groups:
        places: list[Place] = []
        for _, _, _, pts in g:
            for p in pts:
                if p not in places:
                    places.append(p)
        lat = sum(p.lat for p in places) / len(places)
        lon = sum(p.lon for p in places) / len(places)
        dists = [haversine_km(lat, lon, p.lat, p.lon) for p in places]
        mins = [estimate_leg("c", lat, lon, p.id, p.lat, p.lon, trip.meta.mode).minutes for p in places]
        near = min(places, key=lambda p: haversine_km(lat, lon, p.lat, p.lon))
        out.append(StaySegment(
            from_night=g[0][0], to_night=g[-1][0], lat=lat, lon=lon, radius_km=round(max(dists), 2),
            near_place=near.name, place_names=[p.name for p in places],
            avg_minutes_to_places=round(sum(mins) / len(mins), 1),
        ))
    return out
