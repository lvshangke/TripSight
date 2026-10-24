"""工作台「更多」面板的后端：能力目录、分享预览、照片上传/删除、游记骨架与自查。"""

import base64
import io

import pytest

from tests.test_web import call, server  # noqa: F401  (复用服务器夹具)
from tripcore import mcp_server as s
from tripcore import share

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def _jpeg_b64(size=(800, 600), exif=True) -> str:
    im = Image.new("RGB", size, (30, 90, 200))
    buf = io.BytesIO()
    if exif:
        e = Image.Exif()
        e[0x010F] = "SecretCameraMaker"
        e[0x8825] = {1: "N", 2: (34.0, 15.0, 0.0), 3: "E", 4: (108.0, 54.0, 0.0)}
        im.save(buf, "JPEG", exif=e)
    else:
        im.save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def test_tools_catalog_route(server):
    code, r = call(server, "/tok/api/tools")
    assert code == 200 and r["total"] == len(s.TOOLS) and r["promises"]
    names = {t["name"] for b in r["blocks"] for t in b["tools"]}
    assert names == {f.__name__ for f in s.TOOLS}


def test_share_preview_respects_options_and_hides_hotel_by_default(server):
    s.add_lodging("秘密酒店XYZ", 34.21, 108.91, price_min=300, price_max=500, choose=True)
    s.schedule_days()
    code, r = call(server, "/tok/api/share_preview", {})
    assert code == 200 and "甲" in r["html"] and "秘密酒店XYZ" not in r["html"] and "门票" not in r["html"]
    code, r2 = call(server, "/tok/api/share_preview", {"lodging": True})
    assert "秘密酒店XYZ" in r2["html"]
    assert isinstance(r["png_ok"], bool) and r["photo_count"] == 0


def test_share_image_reports_missing_playwright(server, monkeypatch):
    monkeypatch.setattr(share, "render_png", lambda *a, **k: "没有安装 playwright")
    code, r = call(server, "/tok/api/share_image", {})
    assert code == 400 and "playwright" in r["error"]


def test_photo_upload_strips_exif_lists_and_removes(server, tmp_path):
    pid = s._load().places[0].id
    code, r = call(server, "/tok/api/photo_add", {"place_id": pid, "caption": "", "name": "a.jpg", "data": _jpeg_b64()})
    assert code == 200 and r["id"]
    stored = list((tmp_path / "photos").glob("*.jpg"))
    assert len(stored) == 1 and b"SecretCameraMaker" not in stored[0].read_bytes()
    code, lst = call(server, "/tok/api/photos")
    assert lst["photos"][0]["place_id"] == pid and lst["photos"][0]["thumb"].startswith("data:image/jpeg")
    code, full = call(server, "/tok/api/photo_full", {"id": lst["photos"][0]["id"]})
    assert code == 200 and full["uri"].startswith("data:image/jpeg;base64,")
    assert call(server, "/tok/api/photo_full", {"id": "missing"})[0] == 404
    code, r = call(server, "/tok/api/share_preview", {"photos": True})
    assert r["html"].count("data:image/jpeg;base64,") == 1 and r["photo_count"] == 1
    assert 'id="lb"' in r["html"]                                    # 带照片时才内联放大查看器
    assert 'id="lb"' not in call(server, "/tok/api/share_preview", {})[1]["html"]
    assert len(r["themes"]) == 8 and "#ffd500" in call(server, "/tok/api/share_preview", {"theme": "dopamine"})[1]["html"]
    assert call(server, "/tok/api/share_preview", {"theme": "neon"})[0] == 400
    assert call(server, "/tok/api/photo_remove", {"id": lst["photos"][0]["id"]})[0] == 200
    assert call(server, "/tok/api/photos")[1]["photos"] == [] and not list((tmp_path / "photos").glob("*.jpg"))


def test_photo_upload_rejects_bad_input(server):
    pid = s._load().places[0].id
    assert call(server, "/tok/api/photo_add", {"place_id": "nope", "data": _jpeg_b64()})[0] == 400
    assert call(server, "/tok/api/photo_add", {"place_id": pid, "data": "***"})[0] == 400
    assert call(server, "/tok/api/photo_add", {"place_id": pid, "data": base64.b64encode(b"not an image").decode()})[0] == 400
    assert call(server, "/tok/api/photo_remove", {"id": "missing"})[0] == 404


def test_big_body_allowed_only_for_photo_upload(server):
    big = "A" * 150_000
    assert call(server, "/tok/api/undo", {"base_revision": 0, "x": big})[0] == 413
    assert call(server, "/tok/api/photo_add", {"place_id": "nope", "data": big})[0] == 400      # 没被 413 拦下，进入了业务校验


def test_share_gif_route_reports_missing_dependency(server, monkeypatch):
    from tripcore import share
    monkeypatch.setattr(share, "render_gif", lambda *a, **k: "测试里不录制")
    code, r = call(server, "/tok/api/share_gif", {})
    assert code == 400 and "测试里不录制" in r["error"]
    assert "gif_ok" in call(server, "/tok/api/share_preview", {})[1]


def test_travelogue_routes(server):
    s.record_review("甲", "去了", 4, "很好")
    code, f = call(server, "/tok/api/travelogue", {"style": "小红书"})
    assert code == 200 and f["suggested_tags"] and f["unrecorded"]
    code, r = call(server, "/tok/api/travelogue_check", {"text": "乙很棒，花了99元"})
    assert code == 200 and r["problems"]
    assert call(server, "/tok/api/travelogue_check", {"text": "  "})[0] == 400
