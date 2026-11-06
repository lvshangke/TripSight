"""行程手册的“书”版式 PDF：A5 竖版，一页一个内容，页码和目录都是确定的。

只排版已有内容（景点、时间、照片、来源明确的资料和用户自己写的话），不产生新的事实。
结构：封面 → 目录 → 每天一个章首页（路线图 + 站点表）→ 每个景点一页（照片 + 资料）→ 后记（花费，可选）→ 版权页。
每个景点固定一页，照片多就换网格，不会拆页；页码按这个顺序直接算出来。
"""

from __future__ import annotations

import html
from typing import Any, Optional

e = html.escape

BOOK_CSS = """
@page{size:148mm 210mm;margin:0}
html,body{margin:0;padding:0}body{background:var(--bg);color:var(--ink);font-family:"Noto Serif SC","Songti SC",serif;line-height:1.6;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.pg{width:148mm;height:210mm;position:relative;overflow:hidden;break-after:page;page-break-after:always;padding:16mm 14mm 18mm;display:flex;flex-direction:column;background:var(--bg)}
.pg:last-child{break-after:auto;page-break-after:auto}
.pn{position:absolute;bottom:7mm;left:0;right:0;text-align:center;font-size:8pt;color:var(--sub);letter-spacing:.1em}
.run{position:absolute;top:7mm;left:14mm;right:14mm;display:flex;justify-content:space-between;font-size:7.5pt;color:var(--sub);letter-spacing:.2em}
.k{letter-spacing:.4em;color:var(--acc);font-size:9pt}
.cover{justify-content:flex-start;padding-top:26mm}.cover h1{font-size:34pt;line-height:1.2;margin:6mm 0 4mm;font-weight:700}
.cover .m{color:var(--sub);font-size:11pt}.cover .chs{color:var(--sub);font-size:10pt;margin-top:2mm}
.cover .hero{margin-top:auto;background:#fff;padding:3mm 3mm 10mm;box-shadow:0 2mm 6mm rgba(0,0,0,.2);transform:rotate(-1.5deg);position:relative}
.cover .hero img{width:100%;height:92mm;object-fit:cover;display:block}.cover .hero:before{content:"";position:absolute;top:-3mm;left:40%;width:22mm;height:6mm;background:var(--tape);opacity:.85;transform:rotate(3deg)}
h2.t{font-size:18pt;margin:2mm 0 6mm;padding-bottom:2mm;border-bottom:1.5px solid var(--ink)}
.toc{list-style:none;padding:0}.toc li{display:flex;align-items:baseline;gap:3mm;padding:2mm 0;border-bottom:1px dotted var(--line)}
.toc b{color:var(--acc);width:9mm;flex:none;font-size:11pt}.toc .n{flex:1;min-width:0}.toc .n span{display:block;color:var(--sub);font-size:8.5pt;line-height:1.4}.toc em{font-style:normal;color:var(--sub);font-size:10pt}
.dayno{font-size:56pt;line-height:1;color:var(--acc);font-weight:700;letter-spacing:.02em}.dtitle{font-size:22pt;line-height:1.25;margin:3mm 0 1mm;font-weight:700}
.dmeta{color:var(--sub);font-size:10pt}.route{width:100%;margin:5mm 0;background:var(--paper);border:1px solid var(--line);border-radius:3mm}
.line{fill:none;stroke:var(--acc);stroke-width:3;stroke-dasharray:7 6;stroke-linecap:round}.dot{fill:var(--paper);stroke:var(--acc);stroke-width:2.5}.bl{stroke-width:3.5;stroke:#d9381e}.m-walk{stroke-dasharray:1 7!important}
.dn{font:700 12px sans-serif;text-anchor:middle;fill:var(--acc)}
.sl{list-style:none;padding:0;margin:0}.sl li{display:flex;align-items:center;gap:3mm;padding:1.4mm 0;font-size:11pt}.sl b{flex:none;width:6.5mm;height:6.5mm;border-radius:50%;border:1.5px solid var(--acc);color:var(--acc);display:flex;align-items:center;justify-content:center;font-size:9pt}.sl i{font-style:normal;color:var(--sub);font-size:9pt;width:11mm;flex:none}
.sh{display:flex;align-items:baseline;gap:3mm;flex-wrap:wrap}.sh h3{font-size:17pt;line-height:1.25}.sh h3 b{color:var(--acc);margin-right:2mm}
.sm{color:var(--sub);font-size:9pt;margin-top:1mm}.rg{background:var(--tape);color:var(--ink);border-radius:99px;padding:0 2.5mm;font-size:8pt}
.ph-area{flex:1;min-height:0;margin:5mm 0 3mm;display:grid;gap:3mm}
.ph-area.n1{grid-template-columns:1fr;grid-template-rows:1fr}.ph-area.n2{grid-template-columns:1fr;grid-template-rows:1fr 1fr}
.ph-area.n3{grid-template-columns:1fr 1fr;grid-template-rows:1.4fr 1fr}.ph-area.n3 .f:first-child{grid-column:1/3}
.ph-area.n4{grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr}.ph-area.n5{grid-template-columns:1fr 1fr;grid-template-rows:1.4fr 1fr 1fr}.ph-area.n5 .f:first-child{grid-column:1/3}
.ph-area.n6{grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr 1fr}
.f{background:#fff;padding:2mm 2mm 2mm;box-shadow:0 .6mm 2.4mm rgba(0,0,0,.18);min-height:0;min-width:0;display:flex;flex-direction:column}
.f img{flex:1;min-height:0;width:100%;object-fit:cover;display:block}.f.c img{padding-bottom:0}.f .c{font-size:8pt;color:var(--sub);text-align:center;margin-top:1mm;line-height:1.3}
.nop{flex:1}.facts{margin:0 0 0 4mm;font-size:9pt;padding:0}.facts small,.imp small{color:var(--sub);font-size:7.5pt}
.imp{margin-top:2mm;padding:2mm 3mm;border-left:2px solid var(--acc);background:var(--paper);font-size:9.5pt;font-style:italic}.imp small{display:block;font-style:normal}
.leg{margin-top:2mm;color:var(--sub);font-size:8.5pt;border-left:2px dotted var(--line);padding-left:3mm}
.tot{font-size:30pt;font-weight:700;color:var(--acc)}.tot small{font-size:11pt;color:var(--sub);font-weight:400}.sp{list-style:none;padding:0;margin:3mm 0 0}.sp li{display:flex;justify-content:space-between;border-bottom:1px dotted var(--line);padding:1.5mm 0;font-size:11pt}
.col{justify-content:flex-end;color:var(--sub);font-size:9pt;text-align:center}.col b{color:var(--ink);font-size:12pt}
"""


