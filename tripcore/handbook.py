"""行程手册：一个可直接打开的网页文件夹（index.html + photos/ + media/），外加每天一张 3:4 卡片和一份发布文案。

只写本地文件，不联网、不连账号；小红书只生成"发布包"，由用户自己上传。内容全部来自行程本身（景点、、营业时间、路线）；
照片只用用户用 add_photo 挂过的原图（已去掉定位等元数据），默认不带；视频只用用户明确给出的文件，原样复制不转码。
酒店、花费默认不出现。导出目录已存在时不覆盖，新建 "-2"、"-3"…。
"""

from __future__ import annotations

import html
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


def _route_svg(stops, legs, w=520, h=220, bm=None) -> str:
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
    if bm is not None:                              # 有底图：投影和高德底图严格对应，路线画在图上
        from .basemap import Projection, choose_view
        view = choose_view(stops, w, h, 36)
        uri = bm.fetch(view)
        if uri:
            proj = Projection(view)
            q = lambda p: proj.xy(p[0], p[1])
            lines = "".join('<polyline points="' + " ".join(f"{q(p)[0]:.0f},{q(p)[1]:.0f}" for p in sg) + '" class="line bl"/>' for sg in segs)
            dots = "".join(f'<circle cx="{q(p)[0]:.0f}" cy="{q(p)[1]:.0f}" r="11" class="dot"/><text x="{q(p)[0]:.0f}" y="{q(p)[1] + 4:.0f}" class="dn">{i + 1}</text>' for i, p in enumerate(stops))
            return f'<svg viewBox="0 0 {w} {h}" class="route"><image href="{uri}" width="{w}" height="{h}"/>{lines}{dots}</svg>'
    k = math.cos(math.radians(sum(la) / len(la)))
    x0, y0 = min(lo), max(la)
    W, H = (max(lo) - x0) * k or 1e-6, (y0 - min(la)) or 1e-6
    sc = min((w - 60) / W, (h - 50) / H)
    ox, oy = (w - W * sc) / 2, (h - H * sc) / 2
    pr = lambda p: (ox + (p[1] - x0) * k * sc, oy + (y0 - p[0]) * sc)
    lines = "".join('<polyline points="' + " ".join(f"{pr(p)[0]:.0f},{pr(p)[1]:.0f}" for p in sg) + '" class="line"/>' for sg in segs)
    dots = "".join(f'<circle cx="{pr(p)[0]:.0f}" cy="{pr(p)[1]:.0f}" r="11" class="dot"/><text x="{pr(p)[0]:.0f}" y="{pr(p)[1] + 4:.0f}" class="dn">{i + 1}</text>'
                   for i, p in enumerate(stops))
    return f'<svg viewBox="0 0 {w} {h}" class="route">{lines}{dots}</svg>'


