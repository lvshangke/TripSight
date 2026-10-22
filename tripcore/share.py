"""可分享的行程成品：单文件 HTML（手机直接打开）和长图 PNG（微信里最好发）。

只整理已有数据（和地图页、文字行程同一份 build_map_data），不产生新的“事实”。
默认不公开酒店和花费；用户明确要求时才带（show_lodging / show_costs）。
航班/车次号一律不放（只写到达/离开的站点和时间）。不嵌地图、不带任何 key。
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Optional

from . import daycard as _daycard
from .mapview import build_map_data
from .metrics import estimate_cost
from .models import Trip
from .textview import guard_text
from .weather import fmt_snap

_COLORS = ["#e4572e", "#2e86ab", "#3a9d5d", "#9b5de5", "#f2a541", "#17a398", "#d1495b", "#6c757d"]
_REPO = "https://github.com/lvshangke/TripSight"

_CSS = """
:root{--bg:#f6f4ef;--card:#fff;--ink:#1f2328;--mute:#6b7280;--line:#e7e3da;--chip:#f0ede5}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15171a;--card:#1f2226;--ink:#e8e8e6;--mute:#9aa0a6;--line:#2c3036;--chip:#2a2e33}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:560px;margin:0 auto;padding:20px 16px 36px}
h1{font-size:22px;margin:4px 0 2px}.sub{color:var(--mute);font-size:13px;margin-bottom:14px}
.sum{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:16px}
.chip{background:var(--chip);border-radius:999px;padding:2px 10px;font-size:12.5px;color:var(--mute);white-space:nowrap}
.day{background:var(--card);border-radius:14px;margin:14px 0;overflow:hidden;border-left:5px solid var(--c);box-shadow:0 1px 3px rgba(0,0,0,.06)}
.dh{display:flex;gap:12px;align-items:center;padding:12px 14px;border-bottom:1px solid var(--line)}
.dd{min-width:54px;text-align:center;border-radius:10px;background:var(--c);color:#fff;padding:4px 6px;line-height:1.15}
.dd b{display:block;font-size:20px}.dd span{font-size:11.5px;opacity:.92}
.dt{flex:1}.dt strong{font-size:16px}.dt .sum{margin:4px 0 0}
.wx{padding:6px 14px;color:var(--mute);font-size:13px;border-bottom:1px solid var(--line)}
.stop{display:flex;gap:10px;padding:10px 14px}
.n{flex:none;width:24px;height:24px;border-radius:50%;background:var(--c);color:#fff;font-size:13px;text-align:center;line-height:24px;margin-top:2px}
.sb{flex:1;min-width:0}.sb .nm{font-weight:600}.sb .tm{color:var(--mute);font-size:13px}
.sb .ln{color:var(--mute);font-size:12.5px}.sb a{color:#2e86ab;font-size:12.5px;text-decoration:none}
.leg{margin:0 14px 0 48px;padding:2px 0 2px 10px;border-left:2px dashed var(--line);color:var(--mute);font-size:12.5px}
.meal,.hot,.term{padding:6px 14px 6px 48px;color:var(--mute);font-size:13px}
.foot{color:var(--mute);font-size:12px;margin-top:22px;text-align:center}.foot a{color:inherit}
"""


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


def _day_html(trip: Trip, d: dict, color: str, st: dict, show_lodging: bool, show_costs: bool) -> str:
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
                out.append(f'<div class="leg">{_e(e["mode"])} {e["minutes"]}分钟{km}{est}{_e(note)}</div>')
        elif t == "stop":
            lines = [x for x in e["lines"] if show_costs or not x.startswith("门票")]
            ln = "".join(f'<div class="ln">{_e(x)}</div>' for x in lines)
            link = f'<a href="{_e(e["web"])}">在地图中打开</a>' if e.get("web") else ""
            out.append(f'<div class="stop"><div class="n">{e["n"]}</div><div class="sb"><div class="nm">{_e(e["name"])}</div>'
                       f'<div class="tm">{_e(e["arrive"])}–{_e(e["leave"])} · 停留 {e["stay"]} 分钟</div>{ln}{link}</div></div>')
        elif t == "meal":
            lines = [x for x in e["lines"] if show_costs or not x.startswith("人均")]
            out.append(f'<div class="meal">🍜 用餐：{_e(e["name"])}' + (f'（{_e("；".join(lines))}）' if lines else "") + "</div>")
    out.append("</section>")
    return "".join(out)


def build_share_html(trip: Trip, show_lodging: bool = False, show_costs: bool = False) -> str:
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
    body = "".join(_day_html(trip, d, _COLORS[d["index"] % len(_COLORS)], stats.get(str(d["index"]), {}), show_lodging, show_costs)
                   for d in days)
    return ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{_e(trip.meta.name)}</title><style>{_CSS}</style></head><body><div class=\"wrap\">"
            f"<h1>{_e(trip.meta.name)}</h1><div class=\"sub\">{_e(span)}</div>{_chips(summary)}{body}"
            f"<div class=\"foot\">营业时间等信息来自高德，标“待核实”的出行前请再确认；路程标“估算”的是直线估算，不是实时路线。<br>"
            f"由 <a href=\"{_REPO}\">TripSight</a> 生成</div></div></body></html>")


def guard_html(html: str) -> list[str]:
    return guard_text(html)


def render_png(html_path: Path, png_path: Path, width: int = 430) -> Optional[str]:
    """用 Playwright（可选依赖）把页面截成长图。成功返回 None，失败返回原因。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "没有安装 playwright（pip install 'tripcore[image]' && python -m playwright install chromium）"
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": width, "height": 900}, device_scale_factor=2)
            pg.goto(html_path.resolve().as_uri())
            pg.screenshot(path=str(png_path), full_page=True)
            b.close()
    except Exception as e:                                  # 浏览器没装好等：不影响 HTML
        return f"截图失败：{type(e).__name__}"
    return None
