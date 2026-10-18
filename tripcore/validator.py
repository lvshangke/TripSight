"""校验器：检查行程有没有问题，返回一份“问题清单”。

全部是确定性的规则（不用大模型）。以后 Agent 要“修复问题”，也是先读这份清单。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from .connections import arrival_day, day_window, departure_day
from .metrics import INTERCITY_KM, PACE_LIMITS, day_stats, estimate_cost, intercity_hint
from .hours import hours_window
from .models import Trip
from .timeline import day_visits
from .stays import hint_text
from .weather import SOURCE_NAMES, bad_weather, is_outdoor

Severity = Literal["error", "warning", "info"]

LONG_LEG_MIN = 60       # 单段交通超过这个分钟数，提醒
LODGING_FAR_MIN = 45    # 住宿到当天首/末景点超过这个分钟数，提醒

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
WAIT_WARN_MIN = 30      # 比开门早到超过这么久，提醒（短的等待只给提示）


def _hm(m: int) -> str:
    m = int(m) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def _hours_problem(w, arrive: int, leave: int):
    """把一个景点的到达/离开时间和当天营业窗口对比。返回 (代码, 严重程度, 说明) 或 None（没问题）。"""
    if w.closed:
        return "OUTSIDE_HOURS", "error", "当天不开放（闭馆）"
    if w.all_day:
        if w.last_entry is not None and arrive > w.last_entry:
            return "OUTSIDE_HOURS", "error", f"{_hm(arrive)} 到达，已过最晚进入/售票时间 {_hm(w.last_entry)}"
        return None
    rs = w.ranges
    cur = next((r for r in rs if r[0] <= arrive < r[1]), None)
    span = "、".join(f"{_hm(a)}-{_hm(b)}" for a, b in rs)
    if cur is None:
        if arrive >= rs[-1][1]:
            return "OUTSIDE_HOURS", "error", f"{_hm(arrive)} 到达时已关门（当天 {span} 开放）"
        if arrive < rs[0][0]:
            wait = rs[0][0] - arrive
            return "ARRIVE_BEFORE_OPEN", "warning" if wait >= WAIT_WARN_MIN else "info", f"{_hm(arrive)} 到达，比开门时间 {_hm(rs[0][0])} 早约 {wait} 分钟，需要等待"
        nxt = next(r for r in rs if r[0] > arrive)
        return "OUTSIDE_HOURS", "warning", f"{_hm(arrive)} 到达时正在休息，{_hm(nxt[0])} 才重新开放"
    if w.last_entry is not None and arrive > w.last_entry:
        return "OUTSIDE_HOURS", "error", f"{_hm(arrive)} 到达，已过最晚进入/售票时间 {_hm(w.last_entry)}（{_hm(cur[1])} 闭馆）"
    if leave > cur[1]:
        return "LEAVE_AFTER_CLOSE", "warning", f"计划停留到 {_hm(leave)}，但 {_hm(cur[1])} 闭馆，实际最多停留约 {cur[1] - arrive} 分钟"
    return None


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
    saw_hours_without_date = False

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

        visits, end_min = day_visits(trip, day)
        if not w_why and end_min > w_end:
            issues.append(Issue("DAY_RUNS_LATE", "warning", f"{label}预计{'次日 ' if end_min >= 24 * 60 else ' '}{_hm(end_min)} 才结束，晚于建议的 {_hm(w_end)}。", day.index))
        for v in visits:
            if not v.place.opening_hours:
                continue
            if d is None:
                saw_hours_without_date = True
                continue
            w = hours_window(v.place.opening_hours, d)
            if w is None:
                continue
            prob = _hours_problem(w, v.arrive, v.leave)
            if prob is not None:
                code, sev, text = prob
                src = f"（来源：{v.place.hours_source}）" if v.place.hours_source else ""
                issues.append(Issue(code, sev, f"{label}（{d.isoformat()}）「{v.place.name}」{text}{src}。", day.index, v.place.id))

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
                lodging = trip.lodging_for_day(day.index)
                issues.append(
                    Issue(
                        "LODGING_FAR",
                        "warning",
                        f"{label}往返住宿「{lodging.name if lodging else ''}」单程约 {leg.minutes} 分钟，偏远。",
                        day.index,
                    )
                )
                break  # 同一天只提醒一次

        names = {**{p.id: p.name for p in trip.places}, **{l.id: l.name for l in trip.lodgings}}
        for leg in [*st.legs, st.lodging_out, st.lodging_back]:
            if leg is not None and leg.distance_km > INTERCITY_KM and leg.mode != "drive":
                issues.append(Issue(
                    "INTERCITY_LEG", "info",
                    f"{label}「{names.get(leg.from_id, leg.from_id)}」→「{names.get(leg.to_id, leg.to_id)}」" + intercity_hint(leg.distance_km, leg.mode),
                    day.index))
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
            w = trip.weather.get(d.isoformat()) if d is not None else None
            if w is not None and is_outdoor(p):
                bad = bad_weather(w.day_weather, w.night_weather, w.day_temp)
                if bad:
                    issues.append(
                        Issue(
                            "WEATHER_OUTDOOR",
                            "warning",
                            f"{label}（{d.isoformat()}）预报{w.day_weather}"
                            + (f" {w.day_temp:.0f}°C" if w.day_temp is not None else "")
                            + f"（{'、'.join(bad)}；{SOURCE_NAMES.get(w.source, w.source)}，{w.fetched} 查询），「{p.name}」是户外安排，建议与室内景点调换或备好雨具/避开正午。",
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

    if saw_hours_without_date:
        issues.append(Issue("HOURS_NEED_DATE", "info", "还没有确定日期，无法按营业时间检查各景点的到达时间；确定日期后会自动检查。"))

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

    hint = hint_text(trip)
    if hint:
        issues.append(Issue("STAY_SUGGESTION", "info", hint))

    issues.sort(key=lambda i: (_SEVERITY_ORDER[i.severity], i.day_index if i.day_index is not None else 99))
    return issues
