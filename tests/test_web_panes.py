"""工作台新增的三块：日历导出按钮、视频页、足迹页（后端接口 + 页面里有对应入口）。"""

import json
from datetime import datetime, timedelta

import pytest

pytest.importorskip("mcp")

from tests.test_web import call, server  # noqa: F401
from tripcore import mcp_server as s
from tripcore.webpage import page_html


def test_page_has_new_entries():
    PAGE = page_html()
    for k in ('data-pg="fp"', 'id="sh_cal"', 'id="hv_go"', 'id="fmap"'):
        assert k in PAGE, k
    assert 'data-pg="vid"' not in PAGE and 'id="pane_vid"' not in PAGE


def test_calendar_export_needs_dates_then_writes_ics(server, tmp_path):
    s.new_trip(name="日历", num_days=1)
    s.add_place("甲", 28.7, 121.4, duration_min=60)
    s.schedule_days()
    code, r = call(server, "/tok/api/cal_export", {})
    assert code == 400 and "日期" in r["error"]
    s.set_dates("2026-06-19", "2026-06-19")
    code, r = call(server, "/tok/api/cal_export", {})
    assert code == 200 and ".ics" in r["message"]
    f = next(s.trip_path().with_name("exports").glob("*.ics"))
    assert f.read_text(encoding="utf-8").count("BEGIN:VEVENT") == 1


def test_video_routes_validate_input(server, tmp_path):
    s.new_trip(name="v", num_days=1)
    assert call(server, "/tok/api/video_scan", {})[0] == 400
    assert call(server, "/tok/api/video_scan", {"folder": str(tmp_path / "没有")})[0] == 400
    assert call(server, "/tok/api/video_cut", {"folder": str(tmp_path), "target_seconds": "abc"})[0] == 400


def test_footprint_page_empty_then_filled(server):
    s.new_trip(name="足", num_days=1)
    code, r = call(server, "/tok/api/fp_state")
    assert code == 200 and "还没有可统计" in r["message"] and r["html"] == ""
    s.add_place("甲", 28.70, 121.40, duration_min=60)
    s.add_place("乙", 28.80, 121.50, duration_min=60)
    s.schedule_days()
    (s.trip_path().parent / "photo_trip.json").write_text("{}", encoding="utf-8")
    code, r = call(server, "/tok/api/fp_state")
    assert code == 200 and "1 趟" in r["message"] and "<circle" in r["html"]
    code, r = call(server, "/tok/api/fp_build", {"basemap": True})
    assert code == 200 and "没有加底图" in r["message"]


def test_reveal_exports_rejects_outside(tmp_path, monkeypatch):
    import pytest
    from tripcore import web
    monkeypatch.setenv("TRIPCORE_EXPORT_DIR", str(tmp_path / "x"))
    with pytest.raises(web.HttpError):
        web.reveal_exports({"path": "/etc"})


def test_make_editable_converts_ref_to_copy(tmp_path):
    from PIL import Image
    from tripcore import photos as ph
    src = tmp_path / "o.jpg"; Image.new("RGB", (40, 30), "red").save(src)
    folder = tmp_path / "ph"; folder.mkdir(); items = []
    row = ph.add_ref(folder, items, str(src), None, 0, "")
    assert ph.is_ref(folder, row["file"])
    out = ph.make_editable(folder, row["file"])
    assert out.exists() and not ph.is_ref(folder, row["file"]) and src.exists()


def test_hb_preview_basemap_and_thumbs(tmp_path, monkeypatch):
    from datetime import datetime
    from PIL import Image
    from tests.test_phototrip import _jpg
    from tripcore import web
    d = tmp_path / "a"; d.mkdir()
    for i in range(3):
        _jpg(d / f"{i}.jpg", datetime(2026, 6, 19, 15, i), 28.85, 121.15)
    r = web.hb_preview({"folder": str(d), "min_photos": 1})
    assert r["basemap"] is None and r["stops"][0]["thumbs"]

    class FakeClient:
        def static_map(self, lat, lon, z, w, h):
            b = __import__("io").BytesIO(); Image.new("RGB", (w, h), "green").save(b, "PNG"); return b.getvalue()
    from tripcore import amap
    monkeypatch.setattr(amap.AmapClient, "from_env", classmethod(lambda cls, log_path=None: FakeClient()))
    monkeypatch.setenv("TRIPCORE_FILE", str(tmp_path / "t.json"))
    r = web.hb_preview({"folder": str(d), "min_photos": 1, "basemap": True})
    assert r["basemap"].startswith("data:image") and len(r["xy"]) == len(r["stops"])


def test_pick_path_mac_only_and_cancel(monkeypatch):
    import pytest, subprocess, sys
    from tripcore import web
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(web.HttpError):
        web.pick_path({"kind": "file"})
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "execution error: User canceled. (-128)"))
    assert web.pick_path({"kind": "folder"}) == {"path": ""}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "/Users/x/账单.csv\n", ""))
    assert web.pick_path({"kind": "file"}) == {"path": "/Users/x/账单.csv"}


