"""游记草稿的“事实骨架”和草稿检查（确定性代码，不经过模型）。

骨架只来自两类来源：行程本身（日期、景点、计划时间）和用户事后亲口记录的回顾（去了/没去、评分、备注、实际花费）。
别人游记里的景点介绍（Place.intro）不是用户的经历，不放进骨架。没记录的地方标“未记录”，由助手去问用户，不许编。
检查只做能确定的事：金额/时间对不上骨架、写了没去或没记录的景点、出现酒店名；其余的（感受、形容）无法核实，原样交给用户读。
"""

from __future__ import annotations

import re
from typing import Any

from .models import Trip
from .review import COST_NAMES, STATUS_NAMES
from .timeline import day_visits

TEMPLATES = {
    "通用": {
        "tone": "平实的日记体，第一人称。",
        "sections": ["开头一两句（时间、地点、和谁去，只用已有事实）", "每天一段：去了哪、记录过的感受", "小提示（只用你记录过的备注）", "结尾一句"],
        "length": "每天 80~150 字",
    },
    "小红书": {
        "tone": "轻松、口语化，可用少量 emoji；不夸大，不写没记录的感受。",
        "sections": ["标题：一句话，点出地点和天数", "开头一句：这趟的整体感觉（只用评分和备注）", "每天一小段，带天数小标题",
                     "避雷/小提示（只用备注里有的）", "结尾一句", "话题标签（见 suggested_tags）"],
        "length": "标题尽量简短；正文分短段，每段 2~4 句。平台字数限制会变，发布前以平台为准",
    },
    "朋友圈": {
        "tone": "随手分享的口吻。",
        "sections": ["三五句话概括这趟", "配图说明：每天一句"],
        "length": "总共 100 字左右，不要罗列全部景点",
    },
}


def suggested_tags(trip: Trip, review: dict[str, Any], city: str = "") -> list[str]:
    """话题标签只用事实：目的地城市和“去了”的景点名，最多 5 个；不加热门标签。"""
    tags: list[str] = []
    if city:
        tags += [f"#{city}", f"#{city}旅行"]
    rv = review.get("places", {})
    for p in trip.places:
        if rv.get(p.id, {}).get("status") == "visited" and len(tags) < 5:
            tags.append(f"#{p.name}")
    return tags[:5]


def _hm(m: int) -> str:
    return f"{int(m) // 60:02d}:{int(m) % 60:02d}"


def build_facts(trip: Trip, review: dict[str, Any], style: str = "通用",
                show_lodging: bool = False, show_costs: bool = False,
                photos: list[dict[str, Any]] | None = None, city: str = "") -> dict[str, Any]:
    if trip.plan is None:
        raise ValueError("还没有分天")
    rv_places = review.get("places", {})
    days: list[dict[str, Any]] = []
    unrecorded: list[str] = []
    skipped: list[str] = []
    for day in trip.plan.days:
        visits, _ = day_visits(trip, day)
        d = trip.day_date(day.index)
        stops = []
        for v in visits:
            p, r = v.place, rv_places.get(v.place.id)
            if r is None:
                unrecorded.append(p.name)
            elif r["status"] == "skipped":
                skipped.append(p.name)
            stop: dict[str, Any] = {
                "name": p.name,
                "status": STATUS_NAMES[r["status"]] if r else "未记录",
                "planned_time": f"{_hm(v.arrive)}–{_hm(v.leave)}（计划，不是实际）",
            }
            if r and r.get("rating"):
                stop["rating"] = r["rating"]
            if r and r.get("note"):
                stop["note"] = r["note"]
            if show_costs and p.ticket_price:
                stop["ticket_price_ref"] = p.ticket_price
            ph = [{"id": x["id"], "caption": x.get("caption", "")} for x in (photos or []) if x.get("place_id") == p.id]
            if ph:
                stop["photos"] = ph
            stops.append(stop)
        entry: dict[str, Any] = {"day": day.index + 1, "date": d.isoformat() if d else "", "stops": stops}
        dph = [{"id": x["id"], "caption": x.get("caption", "")} for x in (photos or []) if x.get("day") == day.index + 1]
        if dph:
            entry["photos"] = dph
        days.append(entry)
    facts: dict[str, Any] = {
        "title": trip.meta.name, "style": style if style in TEMPLATES else "通用",
        "template": TEMPLATES.get(style, TEMPLATES["通用"]),
        "days": days, "unrecorded": unrecorded, "skipped": skipped,
        "rules": ["只能使用这里的事实；没有记录的感受、花费、时间一律不写或写“待补充”。",
                  "“未记录”的景点先问用户去没去、感觉如何，再写。", "不要写“没去”的景点当作去过。",
                  "计划时间不是实际时间，不要写成“几点到了”。",
                  "照片只能引用 photos 里有的（写成“配图：说明”即可），不要描述照片里看不到的内容。"],
    }
    if style == "小红书":
        facts["suggested_tags"] = suggested_tags(trip, review, city)
    if show_costs:
        facts["actual_costs"] = {COST_NAMES[k]: v["amount"] for k, v in review.get("costs", {}).items()}
    if show_lodging:
        l = trip.chosen_lodging
        if l:
            facts["lodging"] = l.name
    return facts


def _allowed_numbers(trip: Trip, review: dict[str, Any], show_costs: bool) -> set[float]:
    ok: set[float] = set()
    for r in review.get("places", {}).values():
        for m in re.findall(r"\d+(?:\.\d+)?", r.get("note", "")):
            ok.add(float(m))
    if show_costs:
        for v in review.get("costs", {}).values():
            ok.add(float(v["amount"]))
        for p in trip.places:
            if p.ticket_price:
                ok.add(float(p.ticket_price))
    return ok


def check(trip: Trip, review: dict[str, Any], text: str, show_costs: bool = False) -> list[str]:
    """返回问题清单（空表示没发现能确定的问题；不代表文字都对）。"""
    out: list[str] = []
    rv = review.get("places", {})
    for p in trip.places:
        if p.name and p.name in text:
            r = rv.get(p.id)
            if r is None:
                out.append(f"文中提到「{p.name}」，但回顾里没有记录你去没去。")
            elif r["status"] == "skipped":
                out.append(f"文中提到「{p.name}」，但你记录的是“没去”。")
    allowed = _allowed_numbers(trip, review, show_costs)
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:元|块|¥|￥|rmb|RMB)|[¥￥]\s*(\d+(?:\.\d+)?)", text):
        n = float(m.group(1) or m.group(2))
        if n not in allowed:
            out.append(f"金额“{m.group(0).strip()}”在你的记录里找不到（花费记录{'已公开' if show_costs else '未设为公开'}）。")
    for m in re.finditer(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)", text):
        out.append(f"时间“{m.group(0)}”没有实际记录（计划时间不是实际时间）。")
    for l in trip.lodgings:
        if l.name and l.name in text:
            out.append(f"文中出现了酒店名「{l.name}」，确认是否要公开。")
    return list(dict.fromkeys(out))
