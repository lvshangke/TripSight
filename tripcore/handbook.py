"""行程手册：一个可直接打开的网页文件夹（index.html + photos/ + media/），外加每天一张 3:4 卡片和一份发布文案。

只写本地文件，不联网、不连账号；小红书只生成"发布包"，由用户自己上传。内容全部来自行程本身（景点、、营业时间、路线）；
照片只用用户用 add_photo 挂过的原图（已去掉定位等元数据），默认不带；视频只用用户明确给出的文件，原样复制不转码。
酒店、花费默认不出现。导出目录已存在时不覆盖，新建 "-2"、"-3"…。
"""

from __future__ import annotations

import html
import itertools
import math
import re
import shutil
from pathlib import Path
from typing import Any, Optional

from .metrics import day_stats
from .models import Trip
from .timeline import day_visits

WEEK = "一二三四五六日"
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MAX_PHOTOS = 6          # 每个景点最多展示几张，有几张放几张
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}
e = html.escape


def _hm(m: int) -> str:
    return f"{int(m) // 60 % 24:02d}:{int(m) % 60:02d}"


_PIN_IDS = itertools.count(1)


def _dot(i, x, y, pin) -> str:
    """路线图上的一个点：有缩略图就用圆形照片当图钉（带白边和小序号），没有就是带序号的圆点。"""
    if not pin:
        return f'<circle cx="{x:.0f}" cy="{y:.0f}" r="11" class="dot"/><text x="{x:.0f}" y="{y + 4:.0f}" class="dn">{i + 1}</text>'
    cid = f"pin{next(_PIN_IDS)}"
    r = 19
    return (f'<clipPath id="{cid}"><circle cx="{x:.0f}" cy="{y:.0f}" r="{r}"/></clipPath>'
            f'<image href="{pin}" x="{x - r:.0f}" y="{y - r:.0f}" width="{2 * r}" height="{2 * r}" preserveAspectRatio="xMidYMid slice" clip-path="url(#{cid})"/>'
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" class="pinr"/>'
            f'<circle cx="{x - r + 3:.0f}" cy="{y - r + 3:.0f}" r="8" class="pinb"/><text x="{x - r + 3:.0f}" y="{y - r + 7:.0f}" class="pinn">{i + 1}</text>')


def _route_svg(stops, legs, w=520, h=220, bm=None, pins=None) -> str:
    if len(stops) < 2:
        return ""
    segs = [[(q[0], q[1]) for q in lg.path] if (lg.path and lg.detail_level == "route") else None for lg in legs]
    segs = [sg or [stops[i], stops[i + 1]] for i, sg in enumerate(segs)]
    sl, so = [p[0] for p in stops], [p[1] for p in stops]
    mla, mlo = max((max(sl) - min(sl)) * 0.4, 0.004), max((max(so) - min(so)) * 0.4, 0.004)
    inb = lambda p: min(sl) - mla <= p[0] <= max(sl) + mla and min(so) - mlo <= p[1] <= max(so) + mlo
    segs = [[p for p in sg if inb(p)] or [stops[i], stops[i + 1]] for i, sg in enumerate(segs)]   # 超出站点范围的路径点不画
    allp = [p for sg in segs for p in sg] + stops
    la, lo = [p[0] for p in allp], [p[1] for p in allp]
    cls = [f"m-{lg.mode}" + ("" if lg.detail_level != "estimate" else " est") for lg in legs]
    cls += ["m-drive est"] * (len(segs) - len(cls))
    modes = [lg.mode for lg in legs]
    leg_svg = _mode_legend(modes, w, h)
    if bm is not None:                              # 有底图：投影和高德底图严格对应，路线画在图上
        from .basemap import Projection, choose_view
        view = choose_view(stops, w, h, 36)
        uri = bm.fetch(view)
        if uri:
            proj = Projection(view)
            q = lambda p: proj.xy(p[0], p[1])
            lines = "".join('<polyline points="' + " ".join(f"{q(p)[0]:.0f},{q(p)[1]:.0f}" for p in sg) + f'" class="line bl {cls[i]}"/>' for i, sg in enumerate(segs))
            dots = "".join(_dot(i, q(p)[0], q(p)[1], pins[i] if pins else None) for i, p in enumerate(stops))
            return f'<svg viewBox="0 0 {w} {h}" class="route"><image href="{uri}" width="{w}" height="{h}"/>{lines}{dots}{leg_svg}</svg>'
    k = math.cos(math.radians(sum(la) / len(la)))
    x0, y0 = min(lo), max(la)
    W, H = (max(lo) - x0) * k or 1e-6, (y0 - min(la)) or 1e-6
    sc = min((w - 60) / W, (h - 90) / H)                       # 底部留出图例的位置
    ox, oy = (w - W * sc) / 2, (h - 28 - H * sc) / 2
    pr = lambda p: (ox + (p[1] - x0) * k * sc, oy + (y0 - p[0]) * sc)
    lines = "".join('<polyline points="' + " ".join(f"{pr(p)[0]:.0f},{pr(p)[1]:.0f}" for p in sg) + f'" class="line {cls[i]}"/>' for i, sg in enumerate(segs))
    dots = "".join(_dot(i, pr(p)[0], pr(p)[1], pins[i] if pins else None) for i, p in enumerate(stops))
    return f'<svg viewBox="0 0 {w} {h}" class="route">{lines}{dots}{leg_svg}</svg>'


