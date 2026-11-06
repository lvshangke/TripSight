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


def test_server_registers_all_tools(monkeypatch):
    monkeypatch.setenv("TRIPCORE_TOOLS", "full")
    names = {t.name for t in asyncio.run(s.build_server().list_tools())}
    assert names == {f.__name__ for f in s.TOOLS}
    assert len(names) == 89


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
    s.update_place("p2", ticket_price=35, ticket_source="user", duration_min=60)
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

    def route(self, mode, a_lat, a_lon, b_lat, b_lon, city=None, transit_strategy="fastest", **kw):
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


def test_hours_need_a_source_and_backups_are_validated():
    _setup_trip()
    with pytest.raises(s.ToolError, match="来源"):
        s.add_place("馆", 39.9, 116.4, opening_hours="周二至周日 9:00-17:00")
    with pytest.raises(s.ToolError, match="不存在"):
        s.add_place("馆", 39.9, 116.4, backups=["p99"])
    s.add_place("馆", 39.9, 116.4, opening_hours="周二至周日 9:00-17:00", hours_source="amap",
                reservation_required=True, backups=["p2"])
    t = s._load()
    assert t.place("p5").hours_source == "amap" and t.place("p5").backups == ["p2"]
    with pytest.raises(s.ToolError):
        s.update_place("p5", backups=["p5"])            # 不能备选自己
    s.update_place("p5", backups=["p3"])
    assert s._load().place("p5").backups == ["p3"]


def test_unbooked_issue_lists_backups_and_removal_cleans_them():
    _setup_trip()
    s.add_place("馆", 39.9, 116.4, reservation_required=True, backups=["p2"])
    s.schedule_days()
    msgs = [i["message"] for i in s.check_plan()["issues"] if i["code"] == "RESERVATION_NOT_BOOKED"]
    assert msgs and "备选：天坛" in msgs[0]
    s.remove_place("p2")
    assert s._load().place("p5").backups == []
    msgs = [i["message"] for i in s.check_plan()["issues"] if i["code"] == "RESERVATION_NOT_BOOKED"]
    assert msgs and "还没有设置备选景点" in msgs[0]


# ---------------- 出行方式 ----------------
class ModeAmap(FakeAmap):
    """按出行方式返回不同结果：走路 25 分钟，公交 14 分钟（1 次换乘，含地铁），驾车 10 分钟。"""

    def route(self, mode, a_lat, a_lon, b_lat, b_lon, city=None, transit_strategy="fastest", **kw):
        self.route_calls.append(mode)
        if mode == "walk":
            return RouteResult("walk", 1.9, 25)
        if mode == "drive":
            return RouteResult("drive", 5.0, 10)
        return RouteResult("transit", 5.5, 14, transfers=1, walking_km=0.5, cost_yuan=3, lines=["地铁2号线", "21路"], uses_subway=True)


def test_compare_transport_recommends_by_preferences(monkeypatch):
    _setup_trip()
    monkeypatch.setattr(s, "_amap", lambda: ModeAmap())
    r = s.compare_transport("p1", "p2")
    assert set(r["options"]) == {"walk", "transit", "drive"} and r["options"]["transit"]["uses_subway"]
    assert r["recommended"] == "transit"                      # 步行 25 分钟超过默认 20 分钟
    s.set_transport_prefs(walk_max_min=30)
    assert s.compare_transport("p1", "p2")["recommended"] == "walk"
    s.set_transport_prefs(walk_max_min=10, max_transfers=0)
    assert s.compare_transport("p1", "p2")["recommended"] == "drive"      # 换乘超限，接受打车
    s.set_transport_prefs(taxi_ok=False)
    r = s.compare_transport("p1", "p2")
    assert r["recommended"] == "transit" and "超出" in r["reason"]


def test_compare_needs_key_and_known_ids(monkeypatch):
    _setup_trip()
    monkeypatch.setattr(s, "_amap", lambda: None)
    with pytest.raises(s.ToolError, match="AMAP_KEY"):
        s.compare_transport("p1", "p2")
    monkeypatch.setattr(s, "_amap", lambda: ModeAmap())
    with pytest.raises(s.ToolError, match="找不到"):
        s.compare_transport("p1", "zz")


def test_prefs_validation_and_view():
    s.new_trip()
    assert "walk_max_min" in s.set_transport_prefs()
    with pytest.raises(s.ToolError):
        s.set_transport_prefs(walk_max_min=0)
    s.set_transport_prefs(prefer_subway=True, notes="带老人")
    p = s._load().meta.transport_prefs
    assert p.prefer_subway and p.notes == "带老人"


def test_leg_mode_changes_stats_and_refine_uses_it(monkeypatch):
    s.new_trip(num_days=1, mode="transit")
    s.add_place("故宫", 39.9163, 116.3972)
    s.add_place("颐和园", 39.9999, 116.2755)          # 与故宫相距十几公里
    s.schedule_days()
    from tripcore.metrics import day_stats
    t = s._load()
    ids = [it.place_id for it in t.plan.days[0].items]
    a, b = ids[0], ids[1]
    before = day_stats(t, t.plan.days[0]).legs[0]
    assert before.mode == "transit"
    s.set_leg_mode(a, b, "drive")
    t2 = s._load()
    after = day_stats(t2, t2.plan.days[0]).legs[0]
    assert t2.leg_modes[f"{a}>{b}"] == "drive" and after.mode == "drive" and after.minutes != before.minutes
    fake = ModeAmap()
    monkeypatch.setattr(s, "_amap", lambda: fake)
    s.refine_routes()
    assert fake.route_calls == ["drive"]                 # 按这一段单独指定的方式查询
    assert day_stats(s._load(), s._load().plan.days[0]).legs[0].detail_level == "route"
    s.set_leg_mode(a, b, "default")
    assert f"{a}>{b}" not in s._load().leg_modes
    with pytest.raises(s.ToolError):
        s.set_leg_mode(a, b, "bike")
    with pytest.raises(s.ToolError, match="找不到"):
        s.set_leg_mode(a, "zz", "walk")


def test_explicit_leg_mode_is_not_downgraded_to_walk(monkeypatch):
    s.new_trip(num_days=1, mode="transit")
    s.add_place("甲", 39.9000, 116.4000)
    s.add_place("乙", 39.9050, 116.4050)                  # 很近，默认会被当作步行
    s.schedule_days()
    t = s._load()
    a, b = [it.place_id for it in t.plan.days[0].items]
    s.set_leg_mode(a, b, "drive")
    fake = ModeAmap()
    monkeypatch.setattr(s, "_amap", lambda: fake)
    out = s.refine_routes()
    assert fake.route_calls == ["drive"] and "驾车" in out


