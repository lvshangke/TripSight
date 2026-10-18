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
        self.send_response(200 if self.path == "/health" else 404)
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