def test_trip_delete_moves_to_archive_and_restore(tmp_path, monkeypatch):
    import pytest
    from tripcore import web, workspace as ws
    monkeypatch.delenv("TRIPCORE_FILE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    from tripcore import mcp_server as s
    if s._single_file_mode():
        pytest.skip("single file mode")
    s.new_trip(name="甲", num_days=1)
    s.new_trip(name="乙", num_days=1)
    root = s._root_dir()
    cur = ws.active_slug(root)
    out = web.trip_delete({"slug": cur})
    assert "回收区" in out["message"] and ws.active_slug(root) != cur
    assert [x["slug"] for x in ws.list_trips(root, archived=True)] == [cur]
    assert web.trip_restore({"slug": cur})["slug"]
    with pytest.raises(web.HttpError):
        web.trip_delete({"slug": "nope"})


def test_page_uses_inpage_dialog_and_nav_handler_skips_action_buttons():
    from tripcore.webpage import page_html
    h = page_html()
    assert "confirm(" not in h.replace("function ask", "")       # 内置浏览器里原生 confirm 可能不弹，要用页内确认框
    assert "#topnav button[data-pg]" in h and "document.querySelectorAll('#topnav button').forEach(b => b.onclick" not in h


def test_new_restore_trip_is_an_empty_restore_shell_and_import_fills_it(tmp_path, monkeypatch):
    import pytest
    from datetime import datetime, timedelta
    from tripcore import web, workspace as ws
    from tripcore import mcp_server as s
    from tests.test_phototrip import _jpg
    monkeypatch.delenv("TRIPCORE_FILE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    if s._single_file_mode():
        pytest.skip("single file mode")
    s.new_trip(name="计划A", num_days=2)
    n0 = len(ws.list_trips(s._root_dir()))
    r = web.trip_new_restore({"name": ""})
    kinds = {t["slug"]: t["kind"] for t in ws.list_trips(s._root_dir())}
    assert len(kinds) == n0 + 1 and kinds[r["slug"]] == "restore" and ws.active_slug(s._root_dir()) == r["slug"]
    st = web.hb_state()
    assert st["restored"] is False and st["stops"] == [] and st["name"].startswith("恢复行程 ")
    assert "还没有做过预览" in s.restore_status() and "照片恢复的行程" in s.restore_status()
    ph = tmp_path / "ph"; ph.mkdir()
    t0 = datetime(2026, 6, 19, 10, 0)
    for i in range(4):
        _jpg(ph / f"a{i}.jpg", t0 + timedelta(minutes=3 * i), 28.70, 121.40)
    web.hb_import({"folder": str(ph)})
    assert len(ws.list_trips(s._root_dir())) == n0 + 1                      # 读进了刚建的壳，没有再多出一个行程
    st = web.hb_state()
    assert st["restored"] is True and st["name"].startswith("照片还原 ") and st["stops"]
    # 起了名字就用用户的名字
    web.trip_new_restore({"name": "台州周末"})
    web.hb_import({"folder": str(ph)})
    assert web.hb_state()["name"] == "台州周末"


def test_restore_has_film_option_with_groups_and_preview():
    PAGE = page_html()
    for k in ('id="hb_vid"', 'id="hv_groups"', 'id="hv_prev"', "hvRender", "video_status"):
        assert k in PAGE, k


def test_video_scan_groups_cut_preview_and_range(server, tmp_path):
    """视频页：整理归类返回按景点分组的片段；粗剪后成片可在页面里播放（固定文件、支持 Range）。"""
    import shutil
    import urllib.request
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("需要 ffmpeg")
    from tests.test_photo_trip_tools import _album
    from tests.test_video import _mk
    photos = tmp_path / "ph"; photos.mkdir(); _album(photos)
    s.import_photo_trip(str(photos))
    vids = tmp_path / "vid"; vids.mkdir()
    _mk(vids / "a.mov", "2026-06-19T02:03:00Z")
    _mk(vids / "c.mov", "2026-06-19T14:00:00Z")                       # 归不上
    code, r = call(server, "/tok/api/video_scan", {"folder": str(vids)})
    assert code == 200 and r["total"] == 2 and r["assigned"] == 1
    assert r["groups"][0]["clips"][0]["file"] == "a.mov" and r["lost"][0]["file"] == "c.mov"
    code, r = call(server, "/tok/api/video_cut", {"folder": str(vids), "target_seconds": 10, "clip_max": 2})
    assert code == 200 and r["started"] is True
    import time
    from tripcore.web import video_status as web_status
    for _ in range(300):
        j = web_status()
        if j["state"] != "run":
            break
        time.sleep(0.5)
    assert j["state"] == "ok", j
    assert j["video"].startswith("video/film.mp4")
    req = urllib.request.Request(server + "/tok/" + j["video"], headers={"Range": "bytes=0-99"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 206 and len(resp.read()) == 100 and resp.headers["Content-Range"].startswith("bytes 0-99/")


def test_page_scripts_are_valid_javascript(tmp_path):
    """整页脚本语法要对（改页面时多一个括号会让整页不能用，其它测试发现不了）。"""
    import re
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("需要 node")
    for i, code in enumerate(re.findall(r"<script[^>]*>(.*?)</script>", page_html(), re.S)):
        f = tmp_path / f"p{i}.js"; f.write_text(code, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:400]