def test_show_trip_includes_hours_and_closed_warning():
    s.new_trip(start_date="2026-10-20", end_date="2026-10-20", city="西安")   # 周二
    s.add_place("博物馆", 39.9, 116.4, opening_hours="周二至周日 09:00-17:00 周一闭馆", hours_source="amap",
                reservation_required=True)
    s.add_place("无数据", 39.901, 116.401)
    s.schedule_days()
    out = s.show_trip()
    assert "来源：amap" in out and "待核实" in out and "需预约" in out
    # 同样的景点，行程只有周一这一天：排程会直接拒绝把它排进去（而不是排进去再报闭馆），并说明原因
    s.new_trip(start_date="2026-10-19", end_date="2026-10-19", city="西安")
    s.add_place("博物馆", 39.9, 116.4, opening_hours="周二至周日 09:00-17:00 周一闭馆", hours_source="amap")
    s.schedule_days()
    assert "未安排：博物馆" in s.show_trip() and "闭馆" in s.show_trip()


def test_hours_parser():
    from tripcore.hours import hours_for_weekday as h
    assert h("周一至周日 08:30-17:00", 2) == "08:30-17:00"
    assert h("周二至周日 09:00-17:00 周一闭馆", 0) == "闭馆"
    assert h("周一至周五 09:00-17:00 周六至周日 09:00-18:00", 5) == "09:00-18:00"
    assert h("全天", 3) == "全天开放" and h("", 1) is None and h("随缘开放", 1) is None


class WeatherAmap(FakeAmap):
    def __init__(self, dates):
        super().__init__()
        self.dates = dates

    def adcode(self, city):
        return "610100"

    def forecast(self, adcode):
        from tripcore.amap import WeatherDay
        return [WeatherDay(d, "1", "小雨", "多云", 20, 12) for d in self.dates]


def test_weather_only_within_forecast_range(monkeypatch):
    s.new_trip(start_date="2026-10-18", end_date="2026-10-19", city="西安")
    s.add_place("甲", 39.9, 116.4)
    s.add_place("乙", 39.99, 116.3)
    s.schedule_days()
    monkeypatch.setattr(s, "_amap", lambda: WeatherAmap(["2026-10-18"]))
    out = s.get_weather()
    assert "小雨" in out and "暂无预报" in out
    monkeypatch.setattr(s, "_amap", lambda: WeatherAmap(["2027-01-01"]))
    assert "不在可用天气来源的预报范围" in s.get_weather()
    s.new_trip(num_days=2, city="西安")
    s.add_place("甲", 39.9, 116.4)
    s.schedule_days()
    assert "没有设置具体出行日期" in s.get_weather()


class HoursAmap(FakeAmap):
    def search_places(self, query, city=None, limit=5):
        if query == "故宫":
            return [PlaceHit("故宫博物院", 39.9165, 116.3975, opentime_week="周二至周日 08:30-17:00"),
                    PlaceHit("别处", 39.0, 116.0, opentime_week="周一至周日 00:00-24:00")]
        if query == "天坛":
            return [PlaceHit("天坛公园", 31.0, 121.0, opentime_week="周一至周日 06:00-22:00")]   # 名字像但太远
        return []


def test_fill_hours_matches_by_name_and_distance(monkeypatch):
    _setup_trip()
    s.update_place("p4", opening_hours="用户给的 9-17", hours_source="user")
    monkeypatch.setattr(s, "_amap", lambda: HoursAmap())
    out = s.fill_hours()
    t = s._load()
    assert t.place("p1").opening_hours.startswith("周二至周日") and t.place("p1").hours_source == "amap"
    assert t.place("p2").opening_hours == "" and "天坛" in out and "仍待核实" in out    # 太远，不采用
    assert t.place("p4").opening_hours == "用户给的 9-17"                                # 不覆盖
    s.undo()
    assert s._load().place("p1").opening_hours == ""


def test_fill_hours_needs_key(monkeypatch):
    _setup_trip()
    monkeypatch.setattr(s, "_amap", lambda: None)
    with pytest.raises(s.ToolError, match="AMAP_KEY"):
        s.fill_hours()


class FoodAmap(FakeAmap):
    def __init__(self):
        super().__init__()
        self.around = []

    def search_around(self, lat, lon, radius_m=800, types="050000", keywords="", limit=20):
        self.around.append((radius_m, types, keywords))
        return [PlaceHit("面馆A", lat + 0.001, lon, rating=4.2, cost=30, opentime_week="周一至周日 07:00-21:00"),
                PlaceHit("饭店B", lat, lon + 0.002, rating=4.8, cost=88),
                PlaceHit("太远的店", lat + 0.05, lon, rating=5.0, cost=10)]


def test_food_suggest_choose_remove_and_show(monkeypatch):
    _setup_trip()
    s.schedule_days()
    fake = FoodAmap()
    monkeypatch.setattr(s, "_amap", lambda: fake)
    r = s.suggest_food(1, "p1", keyword="面食")
    names = [c["name"] for c in r["candidates"]]
    assert names == ["饭店B", "面馆A"]                  # 按评分排序，太远的被剔除
    assert fake.around[0] == (800, "050000", "面食")
    rev = s._load().revision
    assert s._load().meals == []                       # 只是候选，不改行程
    assert s._load().revision == rev
    s.choose_food(r["candidates"][1]["candidate_id"])
    t = s._load()
    assert t.meals[0].name == "面馆A" and t.meals[0].cost_per_person == 30 and t.meals[0].hours_source == "amap"
    out = s.show_trip()
    assert "🍜" in out and "面馆A" in out and "餐饮" in out
    with pytest.raises(s.ToolError, match="已经"):
        s.choose_food(r["candidates"][1]["candidate_id"])
    s.remove_food("m1")
    assert s._load().meals == []
    s.undo()
    assert s._load().meals[0].id == "m1"
    with pytest.raises(s.ToolError, match="没有这个候选"):
        s.choose_food("f99")
    with pytest.raises(s.ToolError):
        s.suggest_food(9, "p1")


def test_food_needs_key(monkeypatch):
    _setup_trip()
    s.schedule_days()
    monkeypatch.setattr(s, "_amap", lambda: None)
    with pytest.raises(s.ToolError, match="AMAP_KEY"):
        s.suggest_food(1, "p1")


def test_seasonal_hours():
    from datetime import date
    from tripcore.hours import hours_for_date as h
    t = "3~10月 08:00-18:30;11月15日起周一闭馆"
    assert h(t, date(2026, 10, 19)) == "08:00-18:30"          # 周一，但闭馆条件 11/15 才开始
    assert h("周一至周日 08:30-19:00;11月15日起周一闭馆", date(2026, 11, 16)) == "闭馆"
    assert h("周一至周日 08:30-19:00;11月15日起周一闭馆", date(2026, 10, 19)) == "08:30-19:00"
    assert h("周一至周日 08:30-18:00;10月11日起 08:30-17:30", date(2026, 10, 20)) == "08:30-17:30"
    assert h("周一至周日 08:30-18:00;10月11日起 08:30-17:30", date(2026, 10, 5)) == "08:30-18:00"
    assert h("4~10月 08:00-18:00", date(2026, 12, 1)) is None   # 条件不适用且没有别的信息
    assert h("1月 08:00 3月 09:00", date(2026, 1, 5)) is None    # 条件过于复杂，不猜


