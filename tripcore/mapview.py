"""生成独立的 HTML 地图页：景点（按天分色、按顺序连线）、住宿、用餐点。

- 数据全部来自 Trip，由代码生成；页面里的文字在浏览器端做了转义。
- 内部坐标是 WGS84，高德底图用 GCJ-02，所以生成时统一转换。
- Leaflet 脚本和样式直接内嵌，页面只有地图瓦片需要联网。
"""

from __future__ import annotations

import json
import math
import urllib.parse
from pathlib import Path
from typing import Any

from .coords import wgs84_to_gcj02
from .region import trip_region
from .connections import day_window, leave_by, terminal_leg, terminal_point, transfer_target, arrival_day, departure_day
from .metrics import day_stats
from .hours import hours_window
from .models import Trip
from .weather import fmt_snap
from .routeplace import entry, exit_

_ASSETS = Path(__file__).with_name("assets")
_COLORS = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#008080", "#9a6324"]
DAY_START_MIN = 9 * 60          # 每天默认 9:00 从酒店（或第一个景点）出发
_AMAP_MODE = {"walk": "walk", "transit": "bus", "drive": "car"}
_MODE = {"walk": "步行", "transit": "公交/地铁", "drive": "驾车"}


def _gcj(lat: float, lon: float) -> list[float]:
    g_lat, g_lon = wgs84_to_gcj02(lat, lon)
    return [round(g_lat, 6), round(g_lon, 6)]


def amap_link(a_name: str, a_lat: float, a_lon: float, b_name: str, b_lat: float, b_lon: float, mode: str,
              region: str = "cn") -> str:
    """路线规划链接。国内：高德（电脑上打开网页版，手机上可调起 App，坐标 GCJ-02）；境外：Google Maps（https，坐标 WGS84）。"""
    if region == "abroad":
        q = urllib.parse.urlencode({"api": 1, "origin": f"{a_lat:.6f},{a_lon:.6f}", "destination": f"{b_lat:.6f},{b_lon:.6f}",
                                    "travelmode": {"walk": "walking", "transit": "transit", "drive": "driving"}.get(mode, "driving")},
                                   safe=",")
        return "https://www.google.com/maps/dir/?" + q
    ga, gb = wgs84_to_gcj02(a_lat, a_lon), wgs84_to_gcj02(b_lat, b_lon)
    q = urllib.parse.urlencode({
        "from": f"{ga[1]:.6f},{ga[0]:.6f},{a_name}", "to": f"{gb[1]:.6f},{gb[0]:.6f},{b_name}",
        "mode": _AMAP_MODE.get(mode, "car"), "policy": 0, "src": "tripcore", "callnative": 1,
    }, quote_via=urllib.parse.quote)
    return "https://uri.amap.com/navigation?" + q


def marker_link(name: str, lat: float, lon: float, region: str = "cn") -> str:
    """单点标注的网页链接（https，微信等聊天应用里可以点开；手机上可调起 App）。坐标是 WGS84。
    国内用高德（函数内转 GCJ-02）；境外用 Google Maps（按坐标定位）。"""
    if region == "abroad":
        return "https://www.google.com/maps/search/?" + urllib.parse.urlencode({"api": 1, "query": f"{lat:.6f},{lon:.6f}"}, safe=",")
    g = wgs84_to_gcj02(lat, lon)
    q = urllib.parse.urlencode({
        "position": f"{g[1]:.6f},{g[0]:.6f}", "name": name, "coordinate": "gaode", "src": "tripcore", "callnative": 1,
    }, quote_via=urllib.parse.quote)
    return "https://uri.amap.com/marker?" + q


