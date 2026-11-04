import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest

from tripcore import video as v

HAS_FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _stops():
    d = date(2026, 6, 19)
    return [{"id": "p1", "day": d, "lat": 28.70, "lon": 121.40, "start": datetime(2026, 6, 19, 10, 0), "end": datetime(2026, 6, 19, 10, 10)},
            {"id": "p2", "day": d, "lat": 28.90, "lon": 121.60, "start": datetime(2026, 6, 19, 14, 0), "end": datetime(2026, 6, 19, 14, 30)}]


def _order():
    return [{"id": "p1", "name": "七仙女", "day": 0, "date": "2026-06-19", "lat": 28.70, "lon": 121.40},
            {"id": "p2", "name": "神女峰", "day": 0, "date": "2026-06-19", "lat": 28.90, "lon": 121.60}]


def test_assign_by_gps_then_time():
    a = v.Clip("a.mov", "/x/a.mov", 10, datetime(2026, 6, 19, 9, 0), 28.7005, 121.4005)      # 位置对上 p1（时间不重要）
    b = v.Clip("b.mov", "/x/b.mov", 10, datetime(2026, 6, 19, 14, 20))                        # 无位置，时间在 p2 时段内
    c = v.Clip("c.mov", "/x/c.mov", 10, datetime(2026, 6, 19, 20, 0))                         # 太远
    d = v.Clip("d.mov", "/x/d.mov", 10, datetime(2026, 6, 20, 10, 5), 28.70, 121.40)          # 不是同一天
    assert v.assign([a, b, c, d], _stops()) == 2
    assert (a.stop, b.stop, c.stop, d.stop) == ("p1", "p2", None, None)


def test_plan_scales_to_target_and_adds_cards():
    clips = [v.Clip(f"{i}.mov", f"/x/{i}.mov", 20, datetime(2026, 6, 19, 10, i), stop="p1") for i in range(4)] + \
            [v.Clip("z.mov", "/x/z.mov", 20, datetime(2026, 6, 19, 14, 5), stop="p2")]
    segs = v.plan(clips, _order(), target_s=30, clip_max=8)
    assert segs[0].kind == "card" and segs[0].title == "第1天" and segs[1].points
    total = sum(s.secs for s in segs)
    assert total <= 30.5
    assert {s.stop for s in segs if s.kind == "clip"} == {"p1", "p2"}          # 每个景点至少留一段
    assert all(s.offset >= 0 for s in segs if s.kind == "clip")
    with pytest.raises(v.VideoError):
        v.plan([], _order())
    assert "七仙女" in v.srt(segs) and v.srt(segs).count("-->") == 2


def _mk(path: Path, utc: str, loc: str = "", secs: int = 3, audio: bool = True, size="320x240"):
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=duration={secs}:size={size}:rate=30"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=duration={secs}"]
    cmd += ["-metadata", f"creation_time={utc}"]
    if loc:
        cmd += ["-metadata", f"com.apple.quicktime.location.ISO6709={loc}", "-movflags", "use_metadata_tags"]
    cmd += ["-pix_fmt", "yuv420p", str(path)]
    r = subprocess.run(cmd, capture_output=True)
    assert r.returncode == 0, r.stderr[-300:]


@pytest.mark.skipif(not HAS_FF, reason="需要 ffmpeg")
def test_probe_and_render(tmp_path):
    _mk(tmp_path / "a.mov", "2026-06-19T02:05:00Z", "+28.7000+121.4000/")
    _mk(tmp_path / "b.mp4", "2026-06-19T06:10:00Z", audio=False)
    clips, bad = v.scan(tmp_path)
    assert bad == 0 and len(clips) == 2
    a = clips[0]
    assert a.start == datetime(2026, 6, 19, 10, 5) and abs(a.lat - 28.7) < 1e-6 and a.audio
    assert v.assign(clips, _stops()) == 2
    segs = v.plan(clips, _order(), clip_max=2)
    out = tmp_path / "out.mp4"
    v.render(segs, out, tmp_path / "w", (640, 360))
    info = v.probe(out)
    assert info and 8 < info.dur < 14 and info.w == 640 and info.audio


