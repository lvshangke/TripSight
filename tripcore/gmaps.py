"""Google Maps 封装（Places API (New) + Routes API），接口和 AmapClient 保持一致，调用方不用区分。

- 只用标准库联网；key 从环境变量 GOOGLE_MAPS_KEY 读取，放在请求头里，绝不写进 URL、日志或文件。
- 对外经纬度一律是 WGS84（Google 本来就是），不需要坐标转换。
- 出错抛 GoogleError（是 AmapError 的子类，现有的降级逻辑照常生效）。
- 请求只申请需要的字段（field mask），控制计费。
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from .amap import AmapError, PlaceHit, RouteResult, _close_gaps, _thin

PLACES_URL = "https://places.googleapis.com/v1"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
_MIN_INTERVAL_S = 0.1
_PLACE_FIELDS = ("places.id,places.displayName,places.formattedAddress,places.location,places.rating,"
                 "places.priceRange,places.regularOpeningHours,places.primaryTypeDisplayName,"
                 "places.nationalPhoneNumber")
_ROUTE_FIELDS = ("routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,"
                 "routes.legs.steps.travelMode,routes.legs.steps.distanceMeters,routes.legs.steps.transitDetails")
_TRAVEL_MODE = {"walk": "WALK", "drive": "DRIVE", "transit": "TRANSIT"}
_SUBWAY = {"SUBWAY", "METRO_RAIL", "LIGHT_RAIL", "MONORAIL"}
_RAIL = {"HEAVY_RAIL", "RAIL", "COMMUTER_TRAIN", "HIGH_SPEED_TRAIN", "LONG_DISTANCE_TRAIN", "INTERCITY_BUS"}
_WEEK = "一二三四五六日"
_FOOD_TYPES = "050000"       # 和高德的“餐饮”类别码对应：调用方沿用这个值表示找餐厅


class GoogleError(AmapError):
    pass


def decode_polyline(text: str) -> list[tuple[float, float]]:
    """Google 折线编码（精度 1e-5）→ [(lat, lon)]。"""
    pts: list[tuple[float, float]] = []
    i, lat, lon = 0, 0, 0
    while i < len(text):
        for is_lat in (True, False):
            shift = result = 0
            while True:
                if i >= len(text):
                    return pts
                b = ord(text[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            d = ~(result >> 1) if result & 1 else result >> 1
            if is_lat:
                lat += d
            else:
                lon += d
        pts.append((lat / 1e5, lon / 1e5))
    return pts


def _secs(v: Any) -> Optional[float]:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", str(v or ""))
    return float(m.group(1)) if m else None


def _money(m: Any) -> Optional[float]:
    if not isinstance(m, dict):
        return None
    try:
        return float(m.get("units") or 0) + float(m.get("nanos") or 0) / 1e9
    except (TypeError, ValueError):
        return None


def _hours_text(oh: Any) -> tuple[str, str]:
    """regularOpeningHours → (今天, 一周)，写成和高德一样的“周一 09:00-17:00；周二 休息”，这样 hours.py 能解析。"""
    descs = (oh or {}).get("weekdayDescriptions") if isinstance(oh, dict) else None
    if not descs:
        return "", ""
    parts: list[str] = []
    for i, d in enumerate(descs[:7]):
        times = re.findall(r"(\d{1,2}):(\d{2})\s*[–\-—~至到]\s*(\d{1,2}):(\d{2})", str(d))
        if times:
            body = " ".join(f"{int(a):02d}:{b}-{int(c):02d}:{e}" for a, b, c, e in times)
        elif re.search(r"24\s*小时|全天|Open 24", str(d)):
            body = "00:00-24:00"
        elif re.search(r"休息|关闭|Closed", str(d)):
            parts.append(f"周{_WEEK[i]} 休息")
            continue
        else:
            continue
        parts.append(f"周{_WEEK[i]} {body}")
    week = "；".join(parts)
    today = next((p.split(" ", 1)[1] for p in parts if p.startswith(f"周{_WEEK[datetime.now().weekday()]} ")), "")
    return today, week


class GoogleMapsClient:
    provider = "google"

    def __init__(self, key: str, timeout: int = 15, opener: Optional[Callable[..., dict]] = None,
                 log_path: Optional[Path] = None):
        if not key:
            raise GoogleError("没有 Google Maps key")
        self._key = key
        self._timeout = timeout
        self._opener = opener            # 测试时注入：opener(url, headers, body) -> dict
        self._log_path = log_path
        self._last = 0.0

    @classmethod
    def from_env(cls, log_path: Optional[Path] = None) -> Optional["GoogleMapsClient"]:
        key = os.environ.get("GOOGLE_MAPS_KEY", "").strip()
        return cls(key, log_path=log_path) if key else None

    def _audit(self, path: str, params: dict[str, Any], outcome: str) -> None:
        if self._log_path is None:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat(timespec='seconds')} | google{path} | {params} | {outcome}\n")
        except OSError:
            pass

    def _post(self, url: str, mask: str, body: dict[str, Any], label: str) -> dict:
        headers = {"Content-Type": "application/json", "X-Goog-Api-Key": self._key, "X-Goog-FieldMask": mask}
        if self._opener is None:
            wait = _MIN_INTERVAL_S - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
        try:
            if self._opener is not None:
                data = self._opener(url, headers, body)
            else:
                req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = ""
            try:
                err = json.loads(e.read().decode("utf-8")).get("error", {})
                msg = f"{err.get('status', '')} {err.get('message', '')}".strip()
            except Exception:
                pass
            self._audit(label, body, f"错误 HTTP {e.code}")
            raise GoogleError(f"Google 返回错误：HTTP {e.code} {msg}".strip()[:300]) from None
        except Exception as e:
            self._audit(label, body, f"网络失败 {type(e).__name__}")
            raise GoogleError(f"Google 请求失败：{type(e).__name__}") from None     # 不带 URL/请求头，避免带出 key
        finally:
            self._last = time.monotonic()
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            self._audit(label, body, f"错误 {err.get('status', '')}")
            raise GoogleError(f"Google 返回错误：{err.get('status', '')} {err.get('message', '')}".strip()[:300])
        self._audit(label, body, "OK")
        return data

    # ---- 地点 ----
    @staticmethod
    def _parse_places(data: dict) -> list[PlaceHit]:
        hits: list[PlaceHit] = []
        for p in data.get("places") or []:
            loc = p.get("location") or {}
            try:
                lat, lon = float(loc["latitude"]), float(loc["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            pr = p.get("priceRange") or {}
            lo, hi = _money(pr.get("startPrice")), _money(pr.get("endPrice"))
            cost = (lo + hi) / 2 if lo is not None and hi is not None else lo
            today, week = _hours_text(p.get("regularOpeningHours"))
            rating = p.get("rating")
            hits.append(PlaceHit(
                name=str((p.get("displayName") or {}).get("text", "")), lat=lat, lon=lon,
                address=str(p.get("formattedAddress", "")),
                category=str((p.get("primaryTypeDisplayName") or {}).get("text", "")),
                amap_id=str(p.get("id", "")),
                rating=float(rating) if isinstance(rating, (int, float)) else None, cost=cost,
                opentime_today=today, opentime_week=week, tel=str(p.get("nationalPhoneNumber", "")), source="google",
            ))
        return hits

    def search_places(self, query: str, city: Optional[str] = None, limit: int = 5) -> list[PlaceHit]:
        body = {"textQuery": f"{query} {city}".strip() if city else query, "languageCode": "zh-CN",
                "maxResultCount": max(1, min(limit, 20))}
        return self._parse_places(self._post(f"{PLACES_URL}/places:searchText", _PLACE_FIELDS, body, "/places:searchText"))

    def search_around(self, lat: float, lon: float, radius_m: int = 800, types: str = _FOOD_TYPES,
                      keywords: str = "", limit: int = 20) -> list[PlaceHit]:
        circle = {"center": {"latitude": lat, "longitude": lon}, "radius": float(max(100, min(int(radius_m), 5000)))}
        n = max(1, min(limit, 20))
        if keywords:                         # 带关键词：用文字搜索，偏向这个圆
            body = {"textQuery": keywords + (" 餐厅" if types == _FOOD_TYPES else ""), "languageCode": "zh-CN",
                    "maxResultCount": n, "locationBias": {"circle": circle}}
            return self._parse_places(self._post(f"{PLACES_URL}/places:searchText", _PLACE_FIELDS, body, "/places:searchText"))
        body = {"languageCode": "zh-CN", "maxResultCount": n, "rankPreference": "DISTANCE",
                "locationRestriction": {"circle": circle}}
        if types == _FOOD_TYPES:
            body["includedTypes"] = ["restaurant"]
        return self._parse_places(self._post(f"{PLACES_URL}/places:searchNearby", _PLACE_FIELDS, body, "/places:searchNearby"))

    def geocode(self, address: str, city: Optional[str] = None) -> Optional[tuple[float, float]]:
        hits = self.search_places(address, city, limit=1)
        return (hits[0].lat, hits[0].lon) if hits else None

    # ---- 路线 ----
    @staticmethod
    def _routes(data: dict, mode: str) -> list[RouteResult]:
        out: list[RouteResult] = []
        for r in data.get("routes") or []:
            dur, dist = _secs(r.get("duration")), r.get("distanceMeters")
            if dur is None or not isinstance(dist, (int, float)):
                continue
            path = _thin(decode_polyline(((r.get("polyline") or {}).get("encodedPolyline")) or ""))
            res = RouteResult(mode, round(dist / 1000, 2), max(1, round(dur / 60)), path=path)
            if mode == "transit":
                lines: list[tuple[str, str]] = []
                walk_m, max_walk = 0.0, 0.0
                for leg in r.get("legs") or []:
                    for st in leg.get("steps") or []:
                        td = st.get("transitDetails")
                        if td:
                            tl = td.get("transitLine") or {}
                            vt = str((tl.get("vehicle") or {}).get("type", ""))
                            name = str(tl.get("nameShort") or tl.get("name") or "")
                            sd = td.get("stopDetails") or {}
                            ends = "-".join(x for x in (str((sd.get("departureStop") or {}).get("name", "")),
                                                        str((sd.get("arrivalStop") or {}).get("name", ""))) if x)
                            if vt in _RAIL and ends:
                                name = f"{name}（{ends}）" if name else ends
                            lines.append((name or vt or "公交", "铁路" if vt in _RAIL else vt))
                        elif st.get("travelMode") == "WALK":
                            d = float(st.get("distanceMeters") or 0)
                            walk_m += d
                            max_walk = max(max_walk, d)
                res.lines = [n for n, _ in lines]
                res.transfers = max(len(lines) - 1, 0)
                res.walking_km = round(walk_m / 1000, 2)
                res.max_walk_km = round(max_walk / 1000, 2) if max_walk else None
                res.uses_subway = any(t in _SUBWAY for _, t in lines) or any("地铁" in n for n, _ in lines)
            out.append(res)
        if not out:
            raise GoogleError("没有找到路线")
        return out

    def route(self, mode: str, from_lat: float, from_lon: float, to_lat: float, to_lon: float,
              city: Optional[str] = None, transit_strategy: str = "fastest",
              max_transfers: Optional[int] = None, prefer_subway: bool = False,
              depart: Optional[Any] = None) -> RouteResult:
        if mode not in _TRAVEL_MODE:
            raise GoogleError(f"不支持的出行方式：{mode}")
        body: dict[str, Any] = {
            "origin": {"location": {"latLng": {"latitude": from_lat, "longitude": from_lon}}},
            "destination": {"location": {"latLng": {"latitude": to_lat, "longitude": to_lon}}},
            "travelMode": _TRAVEL_MODE[mode], "languageCode": "zh-CN", "units": "METRIC",
        }
        if mode == "transit":
            body["computeAlternativeRoutes"] = True
            prefs: dict[str, Any] = {}
            if transit_strategy in ("fewest_transfers",):
                prefs["routingPreference"] = "FEWER_TRANSFERS"
            elif transit_strategy in ("least_walking",):
                prefs["routingPreference"] = "LESS_WALKING"
            if transit_strategy == "no_subway":
                prefs["allowedTravelModes"] = ["BUS", "TRAIN", "RAIL", "TRAM"]
            if prefs:
                body["transitPreferences"] = prefs
            if depart is not None:                    # naive 本地时间：按经度粗估时区转 UTC
                off = round(from_lon / 15.0)
                utc = depart.replace(tzinfo=None) - timedelta(hours=off)
                body["departureTime"] = utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            options = self._routes(self._post(ROUTES_URL, _ROUTE_FIELDS, body, "/directions:computeRoutes"), mode)
        except GoogleError:
            if mode == "transit" and "departureTime" in body:      # 那天的班次数据可能还没有：退回按当前时间查
                body.pop("departureTime")
                options = self._routes(self._post(ROUTES_URL, _ROUTE_FIELDS, body, "/directions:computeRoutes"), mode)
            else:
                raise
        for o in options:
            _close_gaps(o, (from_lat, from_lon), (to_lat, to_lon))
        if mode != "transit":
            return options[0]
        if max_transfers is None and not prefer_subway:
            return options[0]
        ok = [r for r in options if max_transfers is None or (r.transfers or 0) <= max_transfers]
        pool = ok or [min(options, key=lambda r: (r.transfers or 0, r.minutes))]
        best = min(pool, key=lambda r: r.minutes)
        if prefer_subway:
            subway = [r for r in pool if r.uses_subway]
            if subway:
                fastest = min(subway, key=lambda r: r.minutes)
                if fastest.minutes <= best.minutes * 1.3:
                    best = fastest
        if not ok and max_transfers is not None:
            best.warning = (best.warning + "；" if best.warning else "") + f"Google 所有方案都要换乘 {best.transfers} 次，超过你的上限 {max_transfers} 次"
        return best