_MODE_NAMES = {"walk": "步行", "transit": "公交/地铁", "drive": "驾车"}


def _mode_legend(modes, w, h) -> str:
    """图例画在图里（跟着图一起缩放）：用线型区分交通方式，不只靠颜色；淡色表示估算的路线。只在图里出现不止一种方式、或有估算时才画。"""
    present = [m for m in ("walk", "transit", "drive") if m in modes]
    if not present:
        return ""
    x, items = 12.0, []
    for m in present:
        items.append(f'<line x1="{x:.0f}" y1="{h - 14}" x2="{x + 26:.0f}" y2="{h - 14}" class="line lg m-{m}"/>'
                     f'<text x="{x + 32:.0f}" y="{h - 10}" class="lt">{_MODE_NAMES[m]}</text>')
        x += 32 + 14 * len(_MODE_NAMES[m]) + 14
    return f'<rect x="4" y="{h - 28}" width="{x - 4:.0f}" height="24" rx="6" class="lgbg"/>' + "".join(items)


THEMES = {      # 只换配色、字体和相框角度，都是浅色底
    "手账": {},
    "杂志": {"bg": "#ffffff", "paper": "#ffffff", "ink": "#111111", "sub": "#6b6b6b", "acc": "#d62828", "line": "#dddddd", "tape": "#ffffff", "rot": "0deg", "font": '"Playfair Display","Noto Serif SC","Songti SC",serif'},
    "清新": {"bg": "#eef6f1", "paper": "#fbfffc", "ink": "#25403a", "sub": "#6b8a80", "acc": "#2e9c7f", "line": "#cfe3d9", "tape": "#bfe6d6", "rot": "-1deg", "font": '"PingFang SC","Noto Sans SC",sans-serif'},
    "胶片": {"bg": "#e9e0d0", "paper": "#f6efe2", "ink": "#3b2f25", "sub": "#8a7a68", "acc": "#a4531f", "line": "#d3c5ae", "tape": "#d9b98a", "rot": "1.5deg", "font": '"Songti SC","Noto Serif SC",serif'},
    "海边": {"bg": "#eaf3f9", "paper": "#ffffff", "ink": "#1f3b52", "sub": "#6b8aa3", "acc": "#1f7fbf", "line": "#cfe0ee", "tape": "#bfdcf0", "rot": "-1.5deg", "font": '"PingFang SC","Noto Sans SC",sans-serif'},
}

