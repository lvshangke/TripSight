"""修改行程日期（确定日期，或清除）。走 commit，所以可以 undo。天数由日期推出来，不自动改已排好的分天。"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import ValidationError

from .models import DateMode, Trip, TripMeta
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

    def mutate(t: Trip) -> None:
        t.meta = meta
        t.weather = {}                       # 旧日期的天气快照作废

    new = commit(trip, mutate)
    notes: list[str] = []
    if meta.num_days != old_days:
        notes.append(f"天数从 {old_days} 天变成 {meta.num_days} 天，已排好的分天没有自动改动，请重新 schedule_days。")
    if any(s.to_day >= meta.num_days for s in trip.stays):
        notes.append("有分段住宿超出了新的天数范围，请用 set_stays 重新设置。")
    if trip.weather:
        notes.append("旧的天气快照已清除，需要的话重新 get_weather。")
    return new, notes
