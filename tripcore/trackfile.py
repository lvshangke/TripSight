"""读取 GPX / KML 轨迹，给没有定位的照片按拍摄时间补位置。只在本机解析，不联网。

GPX 里的时间是 UTC，照片 EXIF 里的是当地时间（没有时区），所以要给时区偏移 tz_hours（默认 +8）。
KML 只有带时间的 gx:Track 才能用来定位照片；普通 LineString 没有时间，读不出来。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .phototrip import Photo

MAX_BYTES = 50 * 1024 * 1024


class TrackError(ValueError):
    pass


def _local(s: str, tz_hours: float) -> Optional[datetime]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone(timedelta(hours=tz_hours))).replace(tzinfo=None)


def _tag(e: ET.Element) -> str:
    return e.tag.rsplit("}", 1)[-1]


def _ok(lat: float, lon: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0)


def parse_file(path: Path, tz_hours: float = 8.0) -> list[tuple[datetime, float, float]]:
    if path.stat().st_size > MAX_BYTES:
        raise TrackError(f"{path.name} 超过 50MB，太大了。")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise TrackError(f"{path.name} 不是有效的 GPX/KML：{e}")
    pts: list[tuple[datetime, float, float]] = []
    kind = path.suffix.lower()
    if kind == ".gpx":
        for e in root.iter():
            if _tag(e) in ("trkpt", "rtept"):
                try:
                    lat, lon = float(e.get("lat")), float(e.get("lon"))
                except (TypeError, ValueError):
                    continue
                t = next((_local(c.text or "", tz_hours) for c in e if _tag(c) == "time"), None)
                if t and _ok(lat, lon):
                    pts.append((t, lat, lon))
    elif kind == ".kml":
        for tr in root.iter():
            if _tag(tr) != "Track":
                continue
            whens = [_local(c.text or "", tz_hours) for c in tr if _tag(c) == "when"]
            coords = [c.text or "" for c in tr if _tag(c) == "coord"]
            for t, c in zip(whens, coords):
                m = re.split(r"[\s,]+", c.strip())
                try:
                    lon, lat = float(m[0]), float(m[1])
                except (ValueError, IndexError):
                    continue
                if t and _ok(lat, lon):
                    pts.append((t, lat, lon))
    else:
        raise TrackError(f"{path.name}：只支持 .gpx 和 .kml。")
    return pts


def read_tracks(target: str, tz_hours: float = 8.0) -> list[tuple[datetime, float, float]]:
    p = Path(target).expanduser()
    if p.is_dir():
        files = sorted(x for x in p.iterdir() if x.is_file() and x.suffix.lower() in (".gpx", ".kml") and not x.name.startswith("."))
    elif p.is_file():
        files = [p]
    else:
        raise TrackError(f"轨迹文件不存在：{target}（请让用户确认路径）。")
    if not files:
        raise TrackError("文件夹里没有 .gpx / .kml 文件。")
    pts: list[tuple[datetime, float, float]] = []
    for f in files:
        pts.extend(parse_file(f, tz_hours))
    if not pts:
        raise TrackError("轨迹里没有带时间的点，没法用来给照片定位。")
    pts.sort(key=lambda x: x[0])
    return pts


def locate(track: list[tuple[datetime, float, float]], untagged: list[tuple[str, datetime]],
           max_gap_min: float = 10.0) -> tuple[list[Photo], list[tuple[str, datetime]]]:
    """按时间在轨迹上给照片补位置：夹在相邻两点之间（间隔不超过 max_gap_min 分钟）就线性插值，
    否则取 max_gap_min 分钟内最近的点。返回 (补上位置的照片, 仍然没位置的)。"""
    import bisect
    times = [p[0] for p in track]
    gap = max_gap_min * 60
    got: list[Photo] = []
    left: list[tuple[str, datetime]] = []
    for f, t in untagged:
        i = bisect.bisect_left(times, t)
        lo = track[i - 1] if i > 0 else None
        hi = track[i] if i < len(track) else None
        pos = None
        if lo and hi and (hi[0] - lo[0]).total_seconds() <= gap * 2:
            span = (hi[0] - lo[0]).total_seconds()
            r = 0.0 if span == 0 else (t - lo[0]).total_seconds() / span
            pos = (lo[1] + (hi[1] - lo[1]) * r, lo[2] + (hi[2] - lo[2]) * r)
        else:
            near = [q for q in (lo, hi) if q and abs((q[0] - t).total_seconds()) <= gap]
            if near:
                q = min(near, key=lambda q: abs((q[0] - t).total_seconds()))
                pos = (q[1], q[2])
        if pos:
            got.append(Photo(f, t, pos[0], pos[1]))
        else:
            left.append((f, t))
    return got, left
