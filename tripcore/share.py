"""可分享的行程成品：单文件 HTML（手机直接打开）和长图 PNG（微信里最好发）。

只整理已有数据（和地图页、文字行程同一份 build_map_data），不产生新的“事实”。
默认不公开酒店和花费；用户明确要求时才带（show_lodging / show_costs）。
航班/车次号一律不放（只写到达/离开的站点和时间）。不嵌地图、不带任何 key。
"""

from __future__ import annotations

import re as _re

from html import escape
from pathlib import Path
from typing import Any, Optional

from . import daycard as _daycard
from . import routemap as _routemap
from .mapview import build_map_data
from .metrics import estimate_cost
from .models import Trip
from .textview import guard_text
from .weather import fmt_snap

_COLORS = ["#e4572e", "#2e86ab", "#3a9d5d", "#9b5de5", "#f2a541", "#17a398", "#d1495b", "#6c757d"]
_REPO = "https://github.com/lvshangke/TripSight"

_BASE_CSS = """
:root{--bg:#f6f4ef;--card:#fff;--ink:#1f2328;--mute:#6b7280;--line:#e7e3da;--chip:#f0ede5;--link:#2e86ab;--on:#fff;--r:14px;--rb:10px;--shadow:0 1px 3px rgba(0,0,0,.06);--font:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;--hfont:var(--font);--hw:700;--hs:22px;--bw:5px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 var(--font)}
.wrap{max-width:560px;margin:0 auto;padding:20px 16px 36px}
h1{font-family:var(--hfont);font-weight:var(--hw);font-size:var(--hs);margin:4px 0 2px}.sub{color:var(--mute);font-size:13px;margin-bottom:14px}
.sum{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:16px}
.chip{background:var(--chip);border-radius:999px;padding:2px 10px;font-size:12.5px;color:var(--mute);white-space:nowrap}
.day{background:var(--card);border-radius:var(--r);margin:14px 0;overflow:hidden;border-left:var(--bw) solid var(--c);box-shadow:var(--shadow)}
.dh{display:flex;gap:12px;align-items:center;padding:12px 14px;border-bottom:1px solid var(--line)}
.dd{min-width:54px;text-align:center;border-radius:var(--rb);background:var(--c);color:var(--on);padding:4px 6px;line-height:1.15}
.dd b{display:block;font-size:20px}.dd span{font-size:11.5px;opacity:.92}
.dt{flex:1}.dt strong{font-size:16px}.dt .sum{margin:4px 0 0}
.wx{padding:6px 14px;color:var(--mute);font-size:13px;border-bottom:1px solid var(--line)}
.stop{display:flex;gap:10px;padding:10px 14px}
.n{flex:none;width:24px;height:24px;border-radius:var(--rn,50%);background:var(--c);color:var(--on);font-size:13px;text-align:center;line-height:24px;margin-top:2px}
.sb{flex:1;min-width:0}.sb .nm{font-weight:600}.sb .tm{color:var(--mute);font-size:13px}
.sb .ln{color:var(--mute);font-size:12.5px}.sb a{color:var(--link);font-size:12.5px;text-decoration:none}
.leg{margin:0 14px 0 48px;padding:2px 0 2px 10px;border-left:2px dashed var(--line);color:var(--mute);font-size:12.5px}
.leg a{color:var(--link);margin-left:6px;text-decoration:none;border-bottom:1px solid currentColor}
.meal,.hot,.term{padding:6px 14px 6px 48px;color:var(--mute);font-size:13px}
.ph{display:block;width:100%;border-radius:var(--rb);margin:6px 0 2px}.cap{color:var(--mute);font-size:12px;margin-bottom:4px}
.ph{cursor:zoom-in}#lb{position:fixed;inset:0;background:rgba(0,0,0,.88);display:none;align-items:center;justify-content:center;flex-direction:column;z-index:9}#lb.on{display:flex}
#lb img{max-width:96vw;max-height:84vh;border-radius:6px}#lb div{color:#eee;font-size:13px;margin-top:10px;padding:0 16px;text-align:center}
#lb button{position:absolute;background:rgba(255,255,255,.18);color:#fff;border:0;border-radius:50%;width:40px;height:40px;font-size:22px}
#lb .x{top:14px;right:14px}#lb .p{left:10px;top:50%}#lb .n{right:10px;top:50%}
.foot{color:var(--mute);font-size:12px;margin-top:22px;text-align:center}.foot a{color:inherit}
"""




