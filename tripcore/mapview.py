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
from .metrics import day_stats
from .models import Trip

_ASSETS = Path(__file__).with_name("assets")
_COLORS = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#008080", "#9a6324"]
DAY_START_MIN = 9 * 60          # 每天默认 9:00 从酒店（或第一个景点）出发
_AMAP_MODE = {"walk": "walk", "transit": "bus", "drive": "car"}
_MODE = {"walk": "步行", "transit": "公交/地铁", "drive": "驾车"}


def _gcj(lat: float, lon: float) -> list[float]:
    g_lat, g_lon = wgs84_to_gcj02(lat, lon)
    return [round(g_lat, 6), round(g_lon, 6)]


def amap_link(a_name: str, a_lat: float, a_lon: float, b_name: str, b_lat: float, b_lon: float, mode: str) -> str:
    """高德路线规划链接（电脑上打开网页版，手机上可调起 App）。坐标按高德坐标系（GCJ-02）。"""
    ga, gb = wgs84_to_gcj02(a_lat, a_lon), wgs84_to_gcj02(b_lat, b_lon)
    q = urllib.parse.urlencode({
        "from": f"{ga[1]:.6f},{ga[0]:.6f},{a_name}", "to": f"{gb[1]:.6f},{gb[0]:.6f},{b_name}",
        "mode": _AMAP_MODE.get(mode, "car"), "policy": 0, "src": "tripcore", "callnative": 1,
    }, quote_via=urllib.parse.quote)
    return "https://uri.amap.com/navigation?" + q


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


def _leg_entry(leg, a_name, a, b_name, b) -> dict[str, Any]:
    real = leg.detail_level == "route"
    path = [_gcj(lat, lon) for lat, lon in leg.path] if real and leg.path else []
    return {"type": "leg", "minutes": leg.minutes, "mode": _MODE.get(leg.mode, leg.mode), "km": leg.distance_km,
            "real": real, "note": leg.note, "path": path,
            "a": _gcj(a.lat, a.lon), "b": _gcj(b.lat, b.lon),
            "link": amap_link(a_name, a.lat, a.lon, b_name, b.lat, b.lon, leg.mode)}


def build_map_data(trip: Trip) -> dict[str, Any]:
    days: list[dict[str, Any]] = []
    lodging = trip.chosen_lodging
    meals_by = {}
    for m in trip.meals:
        meals_by.setdefault((m.day, m.after_place_id), []).append(m)
    if trip.plan:
        for day in trip.plan.days:
            st = day_stats(trip, day)
            d = trip.day_date(day.index)
            timeline: list[dict[str, Any]] = []
            t = float(DAY_START_MIN)
            if lodging and st.places:
                timeline.append({"type": "hotel", "role": "出发", "time": _hm(t), "name": lodging.name, "pos": _gcj(lodging.lat, lodging.lon)})
                if st.lodging_out:
                    timeline.append(_leg_entry(st.lodging_out, lodging.name, lodging, st.places[0].name, st.places[0]))
                    t += st.lodging_out.minutes
            for i, p in enumerate(st.places):
                lines = []
                lines.append(f"营业时间：{p.opening_hours}（来源：{p.hours_source or '未注明'}）" if p.opening_hours else "营业时间：待核实")
                if p.reservation_required:
                    bk = [x.name for x in trip.places if x.id in p.backups]
                    lines.append("需预约；备选：" + ("、".join(bk) if bk else "未设置"))
                if p.ticket_price:
                    lines.append(f"门票：{p.ticket_price:g} 元")
                timeline.append({"type": "stop", "n": i + 1, "name": p.name, "pos": _gcj(p.lat, p.lon), "arrive": _hm(t),
                                 "leave": _hm(t + p.duration_min), "stay": p.duration_min, "lines": lines})
                t += p.duration_min
                for m in meals_by.get((day.index, p.id), []):
                    ml = []
                    if m.rating is not None:
                        ml.append(f"评分 {m.rating:g}（高德）")
                    ml.append(f"人均约 {m.cost_per_person:.0f} 元（参考）" if m.cost_per_person is not None else "人均待核实")
                    ml.append(f"营业时间：{m.opening_hours}（来源：{m.hours_source}）" if m.opening_hours else "营业时间待核实")
                    timeline.append({"type": "meal", "name": m.name, "pos": _gcj(m.lat, m.lon), "lines": ml})
                if i < len(st.legs):
                    timeline.append(_leg_entry(st.legs[i], p.name, p, st.places[i + 1].name, st.places[i + 1]))
                    t += st.legs[i].minutes
            if lodging and st.places:
                if st.lodging_back:
                    timeline.append(_leg_entry(st.lodging_back, st.places[-1].name, st.places[-1], lodging.name, lodging))
                    t += st.lodging_back.minutes
                timeline.append({"type": "hotel", "role": "返回", "time": _hm(t), "name": lodging.name, "pos": _gcj(lodging.lat, lodging.lon)})
            # 标记错开显示（酒店起终点是同一个点，只画一次）
            marks = [e for e in timeline if e["type"] in ("stop", "meal")]
            hotel_pos = [_gcj(lodging.lat, lodging.lon)] if lodging and st.places else []
            shown = _spread(hotel_pos + [e["pos"] for e in marks])[len(hotel_pos):]   # 酒店先占位，景点围绕它错开
            for e, pos in zip(marks, shown):
                e["show"] = pos
            days.append({"index": day.index, "label": f"第{day.index + 1}天" + (f" {d.isoformat()}" if d else ""),
                         "color": _COLORS[day.index % len(_COLORS)], "timeline": timeline,
                         "closed_loop": bool(lodging and st.places)})
    return {"title": trip.meta.name, "days": days, "has_lodging": lodging is not None,
            "start": _hm(DAY_START_MIN)}


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
@media(max-width:700px){#app{flex-direction:column-reverse}#side{width:auto;max-width:none;height:45%;border-right:0;border-top:1px solid #ddd}#map{height:55%;flex:none}}
</style></head><body>
<div id="app"><div id="side"><div id="tabs"><div class="t"></div></div><div id="list"></div></div><div id="map"></div></div>
<div id="note">底图 © 高德地图。实线是高德返回的真实路线；虚线是估算（直线）。路线时间仅供参考。</div>
<script>__JS__</script>
<script>
const DATA = __DATA__;
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const map = L.map('map');
L.tileLayer('https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
  {subdomains:'1234', maxZoom:18, minZoom:3, attribution:'© 高德地图'}).addTo(map);
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
    if (e.type === 'leg') {
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
      else if (e.type === 'meal') { icon = emo('🍜'); title = '用餐：'+e.name; row.innerHTML = '<div class="h"><span class="tm"></span><span class="nm">🍜 '+esc(e.name)+'</span></div><div class="sub">'+e.lines.map(esc).join('<br>')+'</div>'; }
      else { icon = pin(e.n, d.color); title = e.n+'. '+e.name; row.innerHTML = '<div class="h"><span class="tm">'+e.arrive+'</span><span class="nm">'+e.n+'. '+esc(e.name)+'</span></div><div class="sub">停留 '+e.stay+' 分钟，约 '+e.leave+' 离开<br>'+e.lines.map(esc).join('<br>')+'</div>'; }
      const isEnd = e.type === 'hotel' && e.role === '返回';
      if (!isEnd) {
        const m = L.marker(pos, {icon}).bindPopup(popup(d.label+' · '+title, e.type==='hotel'?[]:e.lines)).addTo(layer);
        markers.push(m); row.onclick = () => { map.setView(m.getLatLng(), Math.max(map.getZoom(), 15)); m.openPopup(); };
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
