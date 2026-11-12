import json

import pytest

pytest.importorskip("mcp")

from tripcore import mcp_server as s  # noqa: E402
from tripcore import footprint as fp  # noqa: E402


def _trip(name, pts):
    s.new_trip(name=name, num_days=1, city="台州")
    for i, (n, la, lo) in enumerate(pts):
        s.add_place(n, la, lo, duration_min=60)
    s.schedule_days()
    return s.trip_path().parent


def test_footprint_counts_only_gone_trips(tmp_path):
    d = _trip("台州", [("甲", 28.70, 121.40), ("乙", 28.80, 121.50)])
    assert "还没有可统计" in s.footprint()                      # 纯计划不算
    t = s._load()
    ids = [p.id for p in t.places]
    (d / "photo_trip.json").write_text(json.dumps({"stops": []}), encoding="utf-8")
    (d / "regions.json").write_text(json.dumps({ids[0]: {"city": "台州市"}, ids[1]: {"city": "台州市"}}), encoding="utf-8")
    out = s.footprint()
    assert "1 趟" in out and "台州" in out and "直线" in out and "下限" in out
    assert "约 1" in out                                           # 两点相距约 14 公里
    html = (s.trip_path().parent / "足迹.html").read_text(encoding="utf-8")
    assert "<circle" in html and "<polyline" in html


def test_review_visited_no_longer_counts_only_restored_trips():
    _trip("甲行", [("A", 30.0, 120.0), ("B", 30.1, 120.1)])
    s.record_review("A", "去了")
    assert "还没有可统计" in s.footprint()


