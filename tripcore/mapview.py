"""生成独立的 HTML 地图页：景点（按天分色、按顺序连线）、住宿、用餐点。

- 数据全部来自 Trip，由代码生成；页面里的文字在浏览器端做了转义。
- 内部坐标是 WGS84，高德底图用 GCJ-02，所以生成时统一转换。
- Leaflet 脚本和样式直接内嵌，页面只有地图瓦片需要联网。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .coords import wgs84_to_gcj02
from .metrics import day_stats, lodging_legs
from .models import Trip

_ASSETS = Path(__file__).with_name("assets")
_COLORS = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#008080", "#9a6324"]
_MODE = {"walk": "步行", "transit": "公交/地铁", "drive": "驾车"}


def _gcj(lat: float, lon: float) -> list[float]:
    g_lat, g_lon = wgs84_to_gcj02(lat, lon)
    return [round(g_lat, 6), round(g_lon, 6)]


def build_map_data(trip: Trip) -> dict[str, Any]:
    days: list[dict[str, Any]] = []
    if trip.plan:
        for day in trip.plan.days:
            st = day_stats(trip, day)
            d = trip.day_date(day.index)
            stops = []
            for i, p in enumerate(st.places):
                lines = [f"{p.duration_min} 分钟"]
                lines.append(f"营业时间：{p.opening_hours}（来源：{p.hours_source or '未注明'}）" if p.opening_hours else "营业时间：待核实")
                if p.reservation_required:
                    bk = [x.name for x in trip.places if x.id in p.backups]
                    lines.append("需预约；备选：" + ("、".join(bk) if bk else "未设置"))
                if p.ticket_price:
                    lines.append(f"门票：{p.ticket_price:g} 元")
                stops.append({"n": i + 1, "id": p.id, "name": p.name, "pos": _gcj(p.lat, p.lon), "lines": lines})
            legs = [{"minutes": lg.minutes, "mode": _MODE.get(lg.mode, lg.mode), "km": lg.distance_km,
                     "real": lg.detail_level == "route"} for lg in st.legs]
            lod = None
            lod_legs = []
            lodging = trip.chosen_lodging
            if lodging and st.places:
                out_leg, back_leg = lodging_legs(trip, st.places)
                lod_legs = [
                    {"from": _gcj(lodging.lat, lodging.lon), "to": stops[0]["pos"], "minutes": out_leg.minutes if out_leg else None},
                    {"from": stops[-1]["pos"], "to": _gcj(lodging.lat, lodging.lon), "minutes": back_leg.minutes if back_leg else None},
                ]
            days.append({
                "index": day.index, "label": f"第{day.index + 1}天" + (f" {d.isoformat()}" if d else ""),
                "color": _COLORS[day.index % len(_COLORS)], "stops": stops, "legs": legs, "lodging_legs": lod_legs,
            })
    lodging = trip.chosen_lodging
    meals = []
    for m in trip.meals:
        lines = []
        if m.rating is not None:
            lines.append(f"评分 {m.rating:g}（高德）")
        lines.append(f"人均约 {m.cost_per_person:.0f} 元（参考）" if m.cost_per_person is not None else "人均待核实")
        lines.append(f"营业时间：{m.opening_hours}（来源：{m.hours_source}）" if m.opening_hours else "营业时间待核实")
        meals.append({"day": m.day, "name": m.name, "pos": _gcj(m.lat, m.lon), "lines": lines})
    return {
        "title": trip.meta.name,
        "days": days,
        "lodging": ({"name": lodging.name, "pos": _gcj(lodging.lat, lodging.lon)} if lodging else None),
        "meals": meals,
    }


_TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>__CSS__</style>
<style>
html,body{height:100%;margin:0;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
#bar{position:absolute;z-index:1000;top:10px;left:56px;right:10px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;pointer-events:none}
#bar>*{pointer-events:auto}
#bar .t{background:#fff;padding:5px 10px;border-radius:6px;box-shadow:0 1px 4px #0004;font-weight:600}
#bar button{border:0;border-radius:6px;padding:5px 10px;cursor:pointer;box-shadow:0 1px 4px #0004;background:#fff;color:#222}
#bar button.on{color:#fff}
#map{height:100%}
.pin{border-radius:50%;color:#fff;font-weight:700;text-align:center;border:2px solid #fff;box-shadow:0 1px 4px #0006;width:26px;height:26px;line-height:22px;font-size:13px}
.emo{font-size:22px;line-height:24px;text-align:center;filter:drop-shadow(0 1px 2px #0008)}
#note{position:absolute;z-index:1000;bottom:6px;left:6px;background:#fffc;padding:3px 8px;border-radius:4px;font-size:12px;color:#444}
.leg{background:#fffe;border:0;box-shadow:0 1px 3px #0004;font-size:12px}
</style></head><body>
<div id="bar"></div><div id="map"></div>
<div id="note">底图 © 高德地图。实线为按顺序连接的直线，不是真实道路；标注含“高德路线”的是高德查询到的时间，其余为估算。</div>
<script>__JS__</script>
<script>
const DATA = __DATA__;
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const map = L.map('map', {zoomControl:true});
L.tileLayer('https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
  {subdomains:'1234', maxZoom:18, minZoom:3, attribution:'© 高德地图'}).addTo(map);
const groups = [], bar = document.getElementById('bar'), all = [];
const title = document.createElement('div'); title.className='t'; title.textContent = DATA.title; bar.appendChild(title);
const popup = (name, lines) => '<b>'+esc(name)+'</b><br>'+lines.map(esc).join('<br>');
const pin = (txt, color) => L.divIcon({className:'', html:'<div class="pin" style="background:'+color+'">'+esc(txt)+'</div>', iconSize:[26,26], iconAnchor:[13,13]});
const emo = e => L.divIcon({className:'', html:'<div class="emo">'+e+'</div>', iconSize:[26,26], iconAnchor:[13,13]});
if (!DATA.days.length) { const n=document.createElement('div'); n.className='t'; n.textContent='还没有分天的行程'; bar.appendChild(n); }
DATA.days.forEach(d => {
  const g = L.layerGroup(); groups.push({d, g});
  d.stops.forEach(s => { L.marker(s.pos, {icon: pin(s.n, d.color)}).bindPopup(popup(d.label+' · '+s.n+'. '+s.name, s.lines)).addTo(g); all.push(s.pos); });
  d.stops.slice(1).forEach((s, i) => {
    const a = d.stops[i], lg = d.legs[i];
    const line = L.polyline([a.pos, s.pos], {color:d.color, weight:4, opacity:.85}).addTo(g);
    if (lg) line.bindTooltip(esc(lg.mode)+' 约'+lg.minutes+'分钟（'+(lg.real?'高德路线':'估算')+'，'+lg.km+' km）', {permanent:true, className:'leg', direction:'center'});
  });
  d.lodging_legs.forEach(l => L.polyline([l.from, l.to], {color:d.color, weight:2, dashArray:'5 7', opacity:.6}).addTo(g));
  DATA.meals.filter(m => m.day === d.index).forEach(m => { L.marker(m.pos, {icon: emo('🍜')}).bindPopup(popup(d.label+' · 用餐：'+m.name, m.lines)).addTo(g); all.push(m.pos); });
  g.addTo(map);
  const b = document.createElement('button'); b.textContent = d.label; b.className='on'; b.style.background = d.color;
  b.onclick = () => { if (map.hasLayer(g)) { map.removeLayer(g); b.classList.remove('on'); b.style.background='#fff'; } else { g.addTo(map); b.classList.add('on'); b.style.background=d.color; } };
  bar.appendChild(b);
});
if (DATA.lodging) { L.marker(DATA.lodging.pos, {icon: emo('🏨')}).bindPopup(popup('住宿：'+DATA.lodging.name, [])).addTo(map); all.push(DATA.lodging.pos); }
if (all.length) map.fitBounds(L.latLngBounds(all).pad(0.15)); else map.setView([35, 105], 4);
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
