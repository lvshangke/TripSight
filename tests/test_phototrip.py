"""从照片还原旅程：EXIF 读取、聚类、挑图、联系图、新建行程；位置不泄露到挂载后的照片里。"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from tripcore import phototrip as pt  # noqa: E402


def _jpg(path: Path, taken: datetime, lat=None, lon=None, color=(120, 160, 200)):
    im = Image.new("RGB", (64, 48), color)
    ex = Image.Exif()
    ex.get_ifd(0x8769)[0x9003] = taken.strftime("%Y:%m:%d %H:%M:%S")
    if lat is not None:
        g = ex.get_ifd(0x8825)
        g[1], g[3] = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
        a, b = abs(lat), abs(lon)
        g[2] = (int(a), int((a % 1) * 60), ((a % 1) * 60 % 1) * 60)
        g[4] = (int(b), int((b % 1) * 60), ((b % 1) * 60 % 1) * 60)
    im.save(path, "JPEG", exif=ex)


def _album(tmp_path):
    t0 = datetime(2026, 6, 19, 10, 0)
    for i in range(4):                                         # 景点 A：4 张，10 分钟内，同一位置
        _jpg(tmp_path / f"a{i}.jpg", t0 + timedelta(minutes=3 * i), 28.70, 121.40)
    for i in range(3):                                         # 景点 B：2 公里外，同一天下午
        _jpg(tmp_path / f"b{i}.jpg", t0 + timedelta(hours=4, minutes=2 * i), 28.72, 121.42)
    _jpg(tmp_path / "next.jpg", t0 + timedelta(days=1), 28.70, 121.40)   # 第二天回到 A 附近：新的点
    _jpg(tmp_path / "nogps.jpg", t0, None)
    (tmp_path / "note.txt").write_text("x")


def test_read_photos_counts_and_skips(tmp_path):
    _album(tmp_path)
    photos, st = pt.read_photos(tmp_path)
    assert len(photos) == 8 and st["images"] == 9 and st["no_gps"] == 1
    assert photos == sorted(photos, key=lambda p: (p.taken, p.file))
    assert abs(photos[0].lat - 28.70) < 0.001 and abs(photos[0].lon - 121.40) < 0.001


def test_cluster_by_distance_gap_and_day(tmp_path):
    _album(tmp_path)
    stops = pt.cluster(pt.read_photos(tmp_path)[0])
    assert [s.n for s in stops] == [4, 3, 1]
    assert stops[0].day != stops[2].day and stops[0].minutes == 9
    assert pt.haversine_m((28.70, 121.40), (28.72, 121.42)) > 2000


def test_best_files_and_contact_sheet(tmp_path):
    _album(tmp_path)
    stops = pt.cluster(pt.read_photos(tmp_path)[0])
    assert len(pt.best_files(tmp_path, stops[0].files, 2)) == 2
    data = pt.contact_sheet(tmp_path, stops[0].files)
    sheet = Image.open(__import__("io").BytesIO(data))
    assert sheet.format == "JPEG" and not sheet.getexif()
    with pytest.raises(ValueError):
        pt.contact_sheet(tmp_path, ["missing.jpg"])
