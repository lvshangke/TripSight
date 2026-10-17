"""把某一天的闭环路线导出成 GPX（标准 WGS84）：途经点 + 路线轨迹。

有高德真实路线形状的段用真实形状，没有的段用两点直线，并在轨迹名里注明“估算”。
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from .metrics import day_stats
from .models import Trip


def build_gpx(trip: Trip, day_index: int) -> str:
    if trip.plan is None or not (0 <= day_index < len(trip.plan.days)):
        raise ValueError("没有这一天的行程")
    day = trip.plan.days[day_index]
    st = day_stats(trip, day)
    lod = trip.chosen_lodging
    wpts: list[tuple[str, float, float, str]] = []
    segs: list[tuple[str, list[tuple[float, float]]]] = []

    def leg_pts(leg, a, b):
        real = leg.detail_level == "route" and leg.path
        pts = [(p[0], p[1]) for p in leg.path] if real else [(a.lat, a.lon), (b.lat, b.lon)]
        return pts

    if lod and st.places:
        wpts.append((f"出发：{lod.name}", lod.lat, lod.lon, "酒店"))
    for i, p in enumerate(st.places):
        wpts.append((f"{i + 1}. {p.name}", p.lat, p.lon, f"停留 {p.duration_min} 分钟"))
    if lod and st.places:
        wpts.append((f"返回：{lod.name}", lod.lat, lod.lon, "酒店"))
    for m in trip.meals:
        if m.day == day_index:
            wpts.append((f"用餐：{m.name}", m.lat, m.lon, "用餐点"))

    if lod and st.places and st.lodging_out:
        segs.append((f"{lod.name}→{st.places[0].name}" + ("" if st.lodging_out.detail_level == "route" else "（估算）"),
                     leg_pts(st.lodging_out, lod, st.places[0])))
    for i, leg in enumerate(st.legs):
        a, b = st.places[i], st.places[i + 1]
        segs.append((f"{a.name}→{b.name}" + ("" if leg.detail_level == "route" else "（估算）"), leg_pts(leg, a, b)))
    if lod and st.places and st.lodging_back:
        segs.append((f"{st.places[-1].name}→{lod.name}" + ("" if st.lodging_back.detail_level == "route" else "（估算）"),
                     leg_pts(st.lodging_back, st.places[-1], lod)))

    d = trip.day_date(day_index)
    title = f"{trip.meta.name} 第{day_index + 1}天" + (f" {d.isoformat()}" if d else "")
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gpx version="1.1" creator="tripcore" xmlns="http://www.topografix.com/GPX/1/1">',
           f"<metadata><name>{escape(title)}</name></metadata>"]
    for name, lat, lon, desc in wpts:
        out.append(f'<wpt lat="{lat:.6f}" lon="{lon:.6f}"><name>{escape(name)}</name><desc>{escape(desc)}</desc></wpt>')
    out.append(f"<trk><name>{escape(title)}</name>")
    for name, pts in segs:
        out.append(f"<trkseg><!-- {escape(name.replace('--', '-'))} -->")
        out += [f'<trkpt lat="{lat:.6f}" lon="{lon:.6f}"/>' for lat, lon in pts]
        out.append("</trkseg>")
    out.append("</trk></gpx>")
    return "\n".join(out) + "\n"
