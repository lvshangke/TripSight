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
    tel: str = ""


@dataclass
class RouteResult:
    mode: str                  # walk / transit / drive
    distance_km: float
    minutes: int


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
                opentime_today=_text(biz.get("opentime_today")), tel=_text(biz.get("tel")),
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

    # ---- 路线 ----
    def route(self, mode: str, from_lat: float, from_lon: float, to_lat: float, to_lon: float,
              city: Optional[str] = None) -> RouteResult:
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
            data = self._get("/v3/direction/transit/integrated",
                             {"origin": origin, "destination": dest, "city": city, "cityd": city})
            route = data.get("route") or {}
            transits = route.get("transits") or []
            if not transits:
                raise AmapError("没有找到公交方案")
            t = transits[0]
            dur, dist = _num(t.get("duration")), _num(t.get("distance")) or _num(route.get("distance"))
            if dur is None or dist is None:
                raise AmapError("公交结果缺少时间或距离")
            return RouteResult("transit", round(dist / 1000, 2), max(1, round(dur / 60)))
        raise AmapError(f"不支持的出行方式：{mode}")

    @staticmethod
    def _from_paths(mode: str, data: dict) -> RouteResult:
        paths = (data.get("route") or {}).get("paths") or []
        if not paths:
            raise AmapError("没有找到路线")
        dur, dist = _num(paths[0].get("duration")), _num(paths[0].get("distance"))
        if dur is None or dist is None:
            raise AmapError("路线结果缺少时间或距离")
        return RouteResult(mode, round(dist / 1000, 2), max(1, round(dur / 60)))
