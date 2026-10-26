from datetime import datetime

import pytest

from tripcore import trackfile as tf

GPX = """<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>
<trkpt lat="28.00" lon="121.00"><time>2026-05-01T02:00:00Z</time></trkpt>
<trkpt lat="28.02" lon="121.02"><time>2026-05-01T02:10:00Z</time></trkpt>
<trkpt lat="28.50" lon="121.50"><time>2026-05-01T05:00:00Z</time></trkpt>
</trkseg></trk></gpx>"""

KML = """<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2"><Document><Placemark><gx:Track>
<when>2026-05-01T02:00:00Z</when><when>2026-05-01T02:10:00Z</when>
<gx:coord>121.0 28.0 0</gx:coord><gx:coord>121.02 28.02 0</gx:coord></gx:Track></Placemark></Document></kml>"""


def test_gpx_utc_to_local(tmp_path):
    f = tmp_path / "a.gpx"; f.write_text(GPX, encoding="utf-8")
    pts = tf.parse_file(f, 8)
    assert pts[0][0] == datetime(2026, 5, 1, 10, 0) and len(pts) == 3


def test_kml_track(tmp_path):
    f = tmp_path / "a.kml"; f.write_text(KML, encoding="utf-8")
    pts = tf.parse_file(f, 8)
    assert len(pts) == 2 and pts[1][1:] == (28.02, 121.02)


def test_locate_interpolates_and_respects_gap(tmp_path):
    f = tmp_path / "a.gpx"; f.write_text(GPX, encoding="utf-8")
    pts = tf.read_tracks(str(f), 8)
    got, left = tf.locate(pts, [("mid.jpg", datetime(2026, 5, 1, 10, 5)),
                                 ("near.jpg", datetime(2026, 5, 1, 10, 15)),
                                 ("far.jpg", datetime(2026, 5, 1, 12, 0))])
    d = {p.file: p for p in got}
    assert abs(d["mid.jpg"].lat - 28.01) < 1e-6
    assert abs(d["near.jpg"].lat - 28.02) < 1e-6          # 10:15 在最后一个靠前点之后 5 分钟内 → 取最近点
    assert [x[0] for x in left] == ["far.jpg"]


def test_errors(tmp_path):
    with pytest.raises(tf.TrackError):
        tf.read_tracks(str(tmp_path / "nope.gpx"))
    (tmp_path / "bad.gpx").write_text("<gpx", encoding="utf-8")
    with pytest.raises(tf.TrackError):
        tf.read_tracks(str(tmp_path / "bad.gpx"))
    (tmp_path / "e.gpx").write_text('<gpx><trk><trkseg><trkpt lat="1" lon="1"/></trkseg></trk></gpx>', encoding="utf-8")
    with pytest.raises(tf.TrackError):
        tf.read_tracks(str(tmp_path / "e.gpx"))
