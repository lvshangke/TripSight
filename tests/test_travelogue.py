"""游记草稿：事实骨架只含用户记录的内容，检查能抓到编造的金额/时间/没去的景点。"""

import pytest

pytest.importorskip("mcp")

from tripcore import mcp_server as s  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIPCORE_FILE", str(tmp_path / "trip.json"))


def _trip():
    s.new_trip(name="游记测试", num_days=2, start_date="2026-10-01", end_date="2026-10-02")
    s.add_place("故宫", 39.9163, 116.3972, duration_min=240, must_go=True, priority=5, ticket_price=60)
    s.add_place("天坛", 39.8822, 116.4066, duration_min=120, ticket_price=34)
    s.add_place("颐和园", 39.9999, 116.2755, duration_min=180)
    s.add_lodging("秘密酒店XYZ", 39.91, 116.40, price_min=300, price_max=500, choose=True)
    s.schedule_days()
    s.record_review("故宫", "去了", 5, "人很多，排队40分钟")
    s.record_review("天坛", "没去")
    s.record_actual_cost("门票", 94)


def test_facts_only_from_plan_and_user_records():
    _trip()
    f = s.draft_travelogue()
    stops = {x["name"]: x for d in f["days"] for x in d["stops"]}
    assert stops["故宫"]["status"] == "去了" and stops["故宫"]["rating"] == 5 and "排队" in stops["故宫"]["note"]
    assert stops["天坛"]["status"] == "没去" and stops["颐和园"]["status"] == "未记录"
    assert f["unrecorded"] == ["颐和园"] and f["skipped"] == ["天坛"]
    assert "不是实际" in stops["故宫"]["planned_time"]
    assert "actual_costs" not in f and "lodging" not in f          # 默认不含花费和酒店
    assert "ticket_price_ref" not in stops["故宫"]


def test_options_add_costs_and_lodging():
    _trip()
    f = s.draft_travelogue(show_lodging=True, show_costs=True)
    assert f["actual_costs"] == {"门票": 94.0} and f["lodging"] == "秘密酒店XYZ"


def test_intro_from_other_guides_is_not_in_facts():
    _trip()
    assert "intro" not in str(s.draft_travelogue())


def test_check_flags_unrecorded_skipped_amounts_times_and_hotel():
    _trip()
    r = s.check_travelogue("在天坛逛了一圈，颐和园很美，门票花了120元，早上8:30到的，住在秘密酒店XYZ")
    text = "\n".join(r["problems"])
    assert "天坛" in text and "颐和园" in text and "120" in text and "8:30" in text and "秘密酒店XYZ" in text


def test_check_passes_for_recorded_facts():
    _trip()
    r = s.check_travelogue("故宫人很多，排队40分钟，值得。")
    assert r["problems"] == []


def test_check_costs_allowed_only_when_public():
    _trip()
    assert s.check_travelogue("门票一共94元")["problems"]
    assert s.check_travelogue("门票一共94元", show_costs=True)["problems"] == []


def test_guard_blocks_paths_and_needs_plan():
    _trip()
    with pytest.raises(s.ToolError):
        s.check_travelogue("存在 /Users/foo/x 里")
    s.new_trip(name="空", num_days=1)
    with pytest.raises(s.ToolError):
        s.draft_travelogue()