_SERIF = '"Noto Serif CJK SC","Source Han Serif SC","Songti SC","STSong",Georgia,serif'

# 风格借鉴自 Easel 的风格库（https://github.com/ZJU-REAL/Easel，Apache-2.0）的思路，配色和 CSS 为本项目自写。
# 全部是浅色底；只改颜色、字体、圆角、边线，不改页面结构，也不改“默认不公开酒店/花费”等规则。
THEMES: dict[str, dict] = {
    "default": {"label": "默认", "vars": "", "colors": _COLORS, "extra": ""},
    "magazine": {
        "label": "杂志编辑",
        "vars": f"--bg:#f3f0e8;--card:transparent;--ink:#16251b;--mute:#68625a;--line:#cfc8b8;--chip:#e8e3d6;--link:#315d93;--r:3px;--rb:3px;--shadow:none;--font:{_SERIF};--hw:500;--hs:28px;--bw:0px",
        "colors": ["#315d93", "#9b5a2e", "#2f5d50", "#7a4a6b", "#8a6d2b", "#3d6b73", "#9b3d3d", "#5e5a52"],
        "extra": ".day{border-top:2px solid var(--ink);border-radius:0;margin:22px 0}.dh{border-bottom:1px solid var(--line)}.dd{background:transparent;color:var(--c);border:1px solid var(--c)}"
                 ".sub{font-style:italic;letter-spacing:.04em}.chip{border-radius:2px}.n{background:transparent;color:var(--c);border:1px solid var(--c)}",
    },
    "cream": {
        "label": "奶油温柔",
        "vars": "--bg:#faf6ef;--card:#fffdf8;--ink:#7a6a5c;--mute:#a09282;--line:#ede4d3;--chip:#ede4d3;--link:#8a7a5a;--r:24px;--rb:16px;--shadow:0 4px 18px rgba(122,106,92,.10);--hw:600;--bw:0px",
        "colors": ["#7f927c", "#6f8a96", "#b08683", "#8a7790", "#ad9660", "#6f918a", "#a8796b", "#8b857a"],
        "extra": ".day{margin:18px 0}.chip{background:#f3ebdc}.leg{border-left-style:dotted}",
    },
    "journal": {
        "label": "手账贴纸",
        "vars": "--bg:#fbf7f0;--card:#fffefb;--ink:#4a4036;--mute:#85796b;--line:#d9cdb8;--chip:#f3e9d2;--link:#6a7fa5;--on:#4a4036;--r:6px;--rb:4px;--shadow:2px 3px 0 rgba(120,100,70,.12);--bw:0px;--hs:24px",
        "colors": ["#f3d9a4", "#b8d8c8", "#e8c4c4", "#bcd3e8", "#e3d2ef", "#f6c9a0", "#cbe1a8", "#d8d2c4"],
        "extra": ".day{border:2px dashed var(--line);position:relative;overflow:visible}.day::before{content:\"\";position:absolute;top:-10px;left:22px;width:74px;height:20px;background:var(--c);opacity:.9;transform:rotate(-3deg);clip-path:polygon(6% 0,100% 0,94% 100%,0 100%)}"
                 ".dd{transform:rotate(-2deg);box-shadow:1px 2px 0 rgba(0,0,0,.12)}.chip{transform:rotate(-1deg);border:1px dashed var(--line)}.n{border:1px solid rgba(74,64,54,.25)}.dh{border-bottom:1px dashed var(--line)}.leg{border-left:2px dotted var(--line)}",
    },
    "botanical": {
        "label": "植物清新",
        "vars": "--bg:#f6f4ee;--card:#fcfbf7;--ink:#2f3b2c;--mute:#6b7866;--line:#dfe3d4;--chip:#e9eddf;--link:#5a7f4f;--r:12px;--rb:8px;--shadow:none;--hw:500;--bw:4px",
        "colors": ["#6b8a64", "#b87444", "#4f7f80", "#8f8a3f", "#7d6a93", "#a85f5f", "#5a7f4f", "#857656"],
        "extra": ".day{border:1px solid var(--line);border-left:4px solid var(--c)}.dd{background:transparent;color:var(--c);border:1px solid var(--c)}.chip{background:transparent;border:1px solid var(--line)}",
    },
    "ink": {
        "label": "新中式墨韵",
        "vars": f"--bg:#f3efe4;--card:#f8f4ea;--ink:#1a1a1a;--mute:#6b6357;--line:#d9d0bd;--chip:#ece5d3;--link:#a8322d;--r:2px;--rb:2px;--rn:2px;--shadow:none;--font:{_SERIF};--hw:700;--hs:26px;--bw:3px",
        "colors": ["#a8322d", "#3a3a3a", "#3f5560", "#8a5a2f", "#476b5a", "#8f7440", "#6a4f6e", "#6b6357"],
        "extra": "h1{border-bottom:2px solid #a8322d;padding-bottom:6px;display:inline-block}.dd{border-radius:2px}.chip{border-radius:2px}.day{border-top:1px solid var(--line)}.n{font-weight:700}",
    },
    "dopamine": {
        "label": "多巴胺",
        "vars": "--bg:#ffd500;--card:#fff;--ink:#0a0a0a;--mute:#333;--line:#0a0a0a;--chip:#fff;--link:#002fa7;--r:12px;--rb:8px;--shadow:4px 4px 0 #0a0a0a;--hw:900;--hs:30px;--bw:0px",
        "colors": ["#e6007e", "#002fa7", "#0a8f3c", "#e8530e", "#6b21d8", "#007c8a", "#d1103d", "#0a0a0a"],
        "extra": ".day{border:3px solid #0a0a0a}.chip{border:2px solid #0a0a0a;color:#0a0a0a;font-weight:700}.dd{border:2px solid #0a0a0a}.n{border:2px solid #0a0a0a}.sub{color:#0a0a0a;font-weight:600}.foot,.foot a{color:#0a0a0a}.leg{border-left:2px dashed #0a0a0a}",
    },
    "swiss": {
        "label": "瑞士极简",
        "vars": "--bg:#fafaf8;--card:#fff;--ink:#0a0a0a;--mute:#737373;--line:#d8d8d4;--chip:#f0f0ec;--link:#002fa7;--r:0px;--rb:0px;--rn:0px;--shadow:none;--hw:300;--hs:34px;--bw:0px",
        "colors": ["#002fa7"] * 8,
        "extra": ".day{border:1px solid var(--line);border-top:3px solid #002fa7}.chip{border-radius:0}.dd{background:transparent;color:#002fa7;border:1px solid #002fa7}.n{background:#002fa7}.sub{letter-spacing:.12em;text-transform:uppercase;font-size:12px}",
    },
}


