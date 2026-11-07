"""直接读 Mac 照片 App 的相册（只读）：用开源库 osxphotos 读照片库里的拍摄时间、位置和所属相册，不修改照片库，不联网。

- 只在 macOS 上、装了 osxphotos 时可用（pip install osxphotos）；第一次读需要在“系统设置 → 隐私与安全性”里给运行它的终端/应用授权
  “完全磁盘访问权限”（照片库在 ~/Pictures 下，受系统保护）。
- 聚类只用数据库里的时间和位置，不打开图片文件；真正要放进手册/拼图的几张才读文件：优先原图（JPEG/PNG），
  原图是 HEIC 或只在 iCloud 上时，退回照片 App 本机已有的最大预览图；都没有就跳过这一张。
- 返回的 Photo.file 是绝对路径，和“文件夹”流程共用同一套聚类、挑图、拼图（Path(folder) / 绝对路径 就是这个绝对路径）。
- 照片只读 images；视频另用 album_videos 取原文件路径（只在本机、只读、不复制），给“视频粗剪”用，不进行程聚类。
- 想指定别的照片库：环境变量 TRIPSIGHT_PHOTOS_LIBRARY，指向 .photoslibrary 文件夹。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

from .phototrip import Photo

READ_EXT = {".jpg", ".jpeg", ".png"}


class PhotosLibError(Exception):
    pass


def available() -> tuple[bool, str]:
    if sys.platform != "darwin":
        return False, "只有 macOS 上才能直接读照片 App；其他系统请把照片导出到文件夹。"
    try:
        import osxphotos  # noqa: F401
    except ImportError:
        return False, "没有安装 osxphotos（在你的 Python 环境里运行：pip install osxphotos）。"
    return True, ""


def _open_db() -> Any:
    ok, why = available()
    if not ok:
        raise PhotosLibError(why)
    import osxphotos
    lib = os.environ.get("TRIPSIGHT_PHOTOS_LIBRARY", "").strip()
    try:
        return osxphotos.PhotosDB(dbfile=str(Path(lib).expanduser())) if lib else osxphotos.PhotosDB()
    except PermissionError:
        raise PhotosLibError("没有权限读照片库：请在“系统设置 → 隐私与安全性 → 完全磁盘访问权限”里给运行它的终端/应用打开，然后重启它再试。")
    except Exception as e:
        raise PhotosLibError(f"打不开照片库（{type(e).__name__}）：可能是权限不够、照片库正在升级，或 osxphotos 还不支持这个 macOS 版本。")


def list_albums() -> list[dict[str, Any]]:
    """相册列表：照片和视频分开数，只有视频的相册（如 mate40_video）也要列出来。"""
    db = _open_db()
    out = []
    for a in getattr(db, "album_info", []) or []:
        try:
            items = list(a.photos)
            vids = len([p for p in items if getattr(p, "ismovie", False)])
            n = len([p for p in items if getattr(p, "isphoto", True) and not getattr(p, "ismovie", False)])
            out.append({"name": a.title, "count": n, "videos": vids})
        except Exception:
            continue
    return sorted((x for x in out if x["count"] or x["videos"]), key=lambda x: x["name"])


def _usable_path(p: Any) -> Optional[str]:
    """原图能直接读（JPEG/PNG 且在本机）就用原图，否则用最大的本机预览图。"""
    path = getattr(p, "path", None)
    if path and Path(path).suffix.lower() in READ_EXT and Path(path).is_file():
        return str(path)
    best, size = None, -1
    for d in getattr(p, "path_derivatives", None) or []:
        dp = Path(d)
        if dp.suffix.lower() in READ_EXT and dp.is_file() and dp.stat().st_size > size:
            best, size = str(dp), dp.stat().st_size
    return best


def read_album(album: str) -> tuple[list[Photo], list[tuple[str, Any]], dict[str, int]]:
    """相册里的照片 → (带时间和位置的 Photo, 有时间无位置的 [(路径, 时间)], 统计)。统计的键和读文件夹时一致。"""
    db = _open_db()
    if album not in {x["name"] for x in list_albums_from(db)}:
        raise PhotosLibError(f"照片 App 里没有叫「{album}」的相册（先用 list_photo_albums 看看有哪些）。")
    stats = {"images": 0, "with_gps": 0, "no_gps": 0, "no_time": 0, "heic_skipped": 0, "unreadable": 0}
    out: list[Photo] = []
    untagged: list[tuple[str, Any]] = []
    for p in db.photos(albums=[album], images=True, movies=False):
        if getattr(p, "hidden", False) or getattr(p, "intrash", False):
            continue
        stats["images"] += 1
        d = getattr(p, "date", None)
        if d is None:
            stats["no_time"] += 1
            continue
        taken = d.replace(tzinfo=None)                 # 拍摄地的当地钟点，和 EXIF 一致
        f = _usable_path(p)
        if f is None:
            stats["unreadable"] += 1                  # 本机既没有原图也没有预览（只在 iCloud 上）
            continue
        lat, lon = getattr(p, "latitude", None), getattr(p, "longitude", None)
        if lat is None or lon is None or (lat == 0 and lon == 0):
            stats["no_gps"] += 1
            untagged.append((f, taken))
            continue
        stats["with_gps"] += 1
        out.append(Photo(f, taken, float(lat), float(lon)))
    out.sort(key=lambda x: (x.taken, x.file))
    untagged.sort(key=lambda x: (x[1], x[0]))
    return out, untagged, stats


def album_videos(album: str) -> tuple[list[Path], int]:
    """相册里的视频 → (本机有原文件的路径列表, 只在 iCloud 上没下载的个数)。只读，不复制、不改照片库。"""
    from .video import VIDEO_EXT
    db = _open_db()
    if album not in {x["name"] for x in list_albums_from(db)}:
        raise PhotosLibError(f"照片 App 里没有叫「{album}」的相册。")
    paths: list[Path] = []
    missing = 0
    for p in db.photos(albums=[album], images=False, movies=True):
        if getattr(p, "hidden", False) or getattr(p, "intrash", False):
            continue
        f = getattr(p, "path", None)
        if f and Path(f).is_file() and Path(f).suffix.lower() in VIDEO_EXT:
            paths.append(Path(f))
        else:
            missing += 1
    return sorted(paths), missing


def list_albums_from(db: Any) -> list[dict[str, Any]]:
    out = []
    for a in getattr(db, "album_info", []) or []:
        try:
            out.append({"name": a.title, "count": len(a.photos)})
        except Exception:
            continue
    return out
