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

    s.apply_proposal(r["proposal_id"], r["confirm_code"])
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
        s.apply_proposal(r["proposal_id"], r["confirm_code"])


def test_locked_item_cannot_be_moved_and_failure_changes_nothing():
    _setup_trip()
    s.schedule_days()
    r1 = s.propose_change("锁定故宫", [{"kind": "lock", "place_id": "p1"}])
    s.apply_proposal(r1["proposal_id"], r1["confirm_code"])
    rev = s._load().revision
    r2 = s.propose_change("移动故宫", [{"kind": "move", "place_id": "p1", "to_day": 1}])
    with pytest.raises(s.ToolError, match="锁定"):
        s.apply_proposal(r2["proposal_id"], r2["confirm_code"])
    assert s._load().revision == rev


def test_bad_inputs_give_readable_errors():
    _setup_trip()
    with pytest.raises(s.ToolError):
        s.propose_change("x", [{"kind": "explode", "place_id": "p1"}])
    with pytest.raises(s.ToolError):
        s.propose_change("x", [{"kind": "remove", "place_id": "nope"}])
    with pytest.raises(s.ToolError):
        s.apply_proposal("zzzz", "0000")
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
    assert len(names) == 14


def test_wrong_confirm_code_is_rejected():
    _setup_trip()
    s.schedule_days()
    r = s.propose_change("移动", [{"kind": "move", "place_id": "p1", "to_day": 1}])
    wrong = "0000" if r["confirm_code"] != "0000" else "1111"
    rev = s._load().revision
    with pytest.raises(s.ToolError, match="确认码"):
        s.apply_proposal(r["proposal_id"], wrong)
    assert s._load().revision == rev
    s.apply_proposal(r["proposal_id"], r["confirm_code"])
    assert s._load().revision == rev + 1


def test_update_and_remove_place():
    _setup_trip()
    s.schedule_days()
    s.update_place("p2", ticket_price=35, duration_min=60)
    assert s._load().place("p2").ticket_price == 35
    with pytest.raises(s.ToolError):
        s.update_place("p2")
    with pytest.raises(s.ToolError):
        s.update_place("p2", duration_min=1)
    s.remove_place("p2")
    t = s._load()
    assert all(p.id != "p2" for p in t.places)
    assert all(it.place_id != "p2" for d in t.plan.days for it in d.items)
    s.undo()
    assert any(p.id == "p2" for p in s._load().places)


def test_unverified_place_is_marked_and_city_saved():
    s.new_trip(city="哈尔滨")
    s.add_place("甲", 45.77, 126.62)
    s.add_place("乙", 45.78, 126.63, verified=True)
    t = s._load()
    assert "待核实" in t.place("p1").notes and "待核实" not in t.place("p2").notes
    assert s._load_context()["city"] == "哈尔滨"


def test_lookup_warns_when_far_from_city(monkeypatch):
    s.new_trip(city="哈尔滨")

    def fake(q, city=None, **kw):
        return {"name": q, "lat": 45.8360, "lon": 128.8278, "display_name": "x"} if q == "中央大街" \
            else {"name": q, "lat": 45.7576, "lon": 126.6424, "display_name": "哈尔滨"}

    monkeypatch.setattr(s, "_geocode", fake)
    r = s.lookup_coords("中央大街")
    assert r["found"] and r["warning"] and r["distance_from_city_km"] > 60


# ---------------- 高德相关（全部用假客户端，不联网） ----------------
from tripcore.amap import AmapError, PlaceHit, RouteResult  # noqa: E402


class FakeAmap:
    def __init__(self, hits=None, fail_routes=False):
        self.hits, self.fail_routes, self.route_calls = hits or [], fail_routes, []

    def search_places(self, query, city=None, limit=5):
        return self.hits

    def route(self, mode, a_lat, a_lon, b_lat, b_lon, city=None):
        self.route_calls.append(mode)
        if self.fail_routes:
            raise AmapError("没有找到路线")
        return RouteResult(mode, 7.5, 33)


def test_lookup_uses_amap_candidates(monkeypatch):
    s.new_trip(city="西安")
    hit = PlaceHit(name="秦始皇帝陵博物院", lat=34.38, lon=109.27, address="临潼区", rating=4.8, cost=120)
    monkeypatch.setattr(s, "_amap", lambda: FakeAmap([hit]))
    r = s.lookup_coords("兵马俑")
    assert r["source"] == "amap" and r["candidates"][0]["cost_reference"] == 120 and r["lat"] == 34.38


def test_lookup_falls_back_to_osm_when_amap_fails(monkeypatch):
    s.new_trip(city="西安")

    class Broken:
        def search_places(self, *a, **k):
            raise AmapError("INVALID_USER_KEY")

    monkeypatch.setattr(s, "_amap", lambda: Broken())
    monkeypatch.setattr(s, "_geocode", lambda q, city=None, **k: {"name": q, "lat": 34.34, "lon": 108.94, "display_name": "x"})
    r = s.lookup_coords("大雁塔")
    assert r["found"] and r["source"] == "osm" and "高德不可用" in r["note"]


def test_refine_routes_needs_key(monkeypatch):
    _setup_trip()
    s.schedule_days()
    monkeypatch.setattr(s, "_amap", lambda: None)
    with pytest.raises(s.ToolError, match="AMAP_KEY"):
        s.refine_routes()


def test_refine_routes_caches_and_is_undoable(monkeypatch):
    _setup_trip()
    s.add_lodging("酒店A", 39.91, 116.40, choose=True)
    s.schedule_days()
    fake = FakeAmap()
    monkeypatch.setattr(s, "_amap", lambda: fake)
    out = s.refine_routes()
    assert "高德真实路线" in out and "高德路线" in out
    t = s._load()
    assert t.route_overrides and all(l.detail_level == "route" for l in t.route_overrides.values())
    first_calls = len(fake.route_calls)
    s.refine_routes()                      # 第二次：全部命中缓存，不再请求
    assert len(fake.route_calls) == first_calls
    s.undo()
    assert s._load().route_overrides == {}


def test_cache_invalidated_when_coordinates_change(monkeypatch):
    _setup_trip()
    s.schedule_days()
    monkeypatch.setattr(s, "_amap", lambda: FakeAmap())
    s.refine_routes()
    n = len(s._load().route_overrides)
    assert n > 0
    s.update_place("p1", lat=39.95)        # 坐标变了，含 p1 的路段缓存键随之失效
    f2 = FakeAmap()
    monkeypatch.setattr(s, "_amap", lambda: f2)
    s.refine_routes()
    assert f2.route_calls                  # 受影响的路段被重新查询


def test_refine_failures_are_reported_and_keep_estimates(monkeypatch):
    _setup_trip()
    s.schedule_days()
    monkeypatch.setattr(s, "_amap", lambda: FakeAmap(fail_routes=True))
    out = s.refine_routes()
    assert "失败" in out and s._load().route_overrides == {}


def test_lodging_price_source_tag():
    s.new_trip()
    s.add_lodging("甲", 39.9, 116.4, price_min=300, price_max=400, price_source="rollinggo", price_date="2026-10-25")
    s.add_lodging("乙", 39.9, 116.4)
    t = s._load()
    assert "价格来源:rollinggo 2026-10-25" in t.lodgings[0].notes and "价格来源" not in t.lodgings[1].notes
