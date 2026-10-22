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
        # 单个景点独占一天时允许超限；其余情况“游览 + 路上”不得超过当天总时间上限
        if len(st.places) > 1:
            assert st.total_min <= limits.max_total_minutes


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


# ---- 营业时间参与排程 ----
from datetime import date as _date

from tripcore.models import DateMode as _DM, DayItem, DayPlan, Lodging as _Lodging, Plan
from tripcore.validator import validate as _validate


def _day_trip(places, days=1, lodging=True, start=_date(2026, 10, 14)):
    t = make_trip(places, num_days=days, date_mode=_DM.EXACT, start_date=start, end_date=start + __import__("datetime").timedelta(days=days - 1),
                  pace=Pace.PACKED)
    if lodging:
        t.lodgings = [_Lodging(id="l1", name="酒店", lat=39.9, lon=116.4)]
        t.chosen_lodging_id = "l1"
    return t


def _order(t):
    return [[it.place_id for it in d.items] for d in schedule(t).plan.days]


def test_early_closing_place_goes_first_even_if_farther():
    near = make_place("a", lat=39.9005, lon=116.4005, duration_min=90)
    far = make_place("b", lat=39.93, lon=116.43, duration_min=90, opening_hours="周一至周日 09:00-11:00")
    no_hours = make_place("b", lat=39.93, lon=116.43, duration_min=90)
    assert _order(_day_trip([near, no_hours])) == [["a", "b"]]                  # 没有营业时间：往返路程一样，按编号先后
    assert _order(_day_trip([near, far])) == [["b", "a"]]                       # 有营业时间：远的 11:00 前要到，所以先去（交通代价相同，只有营业时间让顺序变化）


def test_late_opening_place_goes_after():
    a = make_place("a", lat=39.9005, lon=116.4005, duration_min=90)
    b = make_place("b", lat=39.9002, lon=116.4002, duration_min=90, opening_hours="周一至周日 14:00-18:00")
    assert _order(_day_trip([a, b])) == [["a", "b"]]


def test_scheduled_plan_has_no_hours_errors_when_feasible():
    ps = [
        make_place("m", lat=39.91, lon=116.41, duration_min=120, opening_hours="周一至周日 09:00-12:00"),
        make_place("n", lat=39.905, lon=116.405, duration_min=120, opening_hours="周一至周日 13:00-18:00"),
        make_place("o", lat=39.9, lon=116.4, duration_min=60),
    ]
    t = schedule(_day_trip(ps))
    assert not [i for i in _validate(t) if i.code in ("OUTSIDE_HOURS", "LEAVE_AFTER_CLOSE")]


def test_place_closed_on_one_day_goes_to_the_other_day():
    p = make_place("p", lat=39.9, lon=116.4, opening_hours="周一至周日 09:00-17:00；周三 闭馆", duration_min=120)
    q = make_place("q", lat=39.901, lon=116.401, duration_min=120)
    t = _day_trip([p, q], days=2, start=_date(2026, 10, 14))             # 第 1 天是周三
    assert "p" not in _order(t)[0] and "p" in _order(t)[1]


def test_never_possible_place_is_unscheduled_with_reason():
    p = make_place("p", lat=39.9, lon=116.4, opening_hours="周一至周日 06:00-08:30")      # 打烊早于一天的开始
    t = schedule(_day_trip([p, make_place("q", lat=39.901, lon=116.401)]))
    assert [u.place_id for u in t.plan.unscheduled] == ["p"] and "营业时间" in t.plan.unscheduled[0].reason


def test_locked_items_are_never_moved_by_hours():
    a = make_place("a", lat=39.9005, lon=116.4005, duration_min=90)
    b = make_place("b", lat=39.93, lon=116.43, duration_min=90, opening_hours="周一至周日 09:00-10:00")
    t = _day_trip([a, b])
    t.plan = Plan(days=[DayPlan(index=0, items=[DayItem(place_id="a", locked=True), DayItem(place_id="b", locked=True)])])
    assert _order_keep(t) == [["a", "b"]]                                  # 锁定的保持原样（问题交给校验器提示）


