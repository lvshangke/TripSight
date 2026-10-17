from tripcore import mcp_server as s
from tripcore.models import Place
from tripcore.validator import validate
from tripcore.weather import bad_weather, is_outdoor, outdoor_from_category

from .test_mcp_server import WeatherAmap  # noqa: F401


def _p(**kw):
    return Place(id="p1", name="x", lat=1, lon=1, **kw)


def test_outdoor_classification():
    assert outdoor_from_category("科教文化服务;博物馆") is False
    assert outdoor_from_category("风景名胜;公园广场") is True
    assert outdoor_from_category("") is None and outdoor_from_category("餐饮服务") is None
    assert is_outdoor(_p()) is None
    assert is_outdoor(_p(category="风景名胜;公园广场")) is True
    assert is_outdoor(_p(category="风景名胜;公园广场", outdoor=False)) is False


def test_bad_weather():
    assert bad_weather("小雨", "多云", 20) == ["有雨雪"]
    assert bad_weather("晴", "晴", 36) == ["高温"]
    assert bad_weather("晴", "多云", 25) == []


def test_weather_stored_and_flags_outdoor(monkeypatch):
    s.new_trip(start_date="2026-10-18", end_date="2026-10-19", city="西安")
    s.add_place("公园", 39.9, 116.4, category="风景名胜;公园广场")
    s.add_place("博物馆", 39.9001, 116.4001, category="科教文化服务;博物馆")
    s.add_place("不明", 39.9002, 116.4002)
    s.schedule_days()
    rev = s._load().revision
    monkeypatch.setattr(s, "_amap", lambda: WeatherAmap(["2026-10-18", "2026-10-19"]))
    s.get_weather()
    t = s._load()
    assert t.revision == rev and "2026-10-18" in t.weather and t.weather["2026-10-18"].fetched
    msgs = [i for i in validate(t) if i.code == "WEATHER_OUTDOOR"]
    names = {t.place(i.place_id).name for i in msgs}
    assert names == {"公园"}
    assert "🌤" in s.show_trip()


def test_update_place_category():
    s.new_trip(num_days=1, city="西安")
    s.add_place("甲", 39.9, 116.4)
    s.update_place("p1", outdoor=True)
    assert s._load().place("p1").outdoor is True
