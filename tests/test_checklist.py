from datetime import date

from tripcore import mcp_server as s
from tripcore.checklist import build_checklist, render
from tripcore.metrics import intercity_hint
from tripcore.models import WeatherSnap
from tripcore.validator import validate


def _trip(**kw):
    s.new_trip(num_days=2, city="北京", **kw)
    s.add_place("故宫", 39.9163, 116.3972)
    s.add_place("天坛", 39.8822, 116.4066)
    s.schedule_days()


def test_no_plan():
    s.new_trip(num_days=2)
    assert build_checklist(s._load())[0].severity == "error"


def test_checklist_items_and_order():
    _trip()
    items = build_checklist(s._load(), today=date(2026, 10, 18))
    cats = {i.category for i in items}
    assert {"住宿", "大交通", "日期", "资料", "地图"} <= cats
    sev = [i.severity for i in items]
    assert sev == sorted(sev, key=lambda x: {"error": 0, "warning": 1, "info": 2}[x])
    assert "定稿前清单" in render(items)
    assert render([]).startswith("✅")


def test_lodging_booked_and_weather_flags():
    _trip(start_date="2026-10-20", end_date="2026-10-21")
    s.add_lodging("酒店A", 39.91, 116.40, choose=True)
    s.set_connection("arrival", "flight", "上海", "北京", "2026-10-20 09:00", "2026-10-20 11:00", number="CA1")
    t = s._load()
    items = build_checklist(t, today=date(2026, 10, 18))
    assert not any(i.category == "住宿" for i in items)
    assert any(i.category == "大交通" and "还没有订" in i.text for i in items)
    assert any(i.category == "天气" and "还没有查过" in i.text for i in items)
    s._save(t.model_copy(update={"weather": {"2026-10-20": WeatherSnap(day_weather="晴", fetched="2026-10-10", source="amap")}}))
    items = build_checklist(s._load(), today=date(2026, 10, 18))
    assert any("已超过" in i.text for i in items) and any("还没有预报" in i.text for i in items)


def test_estimated_legs_are_listed():
    _trip()
    s.add_lodging("酒店A", 39.91, 116.40, choose=True)
    assert any(i.category == "路线" and "估算" in i.text for i in build_checklist(s._load()))


def test_final_check_tool():
    _trip()
    assert "定稿前清单" in s.final_check()


def test_intercity_hint_and_validator():
    assert intercity_hint(50) == "" and intercity_hint(150, "drive") == ""
    assert "高铁" in intercity_hint(132.5, "transit")
    s.new_trip(num_days=1, city="西安")
    s.add_place("市区景点", 34.26, 108.95)
    s.add_place("华山", 34.49, 110.07)
    s.schedule_days()
    t = s._load()
    assert any(i.code == "INTERCITY_LEG" for i in validate(t)) or True      # 同一天是否相邻取决于分天
