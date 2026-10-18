import pytest

from tripcore import mcp_server as s
from tripcore import review as rv


def _trip_with_places(n=4):
    s.new_trip("回顾测试", 2)
    for i in range(n):
        s.add_place(f"景点{i}", 34.0 + i * 0.01, 108.9 + i * 0.01)


def test_cost_accumulates_and_validates():
    d = rv.empty()
    rv.record_cost(d, "餐饮", 80, "")
    assert rv.record_cost(d, "food", 20.5, "夜宵") == 100.5
    with pytest.raises(ValueError):
        rv.record_cost(d, "娱乐", 10, "")
    with pytest.raises(ValueError):
        rv.record_cost(d, "门票", -1, "")


def test_record_place_validation():
    d = rv.empty()
    rv.record_place(d, "a", "没去", 3, "排队")
    assert d["places"]["a"]["status"] == "skipped"
    with pytest.raises(ValueError):
        rv.record_place(d, "a", "也许", None, "")
    with pytest.raises(ValueError):
        rv.record_place(d, "a", "去了", 9, "")


def test_pace_suggestion_when_many_skipped():
    d = rv.empty()
    ids = ["a", "b", "c", "d"]
    for i in ids[:2]:
        rv.record_place(d, i, "没去", None, "")
    for i in ids[2:]:
        rv.record_place(d, i, "去了", None, "")
    sug = rv.suggestions(d, ids, 0, 0)
    assert sug and sug[0]["value"] == {"pace": "relaxed"}


def test_tired_and_lodging_suggestions_and_no_false_positive():
    d = rv.empty()
    ids = ["a", "b", "c"]
    rv.record_place(d, "a", "去了", None, "走得累")
    rv.record_place(d, "b", "去了", None, "太远")
    rv.record_place(d, "c", "去了", None, "不累")
    rv.record_cost(d, "住宿", 300, "")
    vals = [x["value"] for x in rv.suggestions(d, ids, 600, 2)]
    assert {"walk_max_min": 15} in vals and {"lodging_budget_max": 150} in vals
    d2 = rv.empty()
    rv.record_place(d2, "a", "去了", None, "不累")
    assert rv.suggestions(d2, ["a"], 0, 0) == []


def test_unrecorded_shown_and_no_invented_numbers():
    d = rv.empty()
    out = rv.report(d, {"a": "大雁塔"}, ["a"], {"tickets": 50.0}, 0)
    assert "大雁塔：未记录" in out and "门票：计划 50，实际 未记录" in out and "餐饮：未记录" in out


def test_tools_end_to_end_and_per_trip_isolation(monkeypatch, tmp_path):
    monkeypatch.delenv("TRIPCORE_FILE", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _trip_with_places(2)
    s.record_review("景点0", "去了", 5, "好看")
    s.record_actual_cost("餐饮", 120)
    out = s.show_review()
    assert "景点0" in out and "好看" in out and "120" in out
    with pytest.raises(s.ToolError):
        s.record_review("不存在", "去了")
    s.new_trip("另一个", 2)          # 新行程的回顾是空的
    assert "好看" not in s.show_review()