def theme_names() -> list[str]:
    return list(THEMES)


def _theme(name: str) -> dict:
    t = THEMES.get(name or "default")
    if t is None:
        raise ValueError(f"没有这个风格：{name}。可选：" + "、".join(f"{k}（{v['label']}）" for k, v in THEMES.items()))
    return t


def _css(theme: str) -> str:
    t = _theme(theme)
    return _BASE_CSS + (f":root{{{t['vars']}}}\n" if t["vars"] else "") + t["extra"] + "\n"

_LIGHTBOX = (
    '<div id="lb"><img alt=""><div></div><button class="p">‹</button><button class="n">›</button><button class="x">×</button></div><script>(function(){var b=document.getElementById(\'lb\'),im=b.querySelector(\'img\'),cp=b.querySelector(\'div\'),L=[],i=0;function show(){var e=L[i];im.src=e.src;cp.textContent=(L.length>1?(i+1)+\'/\'+L.length+\' \':\'\')+(e.alt||\'\');b.querySelector(\'.p\').style.display=b.querySelector(\'.n\').style.display=L.length>1?\'\':\'none\';b.className=\'on\'}document.addEventListener(\'click\',function(ev){var t=ev.target;if(t.classList&&t.classList.contains(\'ph\')){L=Array.prototype.slice.call((t.closest(\'.sb\')||t.parentNode).querySelectorAll(\'img.ph\'));i=L.indexOf(t);show()}else if(t===b||t.classList.contains(\'x\')){b.className=\'\'}else if(t.classList.contains(\'p\')){i=(i+L.length-1)%L.length;show()}else if(t.classList.contains(\'n\')){i=(i+1)%L.length;show()}});document.addEventListener(\'keydown\',function(e){if(b.className!==\'on\')return;if(e.key===\'Escape\')b.className=\'\';else if(e.key===\'ArrowLeft\')b.querySelector(\'.p\').click();else if(e.key===\'ArrowRight\')b.querySelector(\'.n\').click()})})();</script>'
)


