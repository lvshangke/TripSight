"""出发前复查：天气/营业时间变化；只读；第一次只建立基线。"""

from datetime import date, timedelta

import pytest

pytest.importorskip("mcp")

from tripcore import mcp_server as s  # noqa: E402
from tripcore.models import WeatherSnap  # noqa: E402


def _trip(days_ahead=3):
    d = (date.today() + timedelta(days=days_ahead)).isoformat()
    s.new_trip(num_days=1, mode="transit", city="北京")
    s.set_dates(d, d)
    s.add_place("故宫", 39.9163, 116.3972, duration_min=120, outdoor=True)
    s.schedule_days()
    return d


def _set_weather(d, weather, temp):
    t = s._load()
    snap = WeatherSnap(day_weather=weather, day_temp=temp, fetched=date.today().isoformat(), source="open-meteo")
    s._save(t.model_copy(update={"weather": {**t.weather, d: snap}}))


def test_first_run_is_baseline_not_change(monkeypatch):
    d = _trip()
    monkeypatch.setattr(s, "get_weather", lambda: _set_weather(d, "小雨", 20) or "ok")
    r = s.check_trip_changes()
    assert r["weather_changes"] == [] and r["baseline_days"] == 1


def test_new_rain_and_temperature_drop_reported_with_outdoor_places(monkeypatch):
    d = _trip()
    _set_weather(d, "晴", 28)
    monkeypatch.setattr(s, "get_weather", lambda: _set_weather(d, "中雨", 20) or "ok")
    r = s.check_trip_changes()
    ch = r["weather_changes"][0]
    assert ch["day"] == 1 and any("雨" in c for c in ch["changes"]) and any("气温" in c for c in ch["changes"])
    assert ch["outdoor_places"] == ["故宫"]


def test_minor_change_not_reported_and_trip_untouched(monkeypatch):
    d = _trip()
    _set_weather(d, "晴", 28)
    before = s._load().revision
    monkeypatch.setattr(s, "get_weather", lambda: _set_weather(d, "多云", 26) or "ok")
    assert s.check_trip_changes()["weather_changes"] == []
    assert s._load().revision == before


def test_hours_change_reported_but_not_applied(monkeypatch):
    _trip()
    t = s._load()
    p = t.places[0]
    s._save(t.model_copy(update={"places": [p.model_copy(update={"opening_hours": "08:30-17:00", "hours_source": "amap"})]}))
    monkeypatch.setattr(s, "get_weather", lambda: "ok")
    monkeypatch.setattr(s, "_amap", lambda: object())
    monkeypatch.setattr(s, "_amap_hours_lookup", lambda client, city, place: "08:30-16:30")
    r = s.check_trip_changes()
    assert r["hours_changes"][0]["new"] == "08:30-16:30"
    assert s._load().places[0].opening_hours == "08:30-17:00"          # 只读，不自动改


def test_no_key_still_checks_weather(monkeypatch):
    _trip()
    monkeypatch.setattr(s, "get_weather", lambda: "ok")
    monkeypatch.setattr(s, "_amap", lambda: None)
    r = s.check_trip_changes()
    assert r["hours_changes"] == [] and "营业时间没有复查" in r["notes"][0]
