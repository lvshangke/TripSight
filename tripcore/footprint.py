"""足迹统计与地图：把走过的行程合起来看——几趟、几天、几个城市、大约走了多少公里，并画一张所有去过的地方的地图。

“走过”的认定（只认事实，不认计划）：只统计从照片恢复出来的行程（恢复行程）；计划行程和复盘不进足迹。
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
    pins: list[dict] = field(default_factory=list)   # 和 points 一一对应：{"date": "2024-01-18", "thumbs": [data URI, ...]}（要缩略图时才有）

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


def collect(trips_root: Path, thumbs: bool = False) -> list[TripFoot]:
    if not trips_root.is_dir():
        return []
    return collect_dirs(sorted(d for d in trips_root.iterdir() if d.is_dir() and not d.name.startswith("_")), thumbs)


def _pin_info(d: Path, side: dict, place_ids: list[str], thumbs: bool) -> list[dict]:
    """每个点的日期，和（可选）这一站自己的照片缩略图：只用手册里没被隐藏的照片，最多 3 张，封面在前。"""
    from . import photos as _ph
    when = {x.get("place_id"): str(x.get("start") or "")[:10] for x in side.get("stops", []) if isinstance(x, dict)}
    items = []
    if thumbs:
        try:
            items = _ph.load(d / "photos.json")
        except Exception:
            items = []
    out = []
    for pid in place_ids:
        ts = []
        for x in items:
            if len(ts) >= 3:
                break
            if x.get("place_id") == pid and not x.get("hide"):
                u = _ph.thumb_uri(d / "photos", x.get("file", ""), 140, 62)
                if u:
                    ts.append(u)
        out.append({"date": when.get(pid, ""), "thumbs": ts})
    return out


def collect_dirs(dirs: list[Path], thumbs: bool = False) -> list[TripFoot]:
    out: list[TripFoot] = []
    for d in dirs:
        if not (d / "trip.json").exists():
            continue
        try:
            t = load_trip(d / "trip.json")
        except Exception:
            continue
        photo = (d / "photo_trip.json").exists()
        if not photo:                                    # 只算“恢复行程”：计划行程和复盘不进足迹，免得和走过的路混在一起
            continue
        went = set()
        regions = _json(d / "regions.json")
        pts: list[tuple[int, float, float, str]] = []
        pids: list[str] = []
        seen: set[str] = set()
        if t.plan:
            for day in t.plan.days:
                for it in day.items:
                    pl = t.place(it.place_id)
                    if (photo or pl.id in went) and pl.id not in seen:
                        seen.add(pl.id)
                        pids.append(pl.id)
                        pts.append((day.index, pl.lat, pl.lon, pl.name))
        if not pts:
            continue
        cities = []
        for pid in seen:
            r = regions.get(pid) or {}
            c = r.get("city") or r.get("province")
            if c and _short(c) not in cities:
                cities.append(_short(c))
        info = _pin_info(d, _json(d / "photo_trip.json"), pids, thumbs)
        real_days = len({x["date"] for x in info if x["date"]})            # 跨了好几年的相册，“天数”按真的拍过照的天数算，不按头尾相隔几天
        out.append(TripFoot(d.name, t.meta.name, real_days or t.meta.num_days, t.meta.start_date.isoformat() if t.meta.start_date else "",
                            photo, pts, cities, bool(cities), info))
    return out


def summary(feet: list[TripFoot]) -> str:
    if not feet:
        return "还没有可统计的足迹：只有用“恢复行程”从照片还原出来的行程才算。"
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


_COLORS = ["#c4553a", "#2e86ab", "#d9a02b", "#5b9a4a", "#8a63b0", "#c0568a", "#3c8f8f", "#8a6d3b"]
_PIN = "M0,0 C-5,-7 -10,-12 -10,-19 a10,10 0 1 1 20,0 C10,-12 5,-7 0,0z"


def build_html(feet: list[TripFoot], bm=None) -> str:
    """一张自包含的 HTML：所有走过的地方，按行程分色；同一天的点按先后连线；很近的点合并成一个带数字的图钉。
    有底图时投影和高德底图（GCJ-02）严格对应，所以照片坐标（WGS84）要先转成 GCJ-02；没有底图就按经纬度等比例展开（不联网）。"""
    import math
    from .coords import wgs84_to_gcj02
    pts = [p for f in feet for p in f.points]
    W, H, pad = 1000, 640, 70
    uri, proj = None, None
    g = lambda la, lo: wgs84_to_gcj02(la, lo)
    if bm is not None:
        from .basemap import Projection, choose_view
        gp = [g(p[1], p[2]) for p in pts]
        if len(gp) == 1:
            gp = [gp[0], (gp[0][0] + 0.002, gp[0][1] + 0.002)]
        view = choose_view(gp, W, H, pad)
        uri = bm.fetch(view)
        if uri:
            proj = Projection(view)
    lats, lons = [p[1] for p in pts], [p[2] for p in pts]
    kx = math.cos(math.radians((min(lats) + max(lats)) / 2))
    xs = [lo * kx for lo in lons]
    span_x, span_y = (max(xs) - min(xs)) or 1e-4, (max(lats) - min(lats)) or 1e-4
    sc = min((W - 2 * pad) / span_x, (H - 2 * pad) / span_y)
    ox, oy = (W - span_x * sc) / 2, (H - span_y * sc) / 2

    def xy(la, lo):
        if proj is not None:
            return proj.xy(*g(la, lo))
        return ox + (lo * kx - min(xs)) * sc, oy + (max(lats) - la) * sc

    lines, pins = [], []
    placed: list[list] = []                              # 合并很近的点：[x, y, 行程序号, [名字...], 第一张缩略图]
    for i, f in enumerate(feet):
        col = _COLORS[i % len(_COLORS)]
        for d in sorted({p[0] for p in f.points}):
            seq = [xy(p[1], p[2]) for p in f.points if p[0] == d]
            if len(seq) > 1:
                pl = " ".join(f"{x:.1f},{y:.1f}" for x, y in seq)
                lines.append(f'<g class="t t{i}"><polyline points="{pl}" fill="none" stroke="#fff" stroke-width="6" stroke-linejoin="round" stroke-linecap="round" opacity=".85"/>'
                             f'<polyline points="{pl}" fill="none" stroke="{col}" stroke-width="3" stroke-dasharray="2 7" stroke-linecap="round"/></g>')
        for k, p in enumerate(f.points):
            x, y = xy(p[1], p[2])
            th = ((f.pins[k]["thumbs"] if k < len(f.pins) else None) or [""])[0]
            hit = next((q for q in placed if q[2] == i and abs(q[0] - x) < 22 and abs(q[1] - y) < 22), None)
            if hit:
                hit[3].append(p[3])
                hit[4] = hit[4] or th
            else:
                placed.append([x, y, i, [p[3]], th])
    for n, (x, y, i, names, th) in enumerate(placed):
        col = _COLORS[i % len(_COLORS)]
        tip = escape(feet[i].name + " · " + (names[0] if len(names) == 1 else f"{len(names)} 处：" + "、".join(names[:4]) + ("…" if len(names) > 4 else "")))
        if th:                                            # 有照片：圆形照片图钉（颜色是哪一趟），合并了几处就在角上写个数
            badge = (f'<circle cx="15" cy="-15" r="9" fill="{col}" stroke="#fff" stroke-width="2"/><text x="15" y="-11" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">{len(names)}</text>' if len(names) > 1 else "")
            pins.append(f'<g class="t t{i} pin" transform="translate({x:.1f},{y:.1f})" data-tip="{tip}"><circle r="21" fill="{col}" stroke="#fff" stroke-width="3"/>'
                        f'<clipPath id="cp{n}"><circle r="17"/></clipPath><image href="{th}" x="-17" y="-17" width="34" height="34" preserveAspectRatio="xMidYMid slice" clip-path="url(#cp{n})"/>{badge}</g>')
            continue
        pins.append(f'<g class="t t{i} pin" transform="translate({x:.1f},{y:.1f})" data-tip="{tip}"><ellipse cx="0" cy="1" rx="6" ry="2.2" fill="#000" opacity=".25"/>'
                    f'<path d="{_PIN}" fill="{col}" stroke="#fff" stroke-width="2"/>'
                    + (f'<text y="-15" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">{len(names)}</text>' if len(names) > 1 else '<circle cy="-19" r="3.6" fill="#fff"/>') + '</g>')
    grid = "" if uri else "".join(f'<path d="M{x},0V{H}" stroke="#e8e2d3"/>' for x in range(0, W, 100)) + "".join(f'<path d="M0,{y}H{W}" stroke="#e8e2d3"/>' for y in range(0, H, 100))
    km = sum(f.km for f in feet)
    cities = sorted({c for f in feet for c in f.cities})
    tiles = [(len(feet), "趟"), (sum(f.days for f in feet), "天"), (len(pts), "个地方"), (len(cities), "座城市"), (f"{km:.0f}", "公里（直线，下限）")]
    tile_html = "".join(f'<div class="tl"><b>{a}</b><span>{b}</span></div>' for a, b in tiles)
    cards = "".join(
        f'<button class="tc on" data-i="{i}"><i style="background:{_COLORS[i % len(_COLORS)]}"></i><div><b>{escape(f.name)}</b>'
        f'<span>{escape(f.start or "日期未记")} · {f.days} 天 · {len(f.points)} 处 · 约 {f.km:.0f} 公里' + (f' · {escape("、".join(f.cities))}' if f.cities else "") + "</span></div></button>"
        for i, f in enumerate(feet))
    note = "" if cities else '<p class="n">还没有城市信息：在恢复行程页点“标注城市/区”后，这里会统计到过的城市。</p>'
    return f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>我的足迹</title>
<style>*{{box-sizing:border-box}}body{{margin:0;font:14px/1.5 -apple-system,"PingFang SC",sans-serif;background:#f6f1e7;color:#33302b}}main{{max-width:1040px;margin:0 auto;padding:18px}}
.tiles{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}}.tl{{flex:1;min-width:110px;background:#fffdf8;border:1px solid #e3dac8;border-radius:12px;padding:10px 14px}}.tl b{{display:block;font-size:24px;color:#c4553a;font-family:"Noto Serif SC","Songti SC",serif}}.tl span{{font-size:12px;color:#8a8374}}
.map{{position:relative;border-radius:16px;overflow:hidden;box-shadow:0 6px 24px rgba(80,60,30,.14);background:#fffdf8}}svg{{display:block;width:100%;height:auto}}.pin{{cursor:pointer}}.pin:hover path{{filter:brightness(1.1)}}.t.off{{display:none}}
.tcs{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px;margin-top:14px}}.tc{{display:flex;gap:10px;align-items:flex-start;text-align:left;background:#fffdf8;border:1px solid #e3dac8;border-radius:12px;padding:10px 12px;cursor:pointer;font:inherit;color:inherit;transition:all .15s}}.tc:hover{{box-shadow:0 6px 16px rgba(80,60,30,.12)}}.tc.on i{{opacity:1}}.tc:not(.on){{opacity:.45}}
.tc i{{width:12px;height:12px;border-radius:50%;margin-top:5px;flex:none}}.tc b{{display:block}}.tc span{{font-size:12px;color:#8a8374}}.n{{color:#8a8374;font-size:12px}}#tp{{position:fixed;background:#33302b;color:#fff;font-size:12px;padding:5px 10px;border-radius:8px;pointer-events:none;opacity:0;white-space:nowrap}}
</style><main><div class="tiles">{tile_html}</div>{note}<div class="map"><svg viewBox="0 0 {W} {H}" role="img" aria-label="足迹地图"><rect width="{W}" height="{H}" fill="#eef3e8"/>{grid}{f'<image href="{uri}" width="{W}" height="{H}"/>' if uri else ''}{''.join(lines)}{''.join(pins)}</svg></div>
<div class="tcs">{cards}</div></main><div id="tp"></div>
<script>const tp=document.getElementById('tp');document.querySelectorAll('.pin').forEach(p=>{{p.onmousemove=e=>{{tp.textContent=p.dataset.tip;tp.style.left=Math.min(innerWidth-tp.offsetWidth-8,e.clientX+12)+'px';tp.style.top=(e.clientY-34)+'px';tp.style.opacity=1}};p.onmouseleave=()=>tp.style.opacity=0}});
document.querySelectorAll('.tc').forEach(b=>b.onclick=()=>{{b.classList.toggle('on');document.querySelectorAll('.t'+b.dataset.i).forEach(x=>x.classList.toggle('off',!b.classList.contains('on')))}})</script>"""


def data(feet: list[TripFoot]) -> dict:
    """给网页足迹页的数据：统计 + 每趟的点（坐标已转成高德底图用的 GCJ-02）、日期和照片缩略图。"""
    from .coords import wgs84_to_gcj02
    trips = []
    for i, f in enumerate(feet):
        pins = []
        for k, p in enumerate(f.points):
            la, lo = wgs84_to_gcj02(p[1], p[2])
            info = f.pins[k] if k < len(f.pins) else {}
            pins.append({"day": p[0] + 1, "pos": [round(la, 6), round(lo, 6)], "name": p[3], "date": info.get("date", ""), "thumbs": info.get("thumbs", [])})
        trips.append({"slug": f.slug, "name": f.name, "start": f.start, "days": f.days, "km": round(f.km), "cities": f.cities, "color": _COLORS[i % len(_COLORS)], "pins": pins})
    cities = sorted({c for f in feet for c in f.cities})
    return {"trips": trips, "totals": {"trips": len(feet), "days": sum(f.days for f in feet), "places": sum(len(f.points) for f in feet), "cities": len(cities), "km": round(sum(f.km for f in feet))}}
