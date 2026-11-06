"""照片还原旅程的 MCP 工具：新建行程、挂照片（去定位）、看点、写介绍/描写（要来源）、手册里分开显示。"""

from datetime import datetime, timedelta
from pathlib import Path

import json
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


def test_day_titles_show_in_page_card_and_edit_hooks(tmp_path, monkeypatch):
    from tripcore import web
    monkeypatch.setenv("TRIPCORE_EXPORT_DIR", str(tmp_path / "out"))
    s.import_photo_trip(str(_album(tmp_path)))
    assert s.suggest_day_titles()["days"][0]["stops"]
    with pytest.raises(s.ToolError):
        s.set_day_title(9, "x")
    with pytest.raises(s.ToolError):
        s.set_day_title(1, "字" * 21)
    s.set_day_title(1, "从港口走到日落")
    r = web.hb_style_preview({"style": "手账", "edit": True})
    assert "从港口走到日落" in r["page"] and "从港口走到日落" in r["card"] and "第 1 天 · " in r["page"]
    assert 'data-ed="title:1"' in r["page"] and 'data-ed="imp:' in r["page"] and "data-rz=" in r["page"]
    plain = web.hb_style_preview({"style": "手账"})["page"]
    assert "data-ed" not in plain and "data-rz" not in plain
    assert "已恢复" in web.hb_day_title({"day": 1, "title": "第 1 天"})["message"] and not s._day_titles()


def test_photo_scale_saved_and_applied_to_export(tmp_path, monkeypatch):
    from tripcore import web
    monkeypatch.setenv("TRIPCORE_EXPORT_DIR", str(tmp_path / "out"))
    s.import_photo_trip(str(_album(tmp_path)))
    first = s._ph.load(s._photo_index())[1]
    assert web.hb_photo_scale({"id": first["id"], "scale": 500})["scale"] == 160
    web.hb_photo_scale({"id": first["id"], "scale": 60})
    page = web.hb_style_preview({"style": "手账"})["page"]
    assert "--s:0.6" in page or "--s:1.6" in page
    web.hb_photo_scale({"id": first["id"], "scale": 100})
    assert "scale" not in [x for x in s._ph.load(s._photo_index()) if x["id"] == first["id"]][0]


def test_activity_log_records_tool_calls_and_hides_secrets(tmp_path):
    import asyncio
    from tripcore import web, runner
    s.new_trip(name="x", num_days=1)
    srv = s.build_server()
    asyncio.run(srv.call_tool("show_trip", {}))
    runner.run_tool("list_trips", "")
    with pytest.raises(Exception):
        asyncio.run(srv.call_tool("set_day_title", {"day": 5, "title": "x", "api_key": "SECRET"}))
    ev = web.activity({})["events"]
    names = [e["name"] for e in ev]
    assert names[-3:] == ["show_trip", "list_trips", "set_day_title"]
    assert ev[0]["state"] == "ok" and ev[0]["label"] and ev[-1]["state"] == "err"
    assert "SECRET" not in json.dumps(ev, ensure_ascii=False)
    assert web.activity({"since": ev[-1]["ts"]})["events"] == []


def test_restore_status_sees_preview_draft_before_any_trip_is_created(tmp_path):
    from tripcore import web
    s.new_trip(name="旧计划", num_days=1)
    assert "还没有做过预览" in s.restore_status() and "旧计划" in s.restore_status()
    web.hb_preview({"folder": str(_album(tmp_path)), "radius_m": 300})
    out = s.restore_status()
    assert "旧计划" in out and "预览" in out and "聚成" in out and str(tmp_path) in out
    assert s._load().meta.name == "旧计划"            # 预览没有新建行程


def test_preview_and_state_report_videos_in_same_folder(tmp_path):
    from tripcore import web
    a = _album(tmp_path)
    for n in ("c1.mov", "c2.mp4"):
        (a / n).write_bytes(b"x")
    (a / ".hidden.mov").write_bytes(b"x")
    assert web.hb_preview({"folder": str(a)})["videos"] == 2
    s.import_photo_trip(str(a))
    assert web.hb_state()["videos"] == 2


