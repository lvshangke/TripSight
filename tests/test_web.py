import json
import threading
import urllib.error
import urllib.request
from datetime import date

import pytest

from tripcore import mcp_server as s
from tripcore import web
from tripcore.dates import apply_dates
from tripcore.models import DateMode


@pytest.fixture
def server():
    s.new_trip("工作台", 2)
    for i, nm in enumerate(["甲", "乙", "丙", "丁"]):
        s.add_place(nm, 34.2 + i * 0.01, 108.9 + i * 0.01)
    s.schedule_days()
    state = {"last": 0}
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler("tok", state))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base
    httpd.shutdown()
    httpd.server_close()


def call(base, path, body=None, headers=None, method=None):
    data = None if body is None else json.dumps(body).encode()
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(base + path, data=data, headers=h, method=method or ("POST" if body is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode()) if "json" in r.headers["Content-Type"] else r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def state(base):
    return call(base, "/tok/api/state")[1]


def test_token_and_host_checks(server):
    assert call(server, "/api/state")[0] == 404
    assert call(server, "/wrong/api/state")[0] == 404
    assert call(server, "/tok/api/state", headers={"Host": "evil.example.com"})[0] == 403
    assert call(server, "/tok/api/undo", {"base_revision": 0}, headers={"Origin": "https://evil.example.com"})[0] == 403
    code, html = call(server, "/tok/")
    assert code == 200 and "TripSight" in html and "<script" in html


def test_post_requires_json_and_small_body(server):
    req = urllib.request.Request(server + "/tok/api/undo", data=b"x", headers={"Content-Type": "text/plain"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 415


def test_state_shape(server):
    st = state(server)
    assert st["days"] and st["days"][0]["items"] and st["dates"]["start"] is None and not st["can_undo"] or st["can_undo"] in (True, False)
    assert "tiles" in st["map"]


def test_move_preview_apply_and_undo(server):
    st = state(server)
    pid = st["days"][0]["items"][0]["place_id"]
    code, pv = call(server, "/tok/api/preview", {"base_revision": st["revision"], "ops": [{"kind": "move", "place_id": pid, "to_day": 1, "to_position": 0}]})
    assert code == 200 and any("移动" in c for c in pv["changes"]) and "confirm_code" not in pv
    assert state(server)["revision"] == st["revision"]                 # 预览不改行程
    code, ap = call(server, "/tok/api/apply", {"base_revision": st["revision"], "proposal_id": pv["proposal_id"]})
    assert code == 200
    st2 = state(server)
    assert st2["days"][1]["items"][0]["place_id"] == pid and st2["revision"] > st["revision"]
    assert call(server, "/tok/api/undo", {"base_revision": st2["revision"]})[0] == 200
    assert state(server)["days"][0]["items"][0]["place_id"] == pid


def test_moving_locked_item_requires_unlock_op(server):
    st = state(server)
    pid = st["days"][0]["items"][0]["place_id"]
    mv = {"kind": "move", "place_id": pid, "to_day": 1, "to_position": 0}
    pv = call(server, "/tok/api/preview", {"base_revision": st["revision"], "ops": [mv]})[1]
    call(server, "/tok/api/apply", {"base_revision": st["revision"], "proposal_id": pv["proposal_id"]})
    st = state(server)
    assert next(i for i in st["days"][1]["items"] if i["place_id"] == pid)["locked"]
    code, err = call(server, "/tok/api/preview", {"base_revision": st["revision"], "ops": [{**mv, "to_day": 0}]})
    assert code == 400 and "锁定" in err["error"]
    code, pv = call(server, "/tok/api/preview", {"base_revision": st["revision"],
                                                  "ops": [{"kind": "lock", "place_id": pid, "locked": False}, {**mv, "to_day": 0}]})
    assert code == 200


def test_remove_to_unscheduled(server):
    st = state(server)
    pid = st["days"][0]["items"][0]["place_id"]
    pv = call(server, "/tok/api/preview", {"base_revision": st["revision"], "ops": [{"kind": "remove", "place_id": pid}]})[1]
    call(server, "/tok/api/apply", {"base_revision": st["revision"], "proposal_id": pv["proposal_id"]})
    assert pid in [u["place_id"] for u in state(server)["unscheduled"]]


def test_stale_revision_rejected(server):
    st = state(server)
    pid = st["days"][0]["items"][0]["place_id"]
    s.set_travelers(2)                                                   # 别处（agent）改了行程
    code, err = call(server, "/tok/api/preview", {"base_revision": st["revision"], "ops": [{"kind": "remove", "place_id": pid}]})
    assert code == 409 and "版本" in err["error"]


def test_bad_ops_rejected(server):
    st = state(server)
    assert call(server, "/tok/api/preview", {"base_revision": st["revision"], "ops": [{"kind": "explode"}]})[0] == 400
    assert call(server, "/tok/api/preview", {"base_revision": st["revision"], "ops": []})[0] == 400
    assert call(server, "/tok/api/apply", {"base_revision": st["revision"], "proposal_id": "nope"})[0] == 404


def test_dates_via_web_and_clear(server):
    st = state(server)
    code, r = call(server, "/tok/api/dates", {"base_revision": st["revision"], "start": "2026-11-01", "end": "2026-11-03"})
    assert code == 200 and "共 3 天" in r["message"] and "重新分天" in r["message"]
    st = state(server)
    assert st["dates"] == {"start": "2026-11-01", "end": "2026-11-03", "mode": "exact", "num_days": 3}
    assert call(server, "/tok/api/dates", {"base_revision": st["revision"], "start": "2026-11-05", "end": "2026-11-01"})[0] == 400
    assert call(server, "/tok/api/dates", {"base_revision": st["revision"], "start": "2026-11-05", "end": None})[0] == 400
    assert call(server, "/tok/api/dates", {"base_revision": st["revision"], "start": None, "end": None})[0] == 200
    assert state(server)["dates"]["start"] is None


def test_apply_dates_core_and_set_dates_tool():
    s.new_trip("日期", 3)
    t = s._load()
    new, notes = apply_dates(t, date(2026, 11, 1), date(2026, 11, 2))
    assert new.meta.date_mode == DateMode.EXACT and new.meta.num_days == 2 and new.revision == t.revision + 1 and notes
    with pytest.raises(ValueError):
        apply_dates(t, date(2026, 11, 1), None)
    with pytest.raises(ValueError):
        apply_dates(t, date(2026, 11, 1), date(2026, 12, 20))             # 超过 30 天
    out = s.set_dates("2026-11-01", "2026-11-04")
    assert "共 4 天" in out and s._load().meta.num_days == 4
    s.undo()
    assert s._load().meta.num_days == 3
    assert "清除" in s.set_dates()
    with pytest.raises(s.ToolError):
        s.set_dates("2026-11-04", "2026-11-01")


def test_dates_clear_weather_snapshot():
    from tripcore.models import WeatherSnap
    s.new_trip("天气", 2, start_date="2026-11-01", end_date="2026-11-02")
    t = s._load()
    s._save(t.model_copy(update={"weather": {"2026-11-01": WeatherSnap(day_weather="晴", night_weather="", fetched="2026-10-18")}}))
    out = s.set_dates("2026-11-02", "2026-11-03")
    assert s._load().weather == {} and "天气" in out


# ---- 用餐点、通勤行、自动补路线 ----
def _add_meal(after="p1", day=0):
    from tripcore.models import Meal
    t = s._load()
    s._save(t.model_copy(update={"meals": [Meal(id="m1", day=day, after_place_id=after, name="某面馆", lat=34.2, lon=108.9,
                                                rating=4.5, cost_per_person=30, opening_hours="周一 09:00-21:00", hours_source="amap")]}))


def test_meal_follows_place_when_moved_across_days(server):
    _add_meal()
    st = state(server)
    assert any(r["t"] == "meal" and r["name"] == "某面馆" for r in st["days"][0]["rows"])
    pid = "p1"
    pv = call(server, "/tok/api/preview", {"base_revision": st["revision"], "ops": [{"kind": "move", "place_id": pid, "to_day": 1, "to_position": 0}]})[1]
    call(server, "/tok/api/apply", {"base_revision": st["revision"], "proposal_id": pv["proposal_id"]})
    st = state(server)
    assert s._load().meals[0].day == 1
    assert any(r["t"] == "meal" for r in st["days"][1]["rows"]) and not any(r["t"] == "meal" for r in st["days"][0]["rows"])
    assert st["orphan_meals"] == []


def test_meal_kept_and_listed_when_place_removed(server):
    _add_meal()
    st = state(server)
    pv = call(server, "/tok/api/preview", {"base_revision": st["revision"], "ops": [{"kind": "remove", "place_id": "p1"}]})[1]
    call(server, "/tok/api/apply", {"base_revision": st["revision"], "proposal_id": pv["proposal_id"]})
    st = state(server)
    assert len(s._load().meals) == 1 and st["orphan_meals"][0]["name"] == "某面馆"


def test_agent_move_also_syncs_meal_day():
    s.new_trip("同步", 2)
    for i, nm in enumerate(["甲", "乙", "丙", "丁"]):
        s.add_place(nm, 34.2 + i * 0.01, 108.9 + i * 0.01)
    s.schedule_days()
    _add_meal()
    out = s.propose_change("跨天", [{"kind": "move", "place_id": "p1", "to_day": 1}])
    s.apply_proposal(out["proposal_id"], out["confirm_code"])
    assert s._load().meals[0].day == 1


def test_rows_have_legs_with_real_flag_and_hotel(server):
    st = state(server)
    rows = st["days"][0]["rows"]
    kinds = [r["t"] for r in rows]
    assert kinds.count("stop") == 2 and "leg" in kinds
    leg = next(r for r in rows if r["t"] == "leg")
    assert leg["minutes"] > 0 and leg["real"] is False and leg["mode"]


class FakeRoutes:
    provider = "amap"

    def __init__(self):
        self.calls = 0

    def route(self, mode, a, b, c, d, city=None, **kw):
        from tripcore.amap import RouteResult
        self.calls += 1
        return RouteResult(mode, 1.0, 7, path=[(a, b), (c, d)])


def test_refine_squashes_into_previous_undo_step(server, monkeypatch):
    fake = FakeRoutes()
    monkeypatch.setattr(s, "_amap", lambda: fake)
    st = state(server)
    pv = call(server, "/tok/api/preview", {"base_revision": st["revision"], "ops": [{"kind": "move", "place_id": "p1", "to_day": 0, "to_position": 1}]})[1]
    assert pv["affected_days"] == [1]
    call(server, "/tok/api/apply", {"base_revision": st["revision"], "proposal_id": pv["proposal_id"]})
    st = state(server)
    code, r = call(server, "/tok/api/refine", {"base_revision": st["revision"], "day": 1})
    assert code == 200 and r["ok"] and fake.calls > 0
    st = state(server)
    assert any(x["real"] for x in st["days"][0]["rows"] if x["t"] == "leg")
    assert call(server, "/tok/api/undo", {"base_revision": st["revision"]})[0] == 200      # 一步回到拖拽之前
    assert state(server)["days"][0]["items"][0]["place_id"] == "p1"


def test_refine_without_key_is_not_an_error(server, monkeypatch):
    monkeypatch.setattr(s, "_amap", lambda: None)
    st = state(server)
    code, r = call(server, "/tok/api/refine", {"base_revision": st["revision"], "day": None})
    assert code == 200 and r["ok"] is False and "key" in r["message"]


# ---- 改日期自动重新分天 ----
def _plan_trip(n=4, days=2):
    s.new_trip("改日期", days)
    for i in range(n):
        s.add_place(f"点{i}", 34.2 + i * 0.01, 108.9 + i * 0.01)
    s.schedule_days()


@pytest.mark.parametrize("a,b,n", [("2026-10-30", "2026-11-02", 4), ("2026-12-30", "2027-01-01", 3), ("2026-11-05", "2026-11-05", 1)])
def test_change_days_replans_and_stays_in_range(a, b, n):
    _plan_trip()
    out = s.set_dates(a, b)
    t = s._load()
    assert t.meta.num_days == n and len(t.plan.days) == n and "重新分天" in out
    assert [d.index for d in t.plan.days] == list(range(n))
    placed = {it.place_id for d in t.plan.days for it in d.items} | {u.place_id for u in t.plan.unscheduled}
    assert placed == {p.id for p in t.places}              # 一个景点都没丢
    assert t.day_date(n - 1).isoformat() == b
    s.undo()
    assert s._load().meta.num_days == 2 and len(s._load().plan.days) == 2      # 一步撤销回到改之前


def test_same_length_keeps_plan_and_locked_items_stay():
    _plan_trip()
    before = [[i.place_id for i in d.items] for d in s._load().plan.days]
    s.set_dates("2026-11-01", "2026-11-02")
    assert [[i.place_id for i in d.items] for d in s._load().plan.days] == before        # 天数没变：不重排
    out = s.propose_change("锁定", [{"kind": "move", "place_id": "p1", "to_day": 0, "to_position": 0}])
    s.apply_proposal(out["proposal_id"], out["confirm_code"])                            # 移动后默认锁定
    s.set_dates("2026-11-01", "2026-11-04")
    t = s._load()
    assert t.plan.days[0].items[0].place_id == "p1" and t.plan.days[0].items[0].locked


def test_locked_item_in_removed_day_is_replaced_not_lost():
    _plan_trip(days=3)
    out = s.propose_change("锁定在第3天", [{"kind": "move", "place_id": "p1", "to_day": 2}])
    s.apply_proposal(out["proposal_id"], out["confirm_code"])
    s.set_dates("2026-11-01", "2026-11-02")
    t = s._load()
    seen = {it.place_id for d in t.plan.days for it in d.items} | {u.place_id for u in t.plan.unscheduled}
    assert "p1" in seen and len(t.plan.days) == 2


def test_dates_without_plan_just_sets_days():
    s.new_trip("没分天", 2)
    s.add_place("甲", 34.2, 108.9)
    out = s.set_dates("2026-11-01", "2026-11-03")
    assert s._load().plan is None and "还没有分天" in out


# ---- 聊天转发 ----
import http.server


class _FakeNano(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response({"/health": 200, "/v1/chat/completions": 405}.get(self.path, 404))
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        _FakeNano.seen.append((self.path, json.loads(self.rfile.read(n)), dict(self.headers)))
        if self.headers.get("X-Fail"):
            pass
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for part in ["你", "好"]:
            self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"content": part}}]}, ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")