def _order_keep(t):
    return [[it.place_id for it in d.items] for d in schedule(t, keep_locked=True).plan.days]


def test_scheduling_is_deterministic_with_hours():
    ps = [make_place(f"p{i}", lat=39.9 + i * 0.004, lon=116.4 + i * 0.003, duration_min=60,
                     opening_hours="周一至周日 09:00-12:00" if i % 2 else "周一至周日 13:00-18:00") for i in range(6)]
    t = _day_trip(ps, days=2)
    assert _order(t) == _order(t)


# ---- 总时间容量 / 塞回未安排 / 轻松版 ----------------------------------------

def _hz_trip(**kw):
    """类杭州：西湖片区三个顺路景点（时长较长）+ 远处两个景点。"""
    places = [
        make_place("xihu", lat=30.2590, lon=120.1450, duration_min=180, priority=5),
        make_place("leifeng", lat=30.2310, lon=120.1490, duration_min=120, priority=4),
        make_place("jingci", lat=30.2290, lon=120.1430, duration_min=60, priority=3),
        make_place("jiuxi", lat=30.1960, lon=120.1090, duration_min=120, priority=3),
        make_place("songcheng", lat=30.1700, lon=120.1000, duration_min=240, priority=3),
    ]
    return make_trip(places, num_days=2, pace=Pace.NORMAL)


def test_total_time_rule_keeps_nearby_long_day_together():
    t = schedule(_hz_trip())
    for day in t.plan.days:
        st = day_stats(t, day)
        if len(st.places) > 1:
            assert st.total_min <= PACE_LIMITS[Pace.NORMAL].max_total_minutes
    # 西湖和雷峰塔离得近，应在同一天
    where = {it.place_id: d.index for d in t.plan.days for it in d.items}
    assert where["xihu"] == where["leifeng"]


def test_unscheduled_places_are_filled_back_when_room_exists():
    plan = build_plan(_hz_trip(), comfort=1.0)
    placed = {it.place_id for d in plan.days for it in d.items}
    left = {u.place_id for u in plan.unscheduled}
    assert placed | left == {"xihu", "leifeng", "jingci", "jiuxi", "songcheng"}
    # 没有任何一个落下的景点还能放进某一天（否则就该被塞回去）
    t = schedule(_hz_trip())
    for pid in left:
        for day in t.plan.days:
            st = day_stats(t, day)
            assert len(st.places) >= PACE_LIMITS[Pace.NORMAL].max_places or \
                st.total_min + t.place(pid).duration_min > PACE_LIMITS[Pace.NORMAL].max_total_minutes


def test_relaxed_schedule_is_lighter_and_never_exceeds_comfort_limit():
    from tripcore.scheduler import RELAXED_COMFORT
    t = schedule(_hz_trip(), comfort=RELAXED_COMFORT)
    cap = int(PACE_LIMITS[Pace.NORMAL].max_total_minutes * RELAXED_COMFORT)
    for day in t.plan.days:
        st = day_stats(t, day)
        if len(st.places) > 1:
            assert st.total_min <= cap
    normal = schedule(_hz_trip())
    n_relaxed = sum(len(d.items) for d in t.plan.days)
    n_normal = sum(len(d.items) for d in normal.plan.days)
    assert n_relaxed <= n_normal


def test_locked_items_untouched_by_fill_and_relaxed():
    t = schedule(_hz_trip())
    first = t.plan.days[0].items[0].place_id
    from tripcore.state import commit
    def lock(tt):
        for d in tt.plan.days:
            for it in d.items:
                if it.place_id == first:
                    it.locked = True
    t = commit(t, lock)
    before = next(d.index for d in t.plan.days for it in d.items if it.place_id == first)
    from tripcore.scheduler import RELAXED_COMFORT
    for c in (1.0, RELAXED_COMFORT):
        n = schedule(t, keep_locked=True, comfort=c)
        assert any(it.place_id == first and d.index == before for d in n.plan.days for it in d.items)
