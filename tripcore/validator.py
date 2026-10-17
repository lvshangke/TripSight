"""校验器：检查行程有没有问题，返回一份“问题清单”。

全部是确定性的规则（不用大模型）。以后 Agent 要“修复问题”，也是先读这份清单。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from .connections import arrival_day, day_window, departure_day
from .metrics import PACE_LIMITS, day_stats, estimate_cost
from .models import Trip

Severity = Literal["error", "warning", "info"]

LONG_LEG_MIN = 60       # 单段交通超过这个分钟数，提醒
LODGING_FAR_MIN = 45    # 住宿到当天首/末景点超过这个分钟数，提醒

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    message: str
    day_index: Optional[int] = None
    place_id: Optional[str] = None


def validate(trip: Trip) -> list[Issue]:
    issues: list[Issue] = []
    if trip.plan is None:
        return [Issue("NO_PLAN", "info", "还没有生成行程，请先运行分天。")]

    limits = PACE_LIMITS[trip.meta.pace]

    for day in trip.plan.days:
        st = day_stats(trip, day)
        label = f"第{day.index + 1}天"
        d = trip.day_date(day.index)

        if not st.places:
            issues.append(Issue("EMPTY_DAY", "info", f"{label}还没有安排。", day.index))
            continue

        if len(st.places) > limits.max_places:
            issues.append(
                Issue(
                    "DAY_TOO_MANY_PLACES",
                    "warning",
                    f"{label}安排了 {len(st.places)} 个地点，超过当前节奏的建议上限 {limits.max_places} 个。",
                    day.index,
                )
            )

        if st.total_min > limits.max_total_minutes:
            issues.append(
                Issue(
                    "DAY_TOO_FULL",
                    "warning",
                    f"{label}游览 {st.visit_min} 分钟 + 交通 {st.travel_min} 分钟，"
                    f"共 {st.total_min} 分钟，超过建议上限 {limits.max_total_minutes} 分钟。",
                    day.index,
                )
            )

        w_start, w_end, w_why = day_window(trip, day.index)
        if w_why and st.total_min > (w_end - w_start):
            issues.append(
                Issue(
                    "CONNECTION_WINDOW_TOO_SMALL",
                    "warning",
                    f"{label}（{'；'.join(w_why)}）只有约 {w_end - w_start} 分钟可玩，"
                    f"但安排了游览 {st.visit_min} 分钟 + 交通 {st.travel_min} 分钟，需要减少或挪到别的天。",
                    day.index,
                )
            )

        for leg in st.legs:
            if leg.minutes > LONG_LEG_MIN:
                a, b = trip.place(leg.from_id), trip.place(leg.to_id)
                issues.append(
                    Issue(
                        "LONG_LEG",
                        "warning",
                        f"{label}从「{a.name}」到「{b.name}」约需 {leg.minutes} 分钟，路上较久。",
                        day.index,
                        b.id,
                    )
                )

        for leg in (st.lodging_out, st.lodging_back):
            if leg is not None and leg.minutes > LODGING_FAR_MIN:
                lodging = trip.chosen_lodging
                issues.append(
                    Issue(
                        "LODGING_FAR",
                        "warning",
                        f"{label}往返住宿「{lodging.name if lodging else ''}」单程约 {leg.minutes} 分钟，偏远。",
                        day.index,
                    )
                )
                break  # 同一天只提醒一次

        for p in st.places:
            if d is not None and d.weekday() in p.closed_weekdays:
                issues.append(
                    Issue(
                        "CLOSED_ON_DAY",
                        "error",
                        f"{label}（{d.isoformat()} {_WEEKDAYS[d.weekday()]}）「{p.name}」闭馆。",
                        day.index,
                        p.id,
                    )
                )
            if p.reservation_required and not p.reserved:
                issues.append(
                    Issue(
                        "RESERVATION_NOT_BOOKED",
                        "warning",
                        f"「{p.name}」需要提前预约，目前标记为未预约。"
                        + (
                            "如果约不上，备选：" + "、".join(trip.place(b).name for b in p.backups if any(x.id == b for x in trip.places)) + "。"
                            if any(any(x.id == b for x in trip.places) for b in p.backups)
                            else "还没有设置备选景点。"
                        ),
                        day.index,
                        p.id,
                    )
                )

    for which, c, idx in (("到达", trip.arrival, arrival_day(trip)), ("离开", trip.departure, departure_day(trip))):
        if c is not None and idx is None:
            issues.append(Issue("CONNECTION_DATE_MISMATCH", "warning",
                                f"{which}的大交通（{c.number or c.kind}，{c.dep_time:%Y-%m-%d %H:%M}→{c.arr_time:%Y-%m-%d %H:%M}）"
                                f"不在行程的日期范围内，请核对日期。"))

    for u in trip.plan.unscheduled:
        name = trip.place(u.place_id).name
        issues.append(Issue("UNSCHEDULED", "warning", f"「{name}」没有排进行程：{u.reason}", None, u.place_id))

    budget = trip.meta.budget_total
    if budget is not None:
        cost = estimate_cost(trip)
        if cost.total > budget:
            issues.append(
                Issue(
                    "OVER_BUDGET",
                    "warning",
                    f"门票 {cost.tickets:.0f} + 住宿 {cost.lodging:.0f}（{cost.nights} 晚）"
                    f"= {cost.total:.0f} {trip.meta.currency}，已超过预算 {budget:.0f}（尚未计入餐饮和交通）。",
                )
            )

    issues.sort(key=lambda i: (_SEVERITY_ORDER[i.severity], i.day_index if i.day_index is not None else 99))
    return issues