def test_album_videos_are_read_by_path_without_copying(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    from tripcore import photoslib as pl, video as vd, web
    f1, f2 = tmp_path / "a.mov", tmp_path / "b.mp4"
    f1.write_bytes(b"x"); f2.write_bytes(b"x")
    vids = [NS(path=str(f1), hidden=False, intrash=False), NS(path=str(f2), hidden=False, intrash=False),
            NS(path=None, hidden=False, intrash=False),                      # 只在 iCloud 上
            NS(path=str(tmp_path / "t.mov"), hidden=False, intrash=True)]
    db = NS(album_info=[NS(title="旅行", photos=[1])], photos=lambda albums, images, movies: vids if movies and not images else [])
    monkeypatch.setattr(pl, "_open_db", lambda: db)
    paths, missing = pl.album_videos("旅行")
    assert paths == [f1, f2] and missing == 1
    assert web._album_video_count("旅行") == 3
    with pytest.raises(pl.PhotosLibError):
        pl.album_videos("没有这个")
    seen = []
    monkeypatch.setattr(vd, "need_ffmpeg", lambda: None)
    monkeypatch.setattr(vd, "probe", lambda p: seen.append(p) or vd.Clip(p.name, str(p), 5.0, None, None, None, 1920, 1080, True))
    s.import_photo_trip(str(_album(tmp_path / "ph")) if (tmp_path / "ph").mkdir() is None else "")
    out = s.scan_videos(album="旅行")
    assert seen == [f1, f2] and "2 段视频" in out and "另有 1 个读不了" in out
    with pytest.raises(s.ToolError):
        s.scan_videos()


def test_restore_context_inlines_page_state_for_agents_without_the_tool(tmp_path):
    from tripcore import web
    s.new_restore_trip("旧手机")
    out = web.restore_context("帮我恢复下行程")
    assert out.startswith("【TripSight 页面：恢复行程】") and "旧手机" in out and "照片恢复的行程" in out
    assert "不要列出已有的计划行程" in out and out.endswith("用户说：帮我恢复下行程")


def test_long_span_restores_and_date_filter_works(tmp_path):
    from tripcore import web
    _album(tmp_path)
    t1 = datetime(2023, 1, 5, 9, 0)
    for i in range(4):
        _jpg(tmp_path / f"old{i}.jpg", t1 + timedelta(minutes=2 * i), 31.2, 121.4, color=(5 * i, 9, 9))
    s.import_photo_trip(str(tmp_path))
    t = s._load()
    assert t.meta.start_date.isoformat() == "2023-01-05" and t.meta.num_days > 1200 and sum(1 for d in t.plan.days if d.items) == 2
    s.new_restore_trip("x")
    s.import_photo_trip(str(tmp_path), start_date="2026-06-01", end_date="2026-06-30")
    assert s._load().meta.start_date.isoformat() == "2026-06-19"
    pv = web.hb_preview({"folder": str(tmp_path)})
    assert pv["span_days"] > 30 and {m["m"] for m in pv["months"]} == {"2023-01", "2026-06"}
    pv2 = web.hb_preview({"folder": str(tmp_path), "start_date": "2023-01-01", "end_date": "2023-01-31"})
    assert pv2["span_days"] == 1 and pv2["kept"] == 1
    with pytest.raises(s.ToolError):
        s.date_filter([], [], "2026-13-01", "")


def test_autoname_reports_real_reason_and_stops_after_repeated_errors(tmp_path, monkeypatch):
    s.import_photo_trip(str(_album(tmp_path)), auto_name=False)
    monkeypatch.delenv("AMAP_KEY", raising=False)
    assert "AMAP_KEY" in s.autoname_stops()
    calls = []

    class Bad:
        def where(self, la, lo):
            calls.append(1)
            raise s.AmapError("高德返回错误：INVALID_USER_KEY")
    monkeypatch.setattr(s.AmapClient, "from_env", classmethod(lambda c, log_path=None: Bad()))
    out = s.autoname_stops()
    assert "INVALID_USER_KEY" in out and len(calls) <= 3


def test_restore_auto_mode_is_set_by_page_and_seen_by_agent(tmp_path):
    from tripcore import web
    s.new_restore_trip("旧手机")
    assert "逐步确认" in s.restore_status() and web.restore_mode({})["auto"] is False
    assert web.restore_mode({"auto": True})["auto"] is True
    st = s.restore_status()
    assert "自动执行" in st and "不要调用 export_handbook" in st and "包括删除" in st
    assert "逐步确认" in web.restore_context("x") or "自动执行" in web.restore_context("x")
    web.restore_mode({"auto": False})
    assert "逐步确认" in s.restore_status()
    assert not any(t.__name__ == "set_restore_auto" for t in s.TOOLS)


def test_amap_key_falls_back_to_nanobot_config_env(tmp_path, monkeypatch):
    from tripcore.amap import amap_key
    cfg = tmp_path / "nb.json"
    monkeypatch.delenv("AMAP_KEY", raising=False)
    monkeypatch.setenv("NANOBOT_CONFIG", str(cfg))
    assert amap_key() == ""
    cfg.write_text(json.dumps({"tools": {"mcpServers": {"tripcore": {"env": {"AMAP_KEY": "在这里填你自己的 key"}}}}}), encoding="utf-8")
    assert amap_key() == ""
    cfg.write_text(json.dumps({"tools": {"mcpServers": {"tripcore": {"env": {"AMAP_KEY": " k123 "}}}}}), encoding="utf-8")
    assert amap_key() == "k123"
    monkeypatch.setenv("AMAP_KEY", "fromenv")
    assert amap_key() == "fromenv"


def test_switching_trips_is_blocked_while_the_assistant_is_working(tmp_path, monkeypatch):
    from tripcore import web, activity as ac
    monkeypatch.delenv("TRIPCORE_FILE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    s.new_trip(name="计划A", num_days=2)
    s.new_restore_trip("旧手机")
    web.switch({"slug": web.ws.active_slug(s._root_dir())})                       # 空闲时可以切
    cid = ac.start(s._activity_path(), "import_photo_trip", {"album": "x"})
    with pytest.raises(web.HttpError) as e:
        web.switch({"slug": "whatever"})
    assert e.value.status == 409 and "读取照片" in str(e.value) or "助手正在" in str(e.value)
    with pytest.raises(web.HttpError):
        web.trip_new_restore({"name": "b"})
    ac.finish(s._activity_path(), cid, "import_photo_trip", True, "ok", 0.0)
    web.trip_new_restore({"name": "b"})                                            # 做完就放行
    web._IMPORTING["n"] = 1
    with pytest.raises(web.HttpError):
        web.switch({"slug": "x"})
    web._IMPORTING["n"] = 0


def test_autoname_is_chunked_and_resumable(tmp_path, monkeypatch):
    t0 = datetime(2026, 6, 19, 8, 0)
    for k in range(25):
        for i in range(3):
            _jpg(tmp_path / f"s{k}_{i}.jpg", t0 + timedelta(hours=k, minutes=i), 28 + k * 0.05, 121 + k * 0.05, color=(k, i, 9))
    s.import_photo_trip(str(tmp_path), auto_name=False, include_passing=False)
    n = len([p for p in s._load().places])
    calls = []

    class Fake:
        def where(self, la, lo):
            calls.append(1)
            return {"name": f"地名{len(calls)}", "district": "某区", "city": "某市"}
    monkeypatch.setattr(s.AmapClient, "from_env", classmethod(lambda c, log_path=None: Fake()))
    out = s.autoname_stops(budget_s=1e-9)
    assert "还剩" in out and 0 < len(calls) < n
    first = len(calls)
    out2 = s.autoname_stops(budget_s=0)
    assert "全部处理完了" in out2 and len(calls) == n and first < n
    assert "没有需要重新起名" in s.autoname_stops()


def test_show_trip_pages_a_multi_year_photo_trip(tmp_path):
    t0 = datetime(2022, 1, 5, 9, 0)
    for k in range(7):
        for i in range(3):
            _jpg(tmp_path / f"d{k}_{i}.jpg", t0 + timedelta(days=k * 200, minutes=2 * i), 28 + k * 0.1, 121, color=(k, i, 9))
    s.import_photo_trip(str(tmp_path), auto_name=False)
    assert s._load().meta.num_days > 1000
    out = s.show_trip(page=1, per_page=3)
    assert "共 7 天有景点" in out and "第 1/3 页" in out and "page=2" in out and len(out) < 4000 and "（空）" not in out
    last = s.show_trip(page=3, per_page=3)
    assert "第 3/3 页" in last and "page=" not in last


def test_tag_regions_is_chunked_saves_progress_and_skips_abroad(tmp_path, monkeypatch):
    t0 = datetime(2026, 6, 19, 8, 0)
    for k in range(12):
        for i in range(3):
            _jpg(tmp_path / f"r{k}_{i}.jpg", t0 + timedelta(hours=k, minutes=i), 28 + k * 0.05, 121 + k * 0.05, color=(k, i, 9))
    s.import_photo_trip(str(tmp_path), auto_name=False)
    calls = []

    class Fake:
        def regeo(self, la, lo):
            calls.append((la, lo))
            if len(calls) == 3:
                raise s.AmapError("高德返回错误：INSUFFICIENT_ABROAD_PRIVILEGES")
            return {"province": "浙江", "city": "台州", "district": f"区{len(calls) % 3}"}
    monkeypatch.setattr(s, "_amap", lambda: Fake())
    monkeypatch.setattr(s, "_is_google", lambda c: False)
    out = s.tag_regions(budget_s=1e-9)
    assert "还剩" in out and len(calls) == 1
    out2 = s.tag_regions(budget_s=0)
    assert "还剩" not in out2 and len(calls) == 12
    n = len(calls)
    s.tag_regions(budget_s=0)
    assert len(calls) == n                                   # 查过的（含境外失败的）不再查


def test_every_stop_gets_photos_even_beyond_the_old_200_cap_and_fill_repairs(tmp_path):
    t0 = datetime(2026, 6, 19, 8, 0)
    for k in range(70):                                         # 70 个点 × 6 张 = 420 > 旧上限 200
        for i in range(6):
            _jpg(tmp_path / f"q{k}_{i}.jpg", t0 + timedelta(hours=k * 3, minutes=i), 28 + k * 0.05, 121 + k * 0.05, color=(k, i * 9, 9))
    s.import_photo_trip(str(tmp_path), auto_name=False)
    ids = {p.id for p in s._load().places}
    items = s._ph.load(s._photo_index())
    assert len(ids) == 70 and {x["place_id"] for x in items} == ids         # 每个点都有照片
    assert max(sum(1 for x in items if x["place_id"] == i) for i in ids) <= 4   # 点多时每点最多 4 张，轮流分配
    keep = items[:5]                                                # 模拟旧版本：只有前几个点有照片
    s._ph.save(s._photo_index(), keep)
    out = s.fill_stop_photos(per_stop=2)
    assert "补了" in out
    assert {x["place_id"] for x in s._ph.load(s._photo_index())} == ids
    assert "已经有照片" in s.fill_stop_photos()


def test_naming_job_runs_in_background_and_blocks_merge_while_running(tmp_path, monkeypatch):
    import time as _t
    t0 = datetime(2026, 6, 19, 8, 0)
    for k in range(6):
        for i in range(3):
            _jpg(tmp_path / f"j{k}_{i}.jpg", t0 + timedelta(hours=k, minutes=i), 28 + k * 0.05, 121 + k * 0.05, color=(k, i, 9))
    s.import_photo_trip(str(tmp_path), auto_name=False)
    monkeypatch.delenv("AMAP_KEY", raising=False)
    with pytest.raises(s.ToolError):
        s.run_naming_job()                                          # 没 key：直接说明，不悄悄失败
    class Fake:
        provider = "amap"
        def where(self, la, lo):
            _t.sleep(0.05); return {"name": "景点", "district": "区", "city": "市"}
        def regeo(self, la, lo):
            return {"province": "浙江", "city": "台州", "district": "区"}
    monkeypatch.setenv("AMAP_KEY", "x")
    monkeypatch.setattr(s.AmapClient, "from_env", classmethod(lambda c, log_path=None: Fake()))
    monkeypatch.setattr(s, "_amap", lambda: Fake())
    assert "后台" in s.run_naming_job()
    st = s.restore_status()
    assert "后台任务：" in st
    for _ in range(100):
        if "已完成" in s.wait_restore_job(2):
            break
    assert "已完成" in s.restore_status()
    with pytest.raises(s.ToolError):
        s._job_write(state="running"); s.merge_stops(["p1", "p2"])  # 后台在跑时不让合并
    s._job_write(state="done")


def test_search_links_batch_and_chat_links_and_share_controls(tmp_path):
    out = s.search_links(keywords=["西湖", "灵隐寺", "西湖"], kind="guide")
    assert [i["keyword"] for i in out["items"]] == ["西湖", "灵隐寺"] and all(l["url"].startswith("https://") for i in out["items"] for l in i["links"])
    assert any("xiaohongshu" in l["url"] for l in out["items"][0]["links"])
    with pytest.raises(s.ToolError):
        s.search_links(keywords=[" "])
    from tripcore import webpage
    h = webpage.page_html()
    assert 'id="refine"' in h and h.index('id="refine"') < h.index('id="edit"') + 400           # 更新路线在顶部，不用先点“编辑”
    assert 'class="editonly sec"><button id="undo">撤销</button></div>' in h
    assert 'id="sh_open"' in h and 'id="sh_dirpick"' in h and 'id="sh_pdf"' in h
    assert "rel=\\\"noopener noreferrer\\\"" in h or 'rel="noopener noreferrer"' in h             # 聊天里的链接新窗口打开


def test_share_html_has_navigation_links_on_legs():
    from tripcore import share as sh
    import inspect
    src = inspect.getsource(sh._day_html)
    assert 'e.get("link")' in src and "导航" in src
    assert hasattr(sh, "render_pdf")


def test_hb_title_renames_trip_for_handbook(tmp_path, monkeypatch):
    from tripcore import web
    monkeypatch.setenv("TRIPCORE_EXPORT_DIR", str(tmp_path / "out"))
    s.import_photo_trip(str(_album(tmp_path)))
    with pytest.raises(web.HttpError):
        web.hb_title({"title": "  "})
    with pytest.raises(web.HttpError):
        web.hb_title({"title": "字" * 41})
    assert web.hb_title({"title": "台州三日游"})["name"] == "台州三日游"
    assert web.hb_state()["name"] == "台州三日游"
    assert "台州三日游" in web.hb_style_preview({"style": "手账"})["page"]


def test_restore_page_has_title_box_and_back_step_refills_source():
    from tripcore.webpage import page_html
    h = page_html()
    assert 'id="hb_title"' in h and "hbSaveTitle" in h and "hb_title" in h
    assert "HB.data.folder" in h and "重新恢复会按现在的设置" in h and "ask('重新恢复会" in h


def test_stepper_lets_you_click_forward_again_after_going_back():
    from tripcore.webpage import page_html
    h = page_html()
    assert "span.go" in h and "'go'" in h and ".querySelectorAll('.done,.go')" in h


def test_card_photo_count_auto_varies_and_fixed_is_fixed():
    from tripcore.handbook import card_photo_count
    assert [card_photo_count(0, i, 9) for i in range(4)] == [3, 2, 4, 1]
    assert card_photo_count(0, 2, 2) == 2 and card_photo_count(0, 0, 0) == 1      # 不超过实际有的张数
    assert card_photo_count(5, 0, 2) == 5 and card_photo_count(1, 3, 9) == 1


def test_book_html_pages_toc_and_numbers():
    import re
    from tripcore.book import build_book_html
    st = lambda n, k: {"n": n, "name": f"景点{n}", "rg": "", "t": "09:00–10:00", "dur": 60, "hours": "", "pics": [(f"{n}{j}.jpg", "") for j in range(k)], "facts": [], "imp": "", "leg": ""}
    days = [{"idx": 0, "title": "海边", "date": "1月18日 周四", "wx": "", "km": 3.0, "svg": "<svg class=\"route\"></svg>", "stops": [st(1, 3), st(2, 0)]},
            {"idx": 1, "title": "", "date": "", "wx": "", "km": 0, "svg": "<svg></svg>", "stops": [st(1, 6)]}]
    h = build_book_html("测试书", days, theme_css="", base_css="", km_all=3.0, stops_all=3)
    assert h.count('class="pg') == 1 + 1 + (1 + 2) + (1 + 1) + 1          # 封面、目录、两天的章首和景点页、版权页
    assert '<em>3</em>' in h and '<em>6</em>' in h                         # 目录里的页码：第 1 天从第 3 页，第 2 天从第 6 页
    assert 'ph-area n3' in h and 'ph-area n6' in h and "148mm 210mm" in h
