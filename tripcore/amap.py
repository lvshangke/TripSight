"""高德地图 Web 服务封装：地点搜索、地理编码、路线时间。

- 只用标准库联网（urllib），不增加依赖。
- key 从环境变量 AMAP_KEY 读取，绝不写进代码或文件。
- 对外的经纬度一律是 WGS84（和 tripcore 其他部分一致）；和高德交互时内部转成 GCJ-02。
- 出错一律抛 AmapError，调用方决定是否降级（例如退回 OpenStreetMap / 距离估算）。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .coords import gcj02_to_wgs84, wgs84_to_gcj02

BASE_URL = "https://restapi.amap.com"
_MIN_INTERVAL_S = 0.4   # 个人 key 有 QPS 限制，请求之间留点间隔
_RETRY_CODES = {"CUQPS_HAS_EXCEEDED_THE_LIMIT", "CKQPS_HAS_EXCEEDED_THE_LIMIT", "ACCESS_TOO_FREQUENT"}


class AmapError(Exception):
    pass


@dataclass
class PlaceHit:
    name: str
    lat: float                 # WGS84
    lon: float                 # WGS84
    address: str = ""
    city: str = ""
    district: str = ""
    category: str = ""
    amap_id: str = ""
    rating: Optional[float] = None
    cost: Optional[float] = None      # 高德“人均消费”，仅餐饮/酒店/景点/影院有，是参考值不是实时价
    opentime_today: str = ""
    opentime_week: str = ""
    tel: str = ""


@dataclass
class RouteResult:
    mode: str                  # walk / transit / drive
    distance_km: float
    minutes: int
    # 以下只有公交/地铁方案才有
    transfers: Optional[int] = None
    walking_km: Optional[float] = None
    cost_yuan: Optional[float] = None
    lines: list[str] = field(default_factory=list)
    uses_subway: bool = False
    path: list[tuple[float, float]] = field(default_factory=list)   # 路线形状 (lat, lon)，WGS84，已抽稀
    warning: str = ""          # 不满足用户偏好时的说明（如换乘超限）


@dataclass
class WeatherDay:
    date: str            # YYYY-MM-DD
    week: str
    day_weather: str
    night_weather: str
    day_temp: Optional[float]
    night_temp: Optional[float]


# 公交策略（高德 transit 接口的 strategy 参数）
TRANSIT_STRATEGIES = {"fastest": 0, "cheapest": 1, "fewest_transfers": 2, "least_walking": 3, "no_subway": 5}


_MAX_PATH_POINTS = 250


def _parse_polyline(text: Any) -> list[tuple[float, float]]:
    """高德 polyline "lon,lat;lon,lat;…"（GCJ-02）→ [(lat, lon)]（WGS84）。坏点直接跳过。"""
    out: list[tuple[float, float]] = []
    if not isinstance(text, str):
        return out
    for pair in text.split(";"):
        try:
            lon_g, lat_g = (float(x) for x in pair.split(","))
        except ValueError:
            continue
        lat, lon = gcj02_to_wgs84(lat_g, lon_g)
        out.append((round(lat, 5), round(lon, 5)))
    return out


def _thin(points: list[tuple[float, float]], limit: int = _MAX_PATH_POINTS) -> list[tuple[float, float]]:
    """等间隔抽稀，保留首尾，避免缓存过大。"""
    if len(points) <= limit:
        return points
    step = (len(points) - 1) / (limit - 1)
    idx = sorted({round(i * step) for i in range(limit)} | {len(points) - 1})
    return [points[i] for i in idx]


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _text(v: Any) -> str:
    """高德对“没有”的字段常返回 [] 或 ""。"""
    return v if isinstance(v, str) else ""


class AmapClient:
    def __init__(self, key: str, timeout: int = 15, opener: Optional[Callable[[str], dict]] = None,
                 log_path: Optional[Path] = None):
        if not key:
            raise AmapError("没有高德 key")
        self._key = key
        self._log_path = log_path
        self._timeout = timeout
        self._opener = opener          # 测试时注入假的网络层
        self._last = 0.0

    @classmethod
    def from_env(cls, log_path: Optional[Path] = None) -> Optional["AmapClient"]:
        key = os.environ.get("AMAP_KEY", "").strip()
        return cls(key, log_path=log_path) if key else None

    def _audit(self, path: str, params: dict[str, Any], outcome: str) -> None:
        """每次请求记一行（时间、接口、参数、结果），方便确认确实调用了高德。不含 key。"""
        if self._log_path is None:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            shown = {k: v for k, v in params.items() if k not in ("key", "show_fields")}
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat(timespec='seconds')} | {path} | {shown} | {outcome}\n")
        except OSError:
            pass

    # ---- 底层请求 ----
    def _get(self, path: str, params: dict[str, Any]) -> dict:
        query = urllib.parse.urlencode({**params, "key": self._key})
        url = f"{BASE_URL}{path}?{query}"
        for attempt in range(3):
            if self._opener is None:
                wait = _MIN_INTERVAL_S - (time.monotonic() - self._last)
                if wait > 0:
                    time.sleep(wait)
            try:
                if self._opener is not None:
                    data = self._opener(url)
                else:
                    with urllib.request.urlopen(url, timeout=self._timeout) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                self._audit(path, params, f"网络失败 {type(e).__name__}")
                raise AmapError(f"高德请求失败：{type(e).__name__}") from None   # 不带 URL，避免把 key 打进日志
            finally:
                self._last = time.monotonic()
            if str(data.get("status")) == "1":
                self._audit(path, params, "OK")
                return data
            info = str(data.get("info", ""))
            self._audit(path, params, f"错误 {info}")
            if info in _RETRY_CODES and attempt < 2:
                time.sleep(1.0)
                continue
            raise AmapError(f"高德返回错误：{info or data.get('infocode', '未知')}")
        raise AmapError("高德请求多次失败")

    # ---- 地点 ----
    def search_places(self, query: str, city: Optional[str] = None, limit: int = 5) -> list[PlaceHit]:
        params: dict[str, Any] = {
            "keywords": query, "page_size": max(1, min(limit, 10)),
            "show_fields": "business",
        }
        if city:
            params.update({"region": city, "city_limit": "true"})
        data = self._get("/v5/place/text", params)
        return self._parse_pois(data)

    def search_around(self, lat: float, lon: float, radius_m: int = 800, types: str = "050000",
                      keywords: str = "", limit: int = 20) -> list[PlaceHit]:
        """以某点为中心搜周边（默认餐饮类 050000）。lat/lon 是 WGS84。"""
        g_lat, g_lon = wgs84_to_gcj02(lat, lon)
        params: dict[str, Any] = {
            "location": f"{g_lon:.6f},{g_lat:.6f}", "radius": max(100, min(int(radius_m), 5000)),
            "page_size": max(1, min(limit, 25)), "show_fields": "business",
            "sortrule": "distance",
        }
        if types:
            params["types"] = types
        if keywords:
            params["keywords"] = keywords
        return self._parse_pois(self._get("/v5/place/around", params))

    @staticmethod
    def _parse_pois(data: dict) -> list[PlaceHit]:
        hits: list[PlaceHit] = []
        for poi in data.get("pois", []) or []:
            loc = _text(poi.get("location"))
            try:
                lon_g, lat_g = (float(x) for x in loc.split(","))
            except ValueError:
                continue
            lat, lon = gcj02_to_wgs84(lat_g, lon_g)
            biz = poi.get("business") or {}
            hits.append(PlaceHit(
                name=_text(poi.get("name")), lat=lat, lon=lon,
                address=_text(poi.get("address")), city=_text(poi.get("cityname")),
                district=_text(poi.get("adname")), category=_text(poi.get("type")),
                amap_id=_text(poi.get("id")),
                rating=_num(biz.get("rating")), cost=_num(biz.get("cost")),
                opentime_today=_text(biz.get("opentime_today")),
                opentime_week=_text(biz.get("opentime_week")), tel=_text(biz.get("tel")),
            ))
        return hits

    def geocode(self, address: str, city: Optional[str] = None) -> Optional[tuple[float, float]]:
        """地址/城市名 → (lat, lon)（WGS84）。找不到返回 None。"""
        params: dict[str, Any] = {"address": address}
        if city:
            params["city"] = city
        data = self._get("/v3/geocode/geo", params)
        codes = data.get("geocodes") or []
        if not codes:
            return None
        try:
            lon_g, lat_g = (float(x) for x in _text(codes[0].get("location")).split(","))
        except ValueError:
            return None
        return gcj02_to_wgs84(lat_g, lon_g)

    # ---- 天气 ----
    def adcode(self, city: str) -> Optional[str]:
        """城市名 → 行政区划代码 adcode（天气接口需要）。"""
        data = self._get("/v3/geocode/geo", {"address": city})
        codes = data.get("geocodes") or []
        return _text(codes[0].get("adcode")) or None if codes else None

    def forecast(self, adcode: str) -> list[WeatherDay]:
        """未来几天（高德约 4 天）的天气预报。"""
        data = self._get("/v3/weather/weatherInfo", {"city": adcode, "extensions": "all"})
        out: list[WeatherDay] = []
        for f in data.get("forecasts") or []:
            for c in f.get("casts") or []:
                out.append(WeatherDay(
                    date=_text(c.get("date")), week=_text(c.get("week")),
                    day_weather=_text(c.get("dayweather")), night_weather=_text(c.get("nightweather")),
                    day_temp=_num(c.get("daytemp")), night_temp=_num(c.get("nighttemp")),
                ))
        return out

    # ---- 路线 ----
    def route(self, mode: str, from_lat: float, from_lon: float, to_lat: float, to_lon: float,
              city: Optional[str] = None, transit_strategy: str = "fastest",
              max_transfers: Optional[int] = None, prefer_subway: bool = False,
              depart: Optional[Any] = None) -> RouteResult:
        o_lat, o_lon = wgs84_to_gcj02(from_lat, from_lon)
        d_lat, d_lon = wgs84_to_gcj02(to_lat, to_lon)
        origin, dest = f"{o_lon:.6f},{o_lat:.6f}", f"{d_lon:.6f},{d_lat:.6f}"
        if mode == "walk":
            data = self._get("/v3/direction/walking", {"origin": origin, "destination": dest})
            return self._from_paths("walk", data)
        if mode == "drive":
            data = self._get("/v3/direction/driving", {"origin": origin, "destination": dest})
            return self._from_paths("drive", data)
        if mode == "transit":
            if not city:
                raise AmapError("公交路线需要城市名")
            if transit_strategy not in TRANSIT_STRATEGIES:
                raise AmapError(f"不支持的公交策略：{transit_strategy}")
            def query(strategy: str) -> list[RouteResult]:
                params = {"origin": origin, "destination": dest, "city": city, "cityd": city,
                          "strategy": TRANSIT_STRATEGIES[strategy]}
                if depart is not None:       # 按出发时间查（含夜班车），避免拿白天的地铁方案套深夜
                    params.update({"date": f"{depart.year}-{depart.month}-{depart.day}",
                                   "time": f"{depart.hour}:{depart.minute:02d}", "nightflag": "1"})
                return self._transit_options(self._get("/v3/direction/transit/integrated", params))

            options = query(transit_strategy)
            if max_transfers is None and not prefer_subway:
                return options[0]
            ok = [r for r in options if max_transfers is None or (r.transfers or 0) <= max_transfers]
            if not ok and transit_strategy != "fewest_transfers":
                options += query("fewest_transfers")           # 默认方案换乘太多，再查「少换乘」方案
                ok = [r for r in options if max_transfers is None or (r.transfers or 0) <= max_transfers]
            pool = ok or [min(options, key=lambda r: (r.transfers or 0, r.minutes))]
            best = min(pool, key=lambda r: r.minutes)
            if prefer_subway:
                subway = [r for r in pool if r.uses_subway]
                if subway:
                    fastest_subway = min(subway, key=lambda r: r.minutes)
                    if fastest_subway.minutes <= best.minutes * 1.3:      # 地铁方案最多慢 30% 才优先
                        best = fastest_subway
            if not ok and max_transfers is not None:
                best.warning = f"高德所有方案都要换乘 {best.transfers} 次，超过你的上限 {max_transfers} 次"
            return best
        raise AmapError(f"不支持的出行方式：{mode}")

    @staticmethod
    def _transit_options(data: dict) -> list[RouteResult]:
        route = data.get("route") or {}
        transits = route.get("transits") or []
        out: list[RouteResult] = []
        for t in transits:
            dur, dist = _num(t.get("duration")), _num(t.get("distance")) or _num(route.get("distance"))
            if dur is None or dist is None:
                continue
            lines: list[tuple[str, str]] = []
            path: list[tuple[float, float]] = []
            for seg in t.get("segments") or []:
                for st in ((seg.get("walking") or {}).get("steps")) or []:
                    path += _parse_polyline(st.get("polyline"))
                buslines = ((seg.get("bus") or {}).get("buslines")) or []
                if buslines:
                    lines.append((_text(buslines[0].get("name")).split("(")[0], _text(buslines[0].get("type"))))
                    path += _parse_polyline(buslines[0].get("polyline"))
            walk_m = _num(t.get("walking_distance"))
            out.append(RouteResult(
                "transit", round(dist / 1000, 2), max(1, round(dur / 60)),
                transfers=max(len(lines) - 1, 0),
                walking_km=None if walk_m is None else round(walk_m / 1000, 2),
                cost_yuan=_num(t.get("cost")),
                lines=[n for n, _ in lines],
                uses_subway=any("地铁" in n or "地铁" in ty for n, ty in lines),
                path=_thin(path),
            ))
        if not out:
            raise AmapError("没有找到公交方案" if not transits else "公交结果缺少时间或距离")
        return out

    @staticmethod
    def _from_paths(mode: str, data: dict) -> RouteResult:
        paths = (data.get("route") or {}).get("paths") or []
        if not paths:
            raise AmapError("没有找到路线")
        dur, dist = _num(paths[0].get("duration")), _num(paths[0].get("distance"))
        if dur is None or dist is None:
            raise AmapError("路线结果缺少时间或距离")
        path: list[tuple[float, float]] = []
        for st in paths[0].get("steps") or []:
            path += _parse_polyline(st.get("polyline"))
        return RouteResult(mode, round(dist / 1000, 2), max(1, round(dur / 60)), path=_thin(path))
