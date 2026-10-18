from datetime import date

from tripcore.models import DateMode, DayItem, DayPlan, Lodging, Pace, Plan, Unscheduled
from tripcore.scheduler import schedule
from tripcore.validator import validate

from .conftest import make_place, make_trip


def _codes(trip):
    return {i.code for i in validate(trip)}


def _manual(trip, days):
    """手工指定每天的景点 id 列表。"""
    trip.plan = Plan(days=[DayPlan(index=i, items=[DayItem(place_id=p) for p in ids]) for i, ids in enumerate(days)])
    return trip


def test_no_plan_returns_info():
    t = make_trip([make_place("a")])
    issues = validate(t)
    assert [i.code for i in issues] == ["NO_PLAN"]


def test_too_many_places():
    places = [make_place(f"p{i}", lat=39.9 + i * 0.0005, duration_min=30) for i in range(4)]
    t = _manual(make_trip(places, num_days=1, pace=Pace.RELAXED), [[p.id for p in places]])
    assert "DAY_TOO_MANY_PLACES" in _codes(t)


def test_day_too_full():
    places = [make_place("a", duration_min=400), make_place("b", lat=39.901, duration_min=200)]
    t = _manual(make_trip(places, num_days=1), [["a", "b"]])
    assert "DAY_TOO_FULL" in _codes(t)


def test_long_leg():
    places = [make_place("a", lat=39.9, lon=116.4), make_place("b", lat=40.35, lon=116.0)]
    t = _manual(make_trip(places, num_days=1), [["a", "b"]])
    assert "LONG_LEG" in _codes(t)


def test_closed_on_day_is_error():
    places = [make_place("a", closed_weekdays=[0])]  # 周一闭馆
    t = _manual(
        make_trip(places, num_days=1, date_mode=DateMode.EXACT, start_date=date(2026, 10, 12), end_date=date(2026, 10, 12)),
        [["a"]],
    )
    issues = [i for i in validate(t) if i.code == "CLOSED_ON_DAY"]
    assert len(issues) == 1 and issues[0].severity == "error"


def test_reservation_warning_and_cleared_when_reserved():
    t = _manual(make_trip([make_place("a", reservation_required=True)], num_days=1), [["a"]])
    assert "RESERVATION_NOT_BOOKED" in _codes(t)
    t.place("a").reserved = True
    assert "RESERVATION_NOT_BOOKED" not in _codes(t)


def test_lodging_far():
    places = [make_place("a", lat=39.9, lon=116.4)]
    far = Lodging(id="h", name="远郊酒店", lat=40.3, lon=116.0, price_min=100, price_max=200)
    t = make_trip(places, num_days=1, lodgings=[far])
    t.chosen_lodging_id = "h"
    t = _manual(t, [["a"]])
    assert "LODGING_FAR" in _codes(t)


def test_over_budget():
    places = [make_place("a", ticket_price=500)]
    h = Lodging(id="h", name="酒店", lat=39.9, lon=116.4, price_min=800, price_max=1000)
    t = make_trip(places, num_days=3, lodgings=[h], budget_total=1000)
    t.chosen_lodging_id = "h"
    t = _manual(t, [["a"], [], []])
    assert "OVER_BUDGET" in _codes(t)


def test_unscheduled_reported():
    t = _manual(make_trip([make_place("a")], num_days=1), [[]])
    t.plan.unscheduled = [Unscheduled(place_id="a", reason="测试原因")]
    assert "UNSCHEDULED" in _codes(t)


def test_errors_sorted_first(beijing):
    t = _manual(beijing, [["gugong"], [], [], []])  # 周一排故宫 → error
    issues = validate(t)
    assert issues[0].severity == "error"


def test_demo_plan_has_no_errors(beijing):
    t = schedule(beijing)
    assert not [i for i in validate(t) if i.severity == "error"]


# ---- 营业时间 ----
def _hours_trip(hours: str, durations=(120, 120), start=date(2026, 10, 14), pace=Pace.PACKED):
    a = make_place("a", lat=39.90, lon=116.40, duration_min=durations[0], opening_hours="周一至周日 00:00-24:00")
    b = make_place("b", lat=39.905, lon=116.405, duration_min=durations[1], opening_hours=hours, hours_source="amap")
    return _manual(make_trip([a, b], num_days=1, pace=pace, date_mode=DateMode.EXACT, start_date=start, end_date=start), [["a", "b"]])


def _hr(trip):
    return [i for i in validate(trip) if i.code in ("OUTSIDE_HOURS", "LEAVE_AFTER_CLOSE", "ARRIVE_BEFORE_OPEN")]


def test_arrive_after_close_is_error():
    t = _hours_trip("周一至周日 09:00-10:30")                    # b 约 11:00 才到
    (i,) = _hr(t)
    assert i.code == "OUTSIDE_HOURS" and i.severity == "error" and i.place_id == "b" and "已关门" in i.message and "amap" in i.message


def test_after_last_entry_is_error():
    t = _hours_trip("周一至周日 09:00-18:00 最晚进入11:00")
    (i,) = _hr(t)
    assert i.code == "OUTSIDE_HOURS" and "最晚进入" in i.message


def test_leave_after_close_is_warning_with_real_minutes():
    t = _hours_trip("周一至周日 09:00-12:00")                    # 11:xx 到，停 120 分钟，12:00 闭馆
    (i,) = _hr(t)
    assert i.code == "LEAVE_AFTER_CLOSE" and i.severity == "warning" and "最多停留约" in i.message


def test_arrive_before_open_waits():
    t = _hours_trip("周一至周日 13:00-18:00")
    (i,) = _hr(t)
    assert i.code == "ARRIVE_BEFORE_OPEN" and "需要等待" in i.message


def test_lunch_break_and_ok_cases():
    assert [i.code for i in _hr(_hours_trip("周一至周日 09:00-10:00、11:00-18:00"))] == []      # 11:xx 到达在第二段里
    t = _hours_trip("周一至周日 09:00-18:00")
    assert _hr(t) == []


def test_closed_day_by_hours_text_is_error():
    t = _hours_trip("周一至周日 09:00-18:00；周三 闭馆")           # 2026-10-14 是周三
    (i,) = _hr(t)
    assert i.severity == "error" and "闭馆" in i.message


def test_unknown_hours_or_no_date_not_checked():
    assert _hr(_hours_trip("待核实")) == []
    a = make_place("a", opening_hours="周一至周日 09:00-10:00")
    t = _manual(make_trip([a], num_days=1), [["a"]])
    codes = _codes(t)
    assert "HOURS_NEED_DATE" in codes and not ({"OUTSIDE_HOURS", "LEAVE_AFTER_CLOSE"} & codes)


def test_day_runs_late():
    t = _hours_trip("", durations=(360, 420))
    assert "DAY_RUNS_LATE" in _codes(t)


def test_day_visits_match_map_timeline(beijing):
    from tripcore.mapview import build_map_data
    from tripcore.timeline import day_visits
    beijing = schedule(beijing)
    data = {d["index"]: [e for e in d["timeline"] if e["type"] == "stop"] for d in build_map_data(beijing)["days"]}
    hm = lambda m: f"{int(m) // 60:02d}:{int(m) % 60:02d}"
    n = 0
    for day in beijing.plan.days:
        visits, _ = day_visits(beijing, day)
        assert [(hm(v.arrive), hm(v.leave)) for v in visits] == [(e["arrive"], e["leave"]) for e in data[day.index]]
        n += len(visits)
    assert n > 0
