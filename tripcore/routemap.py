"""分享页里的路线图：内联 SVG，不带底图，不联网，不带任何 key。

- 每天一种颜色；真实路线用粗实线，估算（直线）用细线；景点是编号圆点。
- 默认不画酒店，也不画从酒店出发/回酒店的路段（和分享页文字部分的规则一致）；show_lodging=True 才画。
- 页面里带一小段脚本：点“播放路线”按天依次画出来；脚本导出 window.__seek(p)，p 在 0..1，
  供导出 GIF 时逐帧截图（见 share.render_gif）。没有脚本时看到的是画好的完整路线。
"""

from __future__ import annotations

import json
import math
from html import escape
from typing import Any, Callable, Optional

from . import basemap as _bm

W = 360.0
PAD = 18.0
MAX_H = 440.0
MIN_H = 200.0
MAX_PTS_PER_LEG = 80


def _e(x: Any) -> str:
    return escape(str(x), quote=True)


class _Proj:
    def __init__(self, pts: list[tuple[float, float]], max_h: float = MAX_H):
        lats = [p[0] for p in pts]
        lons = [p[1] for p in pts]
        self.lat1 = max(lats)
        self.lon0 = min(lons)
        k = math.cos(math.radians((min(lats) + max(lats)) / 2)) or 1e-6
        self.k = k
        dx = (max(lons) - self.lon0) * k
        dy = self.lat1 - min(lats)
        # 只有一个点（或点挨得极近）时给一个默认范围，免得除零
        dx, dy = max(dx, 1e-4), max(dy, 1e-4)
        scale = min((W - 2 * PAD) / dx, (max_h - 2 * PAD) / dy)
        self.scale = scale
        self.mpu = 111320.0 / scale                      # 每个视图单位约多少米
        self.h = max(MIN_H, dy * scale + 2 * PAD)
        self.ox = (W - dx * scale) / 2
        self.oy = (self.h - dy * scale) / 2

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (self.ox + (lon - self.lon0) * self.k * self.scale, self.oy + (self.lat1 - lat) * self.scale)


_NICE_M = [50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000]


def _fmt_len(m: float) -> str:
    return f"{m / 1000:g} km" if m >= 1000 else f"{m:g} m"


def _fmt_ext(wm: float, hm: float) -> str:
    if max(wm, hm) >= 1000:
        return f"约 {wm / 1000:.1f} × {hm / 1000:.1f} km"
    return f"约 {round(wm, -1):g} × {round(hm, -1):g} m"


def _scalebar(pr) -> str:
    """比例尺：选一个好读的长度，画成 30~110 个视图单位长；放在不压住景点的角落（优先左下，其次右下、右上）。"""
    mpu = getattr(pr, "mpu", 0) or 0
    if mpu <= 0:
        return ""
    best = None
    for m in _NICE_M:
        u = m / mpu
        if 30 <= u <= 110:
            best = (m, u)
    if best is None:
        return ""
    m, u = best
    occ_marks = getattr(pr, "occ_marks", [])
    occ_path = getattr(pr, "occ_path", [])
    ytop = [pr.h - 12.0, pr.h - 12.0, 26.0]                                   # 三个候选的基线 y
    xs = [12.0, W - 12.0 - u, W - 12.0 - u]                                   # 三个候选的起点 x
    pick, score = 0, None
    for i, (x0, y) in enumerate(zip(xs, ytop)):
        bx0, bx1, by0, by1 = x0 - 6 - 8, x0 + u + 6 + 8, y - 14 - 8, y + 8 + 8   # 方框外再留一个圆点的半径
        sc = sum(1 for (px, py) in occ_marks if bx0 <= px <= bx1 and by0 <= py <= by1) * 1000 + \
            sum(1 for (px, py) in occ_path if bx0 <= px <= bx1 and by0 <= py <= by1)
        if score is None or sc < score:
            pick, score = i, sc
    x0, y = xs[pick], ytop[pick]
    return (f'<g class="sc"><rect x="{x0 - 6:.1f}" y="{y - 14:.1f}" width="{u + 12:.1f}" height="22" rx="3" fill="#fff" opacity=".72"/>'
            f'<path d="M{x0:.1f} {y - 4:.1f} V{y:.1f} H{x0 + u:.1f} V{y - 4:.1f}" fill="none" stroke="#333" stroke-width="1.4"/>'
            f'<text x="{x0:.1f}" y="{y - 6:.1f}" class="st">{_fmt_len(m)}</text></g>')


def _extent(pts) -> tuple[float, float]:
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    k = math.cos(math.radians((min(lats) + max(lats)) / 2))
    return ((max(lons) - min(lons)) * 111320.0 * k, (max(lats) - min(lats)) * 111320.0)


