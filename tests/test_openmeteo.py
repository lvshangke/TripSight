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
    s.add_place("乙", 39.99, 116.3)
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
