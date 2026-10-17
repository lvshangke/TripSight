"""Open-Meteo 天气预报（免费、不需要 key、全球覆盖、最长约 16 天）。

只用来补高德覆盖不到的情况：境外目的地，或日期超出高德约 4 天的预报范围。
返回的结构和高德的 WeatherDay 一样，其余代码不需要区分来源。
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Optional

from .amap import WeatherDay

BASE = "https://api.open-meteo.com/v1/forecast"
MAX_DAYS = 16


class WeatherError(Exception):
    pass


# WMO 天气代码 → 中文（只列 Open-Meteo 会返回的）
_WMO = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "小阵雨", 81: "阵雨", 82: "强阵雨", 85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
}
_WEEK = ["1", "2", "3", "4", "5", "6", "7"]


def wmo_text(code: Optional[int]) -> str:
    return _WMO.get(code, "") if code is not None else ""


def parse(data: dict[str, Any]) -> list[WeatherDay]:
    d = data.get("daily") or {}
    dates = d.get("time") or []
    codes = d.get("weather_code") or []
    tmax = d.get("temperature_2m_max") or []
    tmin = d.get("temperature_2m_min") or []
    out: list[WeatherDay] = []
    from datetime import date as _date
    for i, ds in enumerate(dates):
        try:
            wk = _WEEK[_date.fromisoformat(ds).weekday()]
        except ValueError:
            wk = ""
        code = codes[i] if i < len(codes) else None
        out.append(WeatherDay(
            date=ds, week=wk, day_weather=wmo_text(code) or "未知", night_weather="",
            day_temp=tmax[i] if i < len(tmax) else None, night_temp=tmin[i] if i < len(tmin) else None,
        ))
    return out


class OpenMeteoClient:
    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def forecast(self, lat: float, lon: float, days: int = MAX_DAYS) -> list[WeatherDay]:
        q = urllib.parse.urlencode({
            "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "timezone": "auto",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min", "forecast_days": min(days, MAX_DAYS),
        })
        req = urllib.request.Request(f"{BASE}?{q}", headers={"User-Agent": "tripcore/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # 网络、超时、非 JSON
            raise WeatherError(f"Open-Meteo 查询失败：{type(e).__name__}") from None
        if not isinstance(data, dict) or data.get("error"):
            raise WeatherError("Open-Meteo 返回了错误")
        return parse(data)