def _thin(pts: list[tuple[float, float]], tol: float = 0.6) -> list[tuple[float, float]]:
    """按像素距离抽稀，保证页面不会因为几百个路线点变得很大。"""
    if len(pts) <= 2:
        return pts
    out = [pts[0]]
    for p in pts[1:-1]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= tol * 3:
            out.append(p)
    out.append(pts[-1])
    if len(out) > MAX_PTS_PER_LEG:
        step = len(out) / MAX_PTS_PER_LEG
        out = [out[int(i * step)] for i in range(MAX_PTS_PER_LEG - 1)] + [out[-1]]
    return out


def _d(pts: list[tuple[float, float]]) -> str:
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)


_JS = """(function(){var svg=document.getElementById('rmap');if(!svg)return;
var VB=JSON.parse(svg.getAttribute('data-vb')),EXT=JSON.parse(svg.getAttribute('data-ext')||'{}'),sc=svg.querySelector('.sc'),FULL=svg.getAttribute('viewBox'),FW=+FULL.split(' ')[2];
var legs=[].slice.call(svg.querySelectorAll('.rl path')),stops=[].slice.call(svg.querySelectorAll('.rs g'));
var steps=legs.concat(stops).sort(function(a,b){return a.getAttribute('data-s')-b.getAttribute('data-s')});
var lab=document.getElementById('rm_d'),badge=document.getElementById('rm_n'),total=lab.textContent,T=0,starts=[];
steps.forEach(function(el){var w;if(el.tagName==='path'){var L=el.getTotalLength();el.setAttribute('data-len',L);w=Math.max(L/160,.3)}else{w=.3}starts.push(T);el.setAttribute('data-w',w);T+=w});
function seek(p){var t=p*T,day=-1;steps.forEach(function(el,i){if(t>starts[i]||(p>0&&i===0))day=+el.getAttribute('data-d')});
var live=p>0&&p<1,vb=VB[day],z=1;if(live&&vb){svg.setAttribute('viewBox',vb.join(' '));z=FW/vb[2]}else{svg.setAttribute('viewBox',FULL)}
steps.forEach(function(el,i){var w=+el.getAttribute('data-w'),q=Math.max(0,Math.min(1,(t-starts[i])/w));
if(el.tagName==='path'){var L=+el.getAttribute('data-len');el.style.strokeDasharray=L+' '+L;el.style.strokeDashoffset=L*(1-q);el.style.strokeWidth=((el.getAttribute('class')==='r'?3.4:1.8)/z)+'px'}else{el.style.opacity=q;el.style.transform='scale('+((.6+.4*q)/z)+')'}});
lab.style.display=live?'none':'';badge.textContent=live&&day>=0?'第 '+(day+1)+' 天'+(EXT[day]?' · 范围'+EXT[day]:''):'';if(sc)sc.style.display=live?'none':''}
window.__seek=seek;var raf=0,btn=document.getElementById('rm_b');
function clear(){svg.setAttribute('viewBox',FULL);badge.textContent='';if(sc)sc.style.display='';lab.style.display='';steps.forEach(function(el){el.style.strokeDasharray='';el.style.strokeDashoffset='';el.style.strokeWidth='';el.style.opacity='';el.style.transform=''})}
function play(){cancelAnimationFrame(raf);var D=Math.max(5000,Math.min(16000,T*1100)),t0=null;btn.disabled=true;
function f(ts){if(t0===null)t0=ts;var p=Math.min(1,(ts-t0)/D);seek(p);if(p<1)raf=requestAnimationFrame(f);else{clear();btn.disabled=false;btn.textContent='▶ 再播一次'}}
seek(0.0001);raf=requestAnimationFrame(f)}
btn.onclick=play;window.__rm_ready=true})();"""



def _collect(days, keep, show_lodging):
    legs_raw: list[tuple[int, list[tuple[float, float]], bool]] = []       # (day, 点列, 是否真实路线)
    marks_raw: list[tuple[int, int, float, float, bool]] = []              # (day, n, lat, lon, 是否酒店)
    order: list[tuple[int, str, int]] = []                                  # (day, kind, 序号)，按时间线顺序
    for d in days:
        di = d["index"]
        tl = d["timeline"]
        for i, e in enumerate(tl):
            t = e["type"]
            if t == "leg" and keep(tl, i):
                path = [tuple(p) for p in e.get("path") or []] if e.get("real") else []
                pts = path if len(path) >= 2 else [tuple(e["a"]), tuple(e["b"])]
                legs_raw.append((di, pts, bool(e.get("real") and len(path) >= 2)))
                order.append((di, "leg", len(legs_raw) - 1))
            elif t == "stop":
                marks_raw.append((di, e["n"], e["pos"][0], e["pos"][1], False))
                order.append((di, "mark", len(marks_raw) - 1))
                for pth in (e.get("route") or {}).get("paths", []):
                    legs_raw.append((di, [tuple(p) for p in pth["path"]], bool(pth.get("real"))))
                    order.append((di, "leg", len(legs_raw) - 1))
            elif t == "hotel" and show_lodging:
                marks_raw.append((di, 0, e["pos"][0], e["pos"][1], True))
                order.append((di, "mark", len(marks_raw) - 1))
    return legs_raw, marks_raw, order


