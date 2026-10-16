"""地理计算：两点距离、通勤时间估算。

注意：这里的通勤时间是“估算”，只用经纬度和经验速度换算，不查真实路线。
真实路线（地图服务）会在里程碑 3 接入，到时 Leg.detail_level 会从 estimate 升级为 route。
"""

from __future__ import annotations

import math

from .models import Leg, TravelMode

EARTH_RADIUS_KM = 6371.0088

# 直线距离 → 实际路程的绕行系数（城市道路不是直线）
DETOUR_FACTOR = 1.3

# 短于这个距离（按绕行后的路程算），无论选什么方式都按步行估算
WALK_THRESHOLD_KM = 1.2

# 每种方式的“有效速度”（公里/小时，已含等红灯、换乘、堵车等的粗略折算），按路程分段。
# 格式：[(路程上限km, 速度km/h), ...]，最后一段用 inf 表示无上限。
_SPEED_BANDS: dict[str, list[tuple[float, float]]] = {
    "walk": [(math.inf, 4.5)],
    "transit": [(5, 15.0), (20, 22.0), (math.inf, 35.0)],
    "drive": [(5, 22.0), (20, 30.0), (math.inf, 55.0)],
}

# 每段固定开销（分钟）：等车、找车位等
_FIXED_OVERHEAD_MIN: dict[str, int] = {"walk": 0, "transit": 10, "drive": 5}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两个经纬度之间的直线（球面）距离，单位公里。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _speed_for(mode: str, route_km: float) -> float:
    for upper, speed in _SPEED_BANDS[mode]:
        if route_km <= upper:
            return speed
    return _SPEED_BANDS[mode][-1][1]


def estimate_leg(
    from_id: str,
    from_lat: float,
    from_lon: float,
    to_id: str,
    to_lat: float,
    to_lon: float,
    preferred_mode: TravelMode = "transit",
) -> Leg:
    """估算从 A 到 B 的交通（返回一个 detail_level="estimate" 的 Leg）。"""
    straight = haversine_km(from_lat, from_lon, to_lat, to_lon)
    route_km = straight * DETOUR_FACTOR

    # 很近的话直接走路
    mode: TravelMode = "walk" if route_km < WALK_THRESHOLD_KM else preferred_mode

    minutes = route_km / _speed_for(mode, route_km) * 60 + _FIXED_OVERHEAD_MIN[mode]
    if route_km == 0:
        minutes = 0
    return Leg(
        from_id=from_id,
        to_id=to_id,
        mode=mode,
        distance_km=round(route_km, 2),
        minutes=int(math.ceil(minutes)),
        detail_level="estimate",
    )
