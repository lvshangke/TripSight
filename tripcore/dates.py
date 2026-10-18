"""修改行程日期（确定日期，或清除）。走 commit，所以可以 undo。天数由日期推出来，不自动改已排好的分天。"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import ValidationError

from .models import DateMode, PlaceStatus, Trip, TripMeta
from .scheduler import build_plan
from .state import commit


def apply_dates(trip: Trip, start: Optional[date], end: Optional[date]) -> tuple[Trip, list[str]]:
    """返回 (新行程, 需要提醒用户的事项)。start/end 都为 None 表示清除日期；只给一个会抛 ValueError。"""
    if (start is None) != (end is None):
        raise ValueError("开始和结束日期要一起填（或者都不填表示清除）。")
    if start is not None and end is not None and (end - start).days + 1 > 30:
        raise ValueError("行程最多 30 天。")
    old_days = trip.meta.num_days
    data = trip.meta.model_dump()
    if start is None:
        data.update(date_mode=DateMode.UNKNOWN, start_date=None, end_date=None)
    else:
        data.update(date_mode=DateMode.EXACT, start_date=start, end_date=end, earliest_start=None, latest_end=None)
    try:
        meta = TripMeta.model_validate(data)
    except ValidationError as e:
        raise ValueError("日期不合法：" + "；".join(x["msg"] for x in e.errors())) from None

    replan = trip.plan is not None and meta.num_days != old_days
    unscheduled: list[str] = []

    def mutate(t: Trip) -> None:
        t.meta = meta
        t.weather = {}                       # 旧日期的天气快照作废
        if replan:                           # 天数变了：按新天数重新分天，免得留着超出范围的旧天（锁定且仍在范围内的保持原位）
            plan = build_plan(t, keep_locked=True)
            t.plan = plan
            placed = {it.place_id for d in plan.days for it in d.items}
            for p in t.places:
                if p.id in placed and p.status == PlaceStatus.SHORTLIST:
                    p.status = PlaceStatus.PLANNED
                elif p.id not in placed and p.status == PlaceStatus.PLANNED:
                    p.status = PlaceStatus.SHORTLIST
            unscheduled.extend(f"{t.place(u.place_id).name}（{u.reason}）" for u in plan.unscheduled)

    new = commit(trip, mutate)
    notes: list[str] = []
    if replan:
        notes.append(f"天数从 {old_days} 天变成 {meta.num_days} 天，已按新天数重新分天（已锁定且仍在范围内的景点保持原位，其余重排；"
                     "路线时间沿用已查过的，新相邻的景点先按估算，可以更新路线）。")
        if unscheduled:
            notes.append("没能排进去：" + "、".join(unscheduled) + "。")
    elif meta.num_days != old_days:
        notes.append(f"天数从 {old_days} 天变成 {meta.num_days} 天（还没有分天，之后 schedule_days 会按新天数排）。")
    if any(s.to_day >= meta.num_days for s in trip.stays):
        notes.append("有分段住宿超出了新的天数范围，请用 set_stays 重新设置。")
    if trip.weather:
        notes.append("旧的天气快照已清除，需要的话重新 get_weather。")
    return new, notes
