import pytest

from tripcore.coords import gcj02_to_wgs84, out_of_china, wgs84_to_gcj02
from tripcore.geo import haversine_km


def test_known_offset_in_beijing():
    lat, lon = wgs84_to_gcj02(39.9087, 116.3975)        # 天安门附近
    assert lat - 39.9087 == pytest.approx(0.0014, abs=0.0006)
    assert lon - 116.3975 == pytest.approx(0.0062, abs=0.001)
    assert 400 < haversine_km(39.9087, 116.3975, lat, lon) * 1000 < 900   # 偏移几百米


@pytest.mark.parametrize("lat,lon", [(39.9087, 116.3975), (45.7576, 126.6424), (34.3416, 108.9398), (22.5431, 114.0579)])
def test_roundtrip_is_sub_meter(lat, lon):
    back = gcj02_to_wgs84(*wgs84_to_gcj02(lat, lon))
    assert haversine_km(lat, lon, *back) * 1000 < 1.0


def test_outside_china_unchanged():
    assert out_of_china(35.68, 139.69)                       # 东京
    assert wgs84_to_gcj02(35.68, 139.69) == (35.68, 139.69)
    assert gcj02_to_wgs84(48.85, 2.35) == (48.85, 2.35)
