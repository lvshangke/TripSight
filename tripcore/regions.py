"""手册的"章节"：把每个景点按所在的城市或区县归类，用高德的坐标反查（只发这个点的坐标，用用户自己的 key）。

规则：如果所有点都在同一个城市，就按区县分章（比如临海市 / 仙居县 / 天台县）；跨了多个城市就按城市分章。
反查失败或没有 key 时不猜，那个点没有章节，手册照常按天排。
"""

from __future__ import annotations

from typing import Optional


def chapter_labels(regions: dict[str, dict]) -> dict[str, str]:
    """{place_id: {province, city, district}} → {place_id: 章节名}。"""
    rows = {k: v for k, v in regions.items() if v and (v.get("city") or v.get("district"))}
    if not rows:
        return {}
    cities = {v.get("city") or v.get("province") or "" for v in rows.values()}
    use_district = len(cities) <= 1
    out = {}
    for k, v in rows.items():
        label = (v.get("district") if use_district else v.get("city")) or v.get("city") or v.get("district") or ""
        if label:
            out[k] = _short(label)
    return out


def _short(name: str) -> str:
    """"临海市"→"临海"，"仙居县"→"仙居"；"天台县"→"天台"。区、自治县等保留原名以免歧义。"""
    for suf in ("市", "县"):
        if name.endswith(suf) and len(name) > 2:
            return name[:-1]
    return name


def order_of_appearance(places_in_order: list[str], labels: dict[str, str]) -> list[str]:
    seen: list[str] = []
    for pid in places_in_order:
        c = labels.get(pid)
        if c and c not in seen:
            seen.append(c)
    return seen
