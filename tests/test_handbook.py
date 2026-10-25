"""行程手册：本地网页文件夹 + 3:4 卡片 + 文案；照片默认不带，不覆盖已有导出。"""

from pathlib import Path

import pytest

pytest.importorskip("mcp")

from tripcore import mcp_server as s  # noqa: E402


def _trip():
    s.new_trip(num_days=1, mode="transit", city="北京")
    s.set_dates("2026-11-07", "2026-11-07")
    s.add_place("故宫", 39.9163, 116.3972, duration_min=120)
    s.add_place("天坛", 39.8822, 116.4066, duration_min=60)
    s.schedule_days()


def _root():
    return next(p for p in s.trip_path().with_name("exports").iterdir() if p.is_dir())


def test_handbook_writes_page_and_caption_without_photos():
    _trip()
    out = s.export_handbook(cards=False)
    root = _root()
    page = (root / "index.html").read_text(encoding="utf-8")
    assert "故宫" in page and "天坛" in page and "预计时间" in page and "<img" not in page
    assert (root / "caption.txt").exists() and str(root) in out
    assert not (root / "photos").exists()


def test_handbook_never_overwrites():
    _trip()
    s.export_handbook(cards=False); s.export_handbook(cards=False)
    assert len([p for p in s.trip_path().with_name("exports").iterdir() if p.is_dir()]) == 2


def test_handbook_video_needs_place_and_file(tmp_path):
    _trip()
    with pytest.raises(s.ToolError):
        s.export_handbook(video_path=str(tmp_path / "x.mp4"), video_place="故宫", cards=False)   # 文件不存在
    v = tmp_path / "v.mp4"; v.write_bytes(b"\x00\x00\x00 ftypmp42")
    with pytest.raises(s.ToolError):
        s.export_handbook(video_path=str(v), cards=False)                                         # 没给景点
    s.export_handbook(video_path=str(v), video_place="故宫", cards=False)
    root = _root()
    assert (root / "media").exists() and "<video" in (root / "index.html").read_text(encoding="utf-8")


def test_handbook_requires_plan():
    s.new_trip(num_days=1, city="北京")
    with pytest.raises(s.ToolError):
        s.export_handbook(cards=False)


def test_handbook_shows_up_to_six_photos_and_basemap(tmp_path):
    import io
    from PIL import Image
    from tripcore import handbook as hb
    from tripcore.basemap import Basemap

    class FakeAmap:
        def static_map(self, lat, lon, z, w, h):
            b = io.BytesIO(); Image.new("RGB", (w, h), (200, 220, 200)).save(b, "PNG"); return b.getvalue()

    _trip()
    trip = s._load()
    pid = trip.plan.days[0].items[0].place_id
    pd = tmp_path / "ph"; pd.mkdir()
    photos = []
    for i in range(8):
        Image.new("RGB", (40, 30), (i * 20, 50, 90)).save(pd / f"{i}.jpg"); photos.append({"file": f"{i}.jpg", "place_id": pid, "caption": ""})
    res = hb.build_handbook(trip, tmp_path / "out", photos=photos, photo_dir=pd, cards=False, basemap=Basemap(FakeAmap()))
    page = (Path(res["folder"]) / "index.html").read_text(encoding="utf-8")
    assert page.count('src="photos/') == 6
    assert '<image href="data:image/jpeg' in page


def test_handbook_styles_change_colors_and_reject_unknown():
    _trip()
    s.export_handbook(cards=False, style="胶片")
    page = (_root() / "index.html").read_text(encoding="utf-8")
    assert "--acc:#a4531f" in page
    with pytest.raises(Exception, match="style"):
        s.export_handbook(cards=False, style="暗黑")
