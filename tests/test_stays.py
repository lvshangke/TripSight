import pytest

from tripcore import mcp_server as s
from tripcore.metrics import day_stats, estimate_cost
from tripcore.models import Lodging, Stay, Trip
from tripcore.stays import suggest_segments
from tripcore.validator import validate

# 两个相距约 60 km 的区域（北京市区 / 北京远郊），各 3 个景点
AREA_A = [(39.90, 116.40), (39.91, 116.41), (39.92, 116.39)]
AREA_B = [(40.40, 116.00), (40.41, 116.01), (40.42, 115.99)]


def _trip(days=6):
    s.new_trip(num_days=days, city="北京")
    for i, (la, lo) in enumerate(AREA_A + AREA_B):
        s.add_place(f"景{i}", la, lo, duration_min=120)
    s.add_lodging("市区店", 39.905, 116.40, price_min=300, price_max=300, choose=True)
    s.add_lodging("远郊店", 40.405, 116.00, price_min=200, price_max=200)
    s.schedule_days()
    return s._load()


def test_lodging_for_day_defaults_and_stays():
    t = _trip()
    assert t.lodging_for_day(3).name == "市区店" and t.morning_lodging(3).name == "市区店"
    s.set_stays([{"lodging_id": "l1", "from_day": 1, "to_day": 3}, {"lodging_id": "l2", "from_day": 4, "to_day": 6}])
    t = s._load()
    assert t.lodging_for_day(2).name == "市区店" and t.lodging_for_day(3).name == "远郊店"
    assert t.morning_lodging(3).name == "市区店"      # 换酒店当天早上还在旧酒店
    assert t.morning_lodging(4).name == "远郊店"


def test_set_stays_validation():
    _trip()
    with pytest.raises(s.ToolError):
        s.set_stays([{"lodging_id": "l1", "from_day": 1, "to_day": 3}, {"lodging_id": "l2", "from_day": 3, "to_day": 5}])
    with pytest.raises(s.ToolError):
        s.set_stays([{"lodging_id": "l9", "from_day": 1, "to_day": 3}])
    with pytest.raises(s.ToolError):
        s.set_stays([{"lodging_id": "l1", "from_day": 1, "to_day": 9}])


def test_cost_uses_each_nights_hotel():
    _trip()
    base = estimate_cost(s._load())
    assert base.nights == 5 and base.lodging == 1500
    s.set_stays([{"lodging_id": "l1", "from_day": 1, "to_day": 3}, {"lodging_id": "l2", "from_day": 4, "to_day": 6}])
    c = estimate_cost(s._load())
    assert c.nights == 5 and c.lodging == 3 * 300 + 2 * 200


def test_routes_follow_each_days_hotel():
    t = _trip()
    s.set_stays([{"lodging_id": "l1", "from_day": 1, "to_day": 3}, {"lodging_id": "l2", "from_day": 4, "to_day": 6}])
    t = s._load()
    for day in t.plan.days:
        if not day.items:
            continue
        st = day_stats(t, day)
        near = t.lodging_for_day(day.index)
        assert st.lodging_back is not None and st.lodging_back.to_id == near.id


def test_hint_when_far_and_none_when_close():
    t = _trip()
    segs = suggest_segments(t)
    assert len(segs) == 2                       # 一家酒店守着两个相距很远的片区 → 建议分两段
    assert any(i.code == "STAY_SUGGESTION" for i in validate(t))
    assert "没有改动行程" in s.show_trip()
    s.set_stays([{"lodging_id": "l1", "from_day": 1, "to_day": 3}, {"lodging_id": "l2", "from_day": 4, "to_day": 6}])
    # 每段都已住在自己那一带 → 不再提示
    assert not any(i.code == "STAY_SUGGESTION" for i in validate(s._load()))


def test_no_hint_for_short_trip_or_compact_places():
    s.new_trip(num_days=3, city="北京")
    for i, (la, lo) in enumerate(AREA_A + AREA_B):
        s.add_place(f"景{i}", la, lo)
    s.schedule_days()
    assert suggest_segments(s._load()) == []
    s.new_trip(num_days=5, city="北京")
    for i, (la, lo) in enumerate(AREA_A * 2):
        s.add_place(f"景{i}", la + i * 0.0005, lo)
    s.schedule_days()
    assert suggest_segments(s._load()) == []


def test_clear_stays_and_map_gpx_render():
    _trip()
    s.set_stays([{"lodging_id": "l1", "from_day": 1, "to_day": 3}, {"lodging_id": "l2", "from_day": 4, "to_day": 6}])
    t = s._load()
    from tripcore.gpx import build_gpx
    from tripcore.mapview import build_map_data
    for i in range(6):
        if t.plan.days[i].items:
            build_gpx(t, i)
    assert build_map_data(t)["has_lodging"] is True
    s.clear_stays()
    assert s._load().stays == []
