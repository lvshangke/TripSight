"""路线图的可选底图：向高德“静态地图”要一张不带标注/路线的底图，再把我们自己画的 SVG 路线叠在上面。

- 只有用户明确打开（export_share(basemap=True) / 工作台勾选）才会联网；默认关闭，没有 AMAP_KEY 就用不了。
- 发给高德的只有：地图中心点、缩放级别、图片大小。不发景点名、酒店名、路线形状；key 只在请求里，不会写进页面。
- 图片以 data URI 内嵌进分享页（页面仍是单文件，别人打开不需要联网），同样的范围会缓存在本地，重复生成不会再请求。
- 地图范围由要画的点决定（默认不含酒店）；但底图本身是高德的地图，范围内的酒店名可能出现在底图上。
- 坐标全程是 GCJ-02（和高德一致），投影是 Web 墨卡托，和高德的瓦片一致。
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MIN_Z = 3
MAX_Z = 16          # 选图时的上限；高清图会再放大一级（高德静态图最大 17）


def _world(lat: float, lon: float, z: int) -> tuple[float, float]:
    s = 256.0 * (2 ** z)
    lat = max(min(lat, 85.0511), -85.0511)
    r = math.radians(lat)
    return ((lon + 180.0) / 360.0 * s, (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * s)


def _unworld(x: float, y: float, z: int) -> tuple[float, float]:
    s = 256.0 * (2 ** z)
    lon = x / s * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / s))))
    return lat, lon


@dataclass
class View:
    lat: float          # 中心点（GCJ-02）
    lon: float
    zoom: int           # 按“1 倍图”算的缩放级别（视图单位 = 像素）
    w: float            # 视图宽高（SVG 视图单位）
    h: float

    @property
    def ratio(self) -> int:
        return 2 if self.zoom < 17 else 1          # 请求 2 倍清晰度：缩放级别 +1、图片尺寸 ×2，覆盖的范围不变

    @property
    def req_zoom(self) -> int:
        return self.zoom + (1 if self.ratio == 2 else 0)

    @property
    def req_size(self) -> tuple[int, int]:
        return int(round(self.w * self.ratio)), int(round(self.h * self.ratio))


class Projection:
    """lat/lon（GCJ-02）→ 视图坐标。和高德返回的底图图片严格对应。"""

    def __init__(self, view: View):
        self.view = view
        self.h = view.h
        self._cx, self._cy = _world(view.lat, view.lon, view.req_zoom)

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        x, y = _world(lat, lon, self.view.req_zoom)
        r = self.view.ratio
        return (self.view.w / 2 + (x - self._cx) / r, self.view.h / 2 + (y - self._cy) / r)


def choose_view(pts: list[tuple[float, float]], w: float, h: float, pad: float) -> View:
    """选能把所有点放进 (w, h)（四周留 pad）的最大缩放级别，中心取包围盒中心。"""
    for z in range(MAX_Z, MIN_Z - 1, -1):
        xs, ys = zip(*(_world(la, lo, z) for la, lo in pts))
        if max(xs) - min(xs) <= w - 2 * pad and max(ys) - min(ys) <= h - 2 * pad:
            break
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    lat, lon = _unworld(cx, cy, z)
    return View(lat, lon, z, w, h)


class Basemap:
    """负责取图和缓存。client 是 AmapClient（要有 static_map 方法）。"""

    def __init__(self, client, cache_dir: Optional[Path] = None):
        self._client = client
        self._cache = cache_dir
        self.requests = 0          # 这次真正发给高德的请求数（缓存命中不算）
        self.hits = 0
        self.failures: list[str] = []

    def _key(self, v: View) -> str:
        w, h = v.req_size
        return hashlib.sha1(f"{v.lat:.5f},{v.lon:.5f},{v.req_zoom},{w}x{h}".encode()).hexdigest()[:20]

    def fetch(self, v: View) -> Optional[str]:
        """返回 data URI；失败返回 None（原因记在 failures 里），调用方退回无底图的画法。"""
        f = self._cache / f"basemap-{self._key(v)}.jpg" if self._cache else None
        if f is not None and f.exists():
            try:
                self.hits += 1
                return "data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode("ascii")
            except OSError:
                pass
        w, h = v.req_size
        try:
            raw = self._client.static_map(v.lat, v.lon, v.req_zoom, w, h)
            self.requests += 1
        except Exception as e:
            msg = str(e) or type(e).__name__
            if msg not in self.failures:
                self.failures.append(msg)
            return None
        data, mime = _to_jpeg(raw)
        if data is None:
            if "返回的不是图片" not in self.failures:
                self.failures.append("返回的不是图片")
            return None
        if f is not None:
            try:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(data)
            except OSError:
                pass
        return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def _to_jpeg(raw: bytes) -> tuple[Optional[bytes], str]:
    """尽量转成 JPEG 省体积；没有 Pillow 就原样用（只认 PNG/JPEG/GIF 开头）。"""
    if not raw:
        return None, ""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as im:
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=72, optimize=True)
            return buf.getvalue(), "image/jpeg"
    except ImportError:
        pass
    except Exception:
        return None, ""
    for magic, mime in ((b"\x89PNG", "image/png"), (b"\xff\xd8", "image/jpeg"), (b"GIF8", "image/gif")):
        if raw.startswith(magic):
            return raw, mime
    return None, ""
