"""照片还原旅程的 MCP 工具：新建行程、挂照片（去定位）、看点、写介绍/描写（要来源）、手册里分开显示。"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("mcp")
pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from tripcore import mcp_server as s  # noqa: E402
from tests.test_phototrip import _jpg  # noqa: E402


def _album(tmp_path):
    t0 = datetime(2026, 6, 19, 10, 0)
    for i in range(4):
        _jpg(tmp_path / f"a{i}.jpg", t0 + timedelta(minutes=3 * i), 28.70, 121.40, color=(10 * i, 100, 200))
    for i in range(3):
        _jpg(tmp_path / f"b{i}.jpg", t0 + timedelta(hours=4, minutes=2 * i), 28.72, 121.42)
    _jpg(tmp_path / "lone.jpg", t0 + timedelta(days=1), 28.50, 121.10)         # 只有一张：路过
    return tmp_path


def test_import_creates_new_trip_with_locked_days_and_strips_location(tmp_path):
    out = s.import_photo_trip(str(_album(tmp_path)))
    t = s._load()
    assert t.meta.num_days == 1 and t.meta.start_date.isoformat() == "2026-06-19"
    assert [len(d.items) for d in t.plan.days] == [2] and all(i.locked for d in t.plan.days for i in d.items)
    assert all(p.source == "photo" and "停留点" not in p.name and p.name[:2].isdigit() for p in t.places) and "路过" in out
    items = s._ph.load(s._photo_index())
    assert items and all(not Image.open(s._photo_dir() / x["file"]).getexif() for x in items)


def test_import_errors_are_clear(tmp_path):
    with pytest.raises(s.ToolError):
        s.import_photo_trip(str(tmp_path / "不存在"))
    with pytest.raises(s.ToolError):
        s.import_photo_trip(str(tmp_path))                    # 空文件夹：没有带位置的照片


def test_view_stop_returns_sheet_and_requires_photo_origin(tmp_path, monkeypatch):
    s.import_photo_trip(str(_album(tmp_path)))
    monkeypatch.setattr(s, "_amap", lambda: None)
    pid = s._load().places[0].id
    text, img = s.view_stop(pid)
    assert "4 张照片" in text.text and "没有可用的高德 key" in text.text and img.mimeType == "image/jpeg" and img.data
    s.new_trip(num_days=1, city="北京")
    s.add_place("故宫", 39.9, 116.4)
    with pytest.raises(s.ToolError):
        s.view_stop("p1")


def test_story_needs_sources_and_shows_separately_in_handbook(tmp_path):
    s.import_photo_trip(str(_album(tmp_path)))
    pid = s._load().places[0].id
    with pytest.raises(s.ToolError):
        s.save_stop_story(pid, facts=[{"text": "一座古桥", "source": ""}])
    with pytest.raises(s.ToolError):
        s.save_stop_story(pid)
    s.save_stop_story(pid, impression="午后的光线很柔，水面很静。",
                      facts=[{"text": "始建于某朝代", "source": "https://example.com/a"}])
    s.export_handbook(cards=False)
    root = next(p for p in s.trip_path().with_name("exports").iterdir() if p.is_dir())
    page = (root / "index.html").read_text(encoding="utf-8")
    assert "来源：" in page and "example.com/a" in page and "AI 根据照片的描写" in page and "午后的光线很柔" in page
    assert "<img" in page                                      # 默认带照片


def test_view_stop_works_through_the_mcp_server(tmp_path):
    """经 FastMCP 调用：返回图片内容块不能触发序列化错误（真实助手里出现过）。"""
    import asyncio
    s.import_photo_trip(str(_album(tmp_path)))
    res = asyncio.run(s.build_server().call_tool("view_stop", {"place_id": s._load().places[0].id}))
    blocks = res[0] if isinstance(res, tuple) else res
    assert [b.type for b in blocks] == ["text", "image"]


def test_merge_stops_combines_same_day_points(tmp_path):
    s.import_photo_trip(str(_album(tmp_path)), min_photos=1)
    t = s._load()
    ids = [p.id for p in t.places]
    assert len(ids) >= 2
    day = {r["place_id"]: r["day"] for r in s._load_json_file(s._photo_trip_path())["stops"]}
    same = [i for i in ids if day[i] == day[ids[0]]]
    if len(same) < 2:
        return
    before = sum(1 for x in s._ph.load(s._photo_index()) if x["place_id"] in same)
    s.merge_stops(same, name="合并景区")
    t2 = s._load()
    assert [p.id for p in t2.places].count(same[0]) == 1 and not any(i in [p.id for p in t2.places] for i in same[1:])
    assert t2.place(same[0]).name == "合并景区"
    assert sum(1 for x in s._ph.load(s._photo_index()) if x["place_id"] == same[0]) == before
    with pytest.raises(Exception):
        s.merge_stops([same[0]])


def test_tag_regions_without_key_refuses_and_with_client_stores(monkeypatch, tmp_path):
    s.import_photo_trip(str(_album(tmp_path)))
    monkeypatch.setattr(s, "_amap", lambda: None)
    with pytest.raises(Exception, match="没有可用的高德 key"):
        s.tag_regions()

    class Fake:
        def regeo(self, lat, lon):
            return {"province": "浙江省", "city": "台州市", "district": "临海市" if lat < 28.71 else "仙居县"}
    monkeypatch.setattr(s, "_amap", lambda: Fake())
    monkeypatch.setattr(s, "_is_google", lambda c: False)
    out = s.tag_regions()
    assert "临海 → 仙居" in out and set(s._chapter_labels().values()) == {"临海", "仙居"}


def test_import_with_track_locates_untagged_photos(tmp_path):
    t0 = datetime(2026, 6, 19, 10, 0)
    for i in range(2):
        _jpg(tmp_path / f"g{i}.jpg", t0 + timedelta(minutes=2 * i), 28.70, 121.40, color=(10 * i, 90, 200))
    for i in range(3):                                          # 没有定位，靠轨迹补
        _jpg(tmp_path / f"n{i}.jpg", t0 + timedelta(hours=3, minutes=i), color=(30 * i, 200, 90))
    gpx = tmp_path / "t.gpx"
    gpx.write_text('<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
                   '<trkpt lat="28.80" lon="121.50"><time>2026-06-19T04:59:00Z</time></trkpt>'
                   '<trkpt lat="28.80" lon="121.50"><time>2026-06-19T05:05:00Z</time></trkpt>'
                   '</trkseg></trk></gpx>', encoding="utf-8")
    out = s.import_photo_trip(str(tmp_path), track=str(gpx), min_photos=2)
    t = s._load()
    assert "按拍摄时间在轨迹文件上补出" in out and len(t.places) == 2
    assert any(abs(p.lat - 28.80) < 1e-6 for p in t.places)
    with pytest.raises(s.ToolError):
        s.import_photo_trip(str(tmp_path), track=str(tmp_path / "no.gpx"))


def test_link_photos_does_not_copy_and_exports_without_location(tmp_path):
    from tripcore import photos as ph
    src = _album(tmp_path / "a") if (tmp_path / "a").mkdir() is None else None
    s.import_photo_trip(str(src), link_photos=True)
    d = s._photo_dir()
    items = ph.load(s._photo_index())
    assert items and all(x.get("ref") for x in items)
    assert not list(d.glob("*.jpg"))                                  # 行程目录里没有副本
    assert all(ph.thumb_uri(d, x["file"]) for x in items)             # 缩略图现场从原文件生成
    out = s.export_handbook(show_photos=True, cards=False)
    folder = Path(out.split("已生成：")[1].split("\n")[0].strip()) if "已生成：" in out else None
    pics = list(Path(s.trip_path().with_name("exports")).rglob("photos/*.jpg"))
    assert pics and all(not Image.open(p).getexif() for p in pics)    # 导出的是去掉定位的版本
    # 原文件被移走：不崩，提示缺失
    for f in Path(src).glob("*.jpg"):
        f.rename(f.with_suffix(".moved"))
    out2 = s.export_handbook(show_photos=True, cards=False)
    assert "照片缺失" in out2
    assert not any(ph.thumb_uri(d, x["file"]) for x in items)


def test_remove_linked_photo_keeps_original(tmp_path):
    from tripcore import photos as ph
    t0 = datetime(2026, 6, 19, 10, 0)
    from tests.test_phototrip import _jpg
    f = tmp_path / "x.jpg"; _jpg(f, t0, 28.7, 121.4)
    s.new_trip(name="t", num_days=1)
    s.add_place("甲", 28.7, 121.4, duration_min=60)
    out = s.add_photo(str(f), place="甲", link=True)
    assert "没有复制" in out
    pid = ph.load(s._photo_index())[0]["id"]
    s.remove_photo(pid)
    assert f.exists() and not ph.load(s._photo_index())


def test_handbook_thumb_pins_end_to_end(tmp_path):
    (tmp_path / "a").mkdir()
    s.import_photo_trip(str(_album(tmp_path / "a")), link_photos=True)
    out = s.export_handbook(show_photos=True, cards=False, thumb_pins=True)
    html = next(Path(s.trip_path().with_name("exports")).rglob("index.html")).read_text(encoding="utf-8")
    assert 'class="pinr"' in html and "clip-path=\"url(#pin" in html
    html2 = next(Path(s.trip_path().with_name("exports")).glob("*-2/index.html")).read_text(encoding="utf-8") if False else ""
    s.export_handbook(show_photos=True, cards=False, thumb_pins=False)
    plain = sorted(Path(s.trip_path().with_name("exports")).rglob("index.html"))[-1].read_text(encoding="utf-8")
    assert 'class="pinr"' not in plain


def test_auto_name_uses_amap_where_and_falls_back(tmp_path, monkeypatch):
    class Fake:
        def where(self, lat, lon):
            return {"name": "紫阳古街", "district": "临海市", "city": "台州"}
    monkeypatch.setattr(s.AmapClient, "from_env", classmethod(lambda cls, log_path=None: Fake()))
    s.import_photo_trip(str(_album(tmp_path)))
    assert {p.name.split(" ")[0] for p in s._load().places} == {"紫阳古街"}


def test_hide_and_drag_order(tmp_path):
    from tripcore import web, photos as ph
    s.import_photo_trip(str(_album(tmp_path)))
    items = ph.load(s._photo_index())
    pid = items[0]["place_id"]
    grp = [x for x in items if x["place_id"] == pid]
    if len(grp) >= 2:
        web.hb_photo_move({"id": grp[-1]["id"], "to": "place", "before": grp[0]["id"]})
        assert [x["id"] for x in ph.load(s._photo_index()) if x["place_id"] == pid][0] == grp[-1]["id"]
    assert web.hb_photo_move({"id": grp[0]["id"], "to": "hide"})["hide"] is True


def test_obsidian_uses_relative_markdown_images_and_skips_hidden(tmp_path, monkeypatch):
    from tripcore import photos as ph
    monkeypatch.setenv("TRIPCORE_EXPORT_DIR", str(tmp_path / "out"))
    s.import_photo_trip(str(_album(tmp_path)))
    items = ph.load(s._photo_index())
    items[0]["hide"] = True
    ph.save(s._photo_index(), items)
    msg = s.export_notes()
    root = Path(msg.split("已导出到：")[1].splitlines()[0])
    assert root.parent == tmp_path / "out" and (root / "attachments").is_dir()
    md = "\n".join(f.read_text(encoding="utf-8") for f in root.glob("*.md"))
    assert "](attachments/photos/" in md and "![[" not in md
    assert len(list((root / "attachments" / "photos").glob("*.jpg"))) == len(items) - 1


def test_style_preview_inlines_photos_and_writes_nothing(tmp_path, monkeypatch):
    from tripcore import web
    monkeypatch.setenv("TRIPCORE_EXPORT_DIR", str(tmp_path / "out"))
    s.import_photo_trip(str(_album(tmp_path)))
    for st in ("手账", "杂志"):
        r = web.hb_style_preview({"style": st})
        assert "data:image/jpeg" in r["page"] and "photos/" not in r["page"] and "营业时间" not in r["page"]
        assert r["card"].startswith("<!doctype html>")
    assert not (tmp_path / "out").exists()


def test_card_photos_count_one_to_five(tmp_path, monkeypatch):
    from tripcore import web
    s.import_photo_trip(str(_album(tmp_path)))
    for n in (1, 3, 5):
        card = web.hb_style_preview({"style": "手账", "card_photos": n})["card"]
        assert card.count('class="ph ') == n and f'class="col n{n}"' in card


def test_delete_stop_removes_locked_stop_photos_and_record(tmp_path):
    from tripcore import web
    s.import_photo_trip(str(_album(tmp_path)))
    t = s._load()
    pid, name = t.places[0].id, t.places[0].name
    n_before = len(s._ph.load(s._photo_index()))
    r = web.hb_stop_delete({"place_id": pid})
    assert name in r["message"]
    t = s._load()
    assert pid not in [p.id for p in t.places] and all(i.place_id != pid for d in t.plan.days for i in d.items)
    items = s._ph.load(s._photo_index())
    assert len(items) < n_before and all(x.get("place_id") != pid for x in items)
    assert pid not in [x["place_id"] for x in s._load_json_file(s._photo_trip_path())["stops"]]
    with pytest.raises(web.HttpError):
        web.hb_stop_delete({"place_id": pid})


def test_autoname_renames_old_stop_names_without_touching_manual_ones(tmp_path, monkeypatch):
    from tripcore import web
    monkeypatch.setattr(s, "_stop_names", lambda keep: (["神仙居"] * 0 + [f"地名{i}" for i in range(len(keep))], len(keep)))
    s.import_photo_trip(str(_album(tmp_path)), auto_name=False)
    t = s._load()
    assert all(p.name.endswith("停留点") for p in t.places)
    s.update_place(t.places[1].id, name="我自己起的名字")
    r = web.hb_autoname({})
    assert "1 个" in r["message"] or "重新起名 1" in r["message"]
    names = [p.name for p in s._load().places]
    assert names == ["地名0", "我自己起的名字"]
    assert "没有需要" in web.hb_autoname({})["message"]


def test_export_dir_setting_roundtrip(tmp_path, monkeypatch):
    from tripcore import web
    monkeypatch.delenv("TRIPCORE_EXPORT_DIR", raising=False)
    s.new_trip(name="x", num_days=1)
    default = web.export_dir({})
    assert default["custom"] is False
    target = tmp_path / "我的导出"
    r = web.export_dir({"path": str(target)})
    assert r["custom"] and Path(r["path"]) == target.resolve() and s.export_root() == target.resolve()
    assert web.export_dir({"path": ""})["custom"] is False
