"""离开日：先回早上的酒店取行李，再去车站；当晚（到站后）住的酒店在“离开”之后才出现。"""
from pathlib import Path

from tripcore.mapview import build_map_data
from tripcore.metrics import day_stats
from tripcore.models import Trip

FIX = Path(__file__).parent / "data" / "departure_night.json"


def _trip():
    return Trip.model_validate_json(FIX.read_text(encoding="utf-8"))


def test_night_hotel_after_departure():
    tl = build_map_data(_trip())["days"][-1]["timeline"]
    roles = [(e["type"], e.get("role")) for e in tl if e["type"] in ("hotel", "term")]
    assert roles[-2:] == [("term", "离开"), ("hotel", "入住")]
    assert not [e for e in tl if e["type"] == "hotel" and e["role"] == "返回"]     # 行李随身，不回酒店
    assert "汉庭" in tl[-1]["name"] and tl[-1]["time"] == "20:40"


def test_no_return_leg_on_departure_day():
    t = _trip()
    st = day_stats(t, t.plan.days[-1])
    assert st.lodging_back is None


def _with_weather():
    from tripcore.models import WeatherSnap
    t = _trip()
    return t.model_copy(update={"weather": {"2026-11-07": WeatherSnap(day_weather="多云", day_temp=24, fetched="2026-11-04")}})


def test_day_weather_in_map_data_and_calendar():
    from tripcore.export_notes import build_ics
    t = _with_weather()
    days = build_map_data(t)["days"]
    assert days[0]["weather"] == "多云 24°C" and days[1]["weather"] == ""
    assert "当天天气预报：多云 24°C" in build_ics(t).replace("\r\n ", "")


def test_day_route_map_is_per_day_and_excludes_night_hotel():
    from tripcore import share
    h = share.build_share_html(_trip(), show_lodging=True)
    assert h.count('class="dmap"') == 2 and "__dayInit" in h


def test_auto_weather_due_only_within_forecast_window():
    from datetime import date
    from tripcore import web
    t = _trip()                                     # 11-07 ~ 11-08
    assert web._wx_due(t, today=date(2026, 11, 4))              # 在 16 天内且没查过
    assert not web._wx_due(t, today=date(2026, 10, 1))          # 还太远：临近了才查
    assert not web._wx_due(t, today=date(2026, 12, 1))          # 已经过去
    from tripcore.models import WeatherSnap
    w = {k: WeatherSnap(day_weather="晴", day_temp=20, fetched="2026-11-04") for k in ("2026-11-07", "2026-11-08")}
    assert not web._wx_due(t.model_copy(update={"weather": w}), today=date(2026, 11, 4))    # 今天已查过
    assert web._wx_due(t.model_copy(update={"weather": w}), today=date(2026, 11, 5))        # 隔天刷新


def test_handbook_scripts_are_valid_js(tmp_path):
    """手册里内嵌的脚本曾少一个分号，整段脚本报错（照片点击放大、视频标签页都失效）。"""
    import re, shutil, subprocess
    from tripcore.handbook import JS
    node = shutil.which("node")
    if node is None:
        return
    code = "\n".join(re.findall(r"<script>(.*?)</script>", JS, re.S))
    f = tmp_path / "hb.js"
    f.write_text(code, encoding="utf-8")
    r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
