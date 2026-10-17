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


_BAD_CATEGORY = ("餐饮服务", "住宿服务", "交通设施服务", "公司企业", "商务住宅", "汽车服务", "生活服务")
MAX_EXTRA_CHARS = 6       # 地图名字比候选名最多长这么多才算“同一个地方”（否则像“老菜场老马家牛羊肉店”这种店名会被误认）


def _penalty(h: dict[str, Any]) -> int:
    return 10 if any(b in (h.get("category") or "") for b in _BAD_CATEGORY) else 0


def pick_hit(name: str, hits: list[dict[str, Any]]) -> tuple[Optional[dict[str, Any]], str]:
    """从地图候选里挑一个。名字必须相符：完全一样，或只多几个字（如括号里的区域）；
    餐馆、住宿、地铁站、公司等类别的结果优先级最低，名字不完全一样时直接不要；有多个同样好的、位置相距很远的结果就报歧义。"""
    from .geo import haversine_km
    if not hits:
        return None, "地图没有找到"
    n = _norm(name)
    scored = []
    for h in hits:
        hn = _norm(h["name"])
        if not similar_name(n, hn):
            continue
        exact = hn == n
        if not exact and len(hn) > len(n) + MAX_EXTRA_CHARS:
            continue
        if not exact and _penalty(h):
            continue
        scored.append(((_penalty(h), 0 if exact else 1 + abs(len(hn) - len(n))), h))
    if not scored:
        return None, "地图结果的名字对不上，或只有餐馆/住宿/车站等不相关的同名结果"
    scored.sort(key=lambda x: x[0])
    best = scored[0][0]
    top = scored[0][1]
    for sc, other in scored[1:]:
        if sc == best and haversine_km(top["lat"], top["lon"], other["lat"], other["lon"]) > 1.0:
            return None, "有多个同名地点，位置相距较远，需要你确认是哪个"
    return top, ""