def _e(x: Any) -> str:
    return escape(str(x), quote=True)


def _chips(items: list[str]) -> str:
    return '<div class="sum">' + "".join(f'<span class="chip">{_e(x)}</span>' for x in items if x) + "</div>"


def _fmt_min(m: int) -> str:
    h, mm = divmod(int(m), 60)
    return f"{h}小时{mm:02d}分" if h and mm else (f"{h}小时" if h else f"{mm}分钟")


def _keep_leg(tl: list[dict], i: int, show_lodging: bool) -> bool:
    if show_lodging:
        return True
    def side(rng):
        for j in rng:
            if tl[j]["type"] not in ("meal", "conn"):
                return tl[j]["type"]
        return None
    return side(range(i - 1, -1, -1)) == "stop" and side(range(i + 1, len(tl))) == "stop"


def _photos(items: list[dict]) -> str:
    return "".join(f'<img class="ph" src="{x["uri"]}" alt="{_e(x["caption"])}">' + (f'<div class="cap">{_e(x["caption"])}</div>' if x["caption"] else "") for x in items)


def _day_html(trip: Trip, d: dict, color: str, st: dict, show_lodging: bool, show_costs: bool,
              by_place: dict | None = None, by_day: dict | None = None, route_map: bool = True, basemap=None) -> str:
    idx = d["index"]
    date_ = trip.day_date(idx)
    if date_:
        block = f'<b>{date_.month}/{date_.day}</b><span>{st.get("weekday", "")}</span>'
    else:
        block = f'<b>D{idx + 1}</b><span>第{idx + 1}天</span>'
    chips = [f'{st["places"]} 个景点']
    if st.get("km"):
        chips.append(f'约 {st["km"]:g} km' + ("（估算）" if st.get("km_estimated") else ""))
    if st.get("minutes"):
        chips.append(_fmt_min(st["minutes"]))
    if show_costs and st.get("cost_known"):
        chips.append(f'门票+餐饮约 ¥{st["cost"]}')
    out = [f'<section class="day" style="--c:{color}"><div class="dh"><div class="dd">{block}</div>'
           f'<div class="dt"><strong>第 {idx + 1} 天</strong>{_chips(chips)}</div></div>']
    w = trip.weather.get(date_.isoformat()) if date_ else None
    if w:
        out.append(f'<div class="wx">🌤 {_e(fmt_snap(w))}</div>')
    tl = d["timeline"]
    if route_map:
        out.append(_routemap.build_day(d, color, lambda t_, i_: _keep_leg(t_, i_, show_lodging), show_lodging, basemap))
    for i, e in enumerate(tl):
        t = e["type"]
        if t == "conn":
            out.append(f'<div class="term">⏱ {_e(e["text"])}</div>')
        elif t == "term":
            out.append(f'<div class="term">{_e(e["icon"])} {_e(e["time"])} {_e(e["role"])} {_e(e["name"])}</div>')
        elif t == "hotel":
            if show_lodging:
                out.append(f'<div class="hot">🏨 {_e(e["time"])} {_e(e["role"])} {_e(e["name"])}</div>')
        elif t == "leg":
            if _keep_leg(tl, i, show_lodging):
                km = f' · {e["km"]:.1f}km' if e.get("km") else ""
                est = "" if e.get("real") else "（估算）"
                note = f'｜{e["note"]}' if e.get("note") else ""
                nav = f' <a href="{_e(e["link"])}">导航</a>' if e.get("link") else ""
                out.append(f'<div class="leg">{_e(e["mode"])} {e["minutes"]}分钟{km}{est}{_e(note)}{nav}</div>')
        elif t == "stop":
            lines = [x for x in e["lines"] if show_costs or not x.startswith("门票")]
            ln = "".join(f'<div class="ln">{_e(x)}</div>' for x in lines)
            link = f'<a href="{_e(e["web"])}">在地图中打开</a>' if e.get("web") else ""
            out.append(f'<div class="stop"><div class="n">{e["n"]}</div><div class="sb"><div class="nm">{_e(e["name"])}</div>'
                       f'<div class="tm">{_e(e["arrive"])}–{_e(e["leave"])} · 停留 {e["stay"]} 分钟</div>{ln}{link}'
                       f'{_photos((by_place or {}).get(e["pid"], []))}</div></div>')
        elif t == "meal":
            lines = [x for x in e["lines"] if show_costs or not x.startswith("人均")]
            mtxt = _re.sub(r"（来源：([^）]*)）", r" 来源：\1", "；".join(lines))
            out.append(f'<div class="meal">🍜 用餐：{_e(e["name"])}' + (f'（{_e(mtxt)}）' if lines else "") + "</div>")
    if by_day and by_day.get(idx + 1):
        out.append(f'<div class="meal">{_photos(by_day[idx + 1])}</div>')
    out.append("</section>")
    return "".join(out)