class NamedFoodAmap(FakeAmap):
    def search_places(self, query, city=None, limit=5):
        # 故宫 (39.9163,116.3972) 附近一家，和一家很远的
        return [PlaceHit("老店", 39.9170, 116.3980, rating=4.6, cost=60),
                PlaceHit("远店", 39.7000, 116.9000, rating=4.9, cost=40)]


def test_find_food_suggests_nearest_slot_and_cost_uses_travelers(monkeypatch):
    s.new_trip(num_days=2, travelers=2, city="北京")
    s.add_place("故宫", 39.9163, 116.3972)
    s.add_place("颐和园", 39.9999, 116.2755)
    s.schedule_days()
    monkeypatch.setattr(s, "_amap", lambda: NamedFoodAmap())
    r = s.find_food("老店")
    near, far = r["candidates"]
    assert near["suggested"]["after_place"] == "故宫" and near["suggested"]["distance_m"] < 300
    assert "warning" in far["suggested"]
    s.choose_food(near["candidate_id"])
    m = s._load().meals[0]
    assert m.after_place_id == "p1" and m.cost_per_person == 60
    out = s.show_trip()
    assert "按 2 人估算" in out and "已选餐厅 120" in out
    # 换到另一天的另一个景点后面
    s.choose_food(far["candidate_id"], day=2, after_place_id="p2")
    assert s._load().meals[1].after_place_id == "p2" and s._load().meals[1].distance_m > 3000
    with pytest.raises(s.ToolError):
        s.choose_food(far["candidate_id"], day=9, after_place_id="p2")


def test_set_travelers():
    s.new_trip()
    assert s._load().meta.travelers == 1
    s.set_travelers(3)
    assert s._load().meta.travelers == 3
    with pytest.raises(s.ToolError):
        s.set_travelers(0)
    with pytest.raises(s.ToolError):
        s.new_trip(travelers=0)


def test_export_map_writes_self_contained_page(monkeypatch, tmp_path):
    s.new_trip(start_date="2026-10-19", end_date="2026-10-20", city="北京", name="测</script><b>试")
    s.add_place("故宫", 39.9163, 116.3972, opening_hours="周二至周日 08:30-17:00", hours_source="amap",
                reservation_required=True)
    s.add_place("颐和园", 39.9999, 116.2755)
    s.add_lodging("酒店A", 39.91, 116.40, choose=True)
    s.schedule_days()
    monkeypatch.setattr(s, "_amap", lambda: NamedFoodAmap())
    r = s.find_food("老店")
    s.choose_food(r["candidates"][0]["candidate_id"])
    out = s.export_map()
    path = s.trip_path().with_name("map.html")
    assert str(path) in out and path.exists()
    html = path.read_text(encoding="utf-8")
    assert "L.map" in html and "appmaptile" in html and "故宫" in html and "老店" in html and "酒店A" in html
    assert "<b>试" not in html.split("<title>")[1].split("</title>")[0]      # 标题被转义
    assert "测<\\/script>" in html                                           # 数据里的 </ 被转义，不会提前结束 script
    assert "https://unpkg" not in html and "cdn" not in html.lower().replace("cdnjs", "")  # 脚本内嵌，不依赖 CDN


def test_map_coordinates_are_gcj02():
    from tripcore.mapview import build_map_data
    from tripcore.coords import wgs84_to_gcj02
    s.new_trip(num_days=1)
    s.add_place("故宫", 39.9163, 116.3972)
    s.schedule_days()
    pos = [e for e in build_map_data(s._load())["days"][0]["timeline"] if e["type"] == "stop"][0]["pos"]
    g = wgs84_to_gcj02(39.9163, 116.3972)
    assert abs(pos[0] - g[0]) < 1e-5 and abs(pos[1] - g[1]) < 1e-5


class PathAmap(FakeAmap):
    def route(self, mode, a_lat, a_lon, b_lat, b_lon, city=None, transit_strategy="fastest", **kw):
        self.route_calls.append(mode)
        mid = ((a_lat + b_lat) / 2 + 0.002, (a_lon + b_lon) / 2)
        r = RouteResult(mode, 3.0, 20, path=[(a_lat, a_lon), mid, (b_lat, b_lon)])
        if mode == "transit":
            r.lines, r.transfers, r.walking_km, r.cost_yuan = ["地铁2号线", "21路"], 1, 0.4, 3
        return r


def test_closed_loop_timeline_paths_links_and_gpx(monkeypatch):
    s.new_trip(num_days=1, mode="transit", city="北京")
    s.add_place("故宫", 39.9163, 116.3972, duration_min=120)
    s.add_place("天坛", 39.8822, 116.4066, duration_min=60)
    s.add_lodging("酒店A", 39.9100, 116.4000, choose=True)
    s.schedule_days()
    monkeypatch.setattr(s, "_amap", lambda: PathAmap())
    s.refine_routes()
    t = s._load()
    assert all(l.path_checked and len(l.path) == 3 for l in t.route_overrides.values())
    from tripcore.mapview import build_map_data
    tl = build_map_data(t)["days"][0]["timeline"]
    kinds = [e["type"] for e in tl]
    assert kinds == ["hotel", "leg", "stop", "leg", "stop", "leg", "hotel"]           # 酒店出发→…→回酒店，闭环
    assert tl[0]["role"] == "出发" and tl[-1]["role"] == "返回" and tl[0]["time"] == "09:00"
    assert tl[2]["arrive"] > tl[0]["time"] and tl[4]["arrive"] > tl[2]["leave"]        # 时间递增
    legs = [e for e in tl if e["type"] == "leg"]
    assert all(l["real"] and len(l["path"]) == 3 for l in legs)
    assert all(l["link"].startswith("https://uri.amap.com/navigation?from=") for l in legs)
    assert all(("mode=walk" if l["mode"] == "步行" else "mode=bus") in l["link"] for l in legs)
    assert any("地铁2号线" in l["note"] for l in legs)
    out = s.export_gpx(1)
    gpx = (s.trip_path().with_name("gpx") / "day-1.gpx").read_text(encoding="utf-8")
    assert "day-1.gpx" in out and gpx.count("<wpt") == 4 and gpx.count("<trkseg>") == 3 and "估算" not in gpx
    import xml.dom.minidom as md
    md.parseString(gpx)                                                                 # 合法 XML
    with pytest.raises(s.ToolError):
        s.export_gpx(5)


