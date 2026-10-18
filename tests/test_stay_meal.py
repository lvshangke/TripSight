from .conftest import make_place, make_trip
from tripcore.lodging import suggest_stay_segments
from tripcore.mealgaps import meal_gaps
from tripcore.metrics import day_budgets
from tripcore.models import DayItem, DayPlan, Meal, Plan


def _plan(trip, days):
    trip.plan = Plan(days=[DayPlan(index=i, items=[DayItem(place_id=p) for p in ids]) for i, ids in enumerate(days)])
    return trip


def test_segments_split_across_cities_and_merge_nearby():
    # 第 1、2 天在北京，第 3、4 天在西安：应分成两段
    bj1 = make_place("a", 39.91, 116.39); bj2 = make_place("b", 39.92, 116.40)
    bj3 = make_place("c", 39.90, 116.41); xa1 = make_place("d", 34.26, 108.94)
    xa2 = make_place("e", 34.27, 108.95)
    t = _plan(make_trip([bj1, bj2, bj3, xa1, xa2], num_days=4), [["a"], ["b", "c"], ["d"], ["e"]])
    segs = suggest_stay_segments(t)
    assert len(segs) >= 2
    assert segs[0].from_night == 0
    # 北京那段的中心不会跑到西安
    assert segs[0].lat > 39 and segs[-1].lat < 35
    assert segs[0].near_place in ("a", "b", "c")


def test_segments_merge_when_close():
    ps = [make_place(str(i), 39.90 + i * 0.002, 116.40) for i in range(4)]
    t = _plan(make_trip(ps, num_days=4), [["0"], ["1"], ["2"], ["3"]])
    segs = suggest_stay_segments(t)
    assert len(segs) == 1 and (segs[0].from_night, segs[0].to_night) == (0, 2)


def test_segments_empty_without_plan_or_places():
    assert suggest_stay_segments(make_trip([make_place("a")], num_days=2)) == []
    t = _plan(make_trip([make_place("a")], num_days=2), [[], []])
    assert suggest_stay_segments(t) == []


def test_meal_gaps_by_window_and_chosen_meals():
    # 一天排 9:00 起约 8 小时（跨午餐和晚餐）；第二天只上午
    long1 = make_place("a", duration_min=240); long2 = make_place("b", duration_min=300)
    short = make_place("c", duration_min=90)
    t = _plan(make_trip([long1, long2, short], num_days=2), [["a", "b"], ["c"]])
    assert meal_gaps(t) == {0: ["午餐", "晚餐"]}
    t.meals.append(Meal(id="m1", day=0, after_place_id="a", name="店", lat=39.9, lon=116.4))
    assert meal_gaps(t) == {0: ["晚餐"]}
    t.meals.append(Meal(id="m2", day=0, after_place_id="b", name="店2", lat=39.9, lon=116.4))
    assert meal_gaps(t) == {}


def test_day_budgets_multiply_travelers():
    a = make_place("a", ticket_price=50); b = make_place("b", ticket_price=30)
    t = _plan(make_trip([a, b], num_days=2, travelers=2), [["a"], ["b"]])
    t.meals.append(Meal(id="m", day=0, after_place_id="a", name="店", lat=39.9, lon=116.4, cost_per_person=40))
    d = day_budgets(t)
    assert (d[0].tickets, d[0].meals, d[0].meals_chosen) == (100, 80, 1)
    assert (d[1].tickets, d[1].meals, d[1].meals_chosen) == (60, 0, 0)


def test_suggest_lodging_tool_returns_segments_and_snapshot_has_meal_gaps():
    from tripcore import mcp_server as s, web
    s.new_trip(start_date="2026-10-20", end_date="2026-10-22", city="北京")
    s.add_place("甲", 39.91, 116.39, duration_min=240, ticket_price=50)
    s.add_place("乙", 39.92, 116.40, duration_min=300)
    s.schedule_days()
    out = s.suggest_lodging()
    assert "segments" in out and out["segments"] and "search_near" in out["segments"][0]
    assert "meal_gaps" in web.snapshot()
    assert "按天" in s.show_trip()


def test_day_trip_does_not_pull_the_hotel_away():
    # 第 2 天去 60 km 外的一日游，前后两天都在市区：酒店仍应住市区
    from tripcore.lodging import day_trips
    city = [make_place("a", 34.26, 108.94), make_place("b", 34.27, 108.95), make_place("c", 34.25, 108.93)]
    far = make_place("z", 34.48, 110.08)          # 约 105 km，华山式一日游
    t = _plan(make_trip(city + [far], num_days=4), [["a"], ["z"], ["b"], ["c"]])
    assert list(day_trips(t)) == [1] and day_trips(t)[1][0] == ["z"]
    segs = suggest_stay_segments(t)
    assert len(segs) == 1 and (segs[0].from_night, segs[0].to_night) == (0, 2)
    assert segs[0].lon < 109


def test_far_multi_day_group_is_a_separate_stay_not_a_day_trip():
    from tripcore.lodging import day_trips
    a = [make_place("a", 39.91, 116.39), make_place("b", 39.92, 116.40)]
    x = [make_place("c", 34.26, 108.94), make_place("d", 34.27, 108.95)]
    t = _plan(make_trip(a + x, num_days=4), [["a"], ["b"], ["c"], ["d"]])
    assert day_trips(t) == {}
