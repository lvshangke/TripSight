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
    assert "故宫" in page and "天坛" in page and "营业时间" not in page and "<img" not in page
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


def test_handbook_shows_chapters_when_regions_known():
    from tripcore import handbook as hb
    from tripcore.regions import chapter_labels
    _trip()
    t = s._load()
    ids = [it.place_id for it in t.plan.days[0].items]
    labels = chapter_labels({ids[0]: {"province": "浙江省", "city": "台州市", "district": "临海市"}, ids[1]: {"province": "浙江省", "city": "台州市", "district": "仙居县"}})
    assert labels == {ids[0]: "临海", ids[1]: "仙居"}
    res = hb.build_handbook(t, s.trip_path().with_name("exp2"), cards=False, regions=labels)
    page = (Path(res["folder"]) / "index.html").read_text(encoding="utf-8")
    assert "临海 → 仙居" in page and 'class="rg"' in page


def test_chapters_by_city_when_trip_spans_cities():
    from tripcore.regions import chapter_labels
    r = {"a": {"province": "浙江省", "city": "杭州市", "district": "西湖区"}, "b": {"province": "江苏省", "city": "苏州市", "district": "姑苏区"}}
    assert chapter_labels(r) == {"a": "杭州", "b": "苏州"}
    assert chapter_labels({"a": {"province": "", "city": "", "district": ""}}) == {}


def test_route_svg_styles_segments_by_mode_with_legend():
    from tripcore.handbook import _route_svg
    from tripcore.models import Leg
    stops = [(30.0, 120.0), (30.01, 120.01), (30.05, 120.05)]
    legs = [Leg(from_id="a", to_id="b", mode="walk", distance_km=1, minutes=12, detail_level="route"),
            Leg(from_id="b", to_id="c", mode="drive", distance_km=6, minutes=15)]
    svg = _route_svg(stops, legs)
    assert "m-walk" in svg and "m-drive est" in svg and "步行" in svg and "驾车" in svg
    assert "公交" not in svg                                    # 图例只列出现过的方式


def test_route_svg_thumbnail_pins_use_unique_clip_ids():
    from tripcore.handbook import _route_svg
    from tripcore.models import Leg
    stops = [(30.0, 120.0), (30.01, 120.01), (30.05, 120.05)]
    legs = [Leg(from_id="a", to_id="b", mode="walk", distance_km=1, minutes=12),
            Leg(from_id="b", to_id="c", mode="walk", distance_km=6, minutes=15)]
    a = _route_svg(stops, legs, pins=["data:image/jpeg;base64,AA", None, "data:image/jpeg;base64,BB"])
    b = _route_svg(stops, legs, pins=["data:image/jpeg;base64,AA", None, None])
    import re
    ids = re.findall(r'<clipPath id="(pin\d+)"', a + b)
    assert len(ids) == 3 and len(set(ids)) == 3                  # 同一页里多张图，clipPath 不重名
    assert a.count("<image") == 2 and "pinr" in a
    assert "<image" not in _route_svg(stops, legs)
