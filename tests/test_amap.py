import pytest

from tripcore.amap import AmapClient, AmapError
from tripcore.coords import wgs84_to_gcj02


def client(responses: dict):
    """假网络层：按 URL 里的路径返回预设的 JSON，并记录请求。"""
    calls = []

    def opener(url: str) -> dict:
        calls.append(url)
        for path, data in responses.items():
            if path in url:
                return data
        raise AssertionError(f"unexpected url {url}")

    c = AmapClient("TESTKEY", opener=opener)
    c.calls = calls
    return c


def _gcj_loc(lat, lon):
    g_lat, g_lon = wgs84_to_gcj02(lat, lon)
    return f"{g_lon},{g_lat}"


def test_requires_key():
    with pytest.raises(AmapError):
        AmapClient("")


def test_search_places_parses_and_converts_back_to_wgs84():
    c = client({"/v5/place/text": {"status": "1", "pois": [
        {"name": "中央大街", "id": "B1", "location": _gcj_loc(45.7670, 126.6142), "address": "道里区", "adname": "道里区",
         "type": "风景名胜", "business": {"rating": "4.7", "cost": "0", "opentime_today": "全天", "tel": []}},
        {"name": "坏数据", "location": "", "business": {}},
    ]}})
    hits = c.search_places("中央大街", "哈尔滨")
    assert len(hits) == 1
    h = hits[0]
    assert (h.lat, h.lon) == pytest.approx((45.7670, 126.6142), abs=1e-5)
    assert h.rating == 4.7 and h.cost == 0 and h.tel == ""
    url = c.calls[0]
    assert "city_limit=true" in url and "show_fields=business" in url


def test_api_error_never_leaks_key():
    c = client({"/v5/place/text": {"status": "0", "info": "INVALID_USER_KEY"}})
    with pytest.raises(AmapError) as e:
        c.search_places("x")
    assert "TESTKEY" not in str(e.value)

    def boom(url):
        raise OSError(url)

    with pytest.raises(AmapError) as e2:
        AmapClient("TESTKEY", opener=boom)._get("/x", {})
    assert "TESTKEY" not in str(e2.value)


def test_routes():
    c = client({
        "/v3/direction/walking": {"status": "1", "route": {"paths": [{"distance": "1200", "duration": "900"}]}},
        "/v3/direction/driving": {"status": "1", "route": {"paths": [{"distance": "8000", "duration": "1260"}]}},
        "/v3/direction/transit/integrated": {"status": "1", "route": {"distance": "9000", "transits": [
            {"duration": "1800", "distance": "9500"}]}},
    })
    w = c.route("walk", 45.77, 126.61, 45.78, 126.62)
    assert (w.mode, w.distance_km, w.minutes) == ("walk", 1.2, 15)
    d = c.route("drive", 45.77, 126.61, 45.80, 126.70)
    assert (d.distance_km, d.minutes) == (8.0, 21)
    t = c.route("transit", 45.77, 126.61, 45.80, 126.70, "哈尔滨")
    assert (t.distance_km, t.minutes) == (9.5, 30)
    with pytest.raises(AmapError):
        c.route("transit", 45.77, 126.61, 45.80, 126.70)          # 缺城市
    with pytest.raises(AmapError):
        c.route("fly", 0, 0, 0, 0)


def test_empty_route_raises():
    c = client({"/v3/direction/walking": {"status": "1", "route": {"paths": []}}})
    with pytest.raises(AmapError):
        c.route("walk", 45.77, 126.61, 45.78, 126.62)


def test_geocode():
    c = client({"/v3/geocode/geo": {"status": "1", "geocodes": [{"location": _gcj_loc(45.7576, 126.6424)}]}})
    assert c.geocode("哈尔滨") == pytest.approx((45.7576, 126.6424), abs=1e-5)
    c2 = client({"/v3/geocode/geo": {"status": "1", "geocodes": []}})
    assert c2.geocode("不存在") is None
