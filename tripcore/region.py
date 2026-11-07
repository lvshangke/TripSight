"""行程在国内还是境外，以及用哪个地图后端（高德 / Google）。

“国内”指中国大陆：港澳台按境外处理（高德在那里数据很少）。判断只看景点/酒店坐标，不联网。
"""

from __future__ import annotations

from typing import Optional

from .coords import out_of_china
from .models import Trip

BACKENDS = ("amap", "google")
# 港澳台的粗略范围（够用即可，不追求精确边界）
_NON_MAINLAND = [
    (21.8, 25.4, 119.3, 122.1),     # 台湾
    (22.1, 22.6, 113.8, 114.5),     # 香港
    (22.1, 22.25, 113.5, 113.65),   # 澳门
]


# 中国大陆的粗略轮廓（经度, 纬度），顺时针；海岸线向海里放宽了约 2°（黄海、东海离日韩还有距离），边界误差约 ±1°，
# 只用来分“国内/境外”（选地图后端、决定能不能用高德反查），不追求精确国界。
_CHINA = [
    (121.0, 53.9), (123.6, 53.9), (126.0, 52.8), (127.5, 49.8), (129.5, 49.4), (131.0, 47.7), (134.8, 48.4), (133.6, 45.9),
    (131.0, 44.9), (131.2, 43.0), (130.7, 42.3), (129.0, 42.0), (128.0, 41.4), (126.5, 40.8), (125.0, 40.0), (124.3, 39.7),
    (123.4, 38.0), (123.4, 35.5), (123.6, 31.0), (123.4, 28.0), (122.3, 25.0), (120.5, 22.5), (118.5, 20.5), (113.0, 20.0),
    (109.8, 20.3), (108.5, 21.3), (107.9, 21.5), (106.7, 22.0), (106.0, 22.8), (105.5, 23.3), (104.8, 22.8), (104.0, 22.4),
    (102.2, 22.4), (101.7, 21.1), (101.1, 21.7), (100.2, 21.5), (99.2, 22.1), (98.8, 23.9), (97.8, 24.0), (97.6, 25.2),
    (98.7, 27.6), (97.4, 28.3), (96.1, 29.0), (94.0, 27.6), (92.1, 27.8), (91.6, 28.1), (89.0, 27.3), (86.9, 27.9),
    (84.0, 28.7), (81.4, 30.1), (79.1, 31.0), (78.5, 32.6), (78.7, 34.4), (79.5, 35.5), (77.8, 35.5), (75.0, 36.9),
    (74.4, 37.3), (73.6, 38.8), (73.7, 39.5), (75.0, 40.4), (76.9, 41.0), (80.2, 42.2), (80.3, 45.0), (82.6, 45.3),
    (83.0, 47.0), (85.5, 47.1), (87.8, 49.2), (90.5, 47.9), (91.0, 46.0), (96.4, 42.7), (100.0, 42.6), (105.0, 41.6),
    (111.0, 43.7), (111.9, 45.1), (116.0, 45.7), (119.3, 46.7), (116.7, 49.8), (119.3, 50.5), (120.0, 52.3),
]


def _in_poly(lat: float, lon: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def is_mainland(lat: float, lon: float) -> bool:
    """在中国大陆吗（含海南）。港澳台、日韩、东南亚、俄罗斯等都算境外——高德只在大陆有可靠数据。"""
    if out_of_china(lat, lon):
        return False
    if any(a <= lat <= b and c <= lon <= d for a, b, c, d in _NON_MAINLAND):
        return False
    if 18.0 <= lat <= 20.3 and 108.5 <= lon <= 111.3:                 # 海南
        return True
    return _in_poly(lat, lon, _CHINA)


def trip_region(trip: Trip) -> str:
    """'cn'（大陆）或 'abroad'。大多数点在大陆就是 cn；没有任何点时按 cn（保持原有行为）。"""
    pts = [(p.lat, p.lon) for p in trip.places] + [(l.lat, l.lon) for l in trip.lodgings]
    if not pts:
        return "cn"
    inside = sum(1 for lat, lon in pts if is_mainland(lat, lon))
    return "cn" if inside * 2 >= len(pts) else "abroad"


def pick_backend(requested: Optional[str], region: str, has_amap: bool, has_google: bool) -> tuple[Optional[str], str]:
    """返回 (后端, 说明)。后端为 None 表示没有可用的 key。说明为空表示没有需要提醒的。
    requested：用户指定的 amap / google；None 表示自动（国内高德、境外 Google，缺哪个 key 就用另一个并提醒）。"""
    if requested in BACKENDS:
        have = has_amap if requested == "amap" else has_google
        if not have:
            return None, f"这个行程指定用 {'高德' if requested == 'amap' else 'Google'}，但没有配置对应的 key"
        warn = ""
        if requested == "amap" and region == "abroad":
            warn = "目的地在境外，高德的数据可能不全"
        if requested == "google" and region == "cn":
            warn = "目的地在中国大陆，Google 的数据可能不全或访问不稳"
        return requested, warn
    want = "amap" if region == "cn" else "google"
    other = "google" if want == "amap" else "amap"
    have = {"amap": has_amap, "google": has_google}
    if have[want]:
        return want, ""
    if have[other]:
        name = "Google" if other == "google" else "高德"
        where = "中国大陆" if region == "cn" else "境外"
        return other, f"目的地在{where}，但只配置了{name}的 key，数据可能不全"
    return None, ""