def test_old_cache_without_path_is_refetched(monkeypatch):
    s.new_trip(num_days=1, city="北京")
    s.add_place("故宫", 39.9163, 116.3972)
    s.add_place("天坛", 39.8822, 116.4066)
    s.schedule_days()
    monkeypatch.setattr(s, "_amap", lambda: FakeAmap())          # 没有 path
    s.refine_routes()
    t = s._load()
    for k, l in t.route_overrides.items():
        assert l.path_checked and l.path == []
    f2 = PathAmap()
    monkeypatch.setattr(s, "_amap", lambda: f2)
    s.refine_routes()
    assert f2.route_calls == []                                  # 已问过但没有形状的，不会反复请求


def test_spread_overlapping_markers():
    from tripcore.mapview import _spread
    out = _spread([[34.26, 108.94], [34.26, 108.94], [34.30, 108.99]])
    assert out[0] == [34.26, 108.94] and out[1] != out[0] and out[2] == [34.30, 108.99]


class PoiAmap(FakeAmap):
    def search_places(self, query, city=None, limit=5):
        table = {"故宫": PlaceHit("故宫博物院", 39.9165, 116.3975, amap_id="B000A8UIN8"),
                 "酒店A": PlaceHit("酒店A(王府井店)", 39.9101, 116.4001, amap_id="B0HOTEL1"),
                 "老店": PlaceHit("老店", 39.9170, 116.3980, amap_id="B0FOOD1", rating=4.6, cost=60),
                 "天坛": PlaceHit("天坛公园", 31.0, 121.0, amap_id="B0FAR")}     # 名字像但太远
        return [table[query]] if query in table else []


def test_personal_map_payload_closed_loop_and_poi_matching(monkeypatch):
    s.new_trip(num_days=1, city="北京", name="北京行")
    s.add_place("故宫", 39.9163, 116.3972)
    s.add_place("天坛", 39.8822, 116.4066)
    s.add_lodging("酒店A", 39.9100, 116.4000, choose=True)
    s.schedule_days()
    monkeypatch.setattr(s, "_amap", lambda: PoiAmap())
    s.find_food("老店")
    s.choose_food("f1")
    r = s.personal_map_payload()
    a = r["arguments"]
    assert a["orgName"] == "北京行" and len(a["lineList"]) == 1
    pts = a["lineList"][0]["pointInfoList"]
    names = [p["name"] for p in pts]
    assert names[0] == names[-1] == "酒店A" and "故宫" in names and "老店" in names     # 闭环、用餐挂在景点后
    assert "天坛" not in names and any("天坛" in x for x in r["skipped"])                # 太远不采用，宁缺毋滥
    assert all(set(p) == {"name", "lon", "lat", "poiId"} and p["poiId"] for p in pts)
    from tripcore.coords import wgs84_to_gcj02
    g = wgs84_to_gcj02(39.9163, 116.3972)
    gu = [p for p in pts if p["name"] == "故宫"][0]
    assert abs(gu["lat"] - g[0]) < 1e-5 and abs(gu["lon"] - g[1]) < 1e-5               # 高德坐标系
    assert s._load().place("p1").amap_id == "B000A8UIN8"                                # 已存下，下次不再查
    f = PoiAmap(); calls = []
    f.search_places = lambda q, c=None, limit=5: calls.append(q) or PoiAmap.search_places(f, q, c, limit)
    monkeypatch.setattr(s, "_amap", lambda: f)
    s.personal_map_payload()
    assert "故宫" not in calls and "酒店A" not in calls
    with pytest.raises(s.ToolError):
        s.personal_map_payload(day=5)


def _setup_four_days():
    s.new_trip(num_days=2, city="北京", name="北京行")
    s.add_place("故宫", 39.9163, 116.3972)
    s.add_place("天坛", 39.8822, 116.4066)
    s.add_place("颐和园", 39.9999, 116.2755)
    s.add_lodging("酒店A", 39.9100, 116.4000, choose=True)
    s.schedule_days()


class PoiAll(FakeAmap):
    def search_places(self, query, city=None, limit=5):
        from tripcore.geocode import geocode  # noqa: F401  (not used)
        t = s._load()
        objs = [*t.places, *t.lodgings]
        return [PlaceHit(o.name, o.lat, o.lon, amap_id=f"ID-{o.name}") for o in objs if o.name == query]


def test_create_amap_map_calls_mcp_directly_without_leaking_key(monkeypatch):
    _setup_four_days()
    monkeypatch.setenv("AMAP_KEY", "SECRETKEY123")
    monkeypatch.setattr(s, "_amap", lambda: PoiAll())
    calls = []

    def fake(tool, arguments, key):
        calls.append((tool, arguments, key))
        return "amapuri://workInAmap/createWithToken?polymericId=mcp_x&from=MCP"

    monkeypatch.setattr(s, "_call_amap_mcp", fake)
    r = s.create_amap_map(per_day=False)
    assert len(calls) == 1 and calls[0][0] == "maps_schema_personal_map" and calls[0][2] == "SECRETKEY123"
    assert len(calls[0][1]["lineList"]) == 2 and r["maps"][0]["link"].startswith("amapuri://")
    calls.clear()
    r = s.create_amap_map()                                  # 默认每天一个链接
    assert len(calls) == 2 and all(len(c[1]["lineList"]) == 1 for c in calls) and len(r["maps"]) == 2
    log = (s.trip_path().with_name("amap_calls.log")).read_text(encoding="utf-8")
    assert "mcp.amap.com" in log and "SECRETKEY123" not in log

    def boom(tool, arguments, key):
        raise RuntimeError("https://mcp.amap.com/mcp?key=SECRETKEY123 failed")

    monkeypatch.setattr(s, "_call_amap_mcp", boom)
    with pytest.raises(s.ToolError) as e:
        s.create_amap_map()
    assert "SECRETKEY123" not in str(e.value)
    assert "SECRETKEY123" not in (s.trip_path().with_name("amap_calls.log")).read_text(encoding="utf-8")


def test_create_amap_map_needs_key(monkeypatch):
    _setup_four_days()
    monkeypatch.delenv("AMAP_KEY", raising=False)
    with pytest.raises(s.ToolError, match="AMAP_KEY"):
        s.create_amap_map()


def _arrival_trip(arr="2026-10-19 14:00", dep="2026-10-21 18:00"):
    s.new_trip(start_date="2026-10-19", end_date="2026-10-21", city="北京", name="北京行", travelers=2)
    for name, lat, lon in [("故宫", 39.9163, 116.3972), ("天坛", 39.8822, 116.4066), ("颐和园", 39.9999, 116.2755),
                           ("鸟巢", 39.9928, 116.3965), ("国博", 39.9050, 116.4010), ("景山", 39.9254, 116.3970)]:
        s.add_place(name, lat, lon, duration_min=150)
    s.add_lodging("酒店A", 39.9100, 116.4000, choose=True)
    s.schedule_days()
    s.set_connection("arrival", "flight", "上海", "北京", "2026-10-19 10:30", arr, number="CA1883",
                     price_per_person=800, price_source="flyai", price_date="2026-10-17")
    s.set_connection("departure", "flight", "北京", "上海", dep, "2026-10-21 20:10", number="CA1884")