def _draw(legs_raw, marks_raw, order, colors, max_h: float = MAX_H, base: Optional[_bm.Basemap] = None):
    """返回 (legs_svg, marks_svg, 投影)；没有点返回 None。"""
    pts_all = [p for _, pts, _ in legs_raw for p in pts] + [(m[2], m[3]) for m in marks_raw]
    if not pts_all:
        return None
    pr = _Proj(pts_all, max_h)
    img = None
    if base is not None:
        view = _bm.choose_view(pts_all, W, pr.h, PAD)
        img = base.fetch(view)
        if img:
            pr = _bm.Projection(view)
    legs_svg, marks_svg = [], []
    occ_marks, occ_path = [], []
    for step, (di, kind, idx) in enumerate(order):
        col = colors[di % len(colors)]
        if kind == "leg":
            _, pts, real = legs_raw[idx]
            xy = _thin([pr.xy(la, lo) for la, lo in pts])
            occ_path.extend(xy)
            legs_svg.append(f'<path data-s="{step}" data-d="{di}" class="{"r" if real else "g"}" style="stroke:{col}" d="{_d(xy)}"/>')
        else:
            _, n, la, lo, hotel = marks_raw[idx]
            x, y = pr.xy(la, lo)
            occ_marks.append((x, y))
            tr = f"transform-origin:{x:.1f}px {y:.1f}px"
            if hotel:
                marks_svg.append(f'<g data-s="{step}" data-d="{di}" style="{tr}"><rect x="{x - 5:.1f}" y="{y - 5:.1f}" width="10" height="10" rx="2" fill="var(--ink)"/>'
                                 f'<text x="{x:.1f}" y="{y + 3.2:.1f}" class="hm">H</text></g>')
            else:
                marks_svg.append(f'<g data-s="{step}" data-d="{di}" style="{tr};--c:{col}"><circle cx="{x:.1f}" cy="{y:.1f}" r="7.5"/>'
                                 f'<text x="{x:.1f}" y="{y + 3.3:.1f}">{n}</text></g>')
    pr.occ_marks, pr.occ_path = occ_marks, occ_path
    pr.ext = _extent(pts_all)
    return legs_svg, marks_svg, pr, img


def _image(img: Optional[str], pr) -> str:
    return f'<image href="{img}" x="0" y="0" width="{W:.0f}" height="{pr.h:.1f}" preserveAspectRatio="none"/>' if img else ""


def build_day(day: dict[str, Any], color: str, keep: Callable[[list[dict], int], bool], show_lodging: bool = False,
              base: Optional[_bm.Basemap] = None) -> str:
    """每天一张按当天范围放大的静态小图；少于 2 个点（没有路段可画）就不画。"""
    legs_raw, marks_raw, order = _collect([day], keep, show_lodging)
    if not legs_raw or len(marks_raw) < 2:
        return ""
    drawn = _draw(legs_raw, marks_raw, order, [color] * (day["index"] + 1), max_h=300.0, base=base)
    if drawn is None:
        return ""
    legs_svg, marks_svg, pr, img = drawn
    return (f'<div class="dmap"><svg class="rsvg{" bm" if img else ""}" viewBox="0 0 {W:.0f} {pr.h:.0f}" role="img" aria-label="当天路线图">{_image(img, pr)}'
            f'<g class="rl">{"".join(legs_svg)}</g><g class="rs">{"".join(marks_svg)}</g>{_scalebar(pr)}</svg>'
            f'<div class="bmc"><span>当天范围{_fmt_ext(*pr.ext)}</span>{"<span>底图 © 高德地图</span>" if img else ""}</div></div>')


