"""随机压力测试：用固定种子生成各种景点分布，检查“不变式”始终成立。"""

import random

import pytest

from tripcore.metrics import PACE_LIMITS
from tripcore.models import Pace
from tripcore.scheduler import build_plan

from .conftest import make_place, make_trip


@pytest.mark.parametrize("seed", range(40))
def test_invariants_hold_on_random_trips(seed):
    rnd = random.Random(seed)
    n_places = rnd.randint(0, 25)
    n_days = rnd.randint(1, 7)
    pace = rnd.choice(list(Pace))
    places = [
        make_place(
            f"p{i}",
            lat=39.8 + rnd.random() * 0.4,
            lon=116.2 + rnd.random() * 0.5,
            duration_min=rnd.choice([30, 60, 90, 120, 180, 240, 300]),
            priority=rnd.randint(1, 5),
            must_go=rnd.random() < 0.15,
        )
        for i in range(n_places)
    ]
    t = make_trip(places, num_days=n_days, pace=pace)
    plan = build_plan(t)
    limits = PACE_LIMITS[pace]

    assert len(plan.days) == n_days
    placed = [it.place_id for d in plan.days for it in d.items]
    unscheduled = [u.place_id for u in plan.unscheduled]
    # 不重复、不遗漏
    assert len(placed) == len(set(placed))
    assert set(placed) | set(unscheduled) == {p.id for p in places}
    assert not (set(placed) & set(unscheduled))

    for d in plan.days:
        members = [t.place(it.place_id) for it in d.items]
        must = [p for p in members if p.must_go]
        # 只有“必去景点放不下被迫塞入”时才允许超限
        if not must and len(members) > 1:
            assert len(members) <= limits.max_places
            assert sum(p.duration_min for p in members) <= limits.max_total_minutes  # 游览本身必须在总时间内（再加路上时间由调度器保证）


def test_repeat_is_deterministic_on_random_input():
    rnd = random.Random(7)
    places = [make_place(f"p{i}", lat=39.8 + rnd.random() * 0.4, lon=116.2 + rnd.random() * 0.5) for i in range(15)]
    t = make_trip(places, num_days=4)
    a = [[it.place_id for it in d.items] for d in build_plan(t).days]
    b = [[it.place_id for it in d.items] for d in build_plan(t).days]
    assert a == b