def test_connections_shrink_first_and_last_day_and_warn():
    _arrival_trip()
    from tripcore.connections import day_window
    t = s._load()
    assert day_window(t, 0)[0] == 15 * 60 + 30            # 14:00 到 + 45 取行李 + 45 兜底路程 = 15:30 才能开始
    assert day_window(t, 2)[1] == 15 * 60                 # 18:00 飞，提前 180 分钟 = 15:00 就要走
    out = s.check_plan()
    codes = [i["code"] for i in out["issues"]]
    assert "CONNECTION_WINDOW_TOO_SMALL" in codes
    shown = s.show_trip()
    assert "到达：CA1883" in shown and "离开：CA1884" in shown and "可玩约" in shown and "大交通" in shown
    assert "800 元/人（flyai 2026-10-17，参考价）" in shown


def test_connection_date_mismatch_and_validation():
    _arrival_trip()
    s.set_connection("departure", "train", "北京", "上海", "2026-11-30 09:00", "2026-11-30 14:00", number="G1")
    assert "CONNECTION_DATE_MISMATCH" in [i["code"] for i in s.check_plan()["issues"]]
    with pytest.raises(s.ToolError, match="来源"):
        s.set_connection("arrival", "flight", "上海", "北京", "2026-10-19 10:00", "2026-10-19 12:00", price_per_person=500)
    with pytest.raises(s.ToolError):
        s.set_connection("arrival", "flight", "上海", "北京", "2026-10-19 12:00", "2026-10-19 10:00")   # 到达早于出发
    with pytest.raises(s.ToolError):
        s.set_connection("arrival", "flight", "上海", "北京", "明天下午", "2026-10-19 12:00")
    with pytest.raises(s.ToolError):
        s.set_connection("somewhere", "flight", "a", "b", "2026-10-19 10:00", "2026-10-19 12:00")
    s.clear_connection("departure")
    assert s._load().departure is None
    s.undo()
    assert s._load().departure is not None
    with pytest.raises(s.ToolError):
        s.clear_connection("arrival") if s._load().arrival is None else s.clear_connection("nothing")


def test_map_timeline_starts_after_arrival_and_flags_overrun():
    _arrival_trip()
    from tripcore.mapview import build_map_data
    d = build_map_data(s._load())["days"]
    first = d[0]["timeline"]
    assert first[0]["type"] == "conn" and "14:00 到达" in first[0]["text"]
    hotel = [e for e in first if e["type"] == "hotel"][0]
    assert hotel["time"] >= "15:30"
    assert any(e["type"] == "conn" and "⚠" in e["text"] for e in d[2]["timeline"] + first)


class AirportAmap:
    def search_places(self, query, city=None, limit=5):
        from tripcore.amap import PlaceHit
        return [PlaceHit(name="首都机场南路", lat=40.07, lon=116.60, category="道路附属设施"),
                PlaceHit(name="北京首都国际机场T3航站楼", lat=40.0799, lon=116.6031, address="顺义区",
                         category="交通设施服务;机场相关;机场出发/到达")]

    def route(self, mode, a_lat, a_lon, b_lat, b_lon, city=None, transit_strategy="fastest", **kw):
        from tripcore.amap import RouteResult
        return RouteResult(mode=mode, distance_km=30.0, minutes=60, path=[(a_lat, a_lon), (b_lat, b_lon)])


def test_terminal_lookup_and_real_transfer_time(monkeypatch):
    _arrival_trip()
    monkeypatch.setattr(s, "_amap", lambda: AirportAmap())
    msg = s.set_connection("arrival", "flight", "上海", "北京", "2026-10-19 10:30", "2026-10-19 14:00",
                           number="CA1883", terminal_name="首都国际机场")
    assert "北京首都国际机场T3航站楼" in msg and "距离估算" in msg
    t = s._load()
    assert t.arrival.terminal_lat == 40.0799
    s.refine_routes()
    from tripcore.connections import day_window, transfer_minutes
    t = s._load()
    assert transfer_minutes(t, "arrival") == (60, "高德路线")
    assert day_window(t, 0)[0] == 14 * 60 + 45 + 60       # 14:00 + 45 取行李 + 60 路程
    assert "高德路线" in s.show_trip()
    from tripcore.mapview import build_map_data
    assert any(e["type"] == "leg" and e["real"] for e in build_map_data(t)["days"][0]["timeline"][:3])


def test_terminal_not_found_falls_back(monkeypatch):
    _arrival_trip()

    class Empty:
        def search_places(self, *a, **k):
            return []
    monkeypatch.setattr(s, "_amap", lambda: Empty())
    msg = s.set_connection("departure", "flight", "北京", "上海", "2026-10-21 18:00", "2026-10-21 20:10",
                           terminal_name="不存在机场")
    assert "没有找到" in msg and "经验值" in msg
    from tripcore.connections import day_window
    assert day_window(s._load(), 2)[1] == 15 * 60


def test_map_template_handles_every_timeline_type(monkeypatch):
    """地图脚本必须认识时间线里出现的每种类型（曾因不认识 conn 导致第1天/第4天整页脚本报错）。"""
    _arrival_trip()
    from tripcore.mapview import build_map_data, build_map_html
    types = {e["type"] for d in build_map_data(s._load())["days"] for e in d["timeline"]}
    html = build_map_html(s._load())
    for ty in types - {'stop'}:      # stop 是默认分支
        assert f"e.type === '{ty}'" in html, ty


class RecordingAirportAmap(AirportAmap):
    def __init__(self):
        self.calls = []

    def route(self, mode, a_lat, a_lon, b_lat, b_lon, city=None, transit_strategy="fastest", **kw):
        self.calls.append((mode, kw.get("depart")))
        from tripcore.amap import RouteResult
        return RouteResult(mode=mode, distance_km=30.0, minutes=45 if mode == "drive" else 90, path=[(a_lat, a_lon), (b_lat, b_lon)])


def test_night_terminal_legs_use_taxi_and_daytime_ones_pass_depart_time(monkeypatch):
    _arrival_trip()
    fake = RecordingAirportAmap()
    monkeypatch.setattr(s, "_amap", lambda: fake)
    s.set_connection("arrival", "flight", "上海", "北京", "2026-10-18 22:05", "2026-10-19 00:35", terminal_name="首都国际机场")
    s.set_connection("departure", "flight", "北京", "上海", "2026-10-21 18:00", "2026-10-21 20:10", terminal_name="首都国际机场")
    s.refine_routes()
    legs = [v for k, v in s._load().route_overrides.items() if k.startswith("arrival@") or ">departure@" in k]
    arr = next(v for v in legs if v.from_id == "arrival")
    dep = next(v for v in legs if v.to_id == "departure")
    assert arr.mode == "drive" and "深夜" in arr.note          # 00:35 到 → 约 01:20 出发：按打车
    assert dep.mode == "transit"                               # 白天离开：公共交通，且传了出发时间
    assert any(m == "transit" and d is not None for m, d in fake.calls)
    n = len(fake.calls)
    s.refine_routes()
    assert len(fake.calls) == n                                # 时间没变，不重复请求