def day_marker_links(trip: Trip, day_index: int) -> list[dict[str, str]]:
    """某一天按顺序的各站点（出发酒店、景点、用餐点、回到的酒店）的 https 网页链接。"""
    if trip.plan is None or not (0 <= day_index < len(trip.plan.days)):
        return []
    region = trip_region(trip)
    day = trip.plan.days[day_index]
    places = [trip.place(it.place_id) for it in day.items]
    if not places:
        return []
    out: list[dict[str, str]] = []
    morning, night = trip.morning_lodging(day_index), trip.lodging_for_day(day_index)
    if morning:
        out.append({"label": "出发酒店", "name": morning.name, "url": marker_link(morning.name, morning.lat, morning.lon, region)})
    for i, p in enumerate(places):
        e = entry(p)
        out.append({"label": f"第{i + 1}站", "name": p.name, "url": marker_link(p.name, e.lat, e.lon, region)})
        for ml in trip.meals:
            if ml.day == day_index and ml.after_place_id == p.id:
                out.append({"label": "用餐", "name": ml.name, "url": marker_link(ml.name, ml.lat, ml.lon, region)})
    if night:
        out.append({"label": "返回酒店", "name": night.name, "url": marker_link(night.name, night.lat, night.lon, region)})
    return out


def _hm(minutes: float) -> str:
    m = int(round(minutes)) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def _spread(positions: list[list[float]]) -> list[list[float]]:
    """相距不到约 40 米的标记，在原位置周围错开一点显示，避免完全重叠（只影响显示位置）。"""
    out: list[list[float]] = []
    for pos in positions:
        near = sum(1 for o in out if abs(o[0] - pos[0]) < 0.0004 and abs(o[1] - pos[1]) < 0.0005)
        if near:
            ang = near * 2.1
            out.append([round(pos[0] + 0.00022 * near * math.sin(ang), 6), round(pos[1] + 0.00028 * near * math.cos(ang), 6)])
        else:
            out.append(pos)
    return out


def _leg_entry(leg, a_name, a, b_name, b, region: str = "cn") -> dict[str, Any]:
    real = leg.detail_level == "route"
    path = [_gcj(lat, lon) for lat, lon in leg.path] if real and leg.path else []
    return {"type": "leg", "minutes": leg.minutes, "mode": _MODE.get(leg.mode, leg.mode), "km": leg.distance_km,
            "real": real, "note": leg.note, "path": path,
            "a": _gcj(a.lat, a.lon), "b": _gcj(b.lat, b.lon),
            "link": amap_link(a_name, a.lat, a.lon, b_name, b.lat, b.lon, leg.mode, region)}


def _route_data(p) -> dict[str, Any]:
    """路线型景点：途经点和相邻途经点之间的步行路线（有真实形状用真实的，否则直线）。"""
    pts = [{"name": w.name, "pos": _gcj(w.lat, w.lon)} for w in p.waypoints]
    paths, mins = [], 0
    for a, b in zip(p.waypoints, p.waypoints[1:]):
        shape = [_gcj(lat, lon) for lat, lon in a.next_path] if a.next_real and a.next_path else [_gcj(a.lat, a.lon), _gcj(b.lat, b.lon)]
        paths.append({"path": shape, "real": a.next_real, "minutes": a.next_minutes})
        mins += a.next_minutes
    return {"points": pts, "paths": paths, "walk_minutes": mins}


def _hm_min(m: int) -> str:
    m %= 24 * 60
    return f"{m // 60:02d}:{m % 60:02d}"


def hours_line(oh: str, src: str, d) -> str:
    """展示用的营业时间一行：知道旅行日期且能解析时，只写当天适用的那一条；否则不猜，写原文前 40 字。"""
    if not oh:
        return "营业时间：待核实"
    tail = f"（来源：{src or '未注明'}）"
    w = hours_window(oh, d) if d is not None else None
    if w is not None:
        if w.closed:
            return "营业时间：当天不开放" + tail
        span = "全天开放" if w.all_day else "、".join(f"{_hm_min(a)}–{_hm_min(b)}" for a, b in w.ranges)
        if w.last_entry is not None:
            span += f"，最晚进入 {_hm_min(w.last_entry)}"
        return f"营业时间：{span}" + tail
    short = oh if len(oh) <= 40 else oh[:40] + "…"
    return f"营业时间：{short}" + tail


def _term_entry(c, role: str, when, tp) -> dict[str, Any]:
    icon = {"flight": "✈", "train": "🚄"}.get(c.kind, "🚌")
    return {"type": "term", "icon": icon, "role": role, "time": when.strftime("%H:%M"), "name": tp.name,
            "pos": _gcj(tp.lat, tp.lon), "lines": [f"{c.number or c.kind}：{c.from_name} → {c.to_name}",
                                                  f"{c.dep_time:%m-%d %H:%M} → {c.arr_time:%m-%d %H:%M}"]}


