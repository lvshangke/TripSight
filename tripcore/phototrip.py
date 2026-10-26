"""从照片还原旅程：读拍摄时间和 GPS（EXIF），把同一天、位置相近、时间连续的照片聚成"停留点"。

全部在本机、确定性代码：不联网、不调用任何模型。GPS 只用来聚类和定位，之后挂到行程里的照片会重新编码、去掉定位信息。
聚类参数（半径、时间间隔）是经验默认值，不是事实；结果要给用户确认。HEIC 需要可选依赖 pillow-heif，没有就跳过并计数。
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

JPEG_EXT = {".jpg", ".jpeg"}
HEIC_EXT = {".heic", ".heif"}


@dataclass
class Photo:
    file: str
    taken: datetime
    lat: float
    lon: float


@dataclass
class Stop:
    day: date
    start: datetime
    end: datetime
    lat: float
    lon: float
    files: list[str] = field(default_factory=list)
    _pts: list[tuple[float, float]] = field(default_factory=list, repr=False)
    guessed: list[str] = field(default_factory=list)      # 没有定位、按拍摄时间挂上来的照片（推测）

    @property
    def n(self) -> int:
        return len(self.files)

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(h)))


def _dms(v, ref) -> Optional[float]:
    try:
        d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
    except (TypeError, ValueError, IndexError):
        return None
    return -d if str(ref).upper() in ("S", "W") else d


def _open_exif(path: Path):
    from PIL import Image
    im = Image.open(path)
    return im, im.getexif()


def read_photos(folder: Path) -> tuple[list[Photo], dict[str, int]]:
    """扫描文件夹（不递归）。返回带时间和位置的照片，以及统计。"""
    out, _, st = read_all(folder)
    return out, st


def read_all(folder: Path) -> tuple[list[Photo], list[tuple[str, datetime]], dict[str, int]]:
    """同 read_photos，另外返回有拍摄时间但没有定位的照片 [(文件名, 时间)]。"""
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        raise ValueError("没有安装 Pillow，无法读取照片信息（pip install pillow）")
    heic_ok = False
    try:
        import pillow_heif  # type: ignore
        pillow_heif.register_heif_opener()
        heic_ok = True
    except Exception:
        pass
    stats = {"images": 0, "with_gps": 0, "no_gps": 0, "no_time": 0, "heic_skipped": 0, "unreadable": 0}
    out: list[Photo] = []
    untagged: list[tuple[str, datetime]] = []
    for p in sorted(folder.iterdir()):
        ext = p.suffix.lower()
        if not p.is_file() or p.name.startswith("."):
            continue
        if ext in HEIC_EXT and not heic_ok:
            stats["heic_skipped"] += 1
            continue
        if ext not in JPEG_EXT and ext not in HEIC_EXT:
            continue
        stats["images"] += 1
        try:
            im, ex = _open_exif(p)
            with im:
                sub, gps = ex.get_ifd(0x8769), ex.get_ifd(0x8825)
        except Exception:
            stats["unreadable"] += 1
            continue
        t = sub.get(0x9003) or ex.get(0x0132)
        try:
            taken = datetime.strptime(str(t), "%Y:%m:%d %H:%M:%S")
        except (TypeError, ValueError):
            stats["no_time"] += 1
            continue
        lat = _dms(gps.get(2), gps.get(1, "N")) if gps and 2 in gps else None
        lon = _dms(gps.get(4), gps.get(3, "E")) if gps and 4 in gps else None
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            stats["no_gps"] += 1
            untagged.append((p.name, taken))
            continue
        stats["with_gps"] += 1
        out.append(Photo(p.name, taken, lat, lon))
    out.sort(key=lambda x: (x.taken, x.file))
    untagged.sort(key=lambda x: (x[1], x[0]))
    return out, untagged, stats


def assign_untagged(stops: list[Stop], untagged: list[tuple[str, datetime]], max_gap_min: float = 45) -> int:
    """没有定位的照片：拍摄时间落在某个停留点的时段内（或前后 max_gap_min 分钟内）、同一天，就挂到时间上最近的那个点。
    只是按时间推测，记在 stop.guessed 里；不改变点的位置和时段。返回挂上的张数。"""
    n = 0
    for f, t in untagged:
        best, bd = None, None
        for sp in stops:
            if sp.day != t.date():
                continue
            d = 0.0 if sp.start <= t <= sp.end else min(abs((t - sp.start).total_seconds()), abs((t - sp.end).total_seconds())) / 60
            if d <= max_gap_min and (bd is None or d < bd):
                best, bd = sp, d
        if best is not None:
            best.files.append(f)
            best.guessed.append(f)
            n += 1
    return n


def cluster(photos: list[Photo], radius_m: float = 300, gap_min: float = 75) -> list[Stop]:
    stops: list[Stop] = []
    for ph in photos:
        s = stops[-1] if stops else None
        pt = (ph.lat, ph.lon)
        if s and ph.taken.date() == s.end.date() and haversine_m((s.lat, s.lon), pt) <= radius_m \
                and (ph.taken - s.end).total_seconds() <= gap_min * 60:
            s._pts.append(pt)
            s.lat = sum(q[0] for q in s._pts) / len(s._pts)
            s.lon = sum(q[1] for q in s._pts) / len(s._pts)
            s.end = ph.taken
            s.files.append(ph.file)
        else:
            stops.append(Stop(ph.taken.date(), ph.taken, ph.taken, ph.lat, ph.lon, [ph.file], [pt]))
    return stops


def _sharpness(path: Path) -> float:
    from PIL import Image, ImageFilter, ImageStat
    with Image.open(path) as im:
        im.draft("L", (320, 320))
        g = im.convert("L")
        g.thumbnail((320, 320))
        return float(ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).var[0])


def best_files(folder: Path, files: list[str], k: int = 3) -> list[str]:
    """每个停留点挑最清晰的 k 张（边缘方差打分，确定性）；打不开的跳过。"""
    scored = []
    for f in files:
        try:
            scored.append((_sharpness(folder / f), f))
        except Exception:
            continue
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [f for _, f in scored[:k]]


def contact_sheet(folder: Path, files: list[str], k: int = 6, tile: int = 320) -> bytes:
    """把一个停留点的几张照片（按时间均匀取）拼成一张缩略图，给助手看图用；输出 JPEG，不含 EXIF。"""
    from PIL import Image, ImageOps
    pick = files if len(files) <= k else [files[round(i * (len(files) - 1) / (k - 1))] for i in range(k)]
    tiles = []
    for f in pick:
        try:
            with Image.open(folder / f) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                tiles.append(ImageOps.fit(im, (tile, tile)))
        except Exception:
            continue
    if not tiles:
        raise ValueError("这个停留点的照片都打不开")
    cols = min(3, len(tiles))
    rows = math.ceil(len(tiles) / cols)
    sheet = Image.new("RGB", (cols * tile, rows * tile), (255, 255, 255))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * tile, (i // cols) * tile))
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=80)
    return buf.getvalue()