EDIT_JS = """<style>[data-ed]{outline:none;cursor:text;border-radius:4px}[data-ed]:hover{background:rgba(196,85,58,.1)}[data-ed]:focus{background:rgba(196,85,58,.16);box-shadow:0 0 0 2px rgba(196,85,58,.4)}[data-ed]:empty:before{content:"点这里写几句…";color:#aaa;font-style:normal}
.rzh{position:absolute;right:-8px;bottom:-8px;width:18px;height:18px;border-radius:50%;background:#c4553a;border:2px solid #fff;cursor:nwse-resize;touch-action:none;z-index:3;box-shadow:0 1px 4px rgba(0,0,0,.35)}
.ed-tip{position:fixed;left:50%;transform:translateX(-50%);bottom:10px;background:rgba(40,40,40,.85);color:#fff;font:13px sans-serif;padding:6px 12px;border-radius:14px;z-index:9}</style>
<div class="ed-tip">可编辑预览：点标题/文字直接改，拖照片右下角的红点调大小</div>
<script>(function(){const send=m=>parent.postMessage(Object.assign({tripsight:1},m),'*');
document.querySelectorAll('[data-ed]').forEach(el=>{el.contentEditable='true';el.spellcheck=false;let v=el.textContent;
el.addEventListener('focus',()=>{v=el.textContent});
el.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();el.blur()}});
el.addEventListener('blur',()=>{const t=el.textContent.trim();if(t!==v.trim()){const a=el.dataset.ed.split(':');send({k:a[0],id:a[1],text:t})}})});
document.querySelectorAll('[data-rz]').forEach(box=>{const h=document.createElement('span');h.className='rzh';h.title='拖动调整大小';box.appendChild(h);
h.addEventListener('pointerdown',e=>{e.preventDefault();h.setPointerCapture(e.pointerId);const w0=box.getBoundingClientRect().width,base=parseFloat(box.dataset.rz)||100,x0=e.clientX;let now=0;
const mv=ev=>{now=Math.max(40,Math.min(160,Math.round(base*(w0+(ev.clientX-x0))/w0)));box.style.setProperty('--s',now/100)};
const up=()=>{h.removeEventListener('pointermove',mv);h.removeEventListener('pointerup',up);if(now){box.dataset.rz=now;send({k:'scale',id:box.dataset.pid,scale:now})}};
h.addEventListener('pointermove',mv);h.addEventListener('pointerup',up)})});})();</script>"""


def theme_css(name: str) -> str:
    t = THEMES.get(name)
    if not t:
        return ""
    v = {"bg": "--bg", "paper": "--paper", "ink": "--ink", "sub": "--sub", "acc": "--acc", "line": "--line", "tape": "--tape", "rot": "--rot"}
    css = ":root{" + ";".join(f"{v[k]}:{t[k]}" for k in v if k in t) + "}"
    if "font" in t:
        css += "body{font-family:" + t["font"] + "}"
    return css


