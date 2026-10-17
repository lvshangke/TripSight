"""长途旅行换酒店的建议（确定性规则，只给提示，不改行程）。

做法：把相邻的天按“景点重心”切成几段，同一段里各天的重心不要离得太远；
如果某一段的重心离当时住的酒店太远，就建议这一段另住一家。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .geo import haversine_km
from .metrics import day_places
from .models import Trip
from .routeplace import entry

MIN_TRIP_DAYS = 4        # 少于这么多天不建议换酒店（折腾不值得）
SEG_KM = 10.0            # 同一段内，某天重心离已有各天平均重心不超过这个距离
STAY_FAR_KM = 8.0        # 某段重心离当时酒店超过这个距离，才建议换
MIN_SEG_DAYS = 2         # 一家酒店至少住这么多天（只有一晚的段并入相邻段）


@dataclass(frozen=True)
class StaySegment:
    from_day: int            # 0 起，含
    to_day: int
    lat: float
    lon: float
    near: str                # 重心最近的景点名，用来描述“在哪一带”
    km_to_hotel: Optional[float]


def _centroid(pts: list[tuple[float, float]]) -> tuple[float, float]:
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def suggest_segments(trip: Trip) -> list[StaySegment]:
    """返回建议的分段；不需要换酒店时返回空列表。"""
    if trip.plan is None or trip.meta.num_days < MIN_TRIP_DAYS:
        return []
    day_pts: dict[int, list[tuple[float, float]]] = {}
    names: dict[int, list[tuple[str, float, float]]] = {}
    for day in trip.plan.days:
        ps = day_places(trip, day)
        if ps:
            es = [entry(p) for p in ps]
            day_pts[day.index] = [(e.lat, e.lon) for e in es]
            names[day.index] = [(p.name, e.lat, e.lon) for p, e in zip(ps, es)]
    idxs = sorted(day_pts)
    if len(idxs) < 2 * MIN_SEG_DAYS:
        return []
    cent = {i: _centroid(day_pts[i]) for i in idxs}
    # 贪心分段
    segs: list[list[int]] = [[idxs[0]]]
    for i in idxs[1:]:
        c = _centroid([cent[j] for j in segs[-1]])
        if haversine_km(c[0], c[1], cent[i][0], cent[i][1]) <= SEG_KM:
            segs[-1].append(i)
        else:
            segs.append([i])
    # 太短的段并入重心更近的相邻段
    changed = True
    while changed and len(segs) > 1:
        changed = False
        for k, sg in enumerate(segs):
            if len(sg) >= MIN_SEG_DAYS:
                continue
            c = _centroid([cent[j] for j in sg])
            nb = [x for x in (k - 1, k + 1) if 0 <= x < len(segs)]
            best = min(nb, key=lambda x: haversine_km(c[0], c[1], *_centroid([cent[j] for j in segs[x]])))
            segs[best] = sorted(segs[best] + sg)
            del segs[k]
            changed = True
            break
    if len(segs) < 2:
        return []
    out: list[StaySegment] = []
    any_far = False
    last_day = trip.meta.num_days - 1
    for k, sg in enumerate(segs):
        pts = [p for i in sg for p in day_pts[i]]
        lat, lon = _centroid(pts)
        near = min((n for i in sg for n in names[i]), key=lambda n: haversine_km(lat, lon, n[1], n[2]))[0]
        # 段覆盖的天数：从上一段结束的次日起到本段最后一个有安排的天（最后一段延伸到最后一天）
        start = 0 if k == 0 else out[-1].to_day + 1
        end = last_day if k == len(segs) - 1 else sg[-1]
        lod = trip.lodging_for_day(sg[0])
        km = haversine_km(lat, lon, lod.lat, lod.lon) if lod else None
        if km is None or km > STAY_FAR_KM:
            any_far = True
        out.append(StaySegment(start, end, lat, lon, near, km))
    return out if any_far else []


def hint_text(trip: Trip) -> Optional[str]:
    segs = suggest_segments(trip)
    if not segs:
        return None
    parts = []
    for s in segs:
        d = f"第{s.from_day + 1}天" if s.from_day == s.to_day else f"第{s.from_day + 1}–{s.to_day + 1}天"
        far = f"，离当前酒店约 {s.km_to_hotel:.0f} km" if s.km_to_hotel is not None else ""
        parts.append(f"{d}景点集中在「{s.near}」一带{far}")
    return ("住宿建议：" + "；".join(parts) + "。长途行程可以考虑分段住宿，每段住在各自那一带，少跑路。"
            "这只是建议、没有改动行程；要采用，请告诉我各段住哪家（可先用 suggest_lodging 或酒店搜索找候选），确认后用 set_stays 设置。")
