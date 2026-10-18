"""手机/聊天用的纯文字行程（确定性生成，不经过模型）。

内容来自和地图页同一份数据（build_map_data），所以时间、交通、天气、预约提示和地图页一致。
发出去之前会过一遍“外发检查”：带 key、本机路径的文字不允许发送（宁可报错也不外泄）。
"""

from __future__ import annotations

import os
import re
from typing import Optional

from .mapview import build_map_data
from .models import Trip
from .weather import fmt_snap

_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_PATH_RE = re.compile(r"(/Users/|/home/|/sessions/|/root/|~/\.|[A-Za-z]:\\)")
_KEY_RE = re.compile(r"(?i)\b(key|token|secret|password)=[A-Za-z0-9_\-]{8,}")


def guard_text(text: str) -> list[str]:
    """外发检查：返回发现的问题（空列表表示可以发送）。"""
    bad: list[str] = []
    if _PATH_RE.search(text):
        bad.append("含有本机文件路径")
    if _KEY_RE.search(text):
        bad.append("含有 key/token 形式的参数")
    secret = os.environ.get("AMAP_KEY", "").strip()
    if len(secret) >= 8 and secret in text:
        bad.append("含有高德 key")
    return bad


def _day_text(trip: Trip, d: dict, with_links: bool) -> str:
    idx = d["index"]
    date_ = trip.day_date(idx)
    head = f"【{trip.meta.name}】第{idx + 1}天" + (f" {date_.isoformat()}（{_WEEKDAYS[date_.weekday()]}）" if date_ else "")
    lines = [head]
    w = trip.weather.get(date_.isoformat()) if date_ else None
    if w:
        lines.append("🌤 " + fmt_snap(w))
    for e in d["timeline"]:
        t = e["type"]
        if t == "conn":
            lines.append("⏱ " + e["text"])
        elif t == "term":
            lines.append(f"{e['icon']} {e['time']} {e['role']} {e['name']}")
            lines += ["   " + x for x in e["lines"]]
        elif t == "hotel":
            lines.append(f"🏨 {e['time']} {e['role']} {e['name']}")
        elif t == "leg":
            km = f" {e['km']:.1f}km" if e.get("km") else ""
            est = "" if e.get("real") else "（估算）"
            lines.append(f"   ↓ {e['mode']} {e['minutes']}分钟{km}{est}" + (f"｜{e['note']}" if e.get("note") else ""))
        elif t == "stop":
            lines.append(f"{e['n']}. {e['arrive']}–{e['leave']} {e['name']}（{e['stay']}分钟）")
            lines += ["   " + x for x in e["lines"]]
            if with_links and e.get("web"):
                lines.append("   📍 " + e["web"])
        elif t == "meal":
            lines.append(f"🍜 用餐：{e['name']}")
            lines += ["   " + x for x in e["lines"]]
            if with_links and e.get("web"):
                lines.append("   📍 " + e["web"])
    return "\n".join(lines)


def build_text(trip: Trip, day: Optional[int] = None, with_links: bool = True) -> str:
    """day 从 1 起；不填则全程，每天之间用分隔线隔开。"""
    if trip.plan is None:
        raise ValueError("还没有分天")
    days = build_map_data(trip)["days"]
    if day is not None:
        days = [d for d in days if d["index"] == day - 1]
        if not days:
            raise ValueError(f"没有第 {day} 天的行程")
    text = "\n\n———\n\n".join(_day_text(trip, d, with_links) for d in days)
    return text