CSS = """
:root{--bg:#f6f1e7;--paper:#fffdf8;--ink:#33302b;--sub:#7a7468;--acc:#c4553a;--line:#e3dac8;--tape:#f0d98a}
*{box-sizing:border-box;margin:0}body{background:var(--bg);color:var(--ink);font-family:"Noto Serif SC","Songti SC",serif;line-height:1.65}
.wrap{max-width:760px;margin:0 auto;padding:0 16px 48px}
.cover{padding:64px 0 36px;text-align:center}.cover .k{letter-spacing:.4em;color:var(--acc);font-size:13px}
.cover h1{font-size:40px;margin:10px 0 8px;font-weight:700}.cover .m{color:var(--sub);font-size:15px}
.day{margin-top:36px}.dh{display:flex;align-items:baseline;gap:12px;border-bottom:2px solid var(--ink);padding-bottom:6px;flex-wrap:wrap}
.dh h2{font-size:26px}.dh span{color:var(--sub);font-size:14px}.wx{color:var(--sub);font-size:14px;margin-top:6px}
.route{width:100%;margin:14px 0;background:var(--paper);border:1px solid var(--line);border-radius:10px}
.line{fill:none;stroke:var(--acc);stroke-width:3;stroke-dasharray:7 6;stroke-linecap:round}.dot{fill:var(--paper);stroke:var(--acc);stroke-width:2.5}.bl{stroke-width:3.5;stroke:#d9381e}.m-walk{stroke-dasharray:1 7!important}.m-transit{stroke-dasharray:none!important}.m-drive{stroke-dasharray:14 7!important}.est{opacity:.5}.pinr{fill:none;stroke:#fff;stroke-width:3}.pinb{fill:var(--acc)}.pinn{font-size:10px;fill:#fff;text-anchor:middle;font-family:sans-serif;font-weight:700}.lg{stroke-width:3}.lgbg{fill:#fff;opacity:.85}.lt{font-size:12px;fill:#33302b;font-family:sans-serif}.gal{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:16px 14px;align-items:start;margin:18px 6px 6px}.gal figure{position:relative;width:calc(100% * var(--s,1));max-width:100%;justify-self:center;margin:0;background:#fff;padding:7px 7px 22px;box-shadow:0 5px 14px rgba(0,0,0,.16);transform:rotate(var(--gr,1.5deg))}.gal figure:nth-child(2n){--gr:-1.8deg}.gal figure:nth-child(3n){--gr:.8deg}.gal img{width:100%;height:auto;display:block;cursor:zoom-in}
.lb{position:fixed;inset:0;background:rgba(0,0,0,.88);display:flex;align-items:center;justify-content:center;z-index:9;cursor:zoom-out}.lb img{max-width:96vw;max-height:94vh}
@media print{.lb{display:none}.stop{break-inside:avoid}.day{break-before:page}}
.dn{font:700 12px sans-serif;text-anchor:middle;fill:var(--acc)}
.stop{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:14px 0;box-shadow:0 2px 0 var(--line)}
.stop h3{font-size:20px}.stop h3 b{color:var(--acc);margin-right:6px}.meta{color:var(--sub);font-size:14px;margin-top:2px}
.leg{color:var(--sub);font-size:13px;border-left:3px dotted var(--line);margin:0 0 0 18px;padding:2px 0 2px 14px}
.polaroid{position:relative;width:calc(min(300px,78%) * var(--s,1));max-width:100%;margin:14px auto 4px;background:#fff;padding:10px 10px 38px;box-shadow:0 6px 18px rgba(0,0,0,.18);transform:rotate(var(--rot,-2deg))}
.polaroid:before{content:"";position:absolute;top:-12px;left:36%;width:80px;height:22px;background:var(--tape);opacity:.8;transform:rotate(3deg)}
.polaroid img,.polaroid video{width:100%;display:block}.cap{position:absolute;left:0;right:0;bottom:9px;text-align:center;font-size:14px;color:var(--sub)}
.tabs{display:flex;gap:8px;justify-content:center;margin:6px 0 0}.tabs button{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--paper);color:var(--ink);border-radius:99px;padding:3px 12px;cursor:pointer}
.tabs button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.tot{font-size:36px;font-weight:700;color:var(--acc)}.tot small{font-size:14px;color:var(--sub);font-weight:400}.sp{list-style:none;margin:8px 0 0}.sp li{display:flex;justify-content:space-between;border-bottom:1px dotted var(--line);padding:3px 0}
.rg{background:var(--tape);color:var(--ink);border-radius:99px;padding:0 8px;font-size:12px}
.facts{margin:10px 0 0 18px;font-size:14px;color:var(--ink)}.facts small,.imp small{color:var(--sub);font-size:12px}.facts a{color:var(--sub)}
.imp{margin-top:10px;padding:8px 12px;border-left:3px solid var(--acc);background:#fbf5ea;font-size:15px;font-style:italic}.imp small{display:block;font-style:normal;margin-top:2px}
.foot{margin-top:40px;text-align:center;color:var(--sub);font-size:13px}
"""
JS = """<script>document.querySelectorAll('.tabs').forEach(t=>{const box=t.previousElementSibling.firstElementChild;t.querySelectorAll('button').forEach(b=>b.onclick=()=>{
t.querySelectorAll('button').forEach(x=>x.classList.remove('on'));b.classList.add('on');box.querySelectorAll('[data-k]').forEach(el=>{el.style.display=el.dataset.k===b.dataset.k?'block':'none';if(el.tagName==='VIDEO'&&el.dataset.k!==b.dataset.k)el.pause()})})})document.querySelectorAll('.gal img,.polaroid img').forEach(i=>i.onclick=()=>{const o=document.createElement('div');o.className='lb';const m=document.createElement('img');m.src=i.src;o.appendChild(m);o.onclick=()=>o.remove();document.body.appendChild(o)})</script>"""


def _scale_attrs(ph: dict, edit: bool) -> str:
    """照片的显示比例（--s，1=默认大小）和预览里拖动调整用的标记；导出的文件里只有 style。"""
    sc = ph.get("scale")
    a = f' style="--s:{sc / 100:g}"' if sc else ""
    if edit:
        a += f' data-rz="{sc or 100}" data-pid="{e(str(ph.get("id", "")))}"'
    return a


def _fig(ph: dict, name: str, edit: bool) -> str:
    cap = e(ph.get("caption") or name)
    return f'<figure{_scale_attrs(ph, edit)}><img src="photos/{ph["file"]}" alt="{cap}" loading="lazy"></figure>'


