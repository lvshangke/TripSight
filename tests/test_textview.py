import pytest

from tripcore import mcp_server as s
from tripcore.textview import guard_text


def _trip():
    s.new_trip(num_days=2, city="北京", name="北京行")
    s.add_place("故宫", 39.9163, 116.3972, duration_min=240, opening_hours="08:30-17:00", hours_source="user")
    s.add_place("天坛", 39.8822, 116.4066, duration_min=120)
    s.add_lodging("酒店A", 39.9100, 116.4000, choose=True)
    s.schedule_days()


def test_export_text_day_and_all():
    _trip()
    one = s.export_text(day=1)
    assert "【北京行】第1天" in one and "🏨" in one and "↓" in one
    assert "https://uri.amap.com/marker" in one and "amapuri" not in one
    both = s.export_text()
    assert "第1天" in both and "第2天" in both and "———" in both
    assert "uri.amap.com" not in s.export_text(day=1, links=False)


def test_export_text_errors():
    s.new_trip(num_days=1)
    with pytest.raises(s.ToolError):
        s.export_text()              # 还没分天
    _trip()
    with pytest.raises(s.ToolError):
        s.export_text(day=9)


def test_guard_blocks_key_and_paths(monkeypatch):
    assert guard_text("正常的行程文字 https://uri.amap.com/marker?position=1,2&name=a") == []
    assert guard_text("文件在 /Users/lv/Desktop/x") and guard_text("C:\\Users\\a\\b") and guard_text("~/.tripcore/trip.json")
    assert guard_text("https://x.com/?key=abcdefgh12345678")
    monkeypatch.setenv("AMAP_KEY", "MYSECRETKEY99")
    assert guard_text("带 MYSECRETKEY99 的文字")


def test_export_text_refuses_when_note_leaks_path():
    _trip()
    s.update_place("p1", name="故宫 /Users/lv/Desktop/secret")
    s.schedule_days()
    with pytest.raises(s.ToolError) as e:
        s.export_text(day=1)
    assert "外发检查" in str(e.value)


def test_text_includes_weather_and_reservation(monkeypatch):
    s.new_trip(start_date="2026-10-18", end_date="2026-10-19", city="北京", name="北京行")
    s.add_place("故宫", 39.9163, 116.3972, reservation_required=True)
    s.schedule_days()
    from tripcore.models import WeatherSnap
    t = s._load()
    s._save(t.model_copy(update={"weather": {"2026-10-18": WeatherSnap(day_weather="小雨", day_temp=12, fetched="2026-10-17", source="amap")}}))
    out = s.export_text(day=1)
    assert "🌤" in out and "小雨" in out and "需预约" in out


def test_export_map_share_writes_named_file_and_guards(tmp_path):
    _trip()
    r = s.export_map(share=True)
    assert "message" in r and "share" in r and "北京行.html" in r
    f = s.trip_path().with_name("share") / "北京行.html"
    assert f.exists() and "<script>" in f.read_text(encoding="utf-8")
    assert s.export_map().endswith("底图需要联网。") and s.trip_path().with_name("map.html").exists()
    s.update_place("p1", name="故宫 /Users/lv/x")
    s.schedule_days()
    with pytest.raises(s.ToolError):
        s.export_map(share=True)
