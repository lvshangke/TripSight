"""多行程管理：每个行程一个目录 <根>/trips/<名字>/，当前行程记在 <根>/active.json。

偏好（preferences.json）和高德调用日志留在根目录，所有行程共用。
旧版本把行程直接放在根目录；第一次使用时把它“复制”（不是移动）进 trips/，原文件原样保留。
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Optional

LEGACY_FILES = ("trip.json", "proposals.json", "context.json", "candidates.json", "food_candidates.json", "map.html")
LEGACY_DIRS = ("gpx", "share")
ARCHIVE = "_archive"


def trips_dir(root: Path) -> Path:
    return root / "trips"


def slugify(name: str) -> str:
    s = re.sub(r"[^0-9A-Za-z一-鿿_-]+", "_", name or "").strip("_")
    return s[:40] or "trip"


def unique_slug(root: Path, base: str) -> str:
    slug, n = base, 2
    while (trips_dir(root) / slug).exists() or (trips_dir(root) / ARCHIVE / slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def active_slug(root: Path) -> Optional[str]:
    try:
        slug = json.loads((root / "active.json").read_text(encoding="utf-8")).get("slug")
    except (OSError, ValueError):
        return None
    return slug if isinstance(slug, str) and (trips_dir(root) / slug).is_dir() else None


def set_active(root: Path, slug: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / "active.json.tmp"
    tmp.write_text(json.dumps({"slug": slug}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(root / "active.json")


def _read_meta(trip_json: Path) -> dict[str, Any]:
    try:
        data = json.loads(trip_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def migrate_legacy(root: Path) -> Optional[str]:
    """把旧版放在根目录的行程复制进 trips/<名字>/ 并设为当前行程。只在没有 active.json 时做一次。"""
    if (root / "active.json").exists() or not (root / "trip.json").exists():
        return None
    name = (_read_meta(root / "trip.json").get("meta") or {}).get("name", "")
    slug = unique_slug(root, slugify(name))
    dest = trips_dir(root) / slug
    dest.mkdir(parents=True, exist_ok=True)
    for f in LEGACY_FILES:
        if (root / f).is_file():
            shutil.copy2(root / f, dest / f)
    for d in LEGACY_DIRS:
        if (root / d).is_dir():
            shutil.copytree(root / d, dest / d, dirs_exist_ok=True)
    set_active(root, slug)
    return slug


def list_trips(root: Path, archived: bool = False) -> list[dict[str, Any]]:
    base = trips_dir(root) / ARCHIVE if archived else trips_dir(root)
    cur = active_slug(root)
    out: list[dict[str, Any]] = []
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.name == ARCHIVE or not (d / "trip.json").exists():
            continue
        data = _read_meta(d / "trip.json")
        meta = data.get("meta") or {}
        out.append({"slug": d.name, "name": meta.get("name", d.name), "num_days": meta.get("num_days"),
                    "places": len(data.get("places") or []), "revision": data.get("revision", 0),
                    "active": (not archived) and d.name == cur})
    return out


def resolve(root: Path, query: str) -> str:
    """按目录名或行程名找行程（完全匹配优先，其次唯一的包含匹配）。找不到/不唯一时抛 KeyError / ValueError。"""
    q = (query or "").strip()
    items = list_trips(root)
    for it in items:
        if q in (it["slug"], it["name"]):
            return it["slug"]
    hit = [it for it in items if q and (q in it["slug"] or q in str(it["name"]))]
    if len(hit) == 1:
        return hit[0]["slug"]
    if not hit:
        raise KeyError(query)
    raise ValueError("、".join(f"{h['name']}（{h['slug']}）" for h in hit))


def archive(root: Path, slug: str) -> Path:
    """把行程目录移到 trips/_archive/（不删除任何文件）。当前行程不能归档。"""
    if slug == active_slug(root):
        raise ValueError("这是当前正在用的行程，请先切换到别的行程再归档。")
    src = trips_dir(root) / slug
    if not src.is_dir():
        raise KeyError(slug)
    dest_base = trips_dir(root) / ARCHIVE
    dest_base.mkdir(parents=True, exist_ok=True)
    dest, n = dest_base / slug, 2
    while dest.exists():
        dest, n = dest_base / f"{slug}-{n}", n + 1
    shutil.move(str(src), str(dest))
    return dest