THEMES = {      # 只换配色、字体和相框角度，都是浅色底
    "手账": {},
    "杂志": {"bg": "#ffffff", "paper": "#ffffff", "ink": "#111111", "sub": "#6b6b6b", "acc": "#d62828", "line": "#dddddd", "tape": "#ffffff", "rot": "0deg", "font": '"Playfair Display","Noto Serif SC","Songti SC",serif'},
    "清新": {"bg": "#eef6f1", "paper": "#fbfffc", "ink": "#25403a", "sub": "#6b8a80", "acc": "#2e9c7f", "line": "#cfe3d9", "tape": "#bfe6d6", "rot": "-1deg", "font": '"PingFang SC","Noto Sans SC",sans-serif'},
    "胶片": {"bg": "#e9e0d0", "paper": "#f6efe2", "ink": "#3b2f25", "sub": "#8a7a68", "acc": "#a4531f", "line": "#d3c5ae", "tape": "#d9b98a", "rot": "1.5deg", "font": '"Songti SC","Noto Serif SC",serif'},
    "海边": {"bg": "#eaf3f9", "paper": "#ffffff", "ink": "#1f3b52", "sub": "#6b8aa3", "acc": "#1f7fbf", "line": "#cfe0ee", "tape": "#bfdcf0", "rot": "-1.5deg", "font": '"PingFang SC","Noto Sans SC",sans-serif'},
}


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
.line{fill:none;stroke:var(--acc);stroke-width:3;stroke-dasharray:7 6;stroke-linecap:round}.dot{fill:var(--paper);stroke:var(--acc);stroke-width:2.5}.bl{stroke-width:3.5;stroke:#d9381e}.gal{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 2px}.gal img{width:calc(33.3% - 4px);aspect-ratio:1;object-fit:cover;border-radius:6px;cursor:zoom-in}
.lb{position:fixed;inset:0;background:rgba(0,0,0,.88);display:flex;align-items:center;justify-content:center;z-index:9;cursor:zoom-out}.lb img{max-width:96vw;max-height:94vh}
@media print{.lb{display:none}.stop{break-inside:avoid}.day{break-before:page}}
.dn{font:700 12px sans-serif;text-anchor:middle;fill:var(--acc)}
.stop{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:14px 0;box-shadow:0 2px 0 var(--line)}
.stop h3{font-size:20px}.stop h3 b{color:var(--acc);margin-right:6px}.meta{color:var(--sub);font-size:14px;margin-top:2px}
.leg{color:var(--sub);font-size:13px;border-left:3px dotted var(--line);margin:0 0 0 18px;padding:2px 0 2px 14px}
.polaroid{position:relative;width:min(300px,78%);margin:14px auto 4px;background:#fff;padding:10px 10px 38px;box-shadow:0 6px 18px rgba(0,0,0,.18);transform:rotate(var(--rot,-2deg))}
.polaroid:before{content:"";position:absolute;top:-12px;left:36%;width:80px;height:22px;background:var(--tape);opacity:.8;transform:rotate(3deg)}
.polaroid img,.polaroid video{width:100%;display:block}.cap{position:absolute;left:0;right:0;bottom:9px;text-align:center;font-size:14px;color:var(--sub)}
.tabs{display:flex;gap:8px;justify-content:center;margin:6px 0 0}.tabs button{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--paper);color:var(--ink);border-radius:99px;padding:3px 12px;cursor:pointer}
.tabs button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.rg{background:var(--tape);color:var(--ink);border-radius:99px;padding:0 8px;font-size:12px}
.facts{margin:10px 0 0 18px;font-size:14px;color:var(--ink)}.facts small,.imp small{color:var(--sub);font-size:12px}.facts a{color:var(--sub)}
.imp{margin-top:10px;padding:8px 12px;border-left:3px solid var(--acc);background:#fbf5ea;font-size:15px;font-style:italic}.imp small{display:block;font-style:normal;margin-top:2px}
.foot{margin-top:40px;text-align:center;color:var(--sub);font-size:13px}
"""
JS = """<script>document.querySelectorAll('.tabs').forEach(t=>{const box=t.previousElementSibling.firstElementChild;t.querySelectorAll('button').forEach(b=>b.onclick=()=>{
t.querySelectorAll('button').forEach(x=>x.classList.remove('on'));b.classList.add('on');box.querySelectorAll('[data-k]').forEach(el=>{el.style.display=el.dataset.k===b.dataset.k?'block':'none';if(el.tagName==='VIDEO'&&el.dataset.k!==b.dataset.k)el.pause()})})})document.querySelectorAll('.gal img,.polaroid img').forEach(i=>i.onclick=()=>{const o=document.createElement('div');o.className='lb';const m=document.createElement('img');m.src=i.src;o.appendChild(m);o.onclick=()=>o.remove();document.body.appendChild(o)})</script>"""


def _card_html(trip_name, idx, d, vs, km, legs, pic, bm=None, style="手账") -> str:
    items = "".join(f'<div class="r"><b>{i + 1}</b><i>{_hm(v.arrive)}</i><span>{e(v.place.name)}</span></div>' for i, v in enumerate(vs))
    pic_html = f'<div class="pic"><img src="{pic}"></div>' if pic else ""
    date = f"{d.month}月{d.day}日 周{WEEK[d.weekday()]} · " if d else ""
    return f"""<!doctype html><meta charset="utf-8"><style>{CSS}{theme_css(style)}
body{{width:1080px;height:1440px;overflow:hidden}}.c{{padding:70px}}.h{{font-size:30px;letter-spacing:.3em;color:var(--acc)}}
.t{{font-size:84px;font-weight:700;margin:14px 0 4px}}.s{{font-size:30px;color:var(--sub)}}.route{{margin:30px 0;height:330px}}
.r{{display:flex;align-items:center;gap:18px;font-size:42px;margin:14px 0}}.r b{{width:56px;height:56px;border-radius:50%;border:3px solid var(--acc);color:var(--acc);display:flex;align-items:center;justify-content:center;font-size:28px}}
.r span{{flex:1;max-width:420px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.r i{{font-style:normal;color:var(--sub);font-size:32px;width:90px}}
.pic{{position:absolute;right:70px;bottom:120px;width:300px;background:#fff;padding:14px 14px 44px;box-shadow:0 10px 26px rgba(0,0,0,.2);transform:rotate(3deg)}}.pic img{{width:100%;display:block}}
.f{{position:absolute;left:70px;bottom:50px;font-size:24px;color:var(--sub)}}</style>
<div class="c"><div class="h">TRIPSIGHT · {e(trip_name)}</div><div class="t">第 {idx + 1} 天</div><div class="s">{date}{len(vs)} 站 · {km} km</div>
{_route_svg([(v.place.lat, v.place.lon) for v in vs], legs, 940, 330, bm=bm)}{items}</div>{pic_html}<div class="f">营业时间以现场为准</div>"""


def build_handbook(trip: Trip, out_root: Path, *, photos: Optional[list[dict]] = None, photo_dir: Optional[Path] = None,
                   show_photos: bool = True, videos: Optional[dict[str, Path]] = None, cards: bool = True,
                   stories: Optional[dict[str, Any]] = None, basemap: Any = None, pdf: bool = False, style: str = "手账", regions: Optional[dict[str, str]] = None) -> dict[str, Any]:
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
            src = Path(photo_dir) / ph["file"]
            if not src.exists() or not ph.get("place_id"):
                if not src.exists():
                    skipped.append(f"照片缺失：{ph['file']}")
                continue
            shutil.copy2(src, root / "photos" / ph["file"]); files.append(f"photos/{ph['file']}")
            by_place.setdefault(ph["place_id"], []).append({"file": ph["file"], "caption": ph.get("caption", "")})
    vids: dict[str, str] = {}
    for pid, vp in (videos or {}).items():
        vp = Path(vp)
        if vp.suffix.lower() not in VIDEO_EXT or not vp.is_file():
            skipped.append(f"视频不可用：{vp.name}"); continue
        dst = root / "media" / f"{pid}{vp.suffix.lower()}"
        shutil.copy2(vp, dst); files.append(f"media/{dst.name}"); vids[pid] = f"media/{dst.name}"

    days_html, card_jobs, km_all, stops_all = [], [], 0.0, 0
    rg = regions or {}
    for day in trip.plan.days:
        vs, _ = day_visits(trip, day)
        if not vs:
            continue
        st = day_stats(trip, day)
        d = trip.day_date(day.index)
        km = round(sum(lg.distance_km for lg in st.legs), 1)
        km_all += km; stops_all += len(vs)
        head = f'<section class="day"><div class="dh"><h2>第 {day.index + 1} 天</h2><span>' + (f"{d.month}月{d.day}日 周{WEEK[d.weekday()]} · " if d else "") + f"{len(vs)} 站 · {km} km</span></div>"
        wx = (trip.weather or {}).get(d.isoformat()) if d else None
        if wx is not None and getattr(wx, "day_weather", ""):
            head += f'<div class="wx">天气预报：{e(wx.day_weather)} {round(wx.day_temp)}°C（预报，非实况）</div>'
        parts = [head, _route_svg([(v.place.lat, v.place.lon) for v in vs], st.legs, bm=basemap)]
        first_pic = None
        for i, v in enumerate(vs):
            p = v.place
            rgtag = f'<span class="rg">{e(rg[p.id])}</span> · ' if rg.get(p.id) else ''
            hours = f"营业：{e(p.opening_hours)}" if p.opening_hours else "营业时间未核实"
            body = f'<div class="stop"><h3><b>{i + 1}</b>{e(p.name)}</h3><div class="meta">{rgtag}{_hm(v.arrive)}–{_hm(v.leave)} · 建议停留 {p.duration_min} 分钟 · {hours}</div>'
            views, tabs = "", []
            pics = by_place.get(p.id, [])[:MAX_PHOTOS]
            if pics:
                views += f'<img data-k="photo" src="photos/{pics[0]["file"]}" alt="{e(p.name)}">'; tabs.append(("photo", "照片"))
                first_pic = first_pic or f"../photos/{pics[0]['file']}"
            if p.id in vids:
                views += f'<video data-k="video" {"style=display:none " if tabs else ""}src="{vids[p.id]}" controls loop playsinline preload="none"></video>'; tabs.append(("video", "视频"))
            if views:
                cap = by_place.get(p.id, [{}])[0].get("caption", "") or p.name
                body += f'<div class="polaroid"><div>{views}</div><div class="cap">{e(cap)}</div></div>'
                if len(tabs) > 1:
                    body += '<div class="tabs">' + "".join(f'<button data-k="{k}" class="{"on" if j == 0 else ""}">{nm}</button>' for j, (k, nm) in enumerate(tabs)) + "</div>"
                else:
                    body += '<div class="tabs" style="display:none"></div>'
            if len(pics) > 1:
                body += '<div class="gal">' + "".join(f'<img src="photos/{ph["file"]}" alt="{e(ph.get("caption") or p.name)}" loading="lazy">' for ph in pics[1:]) + "</div>"
            sty = (stories or {}).get(p.id) or {}
            if sty.get("facts"):
                body += '<ul class="facts">' + "".join(
                    f'<li>{e(f["text"])} <small>来源：' + (f'<a href="{e(f["source"])}" rel="noreferrer">{e(f["source"])}</a>' if f["source"].startswith("http") else e(f["source"])) + "</small></li>"
                    for f in sty["facts"]) + "</ul>"
            if sty.get("impression"):
                body += f'<p class="imp">“{e(sty["impression"])}”<small>{"我写的" if sty.get("by") == "user" else "AI 根据照片的描写，仅供参考，可修改"}</small></p>'
            body += "</div>"
            parts.append(body)
            if i < len(st.legs):
                lg = st.legs[i]
                parts.append(f'<div class="leg">{e(lg.note or lg.mode)} · {lg.distance_km} km · {lg.minutes} 分钟' + ("（估算）" if lg.detail_level == "estimate" else "") + "</div>")
        parts.append("</section>")
        days_html.append("".join(parts))
        card_jobs.append((day.index, d, vs, km, st.legs, first_pic))

    from .regions import order_of_appearance
    order_ids = [v.place.id for day in trip.plan.days for v in day_visits(trip, day)[0]]
    chs = order_of_appearance(order_ids, rg)
    chap_html = '<div class="m">' + ' → '.join(e(c) for c in chs) + '</div>' if len(chs) > 1 else ''
    title = e(trip.meta.name)
    page = (f'<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · 行程手册</title><style>{CSS}{theme_css(style)}</style>'
            f'<div class="wrap"><div class="cover"><div class="k">TRIPSIGHT · 行程手册</div><h1>{title}</h1><div class="m">{len(trip.plan.days)} 天 · {stops_all} 站 · 约 {round(km_all, 1)} km</div>{chap_html}</div>'
            f'{"".join(days_html)}<div class="foot">营业时间来自地图服务，出发前请再核实。</div></div>{JS}</html>')
    (root / "index.html").write_text(page, encoding="utf-8"); files.append("index.html")

    if cards:
        from . import share as _share
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = _share._launch(p)
                pg = b.new_page(viewport={"width": 1080, "height": 1440})
                for idx, d, vs, km, legs, pic in card_jobs:
                    f = root / "cards" / f"day{idx + 1}.html"
                    f.write_text(_card_html(trip.meta.name, idx, d, vs, km, legs, pic, basemap, style), encoding="utf-8")
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
    cap += ["", "营业时间以现场为准。"]
    (root / "caption.txt").write_text("\n".join(cap) + "\n", encoding="utf-8"); files.append("caption.txt")
    return {"folder": str(root), "files": files, "skipped": skipped}
