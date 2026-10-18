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


def is_mainland(lat: float, lon: float) -> bool:
    if out_of_china(lat, lon):
        return False
    return not any(a <= lat <= b and c <= lon <= d for a, b, c, d in _NON_MAINLAND)


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
