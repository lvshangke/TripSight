from datetime import date

from tripcore.mapview import hours_line

ZL = ("1月至3月 周一至周日 08:30-18:00 最晚进入17:30 04-01至09-24 周一至周日 08:30-21:30 最晚进入21:00；"
      "10-08至10-10 周一至周日 08:30-21:30 最晚进入21:00；10-11至12-31 周一至周日 08:30-18:00 最晚进入17:30")


def test_dated_shows_only_that_day():
    s = hours_line(ZL, "amap", date(2026, 10, 25))
    assert s == "营业时间：08:30–18:00，最晚进入 17:30（来源：amap）"
    assert "04-01" not in s and "10-08" not in s


def test_closed_day():
    assert "当天不开放" in hours_line("周一 闭馆；周二至周日 09:00-17:00", "amap", date(2026, 10, 26))


def test_undated_truncates_and_no_source_text_invented():
    s = hours_line(ZL, "amap", None)
    assert "…" in s and len(s) < 80
    assert hours_line("", "", date(2026, 10, 25)) == "营业时间：待核实"


def test_unparseable_falls_back_to_short_original():
    s = hours_line("请电话咨询", "user", date(2026, 10, 25))
    assert s == "营业时间：请电话咨询（来源：user）"


def test_meal_line_has_no_nested_parens():
    import re
    from tripcore.share import _re
    t = _re.sub("（来源：([^）]*)）", r" 来源：\1", "人均约 50 元（参考）；" + hours_line("09:00-17:00", "amap", None))
    assert "））" not in t and "来源：amap" in t