@pytest.fixture
def nano(monkeypatch):
    _FakeNano.seen = []
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FakeNano)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv("NANOBOT_API_URL", f"http://127.0.0.1:{httpd.server_address[1]}")
    monkeypatch.delenv("NANOBOT_API_KEY", raising=False)
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def raw_post(base, path, body, headers=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_chat_streams_and_sends_session(server, nano, monkeypatch):
    monkeypatch.setenv("NANOBOT_API_KEY", "NANOKEY")
    code, body = raw_post(server, "/tok/api/chat", {"message": "加一个景点"})
    assert code == 200 and "你" in body and "[DONE]" in body and "NANOKEY" not in body
    path, sent, headers = _FakeNano.seen[0]
    assert path == "/v1/chat/completions" and sent["session_id"] == "tripsight-workbench" and sent["stream"] is True
    assert sent["messages"] == [{"role": "user", "content": "加一个景点"}] and headers["Authorization"] == "Bearer NANOKEY"


def test_chat_guards(server, nano):
    assert raw_post(server, "/api/chat", {"message": "x"})[0] == 404                                   # 没有令牌
    assert raw_post(server, "/tok/api/chat", {"message": "x"}, {"Origin": "https://evil.example.com"})[0] == 403
    assert raw_post(server, "/tok/api/chat", {"message": "  "})[0] == 400
    assert raw_post(server, "/tok/api/chat", {"message": "字" * 4001})[0] == 400
    assert raw_post(server, "/tok/api/chat", {"message": 5})[0] == 400
    assert _FakeNano.seen == []                                                                        # 被拒绝的请求不会到 nanobot


def test_chat_only_loopback(server, monkeypatch):
    monkeypatch.setenv("NANOBOT_API_URL", "http://evil.example.com:8900")
    code, body = raw_post(server, "/tok/api/chat", {"message": "hi"})
    assert code == 400 and "本机" in body
    assert call(server, "/tok/api/chat_status")[1]["connected"] is False


def test_chat_unreachable_is_friendly(server, monkeypatch):
    monkeypatch.setenv("NANOBOT_API_URL", "http://127.0.0.1:9")            # 没人监听
    code, body = raw_post(server, "/tok/api/chat", {"message": "hi"})
    assert code == 502 and "nanobot" in body and "Traceback" not in body


def test_chat_status_and_rev(server, nano):
    assert call(server, "/tok/api/chat_status")[1]["connected"] is True
    assert call(server, "/tok/api/rev")[1]["revision"] == state(server)["revision"]
    s.set_travelers(3)
    assert call(server, "/tok/api/rev")[1]["revision"] > 0


def test_version_endpoint_and_fingerprint(server):
    code, v = call(server, "/tok/api/version")
    assert code == 200 and v["version"] == web.CODE_VERSION and len(web.CODE_VERSION) == 12
    assert web.code_version() == web.CODE_VERSION


def test_launch_restarts_stale_workbench(tmp_path, monkeypatch):
    """后台还在跑旧代码的工作台（没有 version 接口）时，launch 要结束它并重新启动。"""
    import os, signal, subprocess, sys, time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Old(BaseHTTPRequestHandler):               # 假装是旧版工作台：有 state，没有 version
        def log_message(self, *a):
            pass

        def do_GET(self):
            ok = self.path.endswith("api/state")
            self.send_response(200 if ok else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Old)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    root = tmp_path / "root"
    root.mkdir()
    (root / "workbench.json").write_text(json.dumps({"pid": victim.pid, "url": f"http://127.0.0.1:{httpd.server_address[1]}/tok/"}))
    spawned = []

    class FakeProc:
        pid = 4242

        def poll(self):
            return None

    def fake_popen(cmd, **kw):
        spawned.append(cmd)
        (root / "workbench.url").write_text("http://127.0.0.1:1/newtok/")
        return FakeProc()

    monkeypatch.setattr(web.subprocess, "Popen", fake_popen)
    try:
        out = web.launch(root)
        assert victim.wait(timeout=5) is not None                    # 旧进程被结束
        assert spawned and "newtok" in out and "已启动" in out
    finally:
        httpd.shutdown()
        httpd.server_close()
        if victim.poll() is None:
            victim.kill()


def test_launch_keeps_current_version(tmp_path, monkeypatch, server):
    import subprocess, sys
    root = tmp_path / "root2"
    root.mkdir()
    keep = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (root / "workbench.json").write_text(json.dumps({"pid": keep.pid, "url": server + "/tok/"}))
        monkeypatch.setattr(web.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应重启")))
        out = web.launch(root)
        assert "已在运行" in out and keep.poll() is None
    finally:
        keep.kill()


def test_chat_status_needs_api_route(server, nano, monkeypatch):
    """nanobot 在运行但没开聊天接口（/v1/chat/completions 是 404）：不能显示已连接。"""
    monkeypatch.setattr(_FakeNano, "do_GET", lambda self: (self.send_response(200 if self.path == "/health" else 404), self.end_headers()))
    r = call(server, "/tok/api/chat_status")[1]
    assert r["connected"] is False and "plugins enable api" in r["message"]


def test_chat_status_down(server, monkeypatch):
    monkeypatch.setenv("NANOBOT_API_URL", "http://127.0.0.1:9")
    assert call(server, "/tok/api/chat_status")[1]["connected"] is False


@pytest.fixture
def multi(tmp_path, monkeypatch):
    monkeypatch.delenv("TRIPCORE_FILE", raising=False)
    monkeypatch.setattr(s.Path, "home", classmethod(lambda cls: tmp_path))
    s.new_trip("甲行程", 2)
    s.add_place("景一", 34.2, 108.9)
    s.new_trip("乙行程", 3)
    s.add_place("景二", 31.2, 121.4)
    s.add_place("景三", 31.3, 121.5)
    state_ = {"last": 0}
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler("tok", state_))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_trips_list_and_switch(multi):
    r = call(multi, "/tok/api/trips")[1]
    assert r["single"] is False and [t["name"] for t in r["trips"]] is not None and {t["name"] for t in r["trips"]} == {"甲行程", "乙行程"}
    assert state(multi)["title"] == "乙行程"
    other = next(t["slug"] for t in r["trips"] if t["name"] == "甲行程")
    code, out = call(multi, "/tok/api/switch", {"slug": other})
    assert code == 200 and out["title"] == "甲行程"
    st = state(multi)
    assert st["title"] == "甲行程" and st["trip"] == other
    assert call(multi, "/tok/api/rev")[1]["trip"] == other
    assert "甲行程" in s.list_trips() and "▶ 甲行程" in s.list_trips()          # agent 看到的当前行程也变了


def test_switch_rejects_bad_input(multi):
    assert call(multi, "/tok/api/switch", {"slug": "不存在"})[0] == 404
    assert call(multi, "/tok/api/switch", {})[0] == 400
    assert call(multi, "/tok/api/switch", {"slug": 5})[0] == 400
    assert raw_post(multi, "/api/switch", {"slug": "x"})[0] == 404                      # 没有令牌
    assert state(multi)["title"] == "乙行程"


def test_switch_not_available_in_single_file_mode(server):
    r = call(server, "/tok/api/trips")[1]
    assert r["single"] is True and len(r["trips"]) == 1
    assert call(server, "/tok/api/switch", {"slug": "x"})[0] == 400


def test_new_trip_from_web_switches_and_keeps_old(multi):
    code, out = call(multi, "/tok/api/new_trip", {"name": "东京5日", "city": "东京", "num_days": 5, "travelers": 2,
                                                  "start": None, "end": None, "pace": "relaxed"})
    assert code == 200 and out["title"] == "东京5日" and out["trip"]
    st = state(multi)
    assert st["title"] == "东京5日" and st["trip"] == out["trip"] and st["dates"]["num_days"] == 5
    names = {t["name"] for t in call(multi, "/tok/api/trips")[1]["trips"]}
    assert names == {"甲行程", "乙行程", "东京5日"}                      # 原来的行程都还在
    call(multi, "/tok/api/new_trip", {"name": "东京5日", "num_days": 2})
    slugs = [t["slug"] for t in call(multi, "/tok/api/trips")[1]["trips"] if t["name"] == "东京5日"]
    assert len(slugs) == 2 and len(set(slugs)) == 2                  # 重名自动加后缀，不覆盖


def test_new_trip_with_dates_sets_days_and_prefs_applied(multi):
    code, out = call(multi, "/tok/api/new_trip", {"name": "有日期", "num_days": 1, "start": "2026-11-01", "end": "2026-11-04"})
    assert code == 200
    st = state(multi)
    assert st["dates"]["start"] == "2026-11-01" and st["dates"]["num_days"] == 4


@pytest.mark.parametrize("body", [
    {}, {"name": "  "}, {"name": 5}, {"name": "x" * 41}, {"name": "a", "num_days": 0}, {"name": "a", "num_days": 31},
    {"name": "a", "num_days": "3"}, {"name": "a", "num_days": True}, {"name": "a", "travelers": 0}, {"name": "a", "travelers": 51},
    {"name": "a", "pace": "fast"}, {"name": "a", "start": "2026-11-01"}, {"name": "a", "start": "2026-11-01", "end": "bad"},
    {"name": "a", "start": "2026-11-01", "end": "2026-12-31"}, {"name": "a", "start": "2026-11-05", "end": "2026-11-01"},
    {"name": "a", "city": 5}, {"name": "a", "start": 20261101, "end": 20261102},
])
def test_new_trip_rejects_bad_input_and_changes_nothing(multi, body):
    before = state(multi)["title"]
    code, _ = call(multi, "/tok/api/new_trip", body)
    assert code == 400
    assert state(multi)["title"] == before and len(call(multi, "/tok/api/trips")[1]["trips"]) == 2


def test_new_trip_web_guards(server, multi):
    assert raw_post(multi, "/api/new_trip", {"name": "x"})[0] == 404                                  # 没有令牌
    assert raw_post(multi, "/tok/api/new_trip", {"name": "x"}, {"Origin": "https://evil.example.com"})[0] == 403
    assert len(call(multi, "/tok/api/trips")[1]["trips"]) == 2


def test_new_trip_disabled_in_single_file_mode(server):
    before = state(server)["title"]
    assert call(server, "/tok/api/new_trip", {"name": "覆盖"})[0] == 400
    assert state(server)["title"] == before


def test_mcp_new_trip_rejects_over_30_days_by_dates():
    with pytest.raises(s.ToolError):
        s.new_trip("太长", 3, start_date="2026-11-01", end_date="2026-12-15")


# ---- 加景点 / 改停留时长 ----
def _fake_lookup(monkeypatch, found=True, source="amap"):
    def fake(query, city=None):
        if not found:
            return {"found": False, "source": "osm", "error": "没找到", "note": ""}
        return {"found": True, "source": source, "name": "大雁塔", "lat": 34.2186, "lon": 108.9647, "warning": "", "note": "",
                "candidates": [{"name": "大雁塔", "lat": 34.2186, "lon": 108.9647, "address": "雁塔路", "category": "风景名胜", "rating": 4.8, "opentime_today": "08:00-17:30"},
                               {"name": "大雁塔北广场", "lat": 34.2200, "lon": 108.9650, "address": "雁塔北路", "category": "广场", "rating": None, "opentime_today": ""}]}
    monkeypatch.setattr(s, "lookup_coords", fake)


def test_lookup_hides_coords_and_add_place_uses_candidate(server, monkeypatch):
    _fake_lookup(monkeypatch)
    code, r = call(server, "/tok/api/lookup", {"query": "大雁塔"})
    assert code == 200 and len(r["candidates"]) == 2 and "lat" not in json.dumps(r) and "lon" not in json.dumps(r)
    st0 = state(server)
    code, out = call(server, "/tok/api/add_place", {"base_revision": st0["revision"], "cid": r["candidates"][0]["cid"], "duration_min": 120})
    assert code == 200
    st = state(server)
    assert st["revision"] > st0["revision"]
    new = next(u for u in st["unscheduled"] if u["name"] == "大雁塔")
    assert new["duration_min"] == 120
    p = next(p for p in s._load().places if p.name == "大雁塔")
    assert (p.lat, p.lon) == (34.2186, 108.9647) and p.category == "风景名胜"            # 坐标来自查询结果
    call(server, "/tok/api/undo", {"base_revision": st["revision"]})
    assert all(p.name != "大雁塔" for p in s._load().places)                                # 可撤销


def test_add_place_rejects_made_up_coords_dupes_and_bad_input(server, monkeypatch):
    _fake_lookup(monkeypatch)
    rev_ = state(server)["revision"]
    assert call(server, "/tok/api/add_place", {"base_revision": rev_, "name": "编的", "lat": 1, "lon": 2})[0] == 400      # 没有 cid：不能手填坐标
    assert call(server, "/tok/api/add_place", {"base_revision": rev_, "cid": "nope"})[0] == 400
    cid = call(server, "/tok/api/lookup", {"query": "大雁塔"})[1]["candidates"][0]["cid"]
    for bad in (9, 721, "90", True, None):
        assert call(server, "/tok/api/add_place", {"base_revision": rev_, "cid": cid, "duration_min": bad})[0] == 400
    assert call(server, "/tok/api/add_place", {"base_revision": rev_ + 5, "cid": cid})[0] == 409
    assert call(server, "/tok/api/add_place", {"base_revision": rev_, "cid": cid})[0] == 200
    cid2 = call(server, "/tok/api/lookup", {"query": "大雁塔"})[1]["candidates"][0]["cid"]
    assert call(server, "/tok/api/add_place", {"base_revision": state(server)["revision"], "cid": cid2})[0] == 400         # 重复
    assert sum(1 for p in s._load().places if p.name == "大雁塔") == 1


def test_lookup_not_found_and_osm_warning_and_bad_query(server, monkeypatch):
    _fake_lookup(monkeypatch, found=False)
    code, r = call(server, "/tok/api/lookup", {"query": "不存在的地方"})
    assert code == 200 and r["candidates"] == [] and r["message"]
    _fake_lookup(monkeypatch, source="osm")
    assert "OpenStreetMap" in call(server, "/tok/api/lookup", {"query": "x"})[1]["warning"]
    for bad in ({}, {"query": "  "}, {"query": 5}, {"query": "字" * 61}):
        assert call(server, "/tok/api/lookup", bad)[0] == 400
    assert raw_post(server, "/api/lookup", {"query": "x"})[0] == 404


def test_set_duration_preview_apply_undo(server):
    st = state(server)
    pid = st["days"][0]["items"][0]["place_id"]
    old = next(p.duration_min for p in s._load().places if p.id == pid)
    code, pv = call(server, "/tok/api/preview", {"base_revision": st["revision"], "ops": [{"kind": "set_duration", "place_id": pid, "minutes": old + 30}]})
    assert code == 200 and any(f"{old} → {old + 30} 分钟" in c for c in pv["changes"])
    assert next(p.duration_min for p in s._load().places if p.id == pid) == old                    # 预览不改动
    assert call(server, "/tok/api/apply", {"base_revision": st["revision"], "proposal_id": pv["proposal_id"]})[0] == 200
    assert next(p.duration_min for p in s._load().places if p.id == pid) == old + 30
    assert state(server)["days"][0]["items"][0]["duration_min"] == old + 30
    call(server, "/tok/api/undo", {"base_revision": state(server)["revision"]})
    assert next(p.duration_min for p in s._load().places if p.id == pid) == old


@pytest.mark.parametrize("minutes", [9, 721, 0, -5, None])
def test_set_duration_rejects_out_of_range(server, minutes):
    st = state(server)
    pid = st["days"][0]["items"][0]["place_id"]
    assert call(server, "/tok/api/preview", {"base_revision": st["revision"], "ops": [{"kind": "set_duration", "place_id": pid, "minutes": minutes}]})[0] == 400


def test_set_duration_via_agent_proposal_tool():
    s.new_trip("t", 1)
    s.add_place("甲", 34.2, 108.9)
    pid = s._load().places[0].id
    r = s.propose_change("改时长", [{"kind": "set_duration", "place_id": pid, "minutes": 150}])
    assert "90 → 150 分钟" in r["changes"][0]


def test_refine_reports_more_when_capped(server, monkeypatch):
    monkeypatch.setattr(s, "refine_routes", lambda day=None: "已更新 12 段为高德真实路线，0 段此前已查过。\n还有部分路段没查，请再调用一次 refine_routes。")
    r = call(server, "/tok/api/refine", {"base_revision": state(server)["revision"], "day": None})[1]
    assert r["ok"] is True and r["more"] is True
    monkeypatch.setattr(s, "refine_routes", lambda day=None: "已更新 2 段为高德真实路线，5 段此前已查过。")
    assert call(server, "/tok/api/refine", {"base_revision": state(server)["revision"], "day": None})[1]["more"] is False


def test_snapshot_has_no_lodging_editor_block(server):
    assert "lodging" not in state(server)
    for r in ("lodging_preview", "lodging_apply", "add_lodging"):
        assert call(server, f"/tok/api/{r}", {"base_revision": 1})[0] == 404
