"""可分享行程成品：默认不公开酒店/花费/车次号，用户要求才带；输出自包含且通过外发检查。"""

import pytest

pytest.importorskip("mcp")

from tripcore import mcp_server as s  # noqa: E402
from tripcore import share  # noqa: E402

HOTEL = "秘密酒店XYZ"


@pytest.fixture(autouse=True)
def tmp_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIPCORE_FILE", str(tmp_path / "trip.json"))
    monkeypatch.setattr(share, "render_png", lambda *a, **k: "测试里不截图")


def _trip():
    s.new_trip(name="分享测试", num_days=2, start_date="2026-10-01", end_date="2026-10-02")
    s.add_place("故宫", 39.9163, 116.3972, duration_min=240, must_go=True, priority=5, ticket_price=60)
    s.add_place("天坛", 39.8822, 116.4066, duration_min=120, ticket_price=34)
    s.add_place("颐和园", 39.9999, 116.2755, duration_min=180)
    s.add_lodging(HOTEL, 39.91, 116.40, price_min=300, price_max=500, choose=True)
    s.schedule_days()


def _html():
    path = s.export_share().split("：", 1)[1].split("\n")[0]
    return open(path, encoding="utf-8").read()


def test_default_hides_lodging_and_costs():
    _trip()
    h = _html()
    assert HOTEL not in h and "门票" not in h and "¥" not in h
    assert "故宫" in h and "第 1 天" in h and "10/1" in h
    assert "http" in h and "key=" not in h.lower()


def test_hotel_legs_are_dropped_when_hidden_but_kept_when_shown():
    _trip()
    hidden = _html()
    path = s.export_share(show_lodging=True).split("：", 1)[1].split("\n")[0]
    shown = open(path, encoding="utf-8").read()
    assert HOTEL in shown and HOTEL not in hidden
    assert shown.count('class="leg"') > hidden.count('class="leg"')


def test_costs_option_shows_tickets_only_when_asked():
    _trip()
    path = s.export_share(show_costs=True).split("：", 1)[1].split("\n")[0]
    h = open(path, encoding="utf-8").read()
    assert "门票：60 元" in h and "¥" in h
    assert HOTEL not in h                               # 公开花费不等于公开酒店


def test_png_failure_does_not_break_html():
    _trip()
    out = s.export_share()
    assert "没有生成长图" in out and ".html" in out


def test_needs_plan_and_escapes_html():
    s.new_trip(name="<b>坏</b>名字", num_days=1)
    with pytest.raises(s.ToolError):
        s.export_share()
    s.add_place("<script>x</script>", 39.9, 116.4, duration_min=60)
    s.schedule_days()
    h = _html()
    assert "<script>x" not in h and "&lt;script&gt;" in h


def test_guard_blocks_local_paths(monkeypatch):
    _trip()
    t = s._load()
    s.add_place("/Users/foo/secret", 39.95, 116.35, duration_min=30)
    s.schedule_days()
    with pytest.raises(s.ToolError):
        s.export_share()


def test_all_themes_render_light_and_pass_guard():
    _trip()
    for name in share.theme_names():
        out = s.export_share(theme=name)
        html = open(out.split("：", 1)[1].split("\n")[0], encoding="utf-8").read()
        assert "prefers-color-scheme" not in html and not share.guard_html(html) and HOTEL not in html
        assert "<title>分享测试</title>" in html
    a = share.build_share_html(s._load(), theme="magazine")
    b = share.build_share_html(s._load(), theme="dopamine")
    assert a != b and "#ffd500" in b and "#f3f0e8" in a


def test_unknown_theme_is_refused_with_choices():
    _trip()
    with pytest.raises(Exception) as e:
        s.export_share(theme="neon")
    assert "magazine" in str(e.value) and "没有这个风格" in str(e.value)
