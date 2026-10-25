"""导出到 Obsidian 笔记文件夹和日历 .ics：只写本地文件，内容全部来自行程。"""

import pytest

pytest.importorskip("mcp")

from tripcore import mcp_server as s  # noqa: E402


def _trip():
    s.new_trip(num_days=1, mode="transit", city="北京")
    s.set_dates("2026-11-07", "2026-11-07")
    s.add_place("故宫", 39.9163, 116.3972, duration_min=120)
    s.add_place("天坛", 39.8822, 116.4066, duration_min=60)
    s.schedule_days()


def test_export_notes_writes_obsidian_folder_and_ics():
    _trip()
    out = s.export_notes()
    root = next(p for p in s.trip_path().with_name("exports").iterdir() if p.is_dir())
    day = (root / "第1天.md").read_text(encoding="utf-8")
    assert "[[故宫]]" in day and "[[天坛]]" in day and "预计时间" in day
    assert (root / "景点" / "故宫.md").exists()
    ics = next(root.glob("*.ics")).read_bytes().decode("utf-8")
    assert ics.count("BEGIN:VEVENT") == 2 and "DTSTART:20261107T" in ics and ics.endswith("\r\n")
    assert all(len(l.encode()) <= 75 for l in ics.split("\r\n"))
    assert str(root) in out


def test_export_notes_never_overwrites():
    _trip()
    s.export_notes(); s.export_notes()
    dirs = [p for p in s.trip_path().with_name("exports").iterdir() if p.is_dir()]
    assert len(dirs) == 2


def test_ics_needs_dates_but_notes_still_export():
    s.new_trip(num_days=1, mode="transit", city="北京")
    s.add_place("故宫", 39.9163, 116.3972)
    s.schedule_days()
    out = s.export_notes()
    root = next(p for p in s.trip_path().with_name("exports").iterdir() if p.is_dir())
    assert (root / "第1天.md").exists() and not list(root.glob("*.ics")) and "日历" in out


def test_export_notes_requires_plan():
    s.new_trip(num_days=1, city="北京")
    with pytest.raises(s.ToolError):
        s.export_notes()


def test_export_notes_into_given_folder_only_if_it_exists(tmp_path):
    _trip()
    with pytest.raises(s.ToolError):
        s.export_notes(folder=str(tmp_path / "不存在"))
    assert not (tmp_path / "不存在").exists()
    out = s.export_notes(folder=str(tmp_path))
    sub = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(sub) == 1 and (sub[0] / "第1天.md").exists() and str(sub[0]) in out
