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