def _wx_short(trip: Trip, d) -> str:
    """一天预报的短写法（如“多云 24°C”）；没查过或没有就是空串。只来自已存的预报快照。"""
    w = trip.weather.get(d.isoformat()) if d else None
    if not w or not getattr(w, "day_weather", ""):
        return ""
    return w.day_weather + (f" {w.day_temp:.0f}°C" if w.day_temp is not None else "")


def build_map_data(trip: Trip) -> dict[str, Any]:
    region = trip_region(trip)
    days: list[dict[str, Any]] = []
    meals_by = {}
    for m in trip.meals:
        meals_by.setdefault((m.day, m.after_place_id), []).append(m)
    if trip.plan:
        for day in trip.plan.days:
            st = day_stats(trip, day)
            d = trip.day_date(day.index)
            lodging = trip.lodging_for_day(day.index)         # 今晚住的（返回、到达日去的）
            lod_m = trip.morning_lodging(day.index)           # 早上出发的（换酒店当天是旧的）
            leaving = bool(trip.departure and departure_day(trip) == day.index)
            night_after = lodging if leaving and lodging and lod_m and lodging.id != lod_m.id else None   # 离开日：到站后才入住的那家
            if night_after is not None:
                lodging = None                                 # 行李随身，不回酒店，直接去车站；当晚的酒店在“离开”之后
            timeline: list[dict[str, Any]] = []
            w_start, w_end, w_why = day_window(trip, day.index)
            t = float(w_start)
            if w_why:
                timeline.append({"type": "conn", "text": "；".join(w_why)})
            if trip.arrival and arrival_day(trip) == day.index:
                tp, tg, tl = terminal_point(trip, "arrival"), transfer_target(trip, "arrival"), terminal_leg(trip, "arrival")
                if tp and tg and tl:
                    timeline.append(_term_entry(trip.arrival, "到达", trip.arrival.arr_time, tp))
                    timeline.append(_leg_entry(tl, tp.name, tp, tg.name, tg, region))
                    if lodging and not st.places:
                        timeline.append({"type": "hotel", "role": "到达", "time": _hm(t), "name": lodging.name, "pos": _gcj(lodging.lat, lodging.lon)})
            if lod_m and st.places:
                timeline.append({"type": "hotel", "role": "出发", "time": _hm(t), "name": lod_m.name, "pos": _gcj(lod_m.lat, lod_m.lon)})
                if st.lodging_out:
                    e0 = entry(st.places[0])
                    timeline.append(_leg_entry(st.lodging_out, lod_m.name, lod_m, e0.name, e0, region))
                    t += st.lodging_out.minutes
            for i, p in enumerate(st.places):
                lines = []
                lines.append(hours_line(p.opening_hours, p.hours_source, d))
                if p.reservation_required:
                    bk = [x.name for x in trip.places if x.id in p.backups]
                    lines.append("需预约；备选：" + ("、".join(bk) if bk else "未设置"))
                if p.ticket_price:
                    lines.append(f"门票：{p.ticket_price:g} 元")
                ent = entry(p)
                stop = {"type": "stop", "pid": p.id, "n": i + 1, "name": p.name, "pos": _gcj(ent.lat, ent.lon), "arrive": _hm(t),
                        "web": marker_link(p.name, ent.lat, ent.lon, region),
                        "leave": _hm(t + p.duration_min), "stay": p.duration_min, "lines": lines}
                if p.waypoints:
                    stop["route"] = _route_data(p)
                    stop["lines"] = [f"途经：{'→'.join(w.name for w in p.waypoints)}"] + lines
                timeline.append(stop)
                t += p.duration_min
                for m in meals_by.get((day.index, p.id), []):
                    ml = []
                    if m.rating is not None:
                        ml.append(f"评分 {m.rating:g}（高德）")
                    ml.append(f"人均约 {m.cost_per_person:.0f} 元（参考）" if m.cost_per_person is not None else "人均待核实")
                    ml.append(hours_line(m.opening_hours, m.hours_source, d) if m.opening_hours else "营业时间待核实")
                    timeline.append({"type": "meal", "mid": m.id, "name": m.name, "pos": _gcj(m.lat, m.lon), "lines": ml,
                                     "web": marker_link(m.name, m.lat, m.lon, region)})
                if i < len(st.legs):
                    x, e = exit_(p), entry(st.places[i + 1])
                    timeline.append(_leg_entry(st.legs[i], x.name, x, e.name, e, region))
                    t += st.legs[i].minutes
            if lodging and st.places:
                if st.lodging_back:
                    xl = exit_(st.places[-1])
                    timeline.append(_leg_entry(st.lodging_back, xl.name, xl, lodging.name, lodging, region))
                    t += st.lodging_back.minutes
                timeline.append({"type": "hotel", "role": "返回", "time": _hm(t), "name": lodging.name, "pos": _gcj(lodging.lat, lodging.lon)})
            if trip.departure and departure_day(trip) == day.index:
                tp, tg, tl = terminal_point(trip, "departure"), transfer_target(trip, "departure"), terminal_leg(trip, "departure")
                if tp and tg and tl:
                    if lod_m and not st.places:
                        timeline.append({"type": "hotel", "role": "出发", "time": _hm(leave_by(trip).hour * 60 + leave_by(trip).minute),
                                         "name": lod_m.name, "pos": _gcj(lod_m.lat, lod_m.lon)})
                    timeline.append(_leg_entry(tl, tg.name, tg, tp.name, tp, region))
                    timeline.append(_term_entry(trip.departure, "离开", trip.departure.dep_time, tp))
            if night_after is not None:
                c = trip.departure
                timeline.append({"type": "hotel", "role": "入住", "time": c.arr_time.strftime("%H:%M"), "name": night_after.name,
                                 "pos": _gcj(night_after.lat, night_after.lon),
                                 "lines": [f"到站 {c.to_name} 后入住"]})
            if w_why and t > w_end:
                timeline.append({"type": "conn", "text": f"⚠ 约 {_hm(t)} 才结束，超过了可用时间（{_hm(w_end)}），需要减少安排"})
            # 标记错开显示（酒店起终点是同一个点，只画一次）
            marks = [e for e in timeline if e["type"] in ("stop", "meal")]
            hotel_pos = [_gcj(lod_m.lat, lod_m.lon)] if lod_m and st.places else []
            shown = _spread(hotel_pos + [e["pos"] for e in marks])[len(hotel_pos):]   # 酒店先占位，景点围绕它错开
            for e, pos in zip(marks, shown):
                e["show"] = pos
            days.append({"index": day.index, "label": f"第{day.index + 1}天" + (f" {d.isoformat()}" if d else ""),
                         "color": _COLORS[day.index % len(_COLORS)], "timeline": timeline,
                         "weather": _wx_short(trip, d), "weather_full": (fmt_snap(trip.weather[d.isoformat()]) if d and d.isoformat() in trip.weather else ""),
                         "closed_loop": bool(lod_m and lodging and lod_m.id == lodging.id and st.places)})
    if region == "abroad":       # 境外：高德底图没有数据，用 OpenStreetMap；坐标本来就是 WGS84（_gcj 在境外不转换）
        tiles = {"url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png", "sub": "abc", "attr": "© OpenStreetMap",
                 "note": "底图 © OpenStreetMap。实线是地图服务返回的真实路线；虚线是估算（直线）。路线时间仅供参考。"}
    else:
        tiles = {"url": "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
                 "sub": "1234", "attr": "© 高德地图",
                 "note": "底图 © 高德地图。实线是高德返回的真实路线；虚线是估算（直线）。路线时间仅供参考。"}
    return {"title": trip.meta.name, "days": days, "has_lodging": trip.has_lodging,
            "start": _hm(DAY_START_MIN), "tiles": tiles}


_TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>__CSS__</style>
<style>
html,body{height:100%;margin:0;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#222}
#app{display:flex;height:100%}
#side{width:340px;max-width:42vw;overflow:auto;border-right:1px solid #ddd;background:#fafafa;box-sizing:border-box}
#map{flex:1;height:100%}
#tabs{position:sticky;top:0;background:#fff;padding:8px;border-bottom:1px solid #ddd;display:flex;flex-wrap:wrap;gap:6px;z-index:5}
#tabs .t{font-weight:700;width:100%}
#tabs button{border:1px solid #ccc;border-radius:6px;padding:4px 9px;cursor:pointer;background:#fff;color:#222}
#tabs button.on{color:#fff;border-color:transparent}
.it{padding:8px 12px;border-bottom:1px solid #eee;cursor:pointer}
.it:hover{background:#f0f4ff}
.it .h{display:flex;gap:8px;align-items:baseline}
.it .tm{font-variant-numeric:tabular-nums;color:#666;min-width:42px;font-size:13px}
.it .nm{font-weight:600}
.it .sub{margin:2px 0 0 50px;font-size:12px;color:#555;line-height:1.5}
.leg{padding:4px 12px 4px 62px;font-size:12px;color:#444;border-bottom:1px dashed #e4e4e4;cursor:pointer;background:#fff}
.leg:hover{background:#f0f4ff}
.leg a{color:#1a6fe8;text-decoration:none;margin-left:6px}
.est{color:#b26a00}
.pin{border-radius:50%;color:#fff;font-weight:700;text-align:center;border:2px solid #fff;box-shadow:0 1px 4px #0006;width:26px;height:26px;line-height:22px;font-size:13px}
.emo{font-size:22px;line-height:24px;text-align:center;filter:drop-shadow(0 1px 2px #0008)}
#note{position:absolute;z-index:1000;bottom:6px;right:6px;background:#fffd;padding:3px 8px;border-radius:4px;font-size:12px;color:#444;max-width:50vw}
@media(max-width:700px){#note{top:6px;left:58px;right:6px;bottom:auto;max-width:none;font-size:11px}#app{flex-direction:column-reverse}#side{width:auto;max-width:none;height:45%;border-right:0;border-top:1px solid #ddd}#map{height:55%;flex:none}}
</style></head><body>
<div id="app"><div id="side"><div id="tabs"><div class="t"></div></div><div id="list"></div></div><div id="map"></div></div>
<div id="note"></div>
<script>__JS__</script>
<script>
const DATA = __DATA__;
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const map = L.map('map');
L.tileLayer(DATA.tiles.url, {subdomains:DATA.tiles.sub, maxZoom:18, minZoom:3, attribution:DATA.tiles.attr}).addTo(map);
document.getElementById('note').textContent = DATA.tiles.note;
const tabs = document.getElementById('tabs'), list = document.getElementById('list');
tabs.querySelector('.t').textContent = DATA.title;
const pin = (txt, color) => L.divIcon({className:'', html:'<div class="pin" style="background:'+color+'">'+esc(txt)+'</div>', iconSize:[26,26], iconAnchor:[13,13]});
const emo = e => L.divIcon({className:'', html:'<div class="emo">'+e+'</div>', iconSize:[26,26], iconAnchor:[13,13]});
const popup = (name, lines) => '<b>'+esc(name)+'</b>'+(lines.length?'<br>':'')+lines.map(esc).join('<br>');
let layer = null, current = -1;
function show(di) {
  current = di; if (layer) map.removeLayer(layer); layer = L.featureGroup().addTo(map); list.innerHTML = '';
  [...tabs.querySelectorAll('button')].forEach((b, i) => { b.classList.toggle('on', i === di); b.style.background = i === di ? DATA.days[i].color : '#fff'; });
  const d = DATA.days[di]; if (!d) return;
  const markers = [], legLines = [];
  d.timeline.forEach((e, idx) => {
    const row = document.createElement('div');
    if (e.type === 'conn') {
      row.className = 'leg'; row.style.cursor = 'default'; row.textContent = '⏱ ' + e.text;
    } else if (e.type === 'leg') {
      row.className = 'leg';
      row.innerHTML = '↓ '+esc(e.mode)+' 约'+e.minutes+'分钟 · '+e.km+' km · '+(e.real?'高德路线':'<span class="est">估算</span>')
        + (e.note ? '<br>'+esc(e.note) : '') + '<a href="'+esc(e.link)+'" target="_blank" rel="noopener">在高德打开</a>';
      const pts = e.path.length ? e.path : [e.a, e.b];
      const pl = L.polyline(pts, {color:d.color, weight: e.real?5:3, opacity:.85, dashArray: e.real?null:'6 8'}).addTo(layer);
      pl.bindTooltip(esc(e.mode)+' 约'+e.minutes+'分钟'+(e.real?'':'（估算）'), {sticky:true});
      legLines.push(pl);
      row.onclick = ev => { if (ev.target.tagName === 'A') return; map.fitBounds(pl.getBounds().pad(0.4)); pl.setStyle({weight:8}); setTimeout(()=>pl.setStyle({weight:e.real?5:3}), 1500); };
    } else {
      row.className = 'it';
      let icon, pos = e.show || e.pos, title, sub = '';
      if (e.type === 'hotel') { icon = emo('🏨'); title = e.name; row.innerHTML = '<div class="h"><span class="tm">'+e.time+'</span><span class="nm">🏨 '+esc(e.role)+'：'+esc(e.name)+'</span></div>'; }
      else if (e.type === 'term') { icon = emo(e.icon); title = e.role+'：'+e.name; row.innerHTML = '<div class="h"><span class="tm">'+e.time+'</span><span class="nm">'+e.icon+' '+esc(e.role)+'：'+esc(e.name)+'</span></div><div class="sub">'+e.lines.map(esc).join('<br>')+'</div>'; }
      else if (e.type === 'meal') { icon = emo('🍜'); title = '用餐：'+e.name; row.innerHTML = '<div class="h"><span class="tm"></span><span class="nm">🍜 '+esc(e.name)+'</span></div><div class="sub">'+e.lines.map(esc).join('<br>')+'</div>'; }
      else { icon = pin(e.n, d.color); title = e.n+'. '+e.name; row.innerHTML = '<div class="h"><span class="tm">'+e.arrive+'</span><span class="nm">'+e.n+'. '+esc(e.name)+'</span></div><div class="sub">停留 '+e.stay+' 分钟，约 '+e.leave+' 离开<br>'+e.lines.map(esc).join('<br>')+'</div>'; }
      const isEnd = e.type === 'hotel' && e.role === '返回';
      if (!isEnd) {
        const m = L.marker(pos, {icon}).bindPopup(popup(d.label+' · '+title, e.type==='hotel'?[]:e.lines)).addTo(layer);
        markers.push(m); row.onclick = () => { map.setView(m.getLatLng(), Math.max(map.getZoom(), 15)); m.openPopup(); };
        if (e.route) {
          e.route.paths.forEach(p => L.polyline(p.path, {color:d.color, weight:4, opacity:.9, dashArray: p.real?null:'4 6'}).bindTooltip('步行约'+p.minutes+'分钟'+(p.real?'':'（估算）'), {sticky:true}).addTo(layer));
          e.route.points.forEach((w, k) => L.circleMarker(w.pos, {radius:6, color:d.color, fillColor:'#fff', fillOpacity:1, weight:3}).bindTooltip((k+1)+'. '+w.name, {permanent:false}).addTo(layer));
        }
      } else { row.onclick = () => { map.setView(e.pos, Math.max(map.getZoom(), 15)); }; }
    }
    list.appendChild(row);
  });
  if (!d.closed_loop) { const w = document.createElement('div'); w.className = 'leg'; w.textContent = DATA.has_lodging ? '这一天没有景点。' : '还没有选定住宿，所以不是从酒店出发的闭环。'; list.prepend(w); }
  try { const b = layer.getBounds(); if (b.isValid()) map.fitBounds(b.pad(0.15)); } catch (e) {}
}
if (!DATA.days.length) { list.innerHTML = '<div class="leg">还没有分天的行程。</div>'; map.setView([35,105],4); }
DATA.days.forEach((d, i) => { const b = document.createElement('button'); b.textContent = d.label; b.onclick = () => show(i); tabs.appendChild(b); });
if (DATA.days.length) show(0);
</script></body></html>
"""


def build_map_html(trip: Trip) -> str:
    data = build_map_data(trip)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (_TEMPLATE
            .replace("__TITLE__", _html_escape(data["title"]))
            .replace("__CSS__", (_ASSETS / "leaflet.css").read_text(encoding="utf-8"))
            .replace("__JS__", (_ASSETS / "leaflet.js").read_text(encoding="utf-8").replace("</script", "<\\/script"))
            .replace("__DATA__", payload))


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
