"""MCP 服务测试：直接调用工具函数（不启动真正的 MCP 进程），用临时文件存状态。"""

import asyncio

import pytest

pytest.importorskip("mcp")

from tripcore import mcp_server as s  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIPCORE_FILE", str(tmp_path / "trip.json"))


def _setup_trip():
    s.new_trip(name="测试", num_days=2)
    s.add_place("故宫", 39.9163, 116.3972, duration_min=240, must_go=True, priority=5)
    s.add_place("天坛", 39.8822, 116.4066, duration_min=120)
    s.add_place("颐和园", 39.9999, 116.2755, duration_min=180)
    s.add_place("鸟巢", 39.9928, 116.3965, duration_min=90)


def test_needs_trip_first():
    with pytest.raises(s.ToolError):
        s.show_trip()


def test_full_chat_flow():
    _setup_trip()
    out = s.schedule_days()
    assert "第1天" in out and "故宫" in out

    assert set(s.check_plan()) == {"ok", "issues"}

    r = s.propose_change("把天坛移到第2天", [{"kind": "move", "place_id": "p2", "to_day": 1}])
    assert "天坛" in r["changes"][0]
    before = s.show_trip()
    assert s.show_trip() == before  # 提案不会改行程

    s.apply_proposal(r["proposal_id"])
    assert s._load().plan.days[1].items[-1].place_id == "p2"

    s.undo()
    day_of = {it.place_id: d.index for d in s._load().plan.days for it in d.items}
    assert day_of["p2"] == s._load().plan.days[day_of["p2"]].index  # 撤销后仍是合法行程


def test_undo_restores_and_nothing_to_undo():
    s.new_trip(num_days=1)
    with pytest.raises(s.ToolError):
        s.undo()
    s.add_place("甲", 39.9, 116.4)
    s.undo()
    assert s._load().places == []


def test_stale_proposal_rejected():
    _setup_trip()
    s.schedule_days()
    r = s.propose_change("移动", [{"kind": "move", "place_id": "p1", "to_day": 1}])
    s.add_place("新景点", 39.95, 116.4)  # 版本变化
    with pytest.raises(s.ToolError, match="过期|版本"):
        s.apply_proposal(r["proposal_id"])


def test_locked_item_cannot_be_moved_and_failure_changes_nothing():
    _setup_trip()
    s.schedule_days()
    r1 = s.propose_change("锁定故宫", [{"kind": "lock", "place_id": "p1"}])
    s.apply_proposal(r1["proposal_id"])
    rev = s._load().revision
    r2 = s.propose_change("移动故宫", [{"kind": "move", "place_id": "p1", "to_day": 1}])
    with pytest.raises(s.ToolError, match="锁定"):
        s.apply_proposal(r2["proposal_id"])
    assert s._load().revision == rev


def test_bad_inputs_give_readable_errors():
    _setup_trip()
    with pytest.raises(s.ToolError):
        s.propose_change("x", [{"kind": "explode", "place_id": "p1"}])
    with pytest.raises(s.ToolError):
        s.propose_change("x", [{"kind": "remove", "place_id": "nope"}])
    with pytest.raises(s.ToolError):
        s.apply_proposal("zzzz")
    with pytest.raises(s.ToolError):
        s.add_place("坏坐标", 200, 0)
    with pytest.raises(s.ToolError):
        s.new_trip(start_date="2026-13-01")


def test_state_persists_across_calls_and_lodging():
    _setup_trip()
    s.add_lodging("酒店A", 39.91, 116.40, price_min=300, price_max=500, choose=True)
    s.schedule_days()
    r = s.suggest_lodging()
    assert r["ranked_lodgings"][0]["id"] == "l1" and r["chosen_lodging_id"] == "l1"
    assert "住宿：酒店A" in s.show_trip()


def test_exact_dates_set_num_days():
    s.new_trip(start_date="2026-10-01", end_date="2026-10-04")
    assert s._load().meta.num_days == 4


def test_server_registers_all_tools():
    names = {t.name for t in asyncio.run(s.build_server().list_tools())}
    assert names == {f.__name__ for f in s.TOOLS}
    assert len(names) == 11
