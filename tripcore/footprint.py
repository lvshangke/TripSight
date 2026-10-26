"""足迹统计与地图：把去过的行程合起来看——几趟、几天、几个城市、大约走了多少公里，并画一张所有去过的地方的地图。

“去过”的认定（只认事实，不认计划）：从照片还原的行程算去过；其他行程只数复盘里标了“去了”的景点；纯计划不算。
公里数是按每天经过景点的先后顺序、两点之间的**直线距离**累加的，只是下限参考，不是实际里程（公路和步行会更长）。
城市来自 tag_regions 反查的结果，没标过的行程不猜，单独说明。全程只读本机文件，不联网。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any

from .phototrip import haversine_m
from .regions import _short
from .storage import load_trip


@dataclass
class TripFoot:
    slug: str
    name: str
    days: int
    start: str
    went_all: bool                                   # 照片还原的行程：全部算去过
    points: list[tuple[int, float, float, str]] = field(default_factory=list)   # (第几天, lat, lon, 名字)
    cities: list[str] = field(default_factory=list)
    tagged: bool = False

    @property
    def km(self) -> float:
        total = 0.0
        for d in sorted({p[0] for p in self.points}):
            seq = [p for p in self.points if p[0] == d]
            total += sum(haversine_m((a[1], a[2]), (b[1], b[2])) for a, b in zip(seq, seq[1:]))
        return total / 1000


def _json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def collect(trips_root: Path) -> list[TripFoot]:
    if not trips_root.is_dir():
        return []
    return collect_dirs(sorted(d for d in trips_root.iterdir() if d.is_dir() and not d.name.startswith("_")))


def collect_dirs(dirs: list[Path]) -> list[TripFoot]:
    out: list[TripFoot] = []
    for d in dirs:
        if not (d / "trip.json").exists():
            continue
        try:
            t = load_trip(d / "trip.json")
        except Exception:
            continue
        photo = (d / "photo_trip.json").exists()
        rev = _json(d / "review.json").get("places", {}) if not photo else {}
        went = {pid for pid, r in rev.items() if r.get("status") == "visited"}
        regions = _json(d / "regions.json")
        pts: list[tuple[int, float, float, str]] = []
        seen: set[str] = set()
        if t.plan:
            for day in t.plan.days:
                for it in day.items:
                    pl = t.place(it.place_id)
                    if (photo or pl.id in went) and pl.id not in seen:
                        seen.add(pl.id)
                        pts.append((day.index, pl.lat, pl.lon, pl.name))
        if not pts:
            continue
        cities = []
        for pid in seen:
            r = regions.get(pid) or {}
            c = r.get("city") or r.get("province")
            if c and _short(c) not in cities:
                cities.append(_short(c))
        out.append(TripFoot(d.name, t.meta.name, t.meta.num_days, t.meta.start_date.isoformat() if t.meta.start_date else "",
                            photo, pts, cities, bool(cities)))
    return out


def summary(feet: list[TripFoot]) -> str:
    if not feet:
        return "还没有可统计的足迹：只有从照片还原的行程，或在复盘里标了“去了”的景点才算。"
    cities = sorted({c for f in feet for c in f.cities})
    untagged = [f.name for f in feet if not f.tagged]
    km = sum(f.km for f in feet)
    lines = [f"去过的行程 {len(feet)} 趟，共 {sum(f.days for f in feet)} 天，{sum(len(f.points) for f in feet)} 个地方；"
             f"每天按先后顺序直线相连累计约 {km:.0f} 公里（只是下限，实际路程更长）。"]
    lines.append(f"到过的城市 {len(cities)} 个：" + "、".join(cities) if cities else "还没有城市信息（用 tag_regions 给行程标上城市）。")
    if cities and untagged:
        lines.append("这些行程没标过城市，没算进城市数：" + "、".join(untagged))
    for f in feet:
        lines.append(f"- {f.name}（{f.start or '日期未记'}，{f.days} 天）：{len(f.points)} 处，约 {f.km:.0f} 公里" + (f"，{'、'.join(f.cities)}" if f.cities else ""))
    return "\n".join(lines)


_COLORS = ["#d9534f", "#2e86ab", "#e0a030", "#5b9a4a", "#8a63b0", "#c0568a", "#3c8f8f", "#8a6d3b"]


def build_html(feet: list[TripFoot]) -> str:
    """一张自包含的 HTML：所有去过的地方，按行程分色，同一天的点按先后连线。没有底图（不联网），坐标按经纬度等比例展开。"""
    import math
    pts = [p for f in feet for p in f.points]
    W, H, pad = 1000, 640, 60
    lats, lons = [p[1] for p in pts], [p[2] for p in pts]
    mid = (min(lats) + max(lats)) / 2
    kx = math.cos(math.radians(mid))
    xs = [lo * kx for lo in lons]
    span_x, span_y = (max(xs) - min(xs)) or 1e-4, (max(lats) - min(lats)) or 1e-4
    s = min((W - 2 * pad) / span_x, (H - 2 * pad) / span_y)
    ox = (W - span_x * s) / 2
    oy = (H - span_y * s) / 2

    def xy(la, lo):
        return ox + (lo * kx - min(xs)) * s, oy + (max(lats) - la) * s

    body = []
    for i, f in enumerate(feet):
        col = _COLORS[i % len(_COLORS)]
        for d in sorted({p[0] for p in f.points}):
            seq = [xy(p[1], p[2]) for p in f.points if p[0] == d]
            if len(seq) > 1:
                body.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in seq)}" fill="none" stroke="{col}" stroke-width="1.6" opacity=".55"/>')
        for p in f.points:
            x, y = xy(p[1], p[2])
            body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{col}" stroke="#fff" stroke-width="1.2"><title>{escape(f.name)} · {escape(p[3])}</title></circle>')
    legend = "".join(f'<li><i style="background:{_COLORS[i % len(_COLORS)]}"></i>{escape(f.name)}</li>' for i, f in enumerate(feet))
    return f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>我的足迹</title>
<style>body{{margin:0;font:15px/1.5 -apple-system,"PingFang SC",sans-serif;background:#f6f4ef;color:#1f2328}}main{{max-width:1040px;margin:0 auto;padding:20px}}
h1{{font-size:22px;margin:0 0 4px}}p{{color:#6b7280;margin:0 0 12px;white-space:pre-line}}svg{{width:100%;height:auto;background:#fff;border-radius:14px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
ul{{list-style:none;padding:0;display:flex;flex-wrap:wrap;gap:6px 16px}}li i{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}}</style>
<main><h1>我的足迹</h1><p>{escape(summary(feet).split(chr(10), 2)[0] + chr(10) + summary(feet).split(chr(10), 2)[1])}</p>
<svg viewBox="0 0 {W} {H}" role="img" aria-label="足迹地图">{''.join(body)}</svg><ul>{legend}</ul></main>"""
