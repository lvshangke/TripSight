"""天气相关的确定性规则：户外/室内判断、预报是否影响某天的安排。

户外/室内的判断只来自两处：用户（或工具）明确指定的 outdoor，或高德返回的类别文字；都没有就是“未知”，
未知的不会被当成户外，也不会触发提醒。预报只来自高德，且只缓存查到的那几天，不会编造。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .geo import haversine_km
from .models import Place, Trip
from .routeplace import entry

_INDOOR_WORDS = ("博物馆", "美术馆", "展览馆", "科技馆", "图书馆", "纪念馆", "艺术馆", "文化宫", "剧院", "影院", "商场", "购物中心", "水族馆")
_OUTDOOR_WORDS = ("公园", "广场", "风景名胜", "旅游景点", "城墙", "古迹", "步行街", "商业街", "古镇", "山", "湖", "海滩", "动物园", "植物园", "寺庙", "道教")


def outdoor_from_category(category: str) -> Optional[bool]:
    if not category:
        return None
    if any(w in category for w in _INDOOR_WORDS):
        return False
    if any(w in category for w in _OUTDOOR_WORDS):
        return True
    return None


def is_outdoor(p: Place) -> Optional[bool]:
    """True 户外 / False 室内 / None 未知。路线型景点（边走边逛）按户外。"""
    if p.outdoor is not None:
        return p.outdoor
    if p.waypoints:
        return True
    return outdoor_from_category(p.category)


SOURCE_NAMES = {"amap": "高德", "open-meteo": "Open-Meteo"}


def fmt_snap(w) -> str:
    """一天预报的一行文字（含来源和查询日期）。夜间天气没有时只写气温。"""
    day = f"白天{w.day_weather}" + (f" {w.day_temp:.0f}°C" if w.day_temp is not None else "")
    night = ""
    if w.night_weather or w.night_temp is not None:
        night = "，夜间" + (w.night_weather or "") + (f" {w.night_temp:.0f}°C" if w.night_temp is not None else "")
    where = f"「{w.location}」一带，" if getattr(w, "location", "") else ""
    return f"{day}{night}（{where}{SOURCE_NAMES.get(w.source, w.source)}预报，{w.fetched} 查询，之后可能变化）"


def bad_weather(day_weather: str, night_weather: str, day_temp: Optional[float]) -> list[str]:
    """对户外安排不利的天气因素（文字），没有则为空列表。"""
    out = []
    txt = (day_weather or "") + (night_weather or "")
    if "雨" in txt or "雪" in txt or "冰雹" in txt:
        out.append("有雨雪")
    if day_temp is not None and day_temp >= 35:
        out.append("高温")
    return out


GROUP_KM = 10.0     # 相距不超过这个距离的各天，合并成同一个天气位置


@dataclass
class WeatherSpot:
    lat: float
    lon: float
    label: str               # 离重心最近的景点名，用来说明“哪一带”
    days: list[int]          # 第几天（0 起）


def weather_spots(trip: Trip) -> list[WeatherSpot]:
    """每天按当天景点的重心确定天气位置，相近的天合并；没安排景点的天沿用当天酒店或全程重心。"""
    if trip.plan is None:
        return []
    allp = [(p.name, *_pt(p)) for p in trip.places]
    if not allp and not trip.lodgings:
        return []
    overall = (sum(a[1] for a in allp) / len(allp), sum(a[2] for a in allp) / len(allp)) if allp else (trip.lodgings[0].lat, trip.lodgings[0].lon)
    per_day: list[tuple[int, float, float, str]] = []
    for day in trip.plan.days:
        names = [(trip.place(it.place_id).name, *_pt(trip.place(it.place_id))) for it in day.items]
        if names:
            la, lo = sum(n[1] for n in names) / len(names), sum(n[2] for n in names) / len(names)
            label = min(names, key=lambda n: haversine_km(la, lo, n[1], n[2]))[0]
        else:
            lod = trip.lodging_for_day(day.index)
            la, lo = (lod.lat, lod.lon) if lod else overall
            label = lod.name if lod else ""
        per_day.append((day.index, la, lo, label))
    spots: list[WeatherSpot] = []
    for idx, la, lo, label in per_day:
        for sp in spots:
            if haversine_km(sp.lat, sp.lon, la, lo) <= GROUP_KM:
                sp.days.append(idx)
                break
        else:
            spots.append(WeatherSpot(la, lo, label, [idx]))
    return spots


def _pt(p: Place) -> tuple[float, float]:
    e = entry(p)
    return e.lat, e.lon
