"""出发前复查：只对比"之前记下的"和"这次查到的"，返回有实际影响的变化。纯确定性代码，只读，不改行程。

- 天气：只报"雨雪/高温这类影响户外安排的因素有没有出现或消失"，以及白天气温变化是否超过阈值；多云变阴这种不报。
  没有旧预报的日期只是建立基线，不算变化。已经过去的日期不查。
- 营业时间：只对比来源为 amap 的；这次查不到就说"没核实"，不猜。变了也不自动改，由用户决定是否重排。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from .weather import bad_weather, is_outdoor


def weather_changes(trip, old: dict[str, Any], new: dict[str, Any], delta: float = 5.0, today: Optional[date] = None) -> list[dict[str, Any]]:
    today = today or date.today()
    out: list[dict[str, Any]] = []
    for d in trip.plan.days if trip.plan else []:
        dt = trip.day_date(d.index)
        if dt is None or dt < today:
            continue
        k = dt.isoformat()
        o, n = old.get(k), new.get(k)
        if o is None or n is None:
            continue
        ob, nb = bad_weather(o.day_weather, o.night_weather, o.day_temp), bad_weather(n.day_weather, n.night_weather, n.day_temp)
        why: list[str] = []
        if nb and not ob:
            why.append("新出现：" + "、".join(nb))
        elif ob and not nb:
            why.append("不利天气消失：" + "、".join(ob))
        elif nb and ob and set(nb) != set(ob):
            why.append("变为：" + "、".join(nb))
        if o.day_temp is not None and n.day_temp is not None and abs(n.day_temp - o.day_temp) >= delta:
            why.append(f"白天气温 {o.day_temp:.0f}°C → {n.day_temp:.0f}°C")
        if not why:
            continue
        outdoor = []
        if nb and not ob:
            from .timeline import day_visits
            outdoor = [v.place.name for v in day_visits(trip, d)[0] if is_outdoor(v.place)]
        out.append({"day": d.index + 1, "date": k, "changes": why,
                    "old": f"{o.day_weather} {o.day_temp if o.day_temp is not None else ''}（{o.fetched} 查询）",
                    "new": f"{n.day_weather} {n.day_temp if n.day_temp is not None else ''}（{n.fetched} 查询，{n.source}）",
                    "outdoor_places": outdoor})
    return out


def hours_changes(places: list, fresh: dict[str, Optional[str]]) -> tuple[list[dict[str, Any]], list[str]]:
    """places：有 amap 来源营业时间的景点；fresh：place_id → 这次查到的文字（None = 没查到）。"""
    changed, unchecked = [], []
    for p in places:
        new = fresh.get(p.id)
        if new is None:
            unchecked.append(p.name)
        elif new.strip() != (p.opening_hours or "").strip():
            changed.append({"place": p.name, "place_id": p.id, "old": p.opening_hours, "new": new, "source": "amap"})
    return changed, unchecked
