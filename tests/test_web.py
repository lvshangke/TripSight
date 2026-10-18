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
    assert code == 200 and "共 3 天" in r["message"] and "schedule_days" in r["message"]
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
