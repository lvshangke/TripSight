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
    for k in ('data-t="vid"', 'data-t="fp"', 'id="sh_cal"', 'id="vd_cut"', 'id="fp_frame"'):
        assert k in PAGE, k


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