def build_share_html(trip: Trip, show_lodging: bool = False, show_costs: bool = False,
                     photos: Optional[tuple[dict, dict]] = None, theme: str = "default",
                     route_map: bool = True, basemap=None) -> str:
    """basemap：basemap.Basemap 或 None；给了才联网取高德底图（默认不取）。theme：见 THEMES。photos：(按景点, 按天) 的照片，来自 photos.for_share；None 表示不带照片（默认）。"""
    if trip.plan is None:
        raise ValueError("还没有分天")
    days = build_map_data(trip)["days"]
    stats = _daycard.build(trip, {d["index"]: d["timeline"] for d in days})["day_stats"]
    d0, d1 = trip.day_date(0), trip.day_date(trip.meta.num_days - 1)
    span = f"{d0.isoformat()} 至 {d1.isoformat()}" if d0 and d1 else f"{trip.meta.num_days} 天"
    n_places = sum(len(d.items) for d in trip.plan.days)
    summary = [f"{trip.meta.num_days} 天", f"{n_places} 个景点"]
    if trip.meta.travelers > 1:
        summary.append(f"{trip.meta.travelers} 人")
    if show_costs:
        total = sum(s["cost"] for s in stats.values())
        if total:
            summary.append(f"门票+餐饮约 ¥{total}")
        ce = estimate_cost(trip)
        if show_lodging and ce.nights and ce.lodging:
            summary.append(f"住宿约 ¥{ce.lodging:.0f}（{ce.nights} 晚）")
    colors = _theme(theme)["colors"]
    rmap = _routemap.build(days, colors, lambda tl, i: _keep_leg(tl, i, show_lodging), show_lodging, basemap) if route_map else ""
    body = "".join(_day_html(trip, d, colors[d["index"] % len(colors)], stats.get(str(d["index"]), {}), show_lodging, show_costs,
                                 photos[0] if photos else None, photos[1] if photos else None, route_map, basemap)
                   for d in days)
    return ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{_e(trip.meta.name)}</title><style>{_css(theme)}</style></head><body><div class=\"wrap\">"
            f"<h1>{_e(trip.meta.name)}</h1><div class=\"sub\">{_e(span)}</div>{_chips(summary)}{rmap}{body}"
            f"<div class=\"foot\">营业时间等信息来自高德，标“待核实”的出行前请再确认；路程标“估算”的是直线估算，不是实时路线。<br>"
            f"由 <a href=\"{_REPO}\">TripSight</a> 生成</div></div>"
            + (_LIGHTBOX if photos else "") + "</body></html>")


def guard_html(html: str) -> list[str]:
    return guard_text(html)


def _launch(p):
    """优先用 Playwright 自带的 Chromium；没装（或下载不了）就退回本机已装的 Chrome。"""
    try:
        return p.chromium.launch()
    except Exception as first:
        try:
            return p.chromium.launch(channel="chrome")
        except Exception:
            raise first