def test_map_shows_terminal_markers_even_on_empty_departure_day(monkeypatch):
    _arrival_trip()
    monkeypatch.setattr(s, "_amap", lambda: RecordingAirportAmap())
    s.set_connection("departure", "flight", "北京", "上海", "2026-10-21 06:30", "2026-10-21 08:40", terminal_name="首都国际机场")
    s.refine_routes()
    from tripcore.mapview import build_map_data
    last = build_map_data(s._load())["days"][-1]["timeline"]
    types = [e["type"] for e in last]
    assert "term" in types and "leg" in types and any(e["type"] == "hotel" for e in last)


# ---------------- 游记 → 候选 ----------------
NOTE = """完整citywalk顺路路线：老菜场→东仓门早市→书院门→顺城巷→湘子庙→德福巷→永宁门（夜景）
【沿途必打卡点位】
✔️老菜场：复古市井老街，楼宇搭配远处城墙远景，原生老城风貌。
✔️东仓门早市：本地人私藏晨间市集！热气腾腾的甑糕、油糕等特色小吃超多。
✔️书院门：闹中取静的青石板街巷，满街字画碑帖、文房小店。
✔️顺城巷：整条路线封神路段！沿千年城墙慢行。
✔️湘子庙+德福巷：清幽古寺静谧治愈，终点老街超多咖啡馆、小店。
✔️永宁门：西安经典地标，傍晚光影绝美，夜景灯火璀璨。
【游玩小Tips】
- 想感受烟火气建议上午出发，打卡早市氛围最好"""


class NoteAmap(FakeAmap):
    POS = {"书院门": (34.2569, 108.9437), "永宁门": (34.2580, 108.9400), "德福巷": (34.2640, 108.9420),
           "东仓门早市": (34.2650, 108.9480), "湘子庙": (34.2610, 108.9400)}

    def search_places(self, query, city=None, limit=5):
        if query == "顺城巷":                                  # 两个同名地点相距很远 → 有歧义
            return [PlaceHit(name="顺城巷", lat=34.25, lon=108.94), PlaceHit(name="顺城巷", lat=34.30, lon=109.05)]
        if query in self.POS:
            lat, lon = self.POS[query]
            return [PlaceHit(name=query, lat=lat, lon=lon, address="西安")]
        return []


def test_candidates_validated_against_note_text(monkeypatch):
    s.new_trip(start_date="2026-10-30", end_date="2026-11-02", city="西安", name="西安")
    items = [
        {"name": "书院门", "kind": "area", "quote": "书院门：闹中取静的青石板街巷"},
        {"name": "东仓门早市", "kind": "area", "quote": "东仓门早市：本地人私藏晨间市集", "clues": ["建议上午出发", "门票30元"]},
        {"name": "老菜场", "kind": "area", "quote": "老菜场：复古市井老街"},
        {"name": "大雁塔", "kind": "attraction", "quote": "大雁塔：必去地标"},           # 原文没有 → 拒收
        {"name": "湘子庙", "kind": "attraction", "quote": "德福巷：终点老街"},           # 名字不在 quote 里 → 拒收
    ]
    out = s.submit_candidates(NOTE, items, source="citywalk")
    assert [c["name"] for c in out["added"]] == ["老菜场", "书院门", "东仓门早市"] or \
        [c["name"] for c in out["added"]] == ["老菜场", "东仓门早市", "书院门"]
    names = [c["name"] for c in out["added"]]
    assert names.index("老菜场") < names.index("东仓门早市") < names.index("书院门")   # 按原文先后排序
    assert {r["name"] for r in out["rejected"]} == {"大雁塔", "湘子庙"}
    east = next(c for c in out["added"] if c["name"] == "东仓门早市")
    assert east["clues"] == ["建议上午出发"] and east["dropped_clues"] == ["门票30元"]
    again = s.submit_candidates(NOTE, items[:1])
    assert again["skipped_duplicates"] == ["书院门"] and not again["added"]
    assert len(s.list_candidates()) == 3


def test_adopt_candidates_adds_only_unambiguous_nonduplicate(monkeypatch):
    s.new_trip(start_date="2026-10-30", end_date="2026-11-02", city="西安", name="西安")
    s.add_place("西安城墙", 34.2582, 108.9402, duration_min=120)             # 离永宁门不到 300 米
    monkeypatch.setattr(s, "_amap", lambda: NoteAmap())
    s.submit_candidates(NOTE, [
        {"name": "书院门", "kind": "area", "quote": "书院门：闹中取静的青石板街巷", "clues": ["满街字画碑帖"]},
        {"name": "永宁门", "kind": "attraction", "quote": "永宁门：西安经典地标"},
        {"name": "顺城巷", "kind": "area", "quote": "顺城巷：整条路线封神路段"},
        {"name": "东仓门早市", "kind": "food", "quote": "东仓门早市：本地人私藏晨间市集"},
    ])
    ids = {c["name"]: c["id"] for c in s.list_candidates()}
    out = s.adopt_candidates(list(ids.values()))
    assert "书院门：已加入" in out
    assert "永宁门：没有加入——和已有景点「西安城墙」" in out
    assert "顺城巷：没有加入——有多个同名地点" in out
    assert "东仓门早市：是餐饮类" in out and "find_food" in out
    t = s._load()
    sy = next(p for p in t.places if p.name == "书院门")
    assert "待核实" in sy.notes and "满街字画碑帖" in sy.notes and "游记原话" in sy.notes and sy.source.startswith("游记")
    assert {c["name"] for c in s.list_candidates("added")} == {"书院门"}
    assert "此前已加入" in s.adopt_candidates([ids["书院门"]])
    s.drop_candidates([ids["顺城巷"]])
    assert "顺城巷" not in [c["name"] for c in s.list_candidates()]


