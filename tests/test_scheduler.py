from datetime import date

from tripcore.metrics import PACE_LIMITS, day_stats
from tripcore.models import DateMode, Pace, PlaceStatus
from tripcore.scheduler import build_plan, order_day, schedule
from tripcore.metrics import legs_between_stops

from .conftest import make_place, make_trip


def _ids(plan):
    return [[it.place_id for it in d.items] for d in plan.days]


def test_each_place_appears_at_most_once(beijing):
    plan = build_plan(beijing)
    placed = [i for day in _ids(plan) for i in day]
    assert len(placed) == len(set(placed))
    unscheduled = {u.place_id for u in plan.unscheduled}
    assert not (set(placed) & unscheduled)
    # 每个入围景点要么被安排，要么在未安排名单里（不会凭空消失）
    assert set(placed) | unscheduled == {p.id for p in beijing.places}


def test_respects_pace_limits(beijing):
    t = schedule(beijing)
    limits = PACE_LIMITS[t.meta.pace]
    for day in t.plan.days:
        st = day_stats(t, day)
        assert len(st.places) <= limits.max_places
        # 单个景点独占一天时允许超过游览上限，其余情况不得超过
        if len(st.places) > 1:
            assert st.visit_min <= limits.max_visit_minutes


def test_must_go_places_are_scheduled(beijing):
    plan = build_plan(beijing)
    placed = {i for day in _ids(plan) for i in day}
    for p in beijing.places:
        if p.must_go:
            assert p.id in placed


def test_closed_weekday_is_respected(beijing):
    # 2026-10-12 是周一；故宫、国家博物馆周一闭馆
    plan = build_plan(beijing)
    day0 = {it.place_id for it in plan.days[0].items}
    assert "gugong" not in day0
    assert "guobo" not in day0


def test_deterministic(beijing):
    assert _ids(build_plan(beijing)) == _ids(build_plan(beijing))


def test_low_priority_dropped_first_when_over_capacity():
    places = [make_place(f"p{i}", lat=39.9 + i * 0.001, priority=5 if i < 2 else 1) for i in range(6)]
    t = make_trip(places, num_days=1, pace=Pace.RELAXED)  # 每天最多 2 个
    plan = build_plan(t)
    assert {it.place_id for it in plan.days[0].items} == {"p0", "p1"}
    assert len(plan.unscheduled) == 4
    assert all("容量" in u.reason for u in plan.unscheduled)


def test_fewer_places_than_days_gives_empty_days():
    t = make_trip([make_place("a"), make_place("b", lat=39.95)], num_days=4)
    plan = build_plan(t)
    assert len(plan.days) == 4
    assert sum(len(d.items) for d in plan.days) == 2


def test_idea_and_excluded_are_not_scheduled():
    t = make_trip(
        [
            make_place("a"),
            make_place("b", status=PlaceStatus.IDEA),
            make_place("c", status=PlaceStatus.EXCLUDED),
        ],
        num_days=2,
    )
    placed = {i for day in _ids(build_plan(t)) for i in day}
    assert placed == {"a"}


def test_place_closed_every_day_is_unscheduled():
    t = make_trip(
        [make_place("a", closed_weekdays=list(range(7)))],
        num_days=2,
        date_mode=DateMode.EXACT,
        start_date=date(2026, 10, 12),
        end_date=date(2026, 10, 13),
    )
    plan = build_plan(t)
    assert [u.place_id for u in plan.unscheduled] == ["a"]
    assert "闭馆" in plan.unscheduled[0].reason


def test_locked_item_stays_on_its_day(beijing):
    first = schedule(beijing)
    # 把某一天的第一个条目锁定
    target_day = next(d for d in first.plan.days if len(d.items) >= 2)
    locked_id = target_day.items[0].place_id
    first.plan.days[target_day.index].items[0].locked = True

    # 即使改变节奏重新规划，锁定条目仍在原来的那一天，并保持锁定
    # （注意：新景点可以插到它前面，所以只保证“留在这一天”，不保证排第几个）
    first.meta.pace = Pace.PACKED
    again = schedule(first)
    day = again.plan.days[target_day.index]
    item = next(it for it in day.items if it.place_id == locked_id)
    assert item.locked is True


def test_two_locked_items_keep_relative_order(beijing):
    first = schedule(beijing)
    day = next(d for d in first.plan.days if len(d.items) >= 2)
    a, b = day.items[0].place_id, day.items[1].place_id
    day.items[0].locked = True
    day.items[1].locked = True
    first.meta.pace = Pace.PACKED
    again = schedule(first)
    ids = [it.place_id for it in again.plan.days[day.index].items]
    assert ids.index(a) < ids.index(b)


def test_schedule_bumps_revision_and_marks_planned(beijing):
    t = schedule(beijing)
    assert t.revision == beijing.revision + 1
    assert len(t.history) == 1
    planned = {it.place_id for d in t.plan.days for it in d.items}
    for p in t.places:
        if p.id in planned:
            assert p.status == PlaceStatus.PLANNED
    # 原对象没有被修改
    assert beijing.plan is None


def test_order_day_never_worse_than_input_order():
    ps = [
        make_place("a", lat=39.90, lon=116.30),
        make_place("b", lat=39.90, lon=116.50),
        make_place("c", lat=39.90, lon=116.31),
        make_place("d", lat=39.90, lon=116.49),
    ]
    best = order_day([], ps, None, "transit")

    def total(seq):
        return sum(l.minutes for l in legs_between_stops(make_trip(ps), seq))

    assert total(best) <= total(ps)
    # 相邻的点应该被排在一起：a-c 和 b-d 各自相邻
    ids = [p.id for p in best]
    assert abs(ids.index("a") - ids.index("c")) == 1
    assert abs(ids.index("b") - ids.index("d")) == 1


def test_order_day_keeps_locked_relative_order():
    locked = [make_place("x", lat=39.90, lon=116.30), make_place("y", lat=39.90, lon=116.50)]
    new = [make_place("n", lat=39.90, lon=116.40)]
    seq = order_day(locked, new, None, "transit")
    ids = [p.id for p in seq]
    assert ids.index("x") < ids.index("y")
    assert set(ids) == {"x", "y", "n"}