def _card_html(trip_name, idx, d, vs, km, legs, pic, bm=None, style="手账", pins=None, title="") -> str:
    n_st = len(vs)
    many = n_st > 12                                   # 站点太多：照片拼贴让位，名字分两列排，字号随数量缩小，保证每一站都写得下
    rows_h = min(96, 640 // max(1, (n_st + 1) // 2 if many else n_st))
    fs = max(18, int(min(38, rows_h * 0.4)))
    items = f'<div class="rl{" two" if many else ""}" style="--rh:{rows_h}px;--fs:{fs}px;--rows:{(n_st + 1) // 2}">' + "".join(f'<div class="r"><b>{i + 1}</b><i>{_hm(v.arrive)}</i><span>{e(v.place.name)}</span></div>' for i, v in enumerate(vs)) + "</div>"
    pics = [x for x in (pic if isinstance(pic, list) else ([pic] if pic else []))][:5] if len(vs) <= 12 else []
    n = len(pics)
    pic_html = f'<div class="col n{n}">' + "".join(f'<div class="ph p{i}"><img src="{q}"></div>' for i, q in enumerate(pics)) + "</div>" if n else ""
    date = f"{d.month}月{d.day}日 周{WEEK[d.weekday()]} · " if d else ""
    return f"""<!doctype html><meta charset="utf-8"><style>{CSS}{theme_css(style)}
body{{width:1080px;height:1440px;overflow:hidden}}.c{{padding:70px}}.h{{font-size:30px;letter-spacing:.3em;color:var(--acc)}}
.t{{font-size:84px;font-weight:700;margin:14px 0 4px}}.s{{font-size:30px;color:var(--sub)}}.route{{margin:30px 0;height:330px}}
.rl{{max-width:540px}}.rl.two{{max-width:none;display:grid;grid-template-columns:1fr 1fr;grid-auto-flow:column;grid-template-rows:repeat(var(--rows),var(--rh));column-gap:30px}}
.r{{display:flex;align-items:center;gap:calc(var(--fs)*.4);font-size:var(--fs);height:var(--rh);margin:0;min-width:0}}.r b{{flex:none;width:calc(var(--fs)*1.25);height:calc(var(--fs)*1.25);border-radius:50%;border:3px solid var(--acc);color:var(--acc);display:flex;align-items:center;justify-content:center;font-size:calc(var(--fs)*.62)}}
.r span{{flex:1;min-width:0;line-height:1.12;max-height:calc(var(--rh) - 4px);overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}}.r i{{flex:none;font-style:normal;color:var(--sub);font-size:calc(var(--fs)*.72);width:calc(var(--fs)*2.1)}}
.col{{position:absolute;right:56px;bottom:56px;width:430px;display:grid;gap:14px;grid-template-columns:1fr}}.ph{{background:#fff;padding:12px 12px 36px;box-shadow:0 10px 26px rgba(0,0,0,.2)}}.ph img{{width:100%;display:block;aspect-ratio:4/3;object-fit:cover;object-position:50% 22%}}
.col.n1 .ph{{transform:rotate(3deg)}}.col.n2 .ph:nth-child(1){{transform:rotate(-2deg)}}.col.n2 .ph:nth-child(2){{transform:rotate(2.5deg)}}
.col.n2{{width:370px}}.col.n3,.col.n4,.col.n5{{grid-template-columns:1fr 1fr;width:420px}}.col.n3 .ph img,.col.n4 .ph img,.col.n5 .ph img{{aspect-ratio:3/2}}.col.n3 .ph:first-child,.col.n5 .ph:first-child{{grid-column:1/3}}.col.n3 .ph,.col.n4 .ph,.col.n5 .ph{{padding:8px 8px 22px}}
.col.n3 .ph:nth-child(1){{transform:rotate(-1.5deg)}}.col.n3 .ph:nth-child(2){{transform:rotate(2deg)}}.col.n3 .ph:nth-child(3){{transform:rotate(-2deg)}}.col.n4 .ph:nth-child(odd),.col.n5 .ph:nth-child(odd){{transform:rotate(-1.5deg)}}.col.n4 .ph:nth-child(even),.col.n5 .ph:nth-child(even){{transform:rotate(2deg)}}
.f{{position:absolute;left:70px;bottom:50px;font-size:24px;color:var(--sub)}}</style>
<div class="c"><div class="h">TRIPSIGHT · {e(trip_name)}</div><div class="t" style="font-size:{max(46, min(84, 840 // max(1, len(title)))) if title else 84}px">{e(title) if title else f"第 {idx + 1} 天"}</div><div class="s">{f"第 {idx + 1} 天 · " if title else ""}{date}{len(vs)} 站 · {km} km</div>
{_route_svg([(v.place.lat, v.place.lon) for v in vs], legs, 940, 330, bm=bm, pins=pins)}{items}</div>{pic_html}"""


def build_handbook(trip: Trip, out_root: Path, *, photos: Optional[list[dict]] = None, photo_dir: Optional[Path] = None,
                   show_photos: bool = True, videos: Optional[dict[str, Path]] = None, cards: bool = True,
                   stories: Optional[dict[str, Any]] = None, basemap: Any = None, pdf: bool = False, style: str = "手账", regions: Optional[dict[str, str]] = None, spending: Optional[dict[str, Any]] = None, thumb_pins: bool = False, card_preview: Optional[list] = None, card_photos: int = 3, day_titles: Optional[dict[str, str]] = None, edit: bool = False) -> dict[str, Any]:
    """返回 {"folder", "files", "skipped"}。videos = {place_id: 视频文件}，只有 show_photos 或给了 videos 时才会出现对应素材。"""
    if trip.plan is None or not trip.plan.days:
        raise ValueError("行程还没有排好，无法生成手册")
    base = _BAD.sub(" ", trip.meta.name).strip(" .") or "TripSight 手册"
    root, n = out_root / f"{base}-手册", 2
    while root.exists():
        root = out_root / f"{base}-手册-{n}"; n += 1
    for d in ("photos", "media", "cards"):
        (root / d).mkdir(parents=True)
    files: list[str] = []
    skipped: list[str] = []
    by_place: dict[str, list[dict]] = {}
    if show_photos and photos and photo_dir:
        for ph in photos:
            if not ph.get("place_id") or ph.get("hide"):          # 用户在工作台里点了“不放进手册”的不导出
                continue
            from . import photos as _phm
            if not _phm.export_to(Path(photo_dir), ph["file"], root / "photos" / ph["file"]):
                skipped.append(f"照片缺失（原文件被移动或删除了？）：{ph['file']}")
                continue
            files.append(f"photos/{ph['file']}")
            by_place.setdefault(ph["place_id"], []).append({"file": ph["file"], "caption": ph.get("caption", ""), "id": ph.get("id", ""), "scale": ph.get("scale")})
    pin_of: dict[str, str] = {}
    if thumb_pins and photo_dir:                          # 路线图上用每个点的第一张照片当图钉（96 像素小图，内嵌，现场从原文件生成）
        from . import photos as _phm
        for pid, lst in by_place.items():
            u = _phm.thumb_uri(Path(photo_dir), lst[0]["file"], 96, 72)
            if u:
                pin_of[pid] = u
    vids: dict[str, str] = {}
    for pid, vp in (videos or {}).items():
        vp = Path(vp)
        if vp.suffix.lower() not in VIDEO_EXT or not vp.is_file():
            skipped.append(f"视频不可用：{vp.name}"); continue
        dst = root / "media" / f"{pid}{vp.suffix.lower()}"
        shutil.copy2(vp, dst); files.append(f"media/{dst.name}"); vids[pid] = f"media/{dst.name}"

    days_html, card_jobs, km_all, stops_all = [], [], 0.0, 0
    dt = {str(k): v for k, v in (day_titles or {}).items() if v}
    rg = regions or {}
    for day in trip.plan.days:
        vs, _ = day_visits(trip, day)
        if not vs:
            continue
        st = day_stats(trip, day)
        d = trip.day_date(day.index)
        km = round(sum(lg.distance_km for lg in st.legs), 1)
        km_all += km; stops_all += len(vs)
        dtitle = dt.get(str(day.index + 1), "")
        ed_t = f' data-ed="title:{day.index + 1}"' if edit else ""
        head = f'<section class="day"><div class="dh"><h2{ed_t}>{e(dtitle) if dtitle else f"第 {day.index + 1} 天"}</h2><span>' + (f"第 {day.index + 1} 天 · " if dtitle else "") + (f"{d.month}月{d.day}日 周{WEEK[d.weekday()]} · " if d else "") + f"{len(vs)} 站 · {km} km</span></div>"
        wx = (trip.weather or {}).get(d.isoformat()) if d else None
        if wx is not None and getattr(wx, "day_weather", ""):
            head += f'<div class="wx">天气预报：{e(wx.day_weather)} {round(wx.day_temp)}°C（预报，非实况）</div>'
        parts = [head, _route_svg([(v.place.lat, v.place.lon) for v in vs], st.legs, bm=basemap, pins=[pin_of.get(v.place.id) for v in vs] if thumb_pins else None)]
        first_pic = None
        for i, v in enumerate(vs):
            p = v.place
            rgtag = f'<span class="rg">{e(rg[p.id])}</span> · ' if rg.get(p.id) else ''
            hours_sep = f" · 营业：{e(p.opening_hours)}" if p.opening_hours else ""
            body = f'<div class="stop"><h3><b>{i + 1}</b>{e(p.name)}</h3><div class="meta">{rgtag}{_hm(v.arrive)}–{_hm(v.leave)} · 建议停留 {p.duration_min} 分钟{hours_sep}</div>'
            views, tabs = "", []
            pics = by_place.get(p.id, [])[:MAX_PHOTOS]
            if pics:
                views += f'<img data-k="photo" src="photos/{pics[0]["file"]}" alt="{e(p.name)}">'; tabs.append(("photo", "照片"))
                first_pic = first_pic or f"../photos/{pics[0]['file']}"
            if p.id in vids:
                views += f'<video data-k="video" {"style=display:none " if tabs else ""}src="{vids[p.id]}" controls loop playsinline preload="none"></video>'; tabs.append(("video", "视频"))
            if views:
                cap = by_place.get(p.id, [{}])[0].get("caption", "") or p.name
                pol = _scale_attrs(pics[0], edit) if pics else ""
                body += f'<div class="polaroid"{pol}><div>{views}</div><div class="cap">{e(cap)}</div></div>'
                if len(tabs) > 1:
                    body += '<div class="tabs">' + "".join(f'<button data-k="{k}" class="{"on" if j == 0 else ""}">{nm}</button>' for j, (k, nm) in enumerate(tabs)) + "</div>"
                else:
                    body += '<div class="tabs" style="display:none"></div>'
            if len(pics) > 1:
                body += '<div class="gal">' + "".join(_fig(ph, p.name, edit) for ph in pics[1:]) + "</div>"
            sty = (stories or {}).get(p.id) or {}
            if sty.get("facts"):
                body += '<ul class="facts">' + "".join(
                    f'<li>{e(f["text"])} <small>来源：' + (f'<a href="{e(f["source"])}" rel="noreferrer">{e(f["source"])}</a>' if f["source"].startswith("http") else e(f["source"])) + "</small></li>"
                    for f in sty["facts"]) + "</ul>"
            if edit:
                body += f'<p class="imp">“<span data-ed="imp:{e(p.id)}">{e(sty.get("impression", ""))}</span>”<small>{"我写的" if sty.get("by") == "user" else "AI 根据照片的描写，仅供参考，可修改"}</small></p>'
            elif sty.get("impression"):
                body += f'<p class="imp">“{e(sty["impression"])}”<small>{"我写的" if sty.get("by") == "user" else "AI 根据照片的描写，仅供参考，可修改"}</small></p>'
            body += "</div>"
            parts.append(body)
            if i < len(st.legs):
                lg = st.legs[i]
                parts.append(f'<div class="leg">{e(lg.note or lg.mode)} · {lg.distance_km} km · {lg.minutes} 分钟' + ("（估算）" if lg.detail_level == "estimate" else "") + "</div>")
        parts.append("</section>")
        days_html.append("".join(parts))
        pool = [list(by_place.get(v.place.id, [])) for v in vs]
        picked: list[str] = []
        for r in range(MAX_PHOTOS):                       # 轮流从每一站取，最多 card_photos 张，让一天的卡片尽量覆盖不同地方
            for lst in pool:
                if r < len(lst) and len(picked) < max(1, min(int(card_photos), 5)):
                    picked.append(f"../photos/{lst[r]['file']}")
        card_jobs.append((day.index, d, vs, km, st.legs, picked))

    sp_html = ""
    if spending and spending.get("count"):
        cats = "".join(f'<li><span>{e(k)}</span><b>{v:g} 元</b></li>' for k, v in sorted(spending["by_category"].items(), key=lambda kv: -kv[1]))
        sp_html = (f'<section class="day"><div class="dh"><h2>后记</h2><span>这一趟的花费</span></div><div class="stop"><div class="tot">{spending["total"]:g}<small> 元 · {spending["count"]} 笔</small></div>'
                   f'<ul class="sp">{cats}</ul></div></section>')
    from .regions import order_of_appearance
    order_ids = [v.place.id for day in trip.plan.days for v in day_visits(trip, day)[0]]
    chs = order_of_appearance(order_ids, rg)
    chap_html = '<div class="m">' + ' → '.join(e(c) for c in chs) + '</div>' if len(chs) > 1 else ''
    foot = '<div class="foot">营业时间来自地图服务，出发前请再核实。</div>' if any(p.opening_hours for p in trip.places) else ""
    title = e(trip.meta.name)
    page = (f'<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · 行程手册</title><style>{CSS}{theme_css(style)}</style>'
            f'<div class="wrap"><div class="cover"><div class="k">TRIPSIGHT · 行程手册</div><h1>{title}</h1><div class="m">{len(trip.plan.days)} 天 · {stops_all} 站 · 约 {round(km_all, 1)} km</div>{chap_html}</div>'
            f'{"".join(days_html)}{sp_html}{foot}</div>{JS}{EDIT_JS if edit else ""}</html>')
    (root / "index.html").write_text(page, encoding="utf-8"); files.append("index.html")

    if card_preview is not None and card_jobs:                  # 只要第一天卡片的 HTML 给预览用，不渲染图
        idx, d, vs, km, legs, pic = card_jobs[0]
        card_preview.append(_card_html(trip.meta.name, idx, d, vs, km, legs, pic, basemap, style, [pin_of.get(v.place.id) for v in vs] if thumb_pins else None, dt.get(str(idx + 1), "")))
    if cards:
        from . import share as _share
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = _share._launch(p)
                pg = b.new_page(viewport={"width": 1080, "height": 1440})
                for idx, d, vs, km, legs, pic in card_jobs:
                    f = root / "cards" / f"day{idx + 1}.html"
                    f.write_text(_card_html(trip.meta.name, idx, d, vs, km, legs, pic, basemap, style, [pin_of.get(v.place.id) for v in vs] if thumb_pins else None, dt.get(str(idx + 1), "")), encoding="utf-8")
                    pg.goto(f.resolve().as_uri()); pg.wait_for_timeout(200)
                    pg.screenshot(path=str(f.with_suffix(".png"))); f.unlink(); files.append(f"cards/day{idx + 1}.png")
                b.close()
        except ImportError:
            skipped.append("卡片图：没有安装 playwright（pip install playwright && python -m playwright install chromium）")
        except Exception as ex:
            skipped.append(f"卡片图失败：{type(ex).__name__}")
    if pdf:
        try:
            from playwright.sync_api import sync_playwright
            from . import share as _share
            with sync_playwright() as p:
                b = _share._launch(p)
                pg = b.new_page()
                pg.goto((root / "index.html").resolve().as_uri()); pg.wait_for_timeout(300)
                pg.pdf(path=str(root / f"{base}.pdf"), format="A4", print_background=True, margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
                b.close()
            files.append(f"{base}.pdf")
        except ImportError:
            skipped.append("PDF：没有安装 playwright（pip install playwright && python -m playwright install chromium）")
        except Exception as ex:
            skipped.append(f"PDF 失败：{type(ex).__name__}")
    for d in ("photos", "media", "cards"):
        if not any((root / d).iterdir()):
            (root / d).rmdir()
    cap = [f"{trip.meta.name}｜{len(trip.plan.days)} 天行程手册"]
    for idx, d, vs, km, legs, pic in card_jobs:
        cap.append(f"第{idx + 1}天：" + "→".join(v.place.name for v in vs))
    (root / "caption.txt").write_text("\n".join(cap) + "\n", encoding="utf-8"); files.append("caption.txt")
    return {"folder": str(root), "files": files, "skipped": skipped}
