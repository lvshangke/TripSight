"""路线图的可选高德底图：默认不联网；打开才取图；只发中心点/缩放/大小；失败如实退回。"""

import io
import math

import pytest

pytest.importorskip("mcp")
PIL = pytest.importorskip("PIL.Image")

from tripcore import basemap as bm  # noqa: E402
from tripcore import mcp_server as s  # noqa: E402
from tripcore import share  # noqa: E402
from tripcore.amap import AmapClient, AmapError  # noqa: E402

HOTEL = "秘密酒店XYZ"


def _png(w=720, h=500):
    buf = io.BytesIO()
    PIL.new("RGB", (w, h), (200, 220, 240)).save(buf, "PNG")
    return buf.getvalue()


class FakeClient:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def static_map(self, lat, lon, zoom, w, h):
        self.calls.append((lat, lon, zoom, w, h))
        if self.fail:
            raise AmapError(self.fail)
        return _png(w, h)


@pytest.fixture(autouse=True)
def tmp_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIPCORE_FILE", str(tmp_path / "trip.json"))
    monkeypatch.setattr(share, "render_png", lambda *a, **k: "测试里不截图")


def _trip():
    s.new_trip(name="底图测试", num_days=2, start_date="2026-10-01", end_date="2026-10-02")
    s.add_place("故宫", 39.9163, 116.3972, duration_min=240, must_go=True, priority=5)
    s.add_place("天坛", 39.8822, 116.4066, duration_min=120)
    s.add_place("颐和园", 39.9999, 116.2755, duration_min=180)
    s.add_lodging(HOTEL, 39.91, 116.40, price_min=300, price_max=500, choose=True)
    s.schedule_days()


def test_projection_matches_view_and_choose_view_fits():
    pts = [(39.9, 116.3), (39.95, 116.45), (39.88, 116.36)]
    v = bm.choose_view(pts, 360, 300, 18)
    pr = bm.Projection(v)
    assert pr.xy(v.lat, v.lon) == pytest.approx((180, 150), abs=1e-6)
    xs, ys = zip(*(pr.xy(*p) for p in pts))
    assert min(xs) >= 18 - 1 and max(xs) <= 360 - 18 + 1 and min(ys) >= 18 - 1 and max(ys) <= 300 - 18 + 1
    w, h = v.req_size
    assert (w, h) == (720, 600) and v.req_zoom == v.zoom + 1 and w <= 1024 and h <= 1024
    la, lo = bm._unworld(*bm._world(31.2, 121.5, 12), 12)
    assert (la, lo) == pytest.approx((31.2, 121.5), abs=1e-6)


def test_fetch_caches_and_reports_failures(tmp_path):
    v = bm.choose_view([(39.9, 116.3), (39.95, 116.45)], 360, 300, 18)
    c = FakeClient()
    b = bm.Basemap(c, tmp_path / "cache")
    a1 = b.fetch(v)
    a2 = b.fetch(v)
    assert a1 == a2 and a1.startswith("data:image/jpeg;base64,") and len(c.calls) == 1 and (b.requests, b.hits) == (1, 1)
    bad = bm.Basemap(FakeClient(fail="高德返回错误：INVALID_USER_KEY"))
    assert bad.fetch(v) is None and "INVALID_USER_KEY" in bad.failures[0]
    junk = bm.Basemap(type("J", (), {"static_map": lambda self, *a: b"not an image"})())
    assert junk.fetch(v) is None and junk.failures


def test_amap_static_map_sends_only_numbers_and_never_logs_key(tmp_path):
    urls = []
    log = tmp_path / "amap.log"
    cl = AmapClient("SECRETKEY", opener=lambda u: (urls.append(u) or _png()), log_path=log)
    img = cl.static_map(39.9, 116.4, 15, 720, 600)
    assert img[:4] == b"\x89PNG" and "/v3/staticmap?" in urls[0]
    for part in ("location=116.400000%2C39.900000", "zoom=15", "size=720%2A600"):
        assert part in urls[0]
    assert "SECRETKEY" not in log.read_text(encoding="utf-8")
    err = AmapClient("K", opener=lambda u: {"status": "0", "info": "INVALID_USER_KEY"})
    with pytest.raises(AmapError):
        err.static_map(39.9, 116.4, 15, 100, 100)
    err2 = AmapClient("K", opener=lambda u: b'{"status":"0","info":"DAILY_QUERY_OVER_LIMIT"}')
    with pytest.raises(AmapError) as e:
        err2.static_map(39.9, 116.4, 15, 100, 100)
    assert "DAILY_QUERY_OVER_LIMIT" in str(e.value)


def test_share_default_has_no_basemap_and_opt_in_embeds_it(monkeypatch, tmp_path):
    _trip()
    plain = share.build_share_html(s._load())
    assert "<image" not in plain and "底图 © 高德地图" not in plain
    c = FakeClient()
    monkeypatch.setattr(s, "_make_basemap", lambda trip: (bm.Basemap(c, tmp_path / "c"), ""))
    out = s.export_share(basemap=True)
    html = open(out.split("：", 1)[1].split("\n")[0], encoding="utf-8").read()
    assert html.count("<image href=\"data:image/jpeg") >= 2 and "底图 © 高德地图" in html and "向高德请求了" in out
    assert HOTEL not in html and not share.guard_html(html)
    assert all(isinstance(x, (int, float)) for call in c.calls for x in call)           # 只发了数字，没有名字
    assert 'data-vb="{}"' in html                                                           # 有底图时总览不做放大动画（底图分辨率不够）


def test_basemap_without_key_or_failing_degrades_with_reason(monkeypatch):
    _trip()
    monkeypatch.delenv("AMAP_KEY", raising=False)
    out = s.export_share(basemap=True)
    assert "没有加底图：没有 AMAP_KEY" in out and "<image" not in open(out.split("：", 1)[1].split("\n")[0], encoding="utf-8").read()
    monkeypatch.setattr(s, "_make_basemap", lambda trip: (bm.Basemap(FakeClient(fail="高德返回错误：INVALID_USER_KEY")), ""))
    out2 = s.export_share(basemap=True)
    assert "INVALID_USER_KEY" in out2 and "已退回无底图" in out2
    assert "<image" not in open(out2.split("：", 1)[1].split("\n")[0], encoding="utf-8").read()
