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
