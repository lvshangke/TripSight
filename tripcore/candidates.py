"""游记/攻略里提取出来的“候选”：模型只负责读文字、列清单，代码负责核对原文、去重、排序。

铁规则：每个候选必须带游记里的原话（quote），且 quote 必须真的出现在用户粘贴的原文里，名字必须出现在 quote 里；
价格、时间等“线索”也必须是原文里的片段。对不上的一律拒收。线索只当“待核实”，绝不当作事实写进行程。
"""

from __future__ import annotations

import re
from typing import Any, Optional

KINDS = ("attraction", "area", "food", "other")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def validate_items(text: str, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """返回 (通过的候选, 被拒绝的及原因)。通过的按在原文中出现的先后排序，并带上 order。"""
    nt = _norm(text)
    ok: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in items:
        name = _norm(str(raw.get("name", "")))
        quote = _norm(str(raw.get("quote", "")))
        kind = raw.get("kind", "attraction")
        if not name:
            rejected.append({"name": "", "reason": "缺少名称"})
            continue
        if kind not in KINDS:
            rejected.append({"name": name, "reason": f"kind 只能是 {'/'.join(KINDS)}"})
            continue
        if not quote or quote not in nt:
            rejected.append({"name": name, "reason": "quote 不在游记原文里（必须逐字摘录原文）"})
            continue
        if name not in quote:
            rejected.append({"name": name, "reason": "名称没有出现在 quote 里"})
            continue
        if name in seen:
            rejected.append({"name": name, "reason": "同一次提交里重复"})
            continue
        clues, bad = [], []
        for c in raw.get("clues") or []:
            (clues if _norm(str(c)) and _norm(str(c)) in nt else bad).append(str(c))
        entry = {"name": name, "kind": kind, "quote": str(raw.get("quote", "")).strip(), "clues": clues,
                 "order": nt.find(quote)}
        if bad:
            entry["dropped_clues"] = bad          # 不在原文里的线索，丢弃并告知模型
        seen.add(name)
        ok.append(entry)
    ok.sort(key=lambda e: e["order"])
    return ok, rejected


def similar_name(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return bool(a and b and (a == b or a in b or b in a))


def pick_hit(name: str, hits: list[dict[str, Any]]) -> tuple[Optional[dict[str, Any]], str]:
    """从地图候选里挑一个：名字相符且没有“同名但相距很远”的歧义，才返回；否则返回 (None, 原因)。"""
    from .geo import haversine_km
    if not hits:
        return None, "地图没有找到"
    matches = [h for h in hits if similar_name(name, h["name"])]
    if not matches:
        return None, "地图结果的名字都对不上"
    top = matches[0]
    for other in matches[1:]:
        if haversine_km(top["lat"], top["lon"], other["lat"], other["lon"]) > 1.0:
            return None, "有多个同名地点，位置相距较远，需要你确认是哪个"
    return top, ""
