"""地理编码：把地名变成经纬度（使用免费的 OpenStreetMap Nominatim 服务）。

使用须知（Nominatim 的公共服务有使用政策）：
- 必须带上能标识你的 User-Agent（请通过环境变量 TRIPCORE_CONTACT 填你的邮箱或项目地址）。
- 每秒最多 1 次请求（本模块已内置限速）。
- 只适合少量使用。大量或商业使用请自建服务或换其他服务商。
- 同一个地名会缓存到本地文件，不会重复请求。
- 对中文地名的识别有时不准，请核对结果。
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
DEFAULT_CACHE = Path(".geocode_cache.json")
_MIN_INTERVAL_S = 1.1
_last_request_at = 0.0


class GeocodeError(Exception):
    pass


def _load_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def geocode(query: str, city: Optional[str] = None, cache_path: Path = DEFAULT_CACHE, timeout: int = 15) -> dict:
    """返回 {"name": ..., "lat": ..., "lon": ..., "display_name": ...}。找不到时抛 GeocodeError。"""
    global _last_request_at
    full_query = f"{city} {query}" if city else query

    cache = _load_cache(cache_path)
    if full_query in cache:
        return cache[full_query]

    wait = _MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)

    params = urllib.parse.urlencode({"q": full_query, "format": "jsonv2", "limit": 1, "accept-language": "zh"})
    contact = os.environ.get("TRIPCORE_CONTACT", "unknown-contact")
    req = urllib.request.Request(
        f"{NOMINATIM_URL}?{params}",
        headers={"User-Agent": f"tripcore/0.1 ({contact})"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # 网络错误、超时等
        raise GeocodeError(f"地理编码请求失败：{e}") from e
    finally:
        _last_request_at = time.monotonic()

    if not data:
        raise GeocodeError(f"没有找到：{full_query}")

    top = data[0]
    result = {
        "name": query,
        "lat": float(top["lat"]),
        "lon": float(top["lon"]),
        "display_name": top.get("display_name", ""),
    }
    cache[full_query] = result
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


_POI_KEYS = ("tourism", "historic", "leisure", "amenity", "natural", "man_made", "shop", "building", "railway", "aeroway")


def reverse(lat: float, lon: float, cache_path: Path = DEFAULT_CACHE, timeout: int = 15, lang: str = "zh-CN,zh,en,ja") -> dict:
    """坐标 → 地名（OpenStreetMap Nominatim 反查，境外用；只发这一个坐标，不发照片）。
    返回 {"name": 景点/地标名（没有就空）, "district": 区/町, "city": 市, "province": 都道府县/州, "country": 国家}。
    同一坐标（约 10 米内）会缓存，不重复请求；每秒最多 1 次。查不到抛 GeocodeError。"""
    global _last_request_at
    key = f"rev:{lat:.4f},{lon:.4f}:{lang}"
    cache = _load_cache(cache_path)
    if key in cache:
        return cache[key]
    wait = _MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    params = urllib.parse.urlencode({"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "format": "jsonv2", "zoom": 18, "addressdetails": 1, "accept-language": lang})
    contact = os.environ.get("TRIPCORE_CONTACT", "unknown-contact")
    req = urllib.request.Request(f"{NOMINATIM_REVERSE_URL}?{params}", headers={"User-Agent": f"tripcore/0.1 ({contact})"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise GeocodeError(f"反查请求失败：{e}") from e
    finally:
        _last_request_at = time.monotonic()
    if not isinstance(data, dict) or data.get("error"):
        raise GeocodeError(f"这个坐标没有查到地名：{lat:.4f},{lon:.4f}")
    out = parse_reverse(data)
    cache[key] = out
    try:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return out


def parse_reverse(data: dict) -> dict:
    """把 Nominatim 的反查结果整理成 name/district/city/province/country（纯函数，方便测试）。"""
    a = data.get("address") or {}
    name = ""
    top = (data.get("name") or "").strip()
    if top and data.get("category") in _POI_KEYS:
        name = top
    if not name:
        for k in _POI_KEYS:
            if a.get(k) and not str(a.get(k)).lower() in ("yes", "house"):
                name = str(a[k]).strip()
                break
    if not name:
        name = (a.get("neighbourhood") or a.get("quarter") or a.get("road") or "").strip()
    city = a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or ""
    district = a.get("city_district") or a.get("suburb") or a.get("ward") or a.get("borough") or a.get("quarter") or ""
    return {"name": name[:40], "district": district, "city": city, "province": a.get("state") or a.get("province") or "", "country": a.get("country") or ""}
