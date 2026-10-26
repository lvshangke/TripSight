"""朋友圈九宫格：从行程里已挂的照片挑一组（1/2/3/4/6/9 张），裁成方图，配一段只用你自己的话和行程事实拼成的短文案。

- 只用用户挂过的照片（已去掉定位）；输出是新的方图 JPEG，不带任何元数据；只写本机文件，不联网、不连账号，也不会替用户发布。
- 挑法：按行程顺序，先每个景点取封面，不够再取第二张……尽量覆盖不同景点；张数取 9 / 6 / 4 / 3 / 2 / 1 中不超过可用数的最大值（朋友圈只有这几种排法好看）。
- 文案：标题行（行程名和天数）、路线行（景点名）、你写在“我的话”里的句子（最多两句）。没有你的话就留空，不替你编感受。
- 发布前检查提醒：人脸/路人、住处和实时位置、花费。发出由用户自己在手机上操作。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Optional

from .models import Trip
from .timeline import day_visits

_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
SIZES = (9, 6, 4, 3, 2, 1)
CHECKLIST = ["照片里有没有人脸或路人？要公开发的话，不想露脸的先换掉。",
             "有没有露出住的酒店、小区或门牌？",
             "人还在外面的话，发出去就是你的实时位置：可以回家后再发，或设成部分人可见。",
             "文案里有没有花费、订单这类不想公开的内容？"]


def pick(trip: Trip, photos: list[dict], count: int = 0) -> list[dict]:
    """返回要放进九宫格的照片记录（按行程顺序）。count=0 表示自动。"""
    order = [v.place.id for day in (trip.plan.days if trip.plan else []) for v in day_visits(trip, day)[0]]
    by: dict[str, list[dict]] = {}
    for ph in photos:
        if ph.get("place_id") in order:
            by.setdefault(ph["place_id"], []).append(ph)
    total = sum(len(v) for v in by.values())
    if total == 0:
        return []
    want = count if count in SIZES else next((n for n in SIZES if n <= total), total)
    want = min(want, total)
    stops = [p for p in order if p in by]
    if len(stops) > want:                                     # 景点比格子多：均匀抽样，保持顺序
        stops = [stops[round(i * (len(stops) - 1) / (want - 1))] if want > 1 else stops[0] for i in range(want)]
        stops = list(dict.fromkeys(stops))
    chosen: dict[str, list[dict]] = {p: [] for p in stops}
    r = 0
    while sum(len(v) for v in chosen.values()) < want:
        progressed = False
        for p in stops:
            if r < len(by[p]) and sum(len(v) for v in chosen.values()) < want:
                chosen[p].append(by[p][r]); progressed = True
        if not progressed:
            break
        r += 1
    return [ph for p in stops for ph in chosen[p]]


def caption(trip: Trip, stories: Optional[dict[str, Any]], placed: list[str]) -> str:
    names = []
    for pid in placed:
        try:
            n = trip.place(pid).name
        except KeyError:
            continue
        if n not in names:
            names.append(n)
    lines = [f"{trip.meta.name}｜{trip.meta.num_days} 天"]
    if names:
        lines.append("路线：" + " → ".join(names[:6]) + ("…" if len(names) > 6 else ""))
    mine = [(stories or {}).get(pid, {}).get("impression", "") for pid in placed if (stories or {}).get(pid, {}).get("by") == "user"]
    lines += [x for x in dict.fromkeys(mine) if x][:2]
    return "\n".join(lines)


def build_moments(trip: Trip, out_root: Path, *, photos: list[dict], photo_dir: Path, stories: Optional[dict[str, Any]] = None, count: int = 0) -> dict[str, Any]:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ValueError("没有安装 Pillow，无法裁图（pip install pillow）")
    chosen = pick(trip, photos, count)
    if not chosen:
        raise ValueError("行程里还没有挂照片：先把照片挂到景点上。")
    base = _BAD.sub(" ", trip.meta.name).strip(" .") or "TripSight"
    root, n = out_root / f"{base}-朋友圈", 2
    while root.exists():
        root = out_root / f"{base}-朋友圈-{n}"; n += 1
    root.mkdir(parents=True)
    files, skipped, placed = [], [], []
    for i, ph in enumerate(chosen, 1):
        src = Path(photo_dir) / ph["file"]
        try:
            with Image.open(src) as im:
                sq = ImageOps.fit(im.convert("RGB"), (1080, 1080), centering=(0.5, 0.4))
                sq.save(root / f"{i}.jpg", "JPEG", quality=88)
        except Exception:
            skipped.append(f"照片读不了：{ph['file']}")
            continue
        files.append(f"{i}.jpg"); placed.append(ph["place_id"])
    cap = caption(trip, stories, placed)
    (root / "文案.txt").write_text(cap + "\n", encoding="utf-8")
    (root / "发布前检查.txt").write_text("\n".join(f"□ {c}" for c in CHECKLIST) + "\n", encoding="utf-8")
    return {"folder": str(root), "files": files + ["文案.txt", "发布前检查.txt"], "count": len(files), "caption": cap, "skipped": skipped}
