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


def test_review_visited_counts_and_untagged_note(tmp_path):
    d = _trip("甲行", [("A", 30.0, 120.0), ("B", 30.1, 120.1)])
    s.record_review("A", "去了")
    out = s.footprint()
    assert "1 个地方" in out and "还没有城市信息" in out
