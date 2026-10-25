"""旅途照片：用户自己提供的照片，挂在某个景点或某一天下面，用于游记草稿和分享页。

隐私优先：存入时用 Pillow 重新编码（去掉 EXIF，含拍摄定位），并缩小；没有 Pillow 就拒绝保存，
绝不原样复制带定位的文件。只接受用户给的本机图片路径，不从网上找图。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Optional

EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_BYTES = 20 * 1024 * 1024
MAX_SIDE = 1600
SHARE_SIDE = 800
MAX_TOTAL = 200
MAX_SHARE_TOTAL = 40
MAX_SHARE_PER_PLACE = 6
MAX_CAPTION = 80


class PhotoError(ValueError):
    pass


def load(index: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [x for x in data if isinstance(x, dict) and x.get("id") and x.get("file")] if isinstance(data, list) else []


def save(index: Path, items: list[dict[str, Any]]) -> None:
    index.parent.mkdir(parents=True, exist_ok=True)
    tmp = index.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(index)


def _encode(img, side: int, quality: int) -> bytes:
    from PIL import Image
    im = img.copy()
    im.thumbnail((side, side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)          # 不传 exif：新文件不带任何元数据
    return buf.getvalue()


def add(folder: Path, items: list[dict[str, Any]], src: str, place_id: Optional[str], day: Optional[int], caption: str) -> dict[str, Any]:
    """从本机路径添加一张照片。"""
    p = Path(src).expanduser()
    if p.suffix.lower() not in EXTS:
        raise PhotoError("只支持 jpg / png / webp 图片")
    try:
        p = p.resolve(strict=True)
    except OSError:
        raise PhotoError("找不到这个文件")
    if not p.is_file():
        raise PhotoError("这不是一个文件")
    if p.stat().st_size > MAX_BYTES:
        raise PhotoError("文件太大（最多 20MB）")
    try:
        raw = p.read_bytes()
    except OSError:
        raise PhotoError("读不了这个文件")
    return add_bytes(folder, items, raw, place_id, day, caption)


def add_bytes(folder: Path, items: list[dict[str, Any]], raw: bytes, place_id: Optional[str], day: Optional[int], caption: str) -> dict[str, Any]:
    """从内存里的图片数据添加（网页上传用）。同样会重新编码、去掉 EXIF；没有 Pillow 就拒绝。"""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise PhotoError("没有安装 Pillow，无法安全地去掉照片里的定位信息，所以没有保存（pip install pillow）")
    if len(raw) > MAX_BYTES:
        raise PhotoError("文件太大（最多 20MB）")
    if (place_id is None) == (day is None):
        raise PhotoError("要么挂在某个景点，要么挂在某一天，二选一")
    if len(items) >= MAX_TOTAL:
        raise PhotoError(f"照片太多了（最多 {MAX_TOTAL} 张）")
    if len(caption or "") > MAX_CAPTION:
        raise PhotoError(f"说明太长（最多 {MAX_CAPTION} 字）")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if (im.format or "").upper() not in ("JPEG", "MPO", "PNG", "WEBP"):
                raise PhotoError("只支持 jpg / png / webp 图片")
            im = ImageOps.exif_transpose(im).convert("RGB")
            data = _encode(im, MAX_SIDE, 85)
    except PhotoError:
        raise
    except Exception:
        raise PhotoError("打不开这张图片")
    pid = hashlib.sha1(data).hexdigest()[:10]
    if any(x["id"] == pid and x.get("place_id") == place_id and x.get("day") == day for x in items):
        raise PhotoError("这张照片已经挂在这里了")
    folder.mkdir(parents=True, exist_ok=True)
    fname = f"{pid}.jpg"
    (folder / fname).write_bytes(data)
    rec = {"id": pid, "file": fname, "place_id": place_id, "day": day, "caption": (caption or "").strip()}
    items.append(rec)
    return rec


def thumb_uri(folder: Path, fname: str, side: int = 120, quality: int = 60) -> str:
    """工作台小缩略图（data URI）；读不出来返回空串。"""
    try:
        from PIL import Image
        with Image.open(folder / fname) as im:
            return "data:image/jpeg;base64," + base64.b64encode(_encode(im.convert("RGB"), side, quality)).decode("ascii")
    except Exception:
        return ""


def remove(folder: Path, items: list[dict[str, Any]], pid: str) -> int:
    gone = [x for x in items if x["id"] == pid]
    if not gone:
        raise PhotoError("找不到这张照片")
    items[:] = [x for x in items if x["id"] != pid]
    if not any(x["file"] == gone[0]["file"] for x in items):
        try:
            (folder / gone[0]["file"]).unlink()
        except OSError:
            pass
    return len(gone)


def for_share(folder: Path, items: list[dict[str, Any]]) -> tuple[dict[str, list[dict]], dict[int, list[dict]]]:
    """分享页用：缩到 800 边的 data URI。每个景点最多 6 张，全部最多 40 张。返回 (按景点, 按天)。"""
    try:
        from PIL import Image
    except ImportError:
        return {}, {}
    by_place: dict[str, list[dict]] = {}
    by_day: dict[int, list[dict]] = {}
    n = 0
    for x in items:
        if n >= MAX_SHARE_TOTAL:
            break
        if x.get("place_id") and len(by_place.get(x["place_id"], [])) >= MAX_SHARE_PER_PLACE:
            continue
        try:
            with Image.open(folder / x["file"]) as im:
                data = _encode(im.convert("RGB"), SHARE_SIDE, 78)
        except Exception:
            continue
        rec = {"uri": "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii"), "caption": x.get("caption", "")}
        if x.get("place_id"):
            by_place.setdefault(x["place_id"], []).append(rec)
        else:
            by_day.setdefault(int(x.get("day") or 0), []).append(rec)
        n += 1
    return by_place, by_day
