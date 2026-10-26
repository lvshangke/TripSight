"""工作台的手册后端：相册恢复、编辑文字和名字、合并、照片排序、视觉描写（模拟）、最终导出。"""

import pytest

from tests.test_web import call, server  # noqa: F401
from tests.test_photo_trip_tools import _album
from tripcore import mcp_server as s
from tripcore import vision


def _restore(server, tmp_path):
    code, r = call(server, "/tok/api/hb_import", {"folder": str(_album(tmp_path)), "min_photos": 3})
    assert code == 200, r
    return call(server, "/tok/api/hb_state")[1]


def test_import_state_and_edit(server, tmp_path):
    st = _restore(server, tmp_path)
    assert st["restored"] and len(st["stops"]) == 2 and all(x["photos"] for x in st["stops"])
    pid = st["stops"][0]["id"]
    code, r = call(server, "/tok/api/hb_edit", {"place_id": pid, "name": "国清寺", "impression": "傍晚的光很柔。",
                                                "facts": [{"text": "始建于隋代", "source": "https://example.com/x"}]})
    assert code == 200, r
    row = call(server, "/tok/api/hb_state")[1]["stops"][0]
    assert row["name"] == "国清寺" and row["story"]["by"] == "user" and row["story"]["facts"][0]["source"].startswith("https")
    code, r = call(server, "/tok/api/hb_edit", {"place_id": pid, "facts": [{"text": "没有来源", "source": ""}]})
    assert code == 400 and "source" in r["error"]                       # 没有来源的介绍不收
    assert call(server, "/tok/api/hb_state")[1]["stops"][0]["story"]["facts"]      # 原来的还在
    call(server, "/tok/api/hb_edit", {"place_id": pid, "facts": []})
    assert "facts" not in call(server, "/tok/api/hb_state")[1]["stops"][0]["story"]
    call(server, "/tok/api/hb_edit", {"place_id": pid, "impression": ""})
    assert "impression" not in call(server, "/tok/api/hb_state")[1]["stops"][0]["story"]


def test_photo_move_sets_cover(server, tmp_path):
    st = _restore(server, tmp_path)
    ph = st["stops"][0]["photos"]
    assert len(ph) >= 2
    code, _ = call(server, "/tok/api/hb_photo_move", {"id": ph[-1]["id"], "to": "front"})
    assert code == 200
    assert call(server, "/tok/api/hb_state")[1]["stops"][0]["photos"][0]["id"] == ph[-1]["id"]


def test_describe_needs_config_and_never_saves(server, tmp_path, monkeypatch):
    st = _restore(server, tmp_path)
    pid = st["stops"][0]["id"]
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    code, r = call(server, "/tok/api/hb_describe", {"place_id": pid})
    assert code == 400 and "视觉模型" in r["error"]
    monkeypatch.setenv("DASHSCOPE_API_KEY", "k"); monkeypatch.setenv("TRIPSIGHT_VISION_MODEL", "m")
    monkeypatch.setattr(vision, "describe", lambda sheet, name: "晨雾里的山色偏青。")
    code, r = call(server, "/tok/api/hb_describe", {"place_id": pid})
    assert code == 200 and r["draft"] == "晨雾里的山色偏青。"
    assert "impression" not in call(server, "/tok/api/hb_state")[1]["stops"][0]["story"]


def test_export_formats_validated(server, tmp_path):
    _restore(server, tmp_path)
    assert call(server, "/tok/api/hb_export", {"formats": []})[0] == 400
    code, r = call(server, "/tok/api/hb_export", {"formats": ["html", "obsidian"]})
    assert code == 200 and "手册已生成" in r["message"]


def test_vision_http_errors_are_readable(monkeypatch):
    import urllib.error
    monkeypatch.setenv("DASHSCOPE_API_KEY", "k"); monkeypatch.setenv("TRIPSIGHT_VISION_MODEL", "m")

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 400, "bad", {}, None)
    monkeypatch.setattr(vision.urllib.request, "urlopen", boom)
    with pytest.raises(vision.VisionError, match="400"):
        vision.describe(b"x", "某地")


def test_preview_does_not_create_a_trip(server, tmp_path):
    from tests.test_photo_trip_tools import _album
    before = call(server, "/tok/api/trips")[1]
    code, r = call(server, "/tok/api/hb_preview", {"folder": str(_album(tmp_path)), "radius_m": 300})
    assert code == 200 and r["kept"] == 2 and r["total"] == 3 and r["dropped"] == 1 and r["stops"][0]["n"] >= 3
    code, r2 = call(server, "/tok/api/hb_preview", {"folder": str(_album(tmp_path)), "radius_m": 5000})
    assert code == 200 and r2["radius_m"] == 2000                       # 半径上限
    assert call(server, "/tok/api/trips")[1] == before
    assert call(server, "/tok/api/hb_preview", {"folder": "/no/such"})[0] == 400
