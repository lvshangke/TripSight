import json
from datetime import datetime

import pytest

from tripcore import mcp_server as s
from tripcore.amap import AmapError
from tripcore.gmaps import GoogleError, GoogleMapsClient, decode_polyline
from tripcore.region import is_mainland, pick_backend, trip_region


def _client(resp, calls=None, log=None):
    def opener(url, headers, body):
        if calls is not None:
            calls.append((url, headers, body))
        if isinstance(resp, Exception):
            raise resp
        return resp(url, body) if callable(resp) else resp
    return GoogleMapsClient("SECRETKEY", opener=opener, log_path=log)


PLACE = {"places": [{
    "id": "ChIJabc", "displayName": {"text": "东京塔"}, "formattedAddress": "日本东京",
    "location": {"latitude": 35.6586, "longitude": 139.7454}, "rating": 4.6,
    "priceRange": {"startPrice": {"currencyCode": "JPY", "units": "1000"}, "endPrice": {"currencyCode": "JPY", "units": "2000"}},
    "primaryTypeDisplayName": {"text": "观景台"},
    "regularOpeningHours": {"weekdayDescriptions": ["星期一: 09:00–17:00", "星期二: 休息", "星期三: 09:00–12:00、13:00–17:00",
                                                  "星期四: 24 小时营业", "星期五: 09:00–17:00", "星期六: 09:00–17:00", "星期日: 09:00–17:00"]},
}]}


def test_polyline_decode_reference_example():
    pts = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert pts == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def test_search_parses_place_and_sends_key_in_header_only():
    calls = []
    c = _client(PLACE, calls)
    h = c.search_places("东京塔", "东京")[0]
    assert (h.name, h.source, h.amap_id, h.rating, h.cost) == ("东京塔", "google", "ChIJabc", 4.6, 1500.0)
    assert "周一 09:00-17:00" in h.opentime_week and "周二 休息" in h.opentime_week
    assert "周三 09:00-12:00 13:00-17:00" in h.opentime_week and "周四 00:00-24:00" in h.opentime_week
    url, headers, body = calls[0]
    assert "SECRETKEY" not in url and headers["X-Goog-Api-Key"] == "SECRETKEY"
    assert "places.location" in headers["X-Goog-FieldMask"] and body["textQuery"] == "东京塔 东京"


def test_hours_parse_with_existing_parser():
    from tripcore.hours import hours_for_weekday
    h = _client(PLACE).search_places("x")[0]
    assert hours_for_weekday(h.opentime_week, 0) == "09:00-17:00"
    assert hours_for_weekday(h.opentime_week, 1) == "闭馆"


def test_search_around_nearby_vs_keyword():
    calls = []
    c = _client({"places": []}, calls)
    c.search_around(35.0, 139.0, 800)
    assert calls[0][0].endswith("places:searchNearby") and calls[0][2]["includedTypes"] == ["restaurant"]
    c.search_around(35.0, 139.0, 800, keywords="拉面")
    assert calls[1][0].endswith("places:searchText") and "locationBias" in calls[1][2]


def test_route_walk_and_transit_parse():
    enc = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    walk = {"routes": [{"duration": "600s", "distanceMeters": 800, "polyline": {"encodedPolyline": enc}}]}
    r = _client(walk).route("walk", 38.5, -120.2, 43.252, -126.453)
    assert (r.mode, r.minutes, r.distance_km) == ("walk", 10, 0.8) and len(r.path) >= 3

    transit = {"routes": [{"duration": "1800s", "distanceMeters": 9000, "polyline": {"encodedPolyline": enc}, "legs": [{"steps": [
        {"travelMode": "WALK", "distanceMeters": 300},
        {"travelMode": "TRANSIT", "transitDetails": {"transitLine": {"nameShort": "银座线", "vehicle": {"type": "SUBWAY"}},
                                                    "stopDetails": {"departureStop": {"name": "A"}, "arrivalStop": {"name": "B"}}}},
        {"travelMode": "TRANSIT", "transitDetails": {"transitLine": {"nameShort": "山手线", "vehicle": {"type": "HEAVY_RAIL"}},
                                                    "stopDetails": {"departureStop": {"name": "B"}, "arrivalStop": {"name": "C"}}}},
    ]}]}]}
    r = _client(transit).route("transit", 38.5, -120.2, 43.252, -126.453)
    assert r.transfers == 1 and r.uses_subway and r.walking_km == 0.3 and r.lines[0] == "银座线" and "B-C" in r.lines[1]