def test_basemap_option_without_key_or_abroad(monkeypatch):
    d = _trip("台州", [("甲", 28.70, 121.40), ("乙", 28.80, 121.50)])
    (d / "photo_trip.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("AMAP_KEY", raising=False)
    assert "没有加底图：没有 AMAP_KEY" in s.footprint(basemap=True)


def test_basemap_view_never_exceeds_static_map_limit():
    from tripcore.basemap import choose_view
    v = choose_view([(28.7, 121.4), (28.9, 121.6)], 940, 330, 36)
    assert max(v.req_size) <= 1024
    v2 = choose_view([(28.7, 121.4), (28.71, 121.41)], 400, 300, 30)
    assert v2.ratio == 2 and max(v2.req_size) <= 1024


def test_html_embeds_basemap_when_available():
    f = fp.TripFoot("a", "甲", 1, "", True, [(0, 28.7, 121.4, "x"), (0, 28.8, 121.5, "y")])

    class BM:
        def fetch(self, v):
            return "data:image/jpeg;base64,AAAA"
    assert "<image href=\"data:image/jpeg" in fp.build_html([f], BM())
    assert "<image" not in fp.build_html([f], None)


def test_basemap_view_uses_gcj02_not_raw_wgs84():
    from tripcore.coords import wgs84_to_gcj02
    f = fp.TripFoot("a", "甲", 1, "", True, [(0, 28.70, 121.40, "x"), (0, 28.72, 121.42, "y")])
    seen = {}

    class BM:
        def fetch(self, v):
            seen["v"] = v
            return "data:image/jpeg;base64,AAAA"
    fp.build_html([f], BM())
    gla, glo = wgs84_to_gcj02(28.71, 121.41)
    assert abs(seen["v"].lat - gla) < 0.003 and abs(seen["v"].lat - 28.71) > 0.0005 or abs(seen["v"].lon - glo) < 0.003


def test_nearby_points_merge_into_one_numbered_pin():
    f = fp.TripFoot("a", "甲", 1, "", True, [(0, 28.7, 121.4, "x"), (0, 28.70001, 121.40001, "y"), (0, 28.8, 121.5, "z")])
    html = fp.build_html([f])
    assert html.count('class="t t0 pin"') == 2 and ">2</text>" in html



def test_footprint_data_photo_pins_and_real_days():
    """网页足迹页：每个点带日期和这一站自己的照片缩略图；天数按真正拍过照的天数算（跨年的相册不是几百天）。"""
    from PIL import Image
    d = _trip("台州", [("甲", 28.70, 121.40), ("乙", 28.80, 121.50)])
    ids = [p.id for p in s._load().places]
    (d / "photos").mkdir(exist_ok=True)
    Image.new("RGB", (80, 60), (200, 80, 60)).save(d / "photos" / "a.jpg")
    (d / "photos.json").write_text(json.dumps([{"id": "x1", "file": "a.jpg", "place_id": ids[0]}, {"id": "x2", "file": "a.jpg", "place_id": ids[0], "hide": True}]), encoding="utf-8")
    (d / "photo_trip.json").write_text(json.dumps({"stops": [{"place_id": ids[0], "start": "2024-01-18T09:00:00"}, {"place_id": ids[1], "start": "2025-03-02T10:00:00"}]}), encoding="utf-8")
    out = s.footprint_data()
    t = out["trips"][0]
    assert t["days"] == 2 and out["totals"]["days"] == 2
    p0, p1 = t["pins"]
    assert p0["date"] == "2024-01-18" and len(p0["thumbs"]) == 1 and p0["thumbs"][0].startswith("data:image/jpeg")   # 隐藏的照片不用
    assert p1["thumbs"] == [] and len(p0["pos"]) == 2
    html = (d / "足迹.html")
    s.footprint()
    assert "<image" in html.read_text(encoding="utf-8")                                                          # 导出的地图页也用照片图钉


def _two_stop_trip():
    d = _trip("台州", [("甲", 28.70, 121.40), ("乙", 28.80, 121.50)])
    ids = [p.id for p in s._load().places]
    (d / "photo_trip.json").write_text(json.dumps({"stops": [{"place_id": ids[0], "start": "2024-01-18T09:00:00"}, {"place_id": ids[1], "start": "2024-01-18T11:00:00"}]}), encoding="utf-8")
    return d


def test_footprint_routes_real_path_cached_and_domestic_only(monkeypatch):
    from tripcore import amap as am
    _two_stop_trip()
    calls = []

    class FakeClient:
        def route(self, mode, a, b, c, d, **kw):
            calls.append(mode)
            return am.RouteResult(mode, 15.0, 25, path=[(a, b), ((a + c) / 2, (b + d) / 2), (c, d)])

    monkeypatch.setattr(s.AmapClient, "from_env", classmethod(lambda cls, log_path=None: FakeClient()))
    out = s.footprint_routes()
    assert out["done"] and len(out["routes"]) == 1 and calls == ["drive"]
    r = out["routes"][0]
    assert r["day"] == 1 and r["i"] == 0 and len(r["path"]) == 3 and r["path"][0] != [28.70, 121.40]   # 已转成高德底图用的坐标
    out2 = s.footprint_routes()                                                                        # 第二次走缓存，不再联网
    assert len(out2["routes"]) == 1 and calls == ["drive"]
    assert "wgs" in s.footprint_data()["trips"][0]["pins"][0]


def test_footprint_routes_needs_key(monkeypatch):
    monkeypatch.setattr(s.AmapClient, "from_env", classmethod(lambda cls, log_path=None: None))
    _two_stop_trip()
    with pytest.raises(s.ToolError, match="高德 key"):
        s.footprint_routes()


def test_footprint_routes_skips_abroad(monkeypatch):
    s.new_trip(name="京都", num_days=1)
    s.add_place("甲", 35.01, 135.76)
    s.add_place("乙", 35.02, 135.77)
    s.schedule_days()
    d = s.trip_path().parent
    ids = [p.id for p in s._load().places]
    (d / "photo_trip.json").write_text(json.dumps({"stops": [{"place_id": ids[0], "start": "2024-04-01T09:00:00"}, {"place_id": ids[1], "start": "2024-04-01T11:00:00"}]}), encoding="utf-8")

    class Boom:
        def route(self, *a, **k):
            raise AssertionError("境外不该联网")

    monkeypatch.setattr(s.AmapClient, "from_env", classmethod(lambda cls, log_path=None: Boom()))
    out = s.footprint_routes()
    assert out["abroad"] == 1 and out["routes"] == [] and out["done"]