def _facts_html(facts: list[dict]) -> str:
    if not facts:
        return ""
    rows = []
    for f in facts[:4]:
        src = f.get("source", "")
        rows.append(f'<li>{e(f["text"])} <small>来源：{e(src)}</small></li>')
    return '<ul class="facts">' + "".join(rows) + "</ul>"


def build_book_html(trip_name: str, days: list[dict[str, Any]], *, theme_css: str, base_css: str, km_all: float, stops_all: int,
                    chapters: str = "", spending: Optional[dict[str, Any]] = None, hero: str = "", subtitle: str = "", afterword: str = "") -> str:
    """days 的每一项：idx, title, date(文字), wx(文字), km, svg(路线图), stops=[{n,name,rg,t,dur,hours,pics:[(file,caption)],facts,imp,imp_by,leg}]"""
    pages: list[str] = []          # 每个元素是一页内的 HTML（不含页码）；页码 = 序号 + 1

    pages.append(
        f'<div class="pg cover"><div class="k">TRIPSIGHT · 行程手册</div><h1>{e(trip_name)}</h1>'
        f'<div class="m">{len(days)} 天 · {stops_all} 站 · 约 {round(km_all, 1)} km</div>'
        + (f'<div class="chs">{e(chapters)}</div>' if chapters else "")
        + (f'<div class="chs" style="font-style:italic;color:var(--ink)">{e(subtitle)}</div>' if subtitle else "")
        + (f'<div class="hero"><img src="{e(hero)}"></div>' if hero else "") + "</div>")

    # 页码先算出来：封面 1，目录 2，然后每天 1 页章首 + 站数页
    page_of: dict[int, int] = {}
    p = 3
    for d in days:
        page_of[d["idx"]] = p
        p += 1 + len(d["stops"])
    def _tt(d):
        return d["title"] or "第 %d 天" % (d["idx"] + 1)
    toc = "".join(
        f'<li><b>{d["idx"] + 1}</b><div class="n">{e(_tt(d))}<span>{e(d["date"])}{" · " if d["date"] else ""}{len(d["stops"])} 站 · {d["km"]} km<br>'
        f'{e(" → ".join(s["name"] for s in d["stops"][:5]))}{"…" if len(d["stops"]) > 5 else ""}</span></div><em>{page_of[d["idx"]]}</em></li>'
        for d in days)
    pages.append(f'<div class="pg"><div class="k">CONTENTS</div><h2 class="t">目录</h2><ul class="toc">{toc}</ul></div>')

    for d in days:
        title = d["title"] or f"第 {d['idx'] + 1} 天"
        sl = "".join(f'<li><b>{s["n"]}</b><i>{e(s["t"].split("–")[0])}</i><span>{e(s["name"])}</span></li>' for s in d["stops"])
        pages.append(
            f'<div class="pg"><div class="k">DAY {d["idx"] + 1:02d}</div><div class="dayno">{d["idx"] + 1:02d}</div>'
            f'<div class="dtitle">{e(title)}</div><div class="dmeta">{e(d["date"])}{" · " if d["date"] else ""}{len(d["stops"])} 站 · {d["km"]} km</div>'
            + (f'<div class="dmeta">{e(d["wx"])}</div>' if d.get("wx") else "")
            + (f'<div class="dmeta" style="font-style:italic;color:var(--ink)">{e(d["summary"])}</div>' if d.get("summary") else "")
            + d["svg"] + f'<ul class="sl">{sl}</ul></div>')
        for s in d["stops"]:
            pics = s["pics"][:6]
            if pics:
                cells = "".join(f'<div class="f"><img src="photos/{e(f)}">' + (f'<div class="c">{e(c)}</div>' if c else "") + "</div>" for f, c in pics)
                area = f'<div class="ph-area n{len(pics)}">{cells}</div>'
            else:
                area = '<div class="nop"></div>'
            meta = (f'<span class="rg">{e(s["rg"])}</span> · ' if s.get("rg") else "") + f'{e(s["t"])} · 建议停留 {s["dur"]} 分钟' + (f' · 营业：{e(s["hours"])}' if s.get("hours") else "") + (f' · {e(s["stay"])}' if s.get("stay") else "")
            imp = f'<p class="imp">“{e(s["imp"])}”<small>{"我写的" if s.get("imp_by") == "user" else "AI 根据照片的描写，仅供参考，可修改"}</small></p>' if s.get("imp") else ""
            leg = f'<div class="leg">下一站：{e(s["leg"])}</div>' if s.get("leg") else ""
            pages.append(f'<div class="pg"><div class="sh"><h3><b>{s["n"]}</b>{e(s["name"])}</h3></div><div class="sm">{meta}</div>{area}{_facts_html(s.get("facts") or [])}{imp}{leg}</div>')

    if afterword and not (spending and spending.get("count")):
        pages.append(f'<div class="pg"><div class="k">AFTERWORD</div><h2 class="t">后记</h2><p style="white-space:pre-wrap;font-size:11pt">{e(afterword)}</p></div>')
    if spending and spending.get("count"):
        aw_p = '<p style="white-space:pre-wrap;font-size:11pt">' + e(afterword) + "</p>" if afterword else ""
        cats = "".join(f'<li><span>{e(k)}</span><b>{v:g} 元</b></li>' for k, v in sorted(spending["by_category"].items(), key=lambda kv: -kv[1]))
        pages.append(f'<div class="pg"><div class="k">AFTERWORD</div><h2 class="t">后记 · 这一趟的花费</h2>{aw_p}<div class="tot">{spending["total"]:g}<small> 元 · {spending["count"]} 笔</small></div><ul class="sp">{cats}</ul></div>')
    pages.append(f'<div class="pg col"><b>{e(trip_name)}</b><div>由 TripSight 整理 · 照片来自本机相册 · 营业时间等信息出发前请再核实</div></div>')

    out = []
    for i, body in enumerate(pages):
        n = i + 1
        if i > 0 and i < len(pages) - 1:
            body = body[:-6] + f'<div class="run"><span>{e(trip_name)}</span><span>TRIPSIGHT</span></div><div class="pn">— {n} —</div></div>'
        out.append(body)
    return (f'<!doctype html><html lang="zh"><meta charset="utf-8"><title>{e(trip_name)} · 行程手册（书）</title>'
            f'<style>{base_css}{theme_css}{BOOK_CSS}</style>' + "".join(out) + "</html>")