def test_transit_transfer_limit_warning_and_departure_time():
    calls = []
    two = {"routes": [{"duration": "1200s", "distanceMeters": 5000, "legs": [{"steps": [
        {"travelMode": "TRANSIT", "transitDetails": {"transitLine": {"nameShort": f"L{i}", "vehicle": {"type": "BUS"}}}} for i in range(3)]}]}]}
    r = _client(two, calls).route("transit", 35.0, 139.0, 35.1, 139.1, max_transfers=0, depart=datetime(2026, 11, 1, 9, 0))
    assert "超过你的上限" in r.warning
    assert calls[0][2]["departureTime"] == "2026-11-01T00:00:00Z"        # 东九区粗估时区


def test_errors_never_leak_key(tmp_path):
    log = tmp_path / "g.log"
    with pytest.raises(AmapError) as e:
        _client(RuntimeError("boom SECRETKEY"), log=log).search_places("x")
    assert "SECRETKEY" not in str(e.value)
    with pytest.raises(GoogleError):
        _client({"error": {"status": "PERMISSION_DENIED", "message": "API not enabled"}}, log=log).search_places("x")
    assert "SECRETKEY" not in log.read_text(encoding="utf-8") and "PERMISSION_DENIED" in log.read_text(encoding="utf-8")


def test_region_and_backend_choice():
    assert is_mainland(34.3, 108.9) and not is_mainland(35.68, 139.7)
    assert not is_mainland(22.3, 114.17) and not is_mainland(25.03, 121.56)     # 香港、台北
    assert pick_backend(None, "cn", True, True) == ("amap", "")
    assert pick_backend(None, "abroad", True, True) == ("google", "")
    b, note = pick_backend(None, "abroad", True, False)
    assert b == "amap" and "数据可能不全" in note
    assert pick_backend("google", "cn", True, False)[0] is None
    assert "不全" in pick_backend("google", "cn", True, True)[1]
    assert pick_backend(None, "cn", False, False) == (None, "")


def _abroad_trip():
    s.new_trip("东京", 1)
    s.add_place("东京塔", 35.6586, 139.7454)
    s.add_place("浅草寺", 35.7148, 139.7967)


def test_set_provider_and_backend_selection(monkeypatch):
    monkeypatch.setenv("AMAP_KEY", "a")
    monkeypatch.setenv("GOOGLE_MAPS_KEY", "g")
    _abroad_trip()
    assert trip_region(s._load()) == "abroad"
    assert s._amap().provider == "google"                       # 自动：境外用 Google
    s.set_provider("amap")
    assert getattr(s._amap(), "provider", "amap") == "amap" and "不全" in s._BACKEND["note"]
    s.set_provider("auto")
    assert s._amap().provider == "google"
    with pytest.raises(s.ToolError):
        s.set_provider("baidu")


def test_abroad_map_uses_osm_and_google_links():
    from tripcore.mapview import build_map_data, build_map_html, day_marker_links
    _abroad_trip()
    s.schedule_days()
    data = build_map_data(s._load())
    assert "openstreetmap" in data["tiles"]["url"]
    links = day_marker_links(s._load(), 0)
    assert links and all(l["url"].startswith("https://www.google.com/maps/") for l in links)
    legs = [e for d in data["days"] for e in d["timeline"] if e["type"] == "leg"]
    assert all(e["link"].startswith("https://www.google.com/maps/dir/") for e in legs)
    assert "tile.openstreetmap.org" in build_map_html(s._load())


def test_domestic_map_still_amap():
    from tripcore.mapview import build_map_data
    s.new_trip("西安", 1)
    s.add_place("大雁塔", 34.2186, 108.9648)
    s.schedule_days()
    d = build_map_data(s._load())
    assert "autonavi" in d["tiles"]["url"]


def test_weather_with_google_backend_uses_open_meteo_only(monkeypatch):
    class G:
        provider = "google"
        def adcode(self, *a):
            raise AssertionError("不应调用高德天气")
    monkeypatch.setattr(s, "_amap", lambda: G())
    _abroad_trip()
    s.schedule_days()
    out = s.get_weather()
    assert isinstance(out, str)
