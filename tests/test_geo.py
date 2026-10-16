from tripcore.geo import estimate_leg, haversine_km


def test_haversine_known_distance():
    # 天安门广场 -> 故宫，直线约 0.8 km
    d = haversine_km(39.9087, 116.3975, 39.9163, 116.3972)
    assert 0.7 < d < 1.0


def test_haversine_zero_and_symmetric():
    assert haversine_km(10, 10, 10, 10) == 0
    a = haversine_km(39.9, 116.4, 40.0, 116.3)
    b = haversine_km(40.0, 116.3, 39.9, 116.4)
    assert abs(a - b) < 1e-9


def test_short_distance_walks_even_if_transit_preferred():
    leg = estimate_leg("a", 39.9087, 116.3975, "b", 39.9163, 116.3972, "transit")
    assert leg.mode == "walk"
    assert leg.detail_level == "estimate"


def test_longer_distance_uses_preferred_mode():
    leg = estimate_leg("a", 39.90, 116.40, "b", 40.00, 116.28, "transit")
    assert leg.mode == "transit"
    assert leg.minutes > 20


def test_minutes_increase_with_distance():
    near = estimate_leg("a", 39.90, 116.40, "b", 39.95, 116.40, "transit").minutes
    far = estimate_leg("a", 39.90, 116.40, "b", 40.20, 116.40, "transit").minutes
    assert far > near


def test_same_point_zero_minutes():
    assert estimate_leg("a", 39.9, 116.4, "b", 39.9, 116.4, "drive").minutes == 0
