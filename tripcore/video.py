"""视频素材整理 + 粗剪：把用户的视频按拍摄时间/位置归到各个景点，按景点顺序排成一条粗剪片，
景点之间插入真实路线的小卡片；同时可以生成剪映草稿。只在本机处理（需要 ffmpeg），不联网。

规则：
- 视频内容不交给模型，只用时间、位置、时长这些元数据；
- 不自带音乐，不加特效，只做“选段、排序、字幕卡片”；创意部分留给用户在剪映里调；
- 片段取中间一段，总长按素材量和目标时长自动缩放。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .phototrip import haversine_m

VIDEO_EXT = {".mov", ".mp4", ".m4v"}
CARD_SECS = 2.0
LOWER_SECS = 2.5


class VideoError(Exception):
    pass


@dataclass
class Clip:
    file: str
    path: str
    dur: float
    start: Optional[datetime] = None        # 当地时间（无时区）
    lat: Optional[float] = None
    lon: Optional[float] = None
    w: int = 0
    h: int = 0
    audio: bool = False
    stop: Optional[str] = None              # 归到的景点 id


def need_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise VideoError("没有找到 ffmpeg / ffprobe。Mac 上用 brew install ffmpeg 装一下再试。")


def _iso6709(s: str) -> Optional[tuple[float, float]]:
    import re
    m = re.match(r"^([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)", (s or "").strip())
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    return lat, lon


def _when(tags: dict) -> Optional[datetime]:
    """优先用 iPhone 写的带时区的本地拍摄时间；否则用 creation_time（UTC）按 +8 换算，不一定准。"""
    t = tags.get("com.apple.quicktime.creationdate")
    if t:
        try:
            return datetime.fromisoformat(t.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    t = tags.get("creation_time")
    if t:
        try:
            dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
            return dt
        except ValueError:
            return None
    return None


def probe(path: Path) -> Optional[Clip]:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                           capture_output=True, text=True, timeout=60)
        j = json.loads(r.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    streams = j.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not v:
        return None
    fmt = j.get("format") or {}
    try:
        dur = float(fmt.get("duration") or v.get("duration") or 0)
    except ValueError:
        dur = 0.0
    if dur <= 0:
        return None
    tags = {k.lower(): val for k, val in {**(v.get("tags") or {}), **(fmt.get("tags") or {})}.items()}
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    rot = 0
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    if not rot and "rotate" in (v.get("tags") or {}):
        try:
            rot = int(v["tags"]["rotate"])
        except ValueError:
            pass
    if abs(rot) % 180 == 90:
        w, h = h, w
    pos = _iso6709(tags.get("com.apple.quicktime.location.iso6709", ""))
    return Clip(path.name, str(path), dur, _when(tags), pos[0] if pos else None, pos[1] if pos else None, w, h,
                any(s.get("codec_type") == "audio" for s in streams))


def scan(folder: Path) -> tuple[list[Clip], int]:
    """扫描文件夹（不递归）里的视频。返回 (读到的片段按拍摄时间排序, 读不了的个数)。"""
    return scan_files([p for p in sorted(folder.iterdir()) if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in VIDEO_EXT])


def scan_files(paths: list[Path]) -> tuple[list[Clip], int]:
    """读一组视频文件（文件夹里的，或照片 App 相册里视频的原文件路径，只读不复制）。"""
    need_ffmpeg()
    out: list[Clip] = []
    bad = 0
    for p in paths:
        c = probe(p)
        if c:
            out.append(c)
        else:
            bad += 1
    out.sort(key=lambda c: (c.start or datetime.max, c.file))
    return out, bad


def assign(clips: list[Clip], stops: list[dict], radius_m: float = 1500, window_min: float = 90) -> int:
    """给每个视频找景点。stops: [{id, day: date, lat, lon, start: datetime|None, end: datetime|None}]。
    有位置：同一天里最近的、1500 米内的景点；没位置：拍摄时间落在（或前后 window_min 分钟内）景点时段里。
    返回归上的个数；归不上的 stop 留 None。"""
    n = 0
    for c in clips:
        c.stop = None
        day = c.start.date() if c.start else None
        cand = [s for s in stops if day is None or s["day"] is None or s["day"] == day]
        if c.lat is not None:
            best = min(((haversine_m((c.lat, c.lon), (s["lat"], s["lon"])), s) for s in cand), key=lambda x: x[0], default=None)
            if best and best[0] <= radius_m:
                c.stop = best[1]["id"]
        if c.stop is None and c.start:
            best = None
            for s in cand:
                if not s.get("start"):
                    continue
                if s["start"] <= c.start <= s["end"]:
                    d = 0.0
                else:
                    d = min(abs((c.start - s["start"]).total_seconds()), abs((c.start - s["end"]).total_seconds())) / 60
                if d <= window_min and (best is None or d < best[0]):
                    best = (d, s)
            if best:
                c.stop = best[1]["id"]
        n += c.stop is not None
    return n


@dataclass
class Seg:
    kind: str                    # "clip" | "card"
    secs: float
    clip: Optional[Clip] = None
    offset: float = 0.0
    title: str = ""
    sub: str = ""
    lower: str = ""              # 片段开头显示的景点名
    stop: str = ""
    day: int = 0
    points: list = field(default_factory=list)   # 路线卡：[(name, lat, lon)]


def plan(clips: list[Clip], order: list[dict], target_s: float = 0, clip_max: float = 8, clip_min: float = 1.5,
         cards: bool = True) -> list[Seg]:
    """order: 按行程顺序 [{id, name, day(0起), date, lat, lon}]。target_s=0 表示不限，每段取 clip_max 秒以内。
    总长超过目标时先按比例缩短每段（不短于 clip_min），还超就每个景点轻轻删几段。"""
    by_stop: dict[str, list[Clip]] = {}
    for c in clips:
        if c.stop:
            by_stop.setdefault(c.stop, []).append(c)
    chosen: list[tuple[dict, Clip, float]] = []
    for s in order:
        for c in sorted(by_stop.get(s["id"], []), key=lambda c: (c.start or datetime.max, c.file)):
            chosen.append((s, c, min(float(clip_max), c.dur)))
    if not chosen:
        raise VideoError("没有视频归到行程里的景点，粗剪不出东西。可以先检查拍摄时间/位置，或者确认行程日期。")
    days = sorted({s["day"] for s, _, _ in chosen})
    overhead = (len(days) * 2 * CARD_SECS) if cards else 0
    if target_s and target_s > overhead:
        budget = target_s - overhead
        total = sum(L for _, _, L in chosen)
        if total > budget:
            f = budget / total
            chosen = [(s, c, max(min(clip_min, c.dur), L * f)) for s, c, L in chosen]
            while sum(L for _, _, L in chosen) > budget and len(chosen) > len(order):
                cnt: dict[str, int] = {}
                for s, _, _ in chosen:
                    cnt[s["id"]] = cnt.get(s["id"], 0) + 1
                top = max(cnt, key=lambda k: cnt[k])
                if cnt[top] <= 1:
                    break
                idx = [i for i, (s, _, _) in enumerate(chosen) if s["id"] == top]
                del chosen[idx[len(idx) // 2]]
    segs: list[Seg] = []
    cur_day = None
    for s, c, L in chosen:
        if cards and s["day"] != cur_day:
            cur_day = s["day"]
            pts = [(o["name"], o["lat"], o["lon"]) for o in order if o["day"] == cur_day and any(x[0]["id"] == o["id"] for x in chosen)]
            segs.append(Seg("card", CARD_SECS, title=f"第{cur_day + 1}天", sub=s.get("date") or "", day=cur_day))
            if len(pts) >= 2:
                segs.append(Seg("card", CARD_SECS, title=f"第{cur_day + 1}天的路线", day=cur_day, points=pts))
        off = max(0.0, (c.dur - L) / 2)
        segs.append(Seg("clip", L, clip=c, offset=off, lower=s["name"], stop=s["id"], day=s["day"]))
    return segs


# ---------- 字体与卡片 ----------

_FONTS = ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc", "/Library/Fonts/Arial Unicode.ttf",
          "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
          "C:/Windows/Fonts/msyh.ttc"]


def _font(size: int):
    from PIL import ImageFont
    for f in _FONTS:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _canvas(clips: list[Clip]) -> tuple[int, int]:
    portrait = sum(1 for c in clips if c.h > c.w)
    big, small = (1920, 1080) if all(max(c.w, c.h) >= 1500 for c in clips if c.w) else (1280, 720)
    return (small, big) if portrait * 2 > len(clips) else (big, small)


def card_png(seg: Seg, size: tuple[int, int], path: Path) -> None:
    from PIL import Image, ImageDraw
    W, H = size
    im = Image.new("RGB", size, (24, 28, 34))
    d = ImageDraw.Draw(im)
    if seg.points:
        d.text((W // 2, int(H * 0.09)), seg.title, font=_font(int(H * 0.05)), fill=(240, 236, 226), anchor="mm")
        lats = [p[1] for p in seg.points]; lons = [p[2] for p in seg.points]
        mx, my = W * 0.14, H * 0.2
        sx = (W - 2 * mx) / (max(lons) - min(lons) or 1e-6)
        sy = (H - my - H * 0.12) / (max(lats) - min(lats) or 1e-6)
        k = min(sx, sy * 1.0)                                    # 经纬度近似等比例
        pts = [(mx + (lo - min(lons)) * k, my + (max(lats) - la) * k) for _, la, lo in seg.points]
        d.line(pts, fill=(236, 180, 90), width=max(4, W // 300), joint="curve")
        for i, ((name, _, _), (x, y)) in enumerate(zip(seg.points, pts)):
            r = max(10, W // 120)
            d.ellipse((x - r, y - r, x + r, y + r), fill=(236, 180, 90), outline=(24, 28, 34), width=3)
            # 文字放在点的右侧（放不下就放左侧），再夹在画布内，名字再长也不会被边缘截断
            f = _font(int(H * 0.03)); label = f"{i + 1} {name}"
            w = d.textlength(label, font=f); gap = r + 10; margin = W * 0.04
            tx = x + gap if x + gap + w <= W - margin else x - gap - w
            ty = y
            if tx < margin or tx + w > W - margin:                   # 两侧都放不下：夹进画布，并挪到点的上方，不压住线和点
                tx = max(margin, min(tx, W - margin - w)); ty = y - r - int(H * 0.025)
            d.text((tx, ty), label, font=f, fill=(240, 236, 226), anchor="lm")
    else:
        d.text((W // 2, H // 2 - int(H * 0.03)), seg.title, font=_font(int(H * 0.09)), fill=(240, 236, 226), anchor="mm")
        if seg.sub:
            d.text((W // 2, H // 2 + int(H * 0.06)), seg.sub, font=_font(int(H * 0.04)), fill=(170, 166, 156), anchor="mm")
    im.save(path, "PNG")


def lower_png(text: str, size: tuple[int, int], path: Path) -> None:
    from PIL import Image, ImageDraw
    W, H = size
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = _font(int(H * 0.042))
    box = d.textbbox((0, 0), text, font=f)
    tw, th = box[2] - box[0], box[3] - box[1]
    pad = int(H * 0.018)
    x0, y1 = int(W * 0.05), int(H * 0.9)
    d.rounded_rectangle((x0, y1 - th - 2 * pad, x0 + tw + 2 * pad, y1), radius=pad, fill=(0, 0, 0, 130))
    d.text((x0 + pad - box[0], y1 - th - pad - box[1]), text, font=f, fill=(255, 255, 255, 255))
    im.save(path, "PNG")


# ---------- 渲染 ----------

def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        lines = (r.stderr or "").strip().splitlines()
        raise VideoError("ffmpeg 出错：" + (lines[-1][:300] if lines else "未知错误"))


def render(segs: list[Seg], out: Path, work: Path, size: tuple[int, int]) -> None:
    need_ffmpeg()
    work.mkdir(parents=True, exist_ok=True)
    W, H = size
    parts: list[Path] = []
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", "30",
           "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"]
    vf = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30"
    for i, sg in enumerate(segs):
        part = work / f"seg{i:03d}.mp4"
        if sg.kind == "card":
            png = work / f"card{i:03d}.png"
            card_png(sg, size, png)
            _run(["ffmpeg", "-y", "-loop", "1", "-t", f"{sg.secs:.2f}", "-i", str(png), "-f", "lavfi", "-i",
                  "anullsrc=r=44100:cl=stereo", "-t", f"{sg.secs:.2f}", *enc, "-shortest", str(part)])
        else:
            c = sg.clip
            ov = work / f"low{i:03d}.png"
            lower_png(sg.lower, size, ov)
            cmd = ["ffmpeg", "-y", "-ss", f"{sg.offset:.2f}", "-t", f"{sg.secs:.2f}", "-i", c.path,
                   "-loop", "1", "-t", f"{sg.secs:.2f}", "-i", str(ov)]
            if not c.audio:
                cmd += ["-f", "lavfi", "-t", f"{sg.secs:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
            fc = f"[0:v]{vf}[b];[b][1:v]overlay=0:0:enable='lt(t,{LOWER_SECS})'[v]"
            cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "0:a:0" if c.audio else "2:a", *enc,
                    "-t", f"{sg.secs:.2f}", str(part)]
            _run(cmd)
        parts.append(part)
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)])


def srt(segs: list[Seg]) -> str:
    """每个景点开头一条字幕（景点名），可以导进剪映或播放器。"""
    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    out, t, n, last = [], 0.0, 0, None
    for sg in segs:
        if sg.kind == "clip" and sg.stop != last:
            n += 1
            out.append(f"{n}\n{ts(t)} --> {ts(t + min(LOWER_SECS, sg.secs))}\n{sg.lower}\n")
            last = sg.stop
        t += sg.secs
    return "\n".join(out)


def jianying_draft(segs: list[Seg], size: tuple[int, int], drafts_dir: Path, name: str, work: Path) -> str:
    """用 pyJianYingDraft 在剪映草稿文件夹里生成草稿（视频轨：卡片图 + 视频段；文字轨：景点名）。
    只写草稿，不导出成片；剪映版本差异大，打不开时用粗剪成片 + 字幕文件就行。"""
    try:
        import pyJianYingDraft as jy                                   # type: ignore
        from pyJianYingDraft import trange
    except ImportError:
        raise VideoError("没有装 pyJianYingDraft（pip install pyJianYingDraft）。")
    W, H = size
    work.mkdir(parents=True, exist_ok=True)
    try:
        folder = jy.DraftFolder(str(drafts_dir))
        script = folder.create_draft(name, W, H, allow_replace=True)
        if hasattr(script, "add_track"):                                # 旧版接口
            script.add_track(jy.TrackType.video).add_track(jy.TrackType.text)
        else:                                                           # 新版接口：先建轨道，后面按类型自动放
            for tt in (jy.TrackType.video, jy.TrackType.text):
                script.append_track(jy.TrackSpec(tt))
        t = 0.0
        for i, sg in enumerate(segs):
            if sg.kind == "card":
                png = work / f"jycard{i:03d}.png"
                card_png(sg, size, png)
                script.add_segment(jy.VideoSegment(str(png), trange(f"{t:.3f}s", f"{sg.secs:.3f}s")))
            else:
                script.add_segment(jy.VideoSegment(sg.clip.path, trange(f"{t:.3f}s", f"{sg.secs:.3f}s"),
                                                   source_timerange=trange(f"{sg.offset:.3f}s", f"{sg.secs:.3f}s")))
                script.add_segment(jy.TextSegment(sg.lower, trange(f"{t:.3f}s", f"{min(LOWER_SECS, sg.secs):.3f}s"),
                                                  style=jy.TextStyle(size=6.0, color=(1.0, 1.0, 1.0)),
                                                  clip_settings=jy.ClipSettings(transform_y=-0.8)))
            t += sg.secs
        script.save()
    except Exception as e:                                             # 库版本/剪映版本不匹配
        raise VideoError(f"生成剪映草稿失败：{e}")
    return str(drafts_dir / name)