@pytest.mark.skipif(not HAS_FF, reason="需要 ffmpeg")
def test_mcp_tools_end_to_end(tmp_path):
    pytest.importorskip("mcp")
    pytest.importorskip("PIL")
    from tests.test_photo_trip_tools import _album
    from tripcore import mcp_server as s
    photos = _album(tmp_path / "ph") if (tmp_path / "ph").mkdir() is None else None
    s.import_photo_trip(str(photos))                                    # 10:00 一组、14:00 一组
    vids = tmp_path / "vid"; vids.mkdir()
    _mk(vids / "a.mov", "2026-06-19T02:03:00Z")                         # 当地 10:03：落在第一个点时段内
    _mk(vids / "b.mov", "2026-06-19T06:02:00Z")                         # 当地 14:02
    _mk(vids / "c.mov", "2026-06-19T14:00:00Z")                         # 当地 22:00：归不上
    out = s.scan_videos(str(vids))
    assert "读到 3 段" in out and "归不上的 1 段" in out
    with pytest.raises(s.ToolError):
        s.scan_videos(str(tmp_path / "没有"))
    res = s.export_rough_cut(str(vids), target_seconds=20, clip_max=2)
    mp4 = Path(res.split("已生成旅行短片：")[1].split("（")[0])
    assert mp4.is_file() and (mp4.parent / "旅行短片.srt").is_file() and "另有 1 段没归到景点" in res
    assert "没有配乐" in res


@pytest.mark.skipif(not HAS_FF, reason="需要 ffmpeg")
def test_jianying_draft_files(tmp_path):
    pytest.importorskip("pyJianYingDraft")
    _mk(tmp_path / "a.mp4", "2026-06-19T02:05:00Z")
    c = v.probe(tmp_path / "a.mp4"); c.stop = "p1"
    segs = v.plan([c], _order(), clip_max=2)
    drafts = tmp_path / "drafts"; drafts.mkdir()
    p = v.jianying_draft(segs, (1920, 1080), drafts, "测试", tmp_path / "w")
    assert (Path(p) / "draft_content.json").is_file()
    with pytest.raises(v.VideoError):
        v.jianying_draft(segs, (1920, 1080), tmp_path / "不存在", "x", tmp_path / "w")


def test_canvas_follows_source_resolution():
    """720p 的竖屏素材不应被放大成 1080×1920（文件虚大、画质无提升）。"""
    small = [v.Clip("a.mov", "a.mov", 5.0, None, None, None, 720, 1280, True)]
    big = [v.Clip("b.mov", "b.mov", 5.0, None, None, None, 1080, 1920, True)]
    wide = [v.Clip("c.mov", "c.mov", 5.0, None, None, None, 1920, 1080, True)]
    assert v._canvas(small) == (720, 1280)
    assert v._canvas(big) == (1080, 1920)
    assert v._canvas(wide) == (1920, 1080)


def test_route_card_labels_stay_inside_canvas(tmp_path):
    """路线卡片的地名放在点的左/右侧，竖屏里不能被画布边缘截断（左右边缘各留 2% 以上的空白）。"""
    from PIL import Image
    seg = v.Seg("card", 2.0, title="第3天的路线", points=[("很长很长的景点名称甲乙丙", 29.2, 121.0), ("另一个很长的景点名称丁戊己", 29.3, 121.2)])
    png = tmp_path / "c.png"
    v.card_png(seg, (720, 1280), png)
    im = Image.open(png).convert("RGB")
    for x, ref in ((0, 10), (1, 10), (718, 710), (719, 710)):            # 底是渐变：边缘列应和靠内几像素的同一行背景一致
        assert all(im.getpixel((x, y)) == im.getpixel((ref, y)) for y in range(0, 1280, 4)), f"边缘列 {x} 有内容，文字被截断"


@pytest.mark.skipif(not HAS_FF, reason="需要 ffmpeg")
def test_render_uses_only_first_audio_track(tmp_path):
    """新款 iPhone 的 .mov 有第二条空间音频（apac）轨，ffmpeg 解不了；渲染只能取第一条音轨。"""
    src = tmp_path / "two_audio.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2", "-f", "lavfi", "-i", "sine=d=2",
                    "-f", "lavfi", "-i", "sine=f=880:d=2", "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
    c = v.probe(src); c.stop = "p1"
    segs = [s for s in v.plan([c], _order(), clip_max=2, cards=False) if s.kind == "clip"]
    out = tmp_path / "o.mp4"
    v.render(segs, out, tmp_path / "w", (320, 240))
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(out)],
                       capture_output=True, text=True)
    assert len(r.stdout.split()) == 1
