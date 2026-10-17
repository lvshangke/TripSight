import pytest

from tripcore import mcp_server as s
from tripcore.amap import WeatherDay
from tripcore.openmeteo import OpenMeteoClient, WeatherError, parse, wmo_text
from tripcore.validator import validate

from .test_mcp_server import WeatherAmap


class FakeOM:
    def __init__(self, days):
        self.days = days
        self.called_with = None

    def forecast(self, lat, lon, days=16):
        self.called_with = (lat, lon)
        return [WeatherDay(d, "1", txt, "", t, 8) for d, txt, t in self.days]


def test_parse_and_wmo():
    data = {"daily": {"time": ["2026-10-18", "2026-10-19"], "weather_code": [0, 63],
                      "temperature_2m_max": [20.1, 15], "temperature_2m_min": [10, 9]}}
    d = parse(data)
    assert d[0].day_weather == "晴" and d[1].day_weather == "中雨" and d[1].day_temp == 15 and d[1].night_temp == 9
    assert wmo_text(95) == "雷阵雨" and wmo_text(None) == "" and wmo_text(12345) == ""


def test_client_wraps_network_errors(monkeypatch):
    import urllib.request

    def boom(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(WeatherError):
        OpenMeteoClient().forecast(35.0, 139.0)


def _trip(start="2026-10-18", end="2026-10-19"):
    s.new_trip(start_date=start, end_date=end, city="西安")
    s.add_place("公园", 39.9, 116.4, category="风景名胜;公园广场")
    s.add_place("乙", 39.905, 116.405)
    s.schedule_days()


def test_falls_back_to_open_meteo_for_dates_amap_lacks(monkeypatch):
    _trip()
    om = FakeOM([("2026-10-18", "晴", 20), ("2026-10-19", "大雨", 18)])
    monkeypatch.setattr(s, "_amap", lambda: WeatherAmap(["2026-10-18"]))   # 高德只有第一天（小雨）
    monkeypatch.setattr(s, "_openmeteo", lambda: om)
    out = s.get_weather()
    t = s._load()
    assert t.weather["2026-10-18"].source == "amap" and t.weather["2026-10-18"].day_weather == "小雨"
    assert t.weather["2026-10-19"].source == "open-meteo" and "大雨" in t.weather["2026-10-19"].day_weather
    assert "Open-Meteo预报" in out and "高德预报" in out
    assert om.called_with is not None
    assert any(i.code == "WEATHER_OUTDOOR" for i in validate(t))
    assert "Open-Meteo" in s.show_trip()


def test_foreign_destination_without_amap(monkeypatch):
    _trip()
    monkeypatch.setattr(s, "_amap", lambda: None)
    monkeypatch.setattr(s, "_openmeteo", lambda: FakeOM([("2026-10-18", "晴", 22), ("2026-10-19", "多云", 21)]))
    out = s.get_weather()
    assert "晴" in out and "没有配置高德 key" in out
    assert s._load().weather["2026-10-18"].source == "open-meteo"


def test_open_meteo_failure_is_reported_not_fatal(monkeypatch):
    _trip()

    class Bad:
        def forecast(self, *a, **k):
            raise WeatherError("Open-Meteo 查询失败：OSError")
    monkeypatch.setattr(s, "_amap", lambda: WeatherAmap(["2026-10-18"]))
    monkeypatch.setattr(s, "_openmeteo", lambda: Bad())
    out = s.get_weather()
    assert "小雨" in out and "暂无预报" in out and "Open-Meteo 查询失败" in out


def test_no_source_at_all_errors(monkeypatch):
    _trip()
    monkeypatch.setattr(s, "_amap", lambda: None)
    with pytest.raises(s.ToolError):
        s.get_weather()


class SpotOM:
    """按坐标返回不同天气：近的点晴，远的点（山上）下雨。"""

    def __init__(self):
        self.calls = []

    def forecast(self, lat, lon, days=16):
        self.calls.append((round(lat, 2), round(lon, 2)))
        rainy = lat > 35
        return [WeatherDay(d, "1", "小雨" if rainy else "晴", "", 5 if rainy else 20, 2) for d in ("2026-10-18", "2026-10-19")]


def test_multi_location_trip_queries_each_spot(monkeypatch):
    s.new_trip(start_date="2026-10-18", end_date="2026-10-19", city="西安")
    s.add_place("市区景点", 34.26, 108.95, category="风景名胜;公园广场")
    s.add_place("远处的山", 34.55, 110.08, category="风景名胜")      # 约 100 km 外
    s.schedule_days()
    om = SpotOM()
    monkeypatch.setattr(s, "_amap", lambda: WeatherAmap(["2026-10-18", "2026-10-19"]))   # 高德有，但多地点时不能用它
    monkeypatch.setattr(s, "_openmeteo", lambda: om)
    s.get_weather()
    t = s._load()
    assert len(set(om.calls)) == 2                              # 两个位置各查一次
    assert all(w.source == "open-meteo" and w.location for w in t.weather.values())
    assert {w.location for w in t.weather.values()} == {"市区景点", "远处的山"}
    assert "「远处的山」一带" in s.show_trip()


def test_multi_location_falls_back_to_amap_with_note(monkeypatch):
    s.new_trip(start_date="2026-10-18", end_date="2026-10-19", city="西安")
    s.add_place("甲", 34.26, 108.95)
    s.add_place("乙", 34.55, 110.08)
    s.schedule_days()
    monkeypatch.setattr(s, "_amap", lambda: WeatherAmap(["2026-10-18", "2026-10-19"]))
    out = s.get_weather()                                       # Open-Meteo 被测试关闭
    assert "仅供参考" in out and s._load().weather["2026-10-18"].source == "amap"
