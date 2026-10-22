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

STYLE_HINTS = {
    "通用": "按天写，每天一两段；先写去了哪、什么感受（只用用户的备注和评分），再写小提示。",
    "小红书": "标题一句抓人的话，正文分短段，可用少量 emoji；结尾放 3~5 个话题标签。不要写没记录的花费和感受。",
    "朋友圈": "三五句话的短文，配图说明按天一句即可，不要罗列全部景点。",
}


def _hm(m: int) -> str:
    return f"{int(m) // 60:02d}:{int(m) % 60:02d}"


def build_facts(trip: Trip, review: dict[str, Any], style: str = "通用",
                show_lodging: bool = False, show_costs: bool = False) -> dict[str, Any]:
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
            stops.append(stop)
        days.append({"day": day.index + 1, "date": d.isoformat() if d else "", "stops": stops})
    facts: dict[str, Any] = {
        "title": trip.meta.name, "style_hint": STYLE_HINTS.get(style, STYLE_HINTS["通用"]),
        "days": days, "unrecorded": unrecorded, "skipped": skipped,
        "rules": ["只能使用这里的事实；没有记录的感受、花费、时间一律不写或写“待补充”。",
                  "“未记录”的景点先问用户去没去、感觉如何，再写。", "不要写“没去”的景点当作去过。",
                  "计划时间不是实际时间，不要写成“几点到了”。"],
    }
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