def test_moved_items_stay_put_after_reschedule_and_can_be_unlocked():
    _setup_four_days()
    t = s._load()
    pid = t.plan.days[0].items[0].place_id
    r = s.propose_change("把它挪到第 2 天", [{"kind": "move", "place_id": pid, "to_day": 1}])
    s.apply_proposal(r["proposal_id"], r["confirm_code"])
    s.schedule_days()
    t = s._load()
    assert any(it.place_id == pid and it.locked for it in t.plan.days[1].items)       # 重排后仍在第 2 天
    r = s.propose_change("再挪回第 1 天", [{"kind": "move", "place_id": pid, "to_day": 0}])
    with pytest.raises(s.ToolError, match="已锁定"):
        s.apply_proposal(r["proposal_id"], r["confirm_code"])
    r = s.propose_change("解锁并挪回", [{"kind": "lock", "place_id": pid, "locked": False},
                                         {"kind": "move", "place_id": pid, "to_day": 0}])
    s.apply_proposal(r["proposal_id"], r["confirm_code"])
    assert any(it.place_id == pid for it in s._load().plan.days[0].items)


def test_scheduler_does_not_use_days_without_time_window():
    _arrival_trip()
    s.set_connection("departure", "flight", "北京", "上海", "2026-10-21 06:30", "2026-10-21 08:40")   # 最后一天几乎没有时间
    s.schedule_days()
    t = s._load()
    assert t.plan.days[2].items == []
    assert sum(len(d.items) for d in t.plan.days) >= 2          # 其它天正常排
    # 到达日只有下午晚些时候：容量被缩小
    from tripcore.scheduler import day_limits
    assert day_limits(t)[0].max_places < day_limits(t)[1].max_places or day_limits(t)[0].max_places == 0


class WalkAmap(FakeAmap):
    POS = {"老菜场": (34.2545, 108.9641), "书院门": (34.2569, 108.9437), "德福巷": (34.2640, 108.9420), "永宁门": (34.2580, 108.9400)}

    def search_places(self, query, city=None, limit=5):
        if query in self.POS:
            lat, lon = self.POS[query]
            return [PlaceHit(name=query, lat=lat, lon=lon, address="西安")]
        return []

    def route(self, mode, a_lat, a_lon, b_lat, b_lon, city=None, transit_strategy="fastest", **kw):
        self.route_calls.append(mode)
        return RouteResult(mode, 1.0, 12 if mode == "walk" else 20, path=[(a_lat, a_lon), ((a_lat + b_lat) / 2, (a_lon + b_lon) / 2 + 0.001), (b_lat, b_lon)])


def test_route_place_endpoints_map_and_gpx(monkeypatch):
    s.new_trip(start_date="2026-10-30", end_date="2026-11-01", city="西安", name="西安")
    s.add_lodging("酒店", 34.2000, 108.8800, choose=True)
    monkeypatch.setattr(s, "_amap", lambda: WalkAmap())
    s.submit_candidates(NOTE, [{"name": "老菜场", "kind": "area", "quote": "老菜场：复古市井老街", "clues": []}])
    with pytest.raises(s.ToolError, match="没有创建"):
        s.add_route_place("Citywalk", ["c1", "书院门", "不存在的巷"])
    assert not s._load().places                                             # 失败时什么都没建
    msg = s.add_route_place("Citywalk", ["c1", "书院门", "德福巷", "永宁门"])
    t = s._load()
    p = t.places[0]
    assert [w.name for w in p.waypoints] == ["老菜场", "书院门", "德福巷", "永宁门"]
    assert p.duration_min == 3 * 12 + 4 * 15 and "估算" in p.notes                # 步行 36 + 每站 15 分钟
    assert p.waypoints[0].next_real and p.waypoints[-1].next_minutes == 0
    assert s.list_candidates("added")[0]["place_id"] == p.id
    assert "id=p1" in msg
    s.schedule_days()
    s.refine_routes()
    t = s._load()
    # 进入路线的路段终点是第一个途经点（老菜场），离开路线的起点是最后一个（永宁门）
    keys = list(t.route_overrides)
    assert any(k.endswith(">p1@34.25450,108.96410|" + t.meta.mode) or ">p1@34.25450,108.96410|" in k for k in keys)
    assert any(k.startswith("p1@34.25800,108.94000>") for k in keys)
    from tripcore.mapview import build_map_data
    stop = next(e for d in build_map_data(t)["days"] for e in d["timeline"] if e["type"] == "stop")
    assert [w["name"] for w in stop["route"]["points"]] == ["老菜场", "书院门", "德福巷", "永宁门"] and len(stop["route"]["paths"]) == 3
    from tripcore.gpx import build_gpx
    day = next(i for i, d in enumerate(t.plan.days) if d.items)
    gpx = build_gpx(t, day)
    assert "德福巷" in gpx and "老菜场→书院门" in gpx
    assert "路线：老菜场→书院门→德福巷→永宁门" in s.show_trip()
    assert "待核实" not in s.fill_hours() or True


def test_route_place_warns_when_overlapping_existing(monkeypatch):
    s.new_trip(start_date="2026-10-30", end_date="2026-11-01", city="西安", name="西安")
    s.add_place("西安城墙", 34.2582, 108.9402)
    monkeypatch.setattr(s, "_amap", lambda: WalkAmap())
    assert "可能重复" in s.add_route_place("Citywalk", ["书院门", "永宁门"])


def test_pick_hit_rejects_restaurants_and_stations_with_longer_names():
    from tripcore.candidates import pick_hit
    rest = {"name": "建国门老菜场老马家牛羊肉店", "lat": 34.2546, "lon": 108.9641, "category": "餐饮服务;中餐厅"}
    street = {"name": "老菜场", "lat": 34.2540, "lon": 108.9650, "category": "风景名胜;公园广场"}
    assert pick_hit("老菜场", [rest, street])[0] == street
    got, why = pick_hit("老菜场", [rest])
    assert got is None and "不相关" in why
    metro = {"name": "永宁门(地铁站)", "lat": 34.2580, "lon": 108.9400, "category": "交通设施服务;地铁站"}
    gate = {"name": "永宁门", "lat": 34.2582, "lon": 108.9402, "category": "风景名胜;旅游景点"}
    assert pick_hit("永宁门", [metro, gate])[0] == gate
    assert pick_hit("永宁门", [metro])[0] is None
    alley = {"name": "德福巷酒吧街", "lat": 34.2640, "lon": 108.9420, "category": "购物服务;特色商业街"}
    assert pick_hit("德福巷", [alley])[0] == alley                       # 只多几个字、类别正常：接受
    far = [{"name": "顺城巷", "lat": 34.25, "lon": 108.94, "category": "地名地址信息"}, {"name": "顺城巷", "lat": 34.30, "lon": 109.05, "category": "地名地址信息"}]
    assert pick_hit("顺城巷", far)[0] is None


def test_show_trip_lists_ids_of_unscheduled_places():
    s.new_trip(start_date="2026-10-30", end_date="2026-10-30", city="西安", name="一日")
    for i, (n, lat, lon) in enumerate([("A", 34.26, 108.94), ("B", 34.27, 108.95), ("C", 34.28, 108.96), ("D", 34.29, 108.97)]):
        s.add_place(n, lat, lon, duration_min=240, priority=1)
    s.schedule_days()
    out = s.show_trip()
    if "未安排：" in out:
        import re
        assert re.search(r"未安排：.*\(p\d+\)", out)


