"""直接读 Mac 照片 App：用假的 osxphotos 数据库测试，不需要真的照片库。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("mcp")
pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from tripcore import mcp_server as s  # noqa: E402
from tripcore import photoslib as pl  # noqa: E402
from tests.test_phototrip import _jpg  # noqa: E402


def _fake_db(tmp_path):
    t0 = datetime(2026, 6, 19, 10, 0, tzinfo=timezone(timedelta(hours=8)))
    ph = []

    def add(i, dt, lat, lon, ext=".jpg", derivative=False, hidden=False):
        f = tmp_path / f"IMG_{i}{ext}"
        if ext == ".heic":
            f.write_bytes(b"heic")
            d = tmp_path / f"IMG_{i}_deriv.jpg"
            Image.new("RGB", (64, 48), (i * 10 % 255, 100, 200)).save(d)
            ph.append(NS(date=dt, latitude=lat, longitude=lon, path=str(f), path_derivatives=[str(d)], hidden=hidden, intrash=False, isphoto=True))
            return
        _jpg(f, dt.replace(tzinfo=None), None, color=(i * 11 % 255, 100 + i, 200 - i))
        ph.append(NS(date=dt, latitude=lat, longitude=lon, path=str(f), path_derivatives=[], hidden=hidden, intrash=False, isphoto=True))

    for i in range(4):
        add(i, t0 + timedelta(minutes=3 * i), 28.70, 121.40, ext=".heic" if i == 0 else ".jpg")
    for i in range(10, 13):
        add(i, t0 + timedelta(hours=4, minutes=2 * i - 20), 28.72, 121.42)
    add(20, t0 + timedelta(minutes=5), None, None)                       # 无定位
    add(21, t0 + timedelta(minutes=1), 28.70, 121.40, hidden=True)       # 隐藏的不读
    album = NS(title="台州", photos=ph)
    return NS(album_info=[album, NS(title="空", photos=[])], photos=lambda albums, images, movies: ph if albums == ["台州"] else [])


def test_read_album_uses_derivative_for_heic_and_skips_hidden(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "_open_db", lambda: _fake_db(tmp_path))
    assert pl.list_albums()[0]["name"] == "台州"
    photos, untagged, st = pl.read_album("台州")
    assert len(photos) == 7 and len(untagged) == 1 and st["images"] == 8 and st["no_gps"] == 1
    assert any(p.file.endswith("_deriv.jpg") for p in photos)            # HEIC 原图 → 本机预览图
    assert all(Path(p.file).is_absolute() for p in photos)
    assert photos[0].taken.tzinfo is None
    with pytest.raises(pl.PhotosLibError, match="没有叫"):
        pl.read_album("不存在")


def test_import_trip_from_album_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "_open_db", lambda: _fake_db(tmp_path))
    out = s.import_photo_trip(album="台州")
    assert "已从照片还原行程" in out and "没有定位的照片" in out
    t = s._load()
    assert len(t.places) == 2
    assert len(s._ph.load(s._photo_index())) >= 6                         # 路径是绝对路径，挂照片也走通
    blocks = s.view_stop(t.places[0].id)
    assert blocks[1].type == "image"
    assert s._load_json_file(s._photo_trip_path())["album"] == "台州"


def test_unavailable_gives_clear_message(monkeypatch):
    monkeypatch.setattr(pl.sys, "platform", "linux")
    ok, why = pl.available()
    assert not ok and "导出到文件夹" in why
    with pytest.raises(Exception, match="导出到文件夹"):
        s.list_photo_albums()
    with pytest.raises(Exception, match="folder"):
        s.import_photo_trip()
