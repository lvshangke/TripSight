"""旅途照片：存入时去掉 EXIF/定位，默认不进分享页，选项打开才在各站下面；游记骨架只列编号和说明。"""

import pytest

pytest.importorskip("mcp")
PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from tripcore import mcp_server as s  # noqa: E402
from tripcore import photos as ph  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIPCORE_FILE", str(tmp_path / "trip.json"))
    from tripcore import share
    monkeypatch.setattr(share, "render_png", lambda *a, **k: "测试里不截图")


def _trip():
    s.new_trip(name="照片测试", num_days=2, start_date="2026-10-01", end_date="2026-10-02", city="北京")
    s.add_place("故宫", 39.9163, 116.3972, duration_min=240, must_go=True, priority=5)
    s.add_place("天坛", 39.8822, 116.4066, duration_min=120)
    s.schedule_days()
    s.record_review("故宫", "去了", 5, "人很多")


def _img(tmp_path, name="a.jpg", gps=True, size=(3000, 2000)):
    im = Image.new("RGB", size, (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"
    if gps:
        exif[0x8825] = {1: "N", 2: (39.0, 54.0, 0.0), 3: "E", 4: (116.0, 23.0, 0.0)}
    p = tmp_path / name
    im.save(p, exif=exif)
    return str(p)


def _stored(tmp_path):
    folder = tmp_path / "photos"
    return sorted(folder.glob("*.jpg"))


def test_exif_and_gps_are_stripped_and_image_is_shrunk(tmp_path):
    _trip()
    src = _img(tmp_path)
    assert b"SecretCameraMaker" in open(src, "rb").read()
    s.add_photo(src, place="故宫", caption="午门")
    (f,) = _stored(tmp_path)
    raw = f.read_bytes()
    assert b"SecretCameraMaker" not in raw and b"Exif" not in raw
    with Image.open(f) as im:
        assert not dict(im.getexif()) and max(im.size) <= ph.MAX_SIDE


def test_rejects_bad_inputs(tmp_path):
    _trip()
    for kwargs in ({"path": str(tmp_path / "none.jpg"), "place": "故宫"},
                   {"path": _img(tmp_path), "place": "故宫", "day": 1},      # 二选一
                   {"path": _img(tmp_path)},                                    # 都没给
                   {"path": _img(tmp_path), "day": 9}):
        with pytest.raises(s.ToolError):
            s.add_photo(**kwargs)
    txt = tmp_path / "x.txt"; txt.write_text("hi")
    with pytest.raises(s.ToolError):
        s.add_photo(str(txt), place="故宫")
    assert _stored(tmp_path) == []


def test_no_pillow_means_refuse(tmp_path, monkeypatch):
    _trip()
    import builtins
    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda n, *a, **k: (_ for _ in ()).throw(ImportError()) if n == "PIL" else real(n, *a, **k))
    with pytest.raises(s.ToolError) as e:
        s.add_photo(_img(tmp_path), place="故宫")
    assert "Pillow" in str(e.value)


def test_share_page_photos_are_off_by_default_and_under_the_stop(tmp_path):
    _trip()
    s.add_photo(_img(tmp_path), place="故宫", caption="午门前")
    s.add_photo(_img(tmp_path, "b.jpg", gps=False), day=2, caption="当天合影")
    def html(**kw):
        out = s.export_share(**kw)
        path = out.split("：", 1)[1].split("\n")[0]
        return open(path, encoding="utf-8").read()
    assert "data:image" not in html()
    h = html(show_photos=True)
    assert h.count("data:image/jpeg;base64,") == 2 and "午门前" in h and "当天合影" in h
    assert h.index("午门前") > h.index("故宫")                       # 照片在对应的站下面
    assert "SecretCameraMaker" not in h


def test_travelogue_facts_list_photo_ids_only(tmp_path):
    _trip()
    s.add_photo(_img(tmp_path), place="故宫", caption="午门前")
    f = s.draft_travelogue()
    stop = next(x for d in f["days"] for x in d["stops"] if x["name"] == "故宫")
    assert stop["photos"][0]["caption"] == "午门前" and set(stop["photos"][0]) == {"id", "caption"}


def test_remove_photo_deletes_stored_copy(tmp_path):
    _trip()
    s.add_photo(_img(tmp_path), place="故宫")
    pid = ph.load(tmp_path / "photos.json")[0]["id"]
    s.remove_photo(pid)
    assert _stored(tmp_path) == [] and ph.load(tmp_path / "photos.json") == []
    with pytest.raises(s.ToolError):
        s.remove_photo(pid)


def test_templates_and_tags_come_from_facts():
    _trip()
    f = s.draft_travelogue(style="小红书")
    assert f["template"]["sections"] and f["suggested_tags"] == ["#北京", "#北京旅行", "#故宫"]
    assert "suggested_tags" not in s.draft_travelogue(style="朋友圈")
    assert s.draft_travelogue(style="随便写")["style"] == "通用"