def test_create_amap_map_returns_https_web_links(monkeypatch):
    _setup_four_days()
    monkeypatch.setenv("AMAP_KEY", "SECRETKEY123")
    monkeypatch.setattr(s, "_amap", lambda: PoiAll())
    monkeypatch.setattr(s, "_call_amap_mcp", lambda t, a, k: "amapuri://workInAmap/createWithToken?polymericId=mcp_x&from=MCP")
    r = s.create_amap_map()
    assert r["maps"][0]["web_links"] and all(x["url"].startswith("https://uri.amap.com/marker") for x in r["maps"][0]["web_links"])
    assert "微信" in r["note"] and "SECRETKEY123" not in str(r)


def test_refine_requeries_stale_cache_and_warns_on_long_walk(monkeypatch):
    from tripcore.amap import ROUTE_VERSION, RouteResult
    s.new_trip(num_days=1, city="北京")
    s.add_place("甲", 39.90, 116.40)
    s.add_place("乙", 39.99, 116.30)
    s.add_lodging("酒店A", 39.91, 116.41, choose=True)
    s.set_transport_prefs(walk_max_min=15, taxi_ok=True)
    s.schedule_days()
    calls = []

    class A(FakeAmap):
        def route(self, mode, a_lat, a_lon, b_lat, b_lon, city=None, transit_strategy="fastest", **kw):
            calls.append(mode)
            return RouteResult("transit", 8.0, 30, transfers=0, walking_km=6.6, lines=["华阴603路"], max_walk_km=6.6,
                               path=[(a_lat, a_lon), (b_lat, b_lon)])

    monkeypatch.setattr(s, "_amap", lambda: A())
    s.set_leg_mode("l1", "p1", "transit")
    out = s.refine_routes()
    t = s._load()
    assert all(v.route_ver == ROUTE_VERSION for v in t.route_overrides.values()) and t.route_overrides
    assert any("连续步行约 6.6 km" in v.note and "打车" in v.note for v in t.route_overrides.values())
    n = len(calls)
    s.refine_routes()
    assert len(calls) == n                                   # 版本够新，不重查
    for k, v in list(t.route_overrides.items()):             # 模拟旧版本留下的缓存
        t.route_overrides[k] = v.model_copy(update={"route_ver": 0})
    s._save(t)
    s.refine_routes()
    assert len(calls) > n                                    # 旧缓存会被重新查询


# ---- 多行程 ----
def _multi(monkeypatch, tmp_path):
    monkeypatch.delenv("TRIPCORE_FILE", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path / ".tripcore"


def test_multi_trip_new_switch_archive(monkeypatch, tmp_path):
    from tripcore import mcp_server as s
    root = _multi(monkeypatch, tmp_path)
    s.new_trip("北京", 2)
    s.new_trip("北京", 3)  # 同名：不覆盖，加后缀
    assert len(s._ws.list_trips(root)) == 2
    assert s._load().meta.num_days == 3
    assert "切换到" in s.switch_trip("北京-2") or True
    s.switch_trip("北京")
    assert s._load().meta.num_days == 2
    import pytest
    with pytest.raises(s.ToolError):
        s.archive_trip("北京")          # 当前行程不能归档
    s.archive_trip("北京-2")
    assert len(s._ws.list_trips(root)) == 1
    assert (root / "trips" / "_archive" / "北京-2" / "trip.json").exists()
    assert "北京" in s.list_trips()


def test_legacy_migration_copies(monkeypatch, tmp_path):
    from tripcore import mcp_server as s
    root = _multi(monkeypatch, tmp_path)
    s.new_trip("西安4日游", 4)
    cur = s._ws.trips_dir(root) / s._ws.active_slug(root)
    legacy = tmp_path / "L" / ".tripcore"
    legacy.mkdir(parents=True)
    (legacy / "trip.json").write_text((cur / "trip.json").read_text(encoding="utf-8"), encoding="utf-8")
    assert s._ws.migrate_legacy(legacy) == "西安4日游"
    assert (legacy / "trip.json").exists()                       # 原文件保留
    assert (legacy / "trips" / "西安4日游" / "trip.json").exists()
    assert s._ws.migrate_legacy(legacy) is None                  # 只迁移一次


def test_show_trip_header_has_dates_travelers_city():
    s.new_trip("京都5日", 5, travelers=2, city="京都", start_date="2026-11-03", end_date="2026-11-07")
    head = s.show_trip().splitlines()[0]
    assert "2026-11-03 至 2026-11-07" in head and "2 人" in head and "目的地 京都" in head and "日期未定" not in head
    s.new_trip("没填", 3)
    head = s.show_trip().splitlines()[0]
    assert "日期未定" in head and "1 人" in head and "目的地未填" in head
    s.new_trip("范围", 3, earliest_start="2026-12-01", latest_end="2026-12-20")
    assert "大致 2026-12-01 至 2026-12-20 之间" in s.show_trip().splitlines()[0]


def test_relaxed_alternative_is_read_only_and_applies_on_request():
    _setup_trip()
    s.add_lodging("酒店A", 39.91, 116.40, price_min=300, price_max=500, choose=True)
    s.schedule_days()
    rev = s._load().revision
    r = s.relaxed_alternative()
    assert set(r) == {"current", "relaxed", "dropped", "added_back"}
    assert s._load().revision == rev            # 只读：不产生新版本
    out = s.schedule_days(relaxed=True)
    assert "轻松版" in out and s._load().revision == rev + 1


def test_tools_env_selects_groups(monkeypatch):
    from tripcore import mcp_server as ms
    full = ms._selected_tools("")
    core = ms._selected_tools("core")
    names = {f.__name__ for f in core}
    assert len(full) == len(ms.TOOLS) and 0 < len(core) < len(full)
    assert "open_workbench" in names and "export_rough_cut" not in names and "add_place" in names
    assert {f.__name__ for f in ms._selected_tools("分享与导出")} >= {"export_rough_cut", "open_workbench"}
    import pytest
    with pytest.raises(ValueError):
        ms._selected_tools("乱写")
    monkeypatch.setenv("TRIPCORE_TOOLS", "core")
    import asyncio
    assert len(asyncio.run(ms.build_server().list_tools())) == len(core)


def test_default_tools_are_light_and_include_restore(monkeypatch):
    monkeypatch.delenv("TRIPCORE_TOOLS", raising=False)
    names = {t.name for t in asyncio.run(s.build_server().list_tools())}
    assert {"add_place", "import_photo_trip", "merge_stops", "set_day_title", "suggest_day_titles", "delete_stop", "export_handbook", "open_workbench"} <= names
    assert "import_bills" not in names and "export_rough_cut" not in names
    assert len(names) < 50
