"""天气相关的确定性规则：户外/室内判断、预报是否影响某天的安排。

户外/室内的判断只来自两处：用户（或工具）明确指定的 outdoor，或高德返回的类别文字；都没有就是“未知”，
未知的不会被当成户外，也不会触发提醒。预报只来自高德，且只缓存查到的那几天，不会编造。
"""

from __future__ import annotations

from typing import Optional

from .models import Place

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


def bad_weather(day_weather: str, night_weather: str, day_temp: Optional[float]) -> list[str]:
    """对户外安排不利的天气因素（文字），没有则为空列表。"""
    out = []
    txt = (day_weather or "") + (night_weather or "")
    if "雨" in txt or "雪" in txt or "冰雹" in txt:
        out.append("有雨雪")
    if day_temp is not None and day_temp >= 35:
        out.append("高温")
    return out