def build(days: list[dict[str, Any]], colors: list[str], keep: Callable[[list[dict], int], bool], show_lodging: bool = False,
          base: Optional[_bm.Basemap] = None) -> str:
    """返回总览路线图的 HTML 片段（含样式和脚本）；没有任何可画的点就返回空串。"""
    legs_raw, marks_raw, order = _collect(days, keep, show_lodging)
    drawn = _draw(legs_raw, marks_raw, order, colors, base=base)
    if drawn is None:
        return ""
    legs_svg, marks_svg, pr, img = drawn
    used = sorted({o[0] for o in order})
    vbs: dict[int, list[float]] = {}
    exts: dict[int, str] = {}
    ratio = W / pr.h
    for di in used:
        dpts = [p_ for dd, pts, _ in legs_raw if dd == di for p_ in pts] + [(m[2], m[3]) for m in marks_raw if m[0] == di]
        exts[di] = _fmt_ext(*_extent(dpts))
    for di in ([] if img else used):
        xy = [pr.xy(la, lo) for dd, pts, _ in legs_raw if dd == di for la, lo in pts] + [pr.xy(m[2], m[3]) for m in marks_raw if m[0] == di]
        x0, x1, y0, y1 = min(x for x, _ in xy), max(x for x, _ in xy), min(y for _, y in xy), max(y for _, y in xy)
        w, h = max((x1 - x0) * 1.35, 60.0), max((y1 - y0) * 1.35, 60.0 / ratio)
        if w / h < ratio:
            w = h * ratio
        else:
            h = w / ratio
        vbs[di] = [round((x0 + x1) / 2 - w / 2, 1), round((y0 + y1) / 2 - h / 2, 1), round(w, 1), round(h, 1)]
    legend = "".join(f'<span class="rk"><i style="background:{colors[di % len(colors)]}"></i>第{di + 1}天</span>' for di in used)
    note = "粗线是真实路线，细线是估算（直线）" if any(not r for _, _, r in legs_raw) else "按高德真实路线绘制"
    css = ("<style>.rmap{margin:14px 0;background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:10px 10px 8px;box-shadow:var(--shadow)}"
           ".rmh{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px}.rmh b{font-size:14px;flex:1}"
           ".rmh button{border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:999px;padding:3px 12px;font-size:12.5px;cursor:pointer}.rmh button:disabled{opacity:.5}"
           ".rk{font-size:12px;color:var(--mute);margin-right:8px;white-space:nowrap}.rk i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:3px;vertical-align:-1px}"
           ".rsvg{width:100%;height:auto;display:block}.rsvg .rl path{fill:none;stroke-linecap:round;stroke-linejoin:round;filter:drop-shadow(0 0 .8px rgba(0,0,0,.4))}"
           ".rsvg .rl path.r{stroke-width:3.4}.rsvg .rl path.g{stroke-width:1.8;opacity:.75}.rsvg .rs circle{fill:var(--c);stroke:#fff;stroke-width:1.5}"
           ".rsvg .rs text{font:700 9px sans-serif;text-anchor:middle;fill:var(--on)}.rsvg .rs text.hm{fill:#fff;font-size:8px}#rm_d{font:700 13px sans-serif;fill:var(--mute)}"
           ".rsvg.bm .rl path{filter:drop-shadow(0 0 2px #fff) drop-shadow(0 0 1px #fff)}.bmc{font-size:11px;color:var(--mute);margin-top:2px;display:flex;justify-content:space-between;gap:8px}.rsvg .sc text{font:600 9px sans-serif;fill:#333}.rmw{position:relative}#rm_n{position:absolute;left:8px;top:6px;font:700 15px sans-serif;color:var(--ink);background:var(--chip);border-radius:999px;padding:0 10px}#rm_n:empty{display:none}.rmn{font-size:11.5px;color:var(--mute);margin-top:4px}.dmap{padding:6px 14px 0}.dmap .rsvg{max-height:340px}</style>")
    svg = (f'<svg class="rsvg{" bm" if img else ""}" id="rmap" data-vb="{_e(json.dumps(vbs))}" data-ext="{_e(json.dumps(exts, ensure_ascii=False))}" viewBox="0 0 {W:.0f} {pr.h:.0f}" role="img" aria-label="路线图">{_image(img, pr)}'
           f'<text id="rm_d" x="10" y="18">共 {len(used)} 天</text><g class="rl">{"".join(legs_svg)}</g><g class="rs">{"".join(marks_svg)}</g>{_scalebar(pr)}</svg>')
    return (css + '<section class="rmap"><div class="rmh"><b>路线图</b><button id="rm_b" type="button">▶ 播放路线</button></div>'
            f'<div class="rmh" style="margin:0 0 4px">{legend}</div><div class="rmw">{svg}<div id="rm_n"></div></div><div class="rmn">{_e(note)}；{"底图 © 高德地图，已内嵌在页面里。" if img else "只画路线和景点，不含街道底图。"}</div></section>'
            f"<script>{_JS}</script>")
