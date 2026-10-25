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
    assert all(p.source == "photo" and "停留点" in p.name for p in t.places) and "路过" in out
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