def render_png(html_path: Path, png_path: Path, width: int = 430) -> Optional[str]:
    """用 Playwright（可选依赖）把页面截成长图。成功返回 None，失败返回原因。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "没有安装 playwright（pip install playwright && python -m playwright install chromium）"
    try:
        with sync_playwright() as p:
            b = _launch(p)
            pg = b.new_page(viewport={"width": width, "height": 900}, device_scale_factor=2)
            pg.goto(html_path.resolve().as_uri())
            pg.screenshot(path=str(png_path), full_page=True)
            b.close()
    except Exception as e:                                  # 浏览器没装好等：不影响 HTML
        return f"截图失败：{type(e).__name__}"
    return None


def render_pdf(html_path: Path, pdf_path: Path, width: int = 430) -> Optional[str]:
    """把分享页存成“一页到底”的 PDF（手机宽度）：和长图长得一样，但“在地图中打开 / 导航”链接可以点。成功返回 None，失败返回原因。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "没有安装 playwright（pip install playwright && python -m playwright install chromium）"
    try:
        with sync_playwright() as p:
            b = _launch(p)
            pg = b.new_page(viewport={"width": width, "height": 900})
            pg.goto(html_path.resolve().as_uri())
            h = int(pg.evaluate("document.documentElement.scrollHeight")) + 2
            pg.pdf(path=str(pdf_path), width=f"{width}px", height=f"{min(h, 18000)}px", print_background=True,
                   margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
            b.close()
    except Exception as e:
        return f"生成 PDF 失败：{type(e).__name__}"
    return None


def _pad(im, size):
    from PIL import Image
    bg = Image.new("RGB", size, (255, 255, 255))
    bg.paste(im, ((size[0] - im.width) // 2, (size[1] - im.height) // 2))
    return bg


def render_gif(html_path: Path, gif_path: Path, width: int = 430, frames: int = 36) -> Optional[str]:
    """把路线图的“按天画出来”动画录成 GIF（逐帧调用页面里的 __seek 截图，所以每次结果一样）。成功返回 None，失败返回原因。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "没有安装 playwright（pip install playwright && python -m playwright install chromium）"
    try:
        from PIL import Image
    except ImportError:
        return "没有安装 Pillow（pip install pillow）"
    import io
    try:
        with sync_playwright() as p:
            b = _launch(p)
            pg = b.new_page(viewport={"width": width, "height": 900}, device_scale_factor=1.5)
            pg.goto(html_path.resolve().as_uri())
            if not pg.evaluate("!!window.__rm_ready"):
                b.close()
                return "这个分享页里没有路线图，没法录动画"
            pg.evaluate("document.querySelectorAll('.dpl,#rm_b').forEach(function(x){x.style.visibility='hidden'})")
            n_days = pg.evaluate("(window.__days||[]).length")
            ims, dur = [], []

            def snap(loc):
                return Image.open(io.BytesIO(loc.screenshot())).convert("RGB")

            if n_days:      # 分天：每天用自己的范围放大，一天一天依次画（两天的景点挤在一张总图里会太小）
                per = max(12, frames // 2)
                for di in range(n_days):
                    loc = pg.locator(".dmap").nth(di)
                    loc.scroll_into_view_if_needed()
                    for i in range(per + 1):
                        pg.evaluate(f"window.__seekDay({di},{i / per})")
                        ims.append(snap(loc))
                        dur.append(1500 if i == per else (300 if i == 0 else 70))
                    pg.evaluate(f"window.__clearDay({di})")
                size = (max(im.width for im in ims), max(im.height for im in ims))
                ims = [im if im.size == size else _pad(im, size) for im in ims]
            else:
                box = pg.locator("section.rmap")
                pg.evaluate("document.querySelector('#rm_b').style.visibility='hidden'")
                for i in range(frames + 1):
                    pg.evaluate(f"window.__seek({i / frames})")
                    ims.append(snap(box))
                dur = [350] + [70] * (len(ims) - 2) + [1800]
            ims = [im.quantize(128, method=Image.Quantize.MEDIANCUT) for im in ims]
            b.close()
    except Exception as e:
        return f"录制失败：{type(e).__name__}"
    ims[0].save(str(gif_path), save_all=True, append_images=ims[1:], duration=dur, loop=0, optimize=True, disposal=2)
    return None
