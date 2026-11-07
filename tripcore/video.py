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
CARD_SECS = 2.4                    # 每天标题卡
ROUTE_SECS = 3.4                   # 每天路线卡（画线动画）
INTRO_SECS = 3.0                   # 片头
OUTRO_SECS = 2.4                   # 片尾
LOWER_SECS = 2.8


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
    skip: bool = False                      # 用户标了“不用”：不放进短片
    t0: Optional[float] = None              # 用户设的起止（秒）；两个都有才算裁剪
    t1: Optional[float] = None
    note: str = ""                          # 用户给这一段写的字幕（放在景点名后面）


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
    pos = next((q for q in (_iso6709(tags.get(k, "")) for k in ("com.apple.quicktime.location.iso6709", "location", "location-eng")) if q), None)
    return Clip(path.name, str(path), dur, _when(tags), pos[0] if pos else None, pos[1] if pos else None, w, h,
                any(s.get("codec_type") == "audio" for s in streams))


def poster(path: Path, out: Path, at: float = 1.0) -> bool:
    """截视频的一帧存成 JPEG（给只有视频的停留点当缩略图）；失败返回 False。"""
    try:
        for t in (at, 0.0):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t}", "-i", str(path), "-frames:v", "1", "-vf", "scale=1280:-2", str(out)],
                           capture_output=True, timeout=60)
            if out.is_file() and out.stat().st_size > 0:
                return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False


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
    variant: str = ""            # 卡片种类："intro" | "day" | "route" | "outro"
    extra: dict = field(default_factory=dict)    # 卡片附加内容：day_title / stops / stats


def _trim(c: Clip) -> Optional[tuple[float, float]]:
    """用户设的裁剪区间（秒），夹在视频长度内；没设或无效返回 None。"""
    if c.t0 is None or c.t1 is None:
        return None
    a, b = max(0.0, float(c.t0)), min(float(c.dur), float(c.t1))
    return (a, b) if b - a >= 0.5 else None


def plan(clips: list[Clip], order: list[dict], target_s: float = 0, clip_max: float = 8, clip_min: float = 1.5,
         cards: bool = True, meta: Optional[dict] = None, day_titles: Optional[dict] = None, orders: Optional[dict] = None) -> list[Seg]:
    """order: 按行程顺序 [{id, name, day(0起), date, lat, lon}]。target_s=0 表示不限，每段取 clip_max 秒以内。
    总长超过目标时先按比例缩短每段（不短于 clip_min），还超就每个景点轻轻删几段。
    meta 给了（{"name", "range", "stats"}）就加片头和片尾；day_titles = {"1": "天涯海角", ...}（第几天从 1 起）用在每天的标题卡上。
    相邻两段会交叉淡化 XFADE 秒，所以实际成片比各段相加短一点。"""
    day_titles = day_titles or {}
    by_stop: dict[str, list[Clip]] = {}
    for c in clips:
        if c.stop:
            by_stop.setdefault(c.stop, []).append(c)
    orders = orders or {}
    chosen: list[tuple[dict, Clip, float]] = []
    for s in order:
        pos = {f: i for i, f in enumerate(orders.get(s["id"], []))}          # 用户排过顺序的先按他排的，其余按拍摄时间接在后面
        for c in sorted((x for x in by_stop.get(s["id"], []) if not x.skip), key=lambda c: (pos.get(c.file, len(pos)), c.start or datetime.max, c.file)):
            tr = _trim(c)
            chosen.append((s, c, (tr[1] - tr[0]) if tr else min(float(clip_max), c.dur)))
    if not chosen:
        raise VideoError("没有视频归到行程里的景点，粗剪不出东西。可以先检查拍摄时间/位置，或者确认行程日期。")
    days = sorted({s["day"] for s, _, _ in chosen})
    overhead = (len(days) * (CARD_SECS + ROUTE_SECS)) if cards else 0
    if meta:
        overhead += INTRO_SECS + OUTRO_SECS
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
    if meta:
        segs.append(Seg("card", INTRO_SECS, title=meta.get("name", ""), sub=meta.get("range", ""), variant="intro",
                        extra={"stats": meta.get("stats", "")}))
    cur_day = None
    for s, c, L in chosen:
        if cards and s["day"] != cur_day:
            cur_day = s["day"]
            pts = [(o["name"], o["lat"], o["lon"]) for o in order if o["day"] == cur_day and any(x[0]["id"] == o["id"] for x in chosen)]
            segs.append(Seg("card", CARD_SECS, title=f"第{cur_day + 1}天", sub=(s.get("date") or "") + (f" · {len(pts)} 处" if pts else ""),
                            day=cur_day, variant="day", extra={"day_title": day_titles.get(str(cur_day + 1), ""), "stops": [p[0] for p in pts]}))
            if len(pts) >= 2:
                segs.append(Seg("card", ROUTE_SECS, title=f"第{cur_day + 1}天的路线", day=cur_day, points=pts, variant="route"))
        tr = _trim(c)
        off = tr[0] if tr else max(0.0, (c.dur - L) / 2)
        segs.append(Seg("clip", L, clip=c, offset=off, lower=(s["name"] + " · " + c.note) if c.note else s["name"], stop=s["id"], day=s["day"]))
    if meta:
        segs.append(Seg("card", OUTRO_SECS, title=meta.get("name", ""), sub=meta.get("range", ""), variant="outro"))
    return segs


# ---------- 版式与卡片 ----------

# 与手册的 5 种风格同色系（手账是工作台的暖米色），短片里的标题卡、路线卡、字幕条都用它
PALETTES = {
    "手账": {"bg": "#f5f0e6", "bg2": "#e9e0cd", "ink": "#2b2823", "sub": "#7a7468", "acc": "#c4553a"},
    "杂志": {"bg": "#ffffff", "bg2": "#eeeeee", "ink": "#111111", "sub": "#6b6b6b", "acc": "#d62828"},
    "清新": {"bg": "#eef6f1", "bg2": "#d9eae0", "ink": "#25403a", "sub": "#6b8a80", "acc": "#2e9c7f"},
    "胶片": {"bg": "#e9e0d0", "bg2": "#d9ccb4", "ink": "#3b2f25", "sub": "#8a7a68", "acc": "#a4531f"},
    "海边": {"bg": "#eaf3f9", "bg2": "#d3e5f2", "ink": "#1f3b52", "sub": "#6b8aa3", "acc": "#1f7fbf"},
}
_SS = 2                                                           # 卡片按 2 倍画布绘制再缩小，边缘更平滑


def _pal(style: str = "手账") -> dict:
    return PALETTES.get(style) or PALETTES["手账"]


def _rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


_FONTS = ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc", "/Library/Fonts/Arial Unicode.ttf",
          "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
          "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", "C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc"]


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


def _bg(size: tuple[int, int], pal: dict):
    from PIL import Image
    mask = Image.linear_gradient("L").resize(size)
    return Image.composite(Image.new("RGB", size, _rgb(pal["bg2"])), Image.new("RGB", size, _rgb(pal["bg"])), mask)


def _tracked(d, x: float, y: float, s: str, font, fill, track: float, center: bool = False) -> None:
    ws = [d.textlength(ch, font=font) for ch in s]
    x0 = x - (sum(ws) + track * (len(s) - 1)) / 2 if center else x
    for ch, w in zip(s, ws):
        d.text((x0, y), ch, font=font, fill=fill, anchor="ls")
        x0 += w + track


def _fit(d, s: str, size: int, maxw: float, floor: int = 24):
    f = _font(size)
    while size > floor and d.textlength(s, font=f) > maxw:
        size -= 2
        f = _font(size)
    return f


def _wrap(d, s: str, font, maxw: float) -> list[str]:
    lines, cur = [], ""
    for ch in s:
        if d.textlength(cur + ch, font=font) > maxw and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    return lines + ([cur] if cur else [])


def _stroke_text(d, xy, s, font, fill, anchor="ms", w=0):
    d.text(xy, s, font=font, fill=fill, anchor=anchor, stroke_width=w, stroke_fill=fill)


def _footer(d, W: int, H: int, pal: dict) -> None:
    d.text((W // 2, int(H * 0.955)), "TripSight · 旅行短片", font=_font(int(H * 0.017)), fill=_rgb(pal["sub"]), anchor="ms")


def _text_card(seg: "Seg", size: tuple[int, int], pal: dict):
    """片头 / 每天标题 / 片尾：渐变底 + 色块细线 + 大标题；每天卡片列出当天的景点。"""
    from PIL import ImageDraw
    W, H = size
    im = _bg(size, pal)
    d = ImageDraw.Draw(im)
    ink, sub, acc = _rgb(pal["ink"]), _rgb(pal["sub"]), _rgb(pal["acc"])
    if seg.variant == "day":
        _tracked(d, W / 2, H * 0.30, f"DAY {seg.day + 1:02d}", _font(int(H * 0.026)), acc, W * 0.012, center=True)
        d.rectangle((W / 2 - W * 0.05, H * 0.325, W / 2 + W * 0.05, H * 0.325 + max(3, H * 0.003)), fill=acc)
        head = seg.extra.get("day_title") or seg.title
        f = _fit(d, head, int(H * 0.075), W * 0.8)
        lines = _wrap(d, head, f, W * 0.8)
        y = H * 0.44
        for ln in lines[:3]:
            _stroke_text(d, (W / 2, y), ln, f, ink, "ms", max(1, int(H * 0.0012)))
            y += f.size * 1.25
        meta = " · ".join(x for x in ([seg.title] if seg.extra.get("day_title") else []) + [seg.sub] if x)
        d.text((W / 2, y + H * 0.01), meta, font=_font(int(H * 0.026)), fill=sub, anchor="ms")
        names = seg.extra.get("stops") or []
        y += H * 0.07
        for n in names[:5]:
            d.text((W / 2, y), "·  " + n[:18], font=_font(int(H * 0.024)), fill=ink, anchor="ms")
            y += H * 0.042
    else:                                                          # intro / outro
        top = seg.variant == "intro"
        _tracked(d, W / 2, H * 0.36, "TRAVEL FILM" if top else "THE END", _font(int(H * 0.024)), acc, W * 0.012, center=True)
        d.rectangle((W / 2 - W * 0.05, H * 0.385, W / 2 + W * 0.05, H * 0.385 + max(3, H * 0.003)), fill=acc)
        f = _fit(d, seg.title, int(H * 0.085), W * 0.8)
        y = H * 0.48
        for ln in _wrap(d, seg.title, f, W * 0.8)[:3]:
            _stroke_text(d, (W / 2, y), ln, f, ink, "ms", max(1, int(H * 0.0014)))
            y += f.size * 1.25
        for ln in [x for x in (seg.sub, seg.extra.get("stats")) if x]:
            d.text((W / 2, y + H * 0.012), ln, font=_font(int(H * 0.027)), fill=sub, anchor="ms")
            y += H * 0.045
    _footer(d, W, H, pal)
    return im


def _project(points: list, size: tuple[int, int]) -> list[tuple[float, float]]:
    """经纬度 → 画布坐标（按纬度修正经度比例，等比放进中间的矩形）。"""
    import math
    W, H = size
    lats = [p[1] for p in points]; lons = [p[2] for p in points]
    k = math.cos(math.radians(sum(lats) / len(lats)))
    xs = [(lo - min(lons)) * k for lo in lons]; ys = [max(lats) - la for la in lats]
    box = (W * 0.2, H * 0.24, W * 0.8, H * 0.82)
    sx = (box[2] - box[0]) / (max(xs) or 1e-9); sy = (box[3] - box[1]) / (max(ys) or 1e-9)
    s = min(sx, sy)
    ox = (box[0] + box[2]) / 2 - (max(xs) * s) / 2; oy = (box[1] + box[3]) / 2 - (max(ys) * s) / 2
    return [(ox + x * s, oy + y * s) for x, y in zip(xs, ys)]


def _route_card(seg: "Seg", size: tuple[int, int], pal: dict, progress: float = 1.0):
    """路线卡：路线按顺序一段段“画出来”，到达的点亮起并显示名字；progress 0~1。
    seg.extra["base_fn"] 给了就把线画在真实地图底图上（fn 返回底图和已投影好的路线）；没有就是简化的等比线条图。"""
    import math
    from PIL import Image, ImageDraw
    W, H = size
    im = _bg(size, pal)
    d = ImageDraw.Draw(im)
    ink, sub, acc = _rgb(pal["ink"]), _rgb(pal["sub"]), _rgb(pal["acc"])
    _tracked(d, W / 2, H * 0.115, "ROUTE", _font(int(H * 0.022)), acc, W * 0.012, center=True)
    d.text((W / 2, H * 0.165), seg.title, font=_font(int(H * 0.044)), fill=ink, anchor="ms", stroke_width=max(1, int(H * 0.001)), stroke_fill=ink)
    box = (int(W * 0.06), int(H * 0.215), int(W * 0.94), int(H * 0.86))
    base = None
    fn = seg.extra.get("base_fn")
    if fn:
        if "_base" not in seg.extra:
            try:
                seg.extra["_base"] = fn(seg.points, (box[2] - box[0], box[3] - box[1]))
            except Exception:
                seg.extra["_base"] = None
        base = seg.extra["_base"]
    if base:
        rad = int(H * 0.012)
        mask = Image.new("L", base["img"].size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, mask.width - 1, mask.height - 1), radius=rad, fill=255)
        im.paste(base["img"], box[:2], mask)
        d.rounded_rectangle(box, radius=rad, outline=_rgb(pal["bg2"]), width=max(2, int(H * 0.003)))
        pts = [(box[0] + x, box[1] + y) for x, y in base["stops"]]
        poly = [(box[0] + x, box[1] + y) for x, y in base["poly"]]
        sidx = base["sidx"]
        bounds = box
        if base.get("note"):
            d.text((W / 2, box[3] + H * 0.03), base["note"], font=_font(int(H * 0.016)), fill=sub, anchor="mm")
    else:
        pts = _project(seg.points, size)
        poly, sidx = pts, list(range(len(pts)))
        bounds = (W * 0.05, H * 0.2, W * 0.95, H * 0.92)
    seglen = [math.dist(poly[i], poly[i + 1]) for i in range(len(poly) - 1)]
    total = sum(seglen) or 1.0
    cum = [0.0]
    for L in seglen:
        cum.append(cum[-1] + L)
    reach = progress * total
    lw = max(4, int(H * 0.005))
    casing = _rgb(pal["bg"])
    drawn = []
    for i, L in enumerate(seglen):                                  # 已画出的线段（含正在画的那一段）
        if reach <= cum[i]:
            break
        t = min(1.0, (reach - cum[i]) / (L or 1))
        a, b = poly[i], poly[i + 1]
        drawn.append((a, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)))
    if base:                                                        # 底图上加一圈浅色描边，线更清楚
        for a, e in drawn:
            d.line([a, e], fill=casing, width=lw + max(4, int(H * 0.004)), joint="curve")
    for a, e in drawn:
        d.line([a, e], fill=acc, width=lw)
        d.ellipse((e[0] - lw / 2, e[1] - lw / 2, e[0] + lw / 2, e[1] + lw / 2), fill=acc)
    f = _font(int(H * 0.03))
    r = max(12, int(H * 0.012))
    placed: list[tuple] = []
    for i, ((name, _, _), (x, y)) in enumerate(zip(seg.points, pts)):
        if reach + 1e-6 < cum[sidx[i]]:
            continue
        d.ellipse((x - r * 1.5, y - r * 1.5, x + r * 1.5, y + r * 1.5), fill=casing, outline=acc, width=max(3, r // 4))
        d.text((x, y), str(i + 1), font=_font(int(r * 1.5)), fill=acc, anchor="mm")
        label = name if d.textlength(name, font=f) < W * 0.62 else name[:12] + "…"
        w = d.textlength(label, font=f); gap = r * 1.5 + 12; hh = f.size * 0.62
        # 候选位置：右、左、上、下（居中），选第一个不出画布、不压线、不压已有标签的；都不行就夹进画布放上方
        cands = [(x + gap, y), (x - gap - w, y), (x - w / 2, y - gap - hh), (x - w / 2, y + gap + hh)]
        pick = None
        for cx, cy in cands:
            rect = (cx, cy - hh, cx + w, cy + hh)
            if rect[0] < bounds[0] + 8 or rect[2] > bounds[2] - 8 or rect[1] < bounds[1] or rect[3] > bounds[3]:
                continue
            if any(not (rect[2] < q[0] or rect[0] > q[2] or rect[3] < q[1] or rect[1] > q[3]) for q in placed):
                continue
            hit = False
            for (ax, ay), (bx, by) in zip(poly, poly[1:]):
                n = max(1, int(math.dist((ax, ay), (bx, by)) / 6))
                for t in range(0, n + 1):
                    px, py = ax + (bx - ax) * t / n, ay + (by - ay) * t / n
                    if rect[0] - 6 <= px <= rect[2] + 6 and rect[1] - 6 <= py <= rect[3] + 6:
                        hit = True
                        break
                if hit:
                    break
            if not hit:
                pick = (cx, cy, rect)
                break
        if pick is None:
            cx = max(bounds[0] + 8, min(x - w / 2, bounds[2] - 8 - w)); cy = y - gap - hh
            pick = (cx, cy, (cx, cy - hh, cx + w, cy + hh))
        tx, ty, rect = pick
        placed.append(rect)
        if base:                                                    # 地图上文字加底色块，避免被街道和注记盖住
            pad = int(H * 0.007)
            d.rounded_rectangle((rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad), radius=pad, fill=casing)
        d.text((tx, ty), label, font=f, fill=ink, anchor="lm")
    _footer(d, W, H, pal)
    return im


def _downscale(im, size):
    from PIL import Image
    return im.resize(size, Image.LANCZOS)


def card_png(seg: "Seg", size: tuple[int, int], path: Path, pal: Optional[dict] = None, progress: float = 1.0) -> None:
    pal = pal or _pal()
    big = (size[0] * _SS, size[1] * _SS)
    im = _route_card(seg, big, pal, progress) if seg.points else _text_card(seg, big, pal)
    _downscale(im, size).save(path, "PNG")


def lower_png(text: str, size: tuple[int, int], path: Path, pal: Optional[dict] = None, tag: str = "") -> None:
    """片段开头的景点名字幕条：深色半透明圆角底 + 左侧色条，上面一行小的 DAY 标签。"""
    from PIL import Image, ImageDraw
    pal = pal or _pal()
    W, H = size[0] * _SS, size[1] * _SS
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = _font(int(H * 0.036)); ft = _font(int(H * 0.017))
    box = d.textbbox((0, 0), text, font=f)
    tw, th = box[2] - box[0], box[3] - box[1]
    padx, pady = int(H * 0.022), int(H * 0.016)
    tagh = int(H * 0.026) if tag else 0
    x0, y1 = int(W * 0.06), int(H * 0.9)
    y0 = y1 - th - 2 * pady - tagh
    rad = int(H * 0.012)
    d.rounded_rectangle((x0, y0, x0 + tw + 2 * padx + int(W * 0.012), y1), radius=rad, fill=(14, 14, 14, 150))
    d.rounded_rectangle((x0, y0, x0 + int(W * 0.012), y1), radius=rad, fill=_rgb(pal["acc"]) + (255,))
    tx = x0 + int(W * 0.012) + padx
    if tag:
        _tracked(d, tx, y0 + pady + int(H * 0.018), tag, ft, (255, 255, 255, 190), W * 0.004)
    d.text((tx - box[0], y1 - pady - th - box[1]), text, font=f, fill=(255, 255, 255, 255))
    _downscale(im, size).save(path, "PNG")


# ---------- 渲染 ----------

def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        lines = (r.stderr or "").strip().splitlines()
        raise VideoError("ffmpeg 出错：" + (lines[-1][:300] if lines else "未知错误"))


XFADE = 0.5                                                      # 相邻两段交叉淡化的时长（秒）


def timeline(segs: list["Seg"], overlap: float = 0.0) -> list[float]:
    """每一段在成片里的开始时间（相邻段有 overlap 秒重叠）。"""
    out, t = [], 0.0
    for sg in segs:
        out.append(t)
        t += sg.secs - overlap
    return out


def overlap_for(segs: list["Seg"]) -> float:
    return min(XFADE, min((s.secs for s in segs), default=XFADE) / 3) if len(segs) > 1 else 0.0


_ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2"]


def _render_part(i: int, sg: "Seg", size: tuple[int, int], work: Path, pal: dict, trip_hint: str = "") -> Path:
    W, H = size
    part = work / f"seg{i:03d}.mp4"
    silent = ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    if sg.kind == "card" and sg.points:                            # 路线卡：画线动画（先画 70% 的时长，最后停一停）
        fps = 24
        n = max(2, int(round(sg.secs * fps)))
        fdir = work / f"route{i:03d}"
        fdir.mkdir(exist_ok=True)
        big = (W * _SS, H * _SS)
        draw_n = int(n * 0.7)
        for k in range(n):
            p = min(1.0, (k + 1) / draw_n)
            p = 1 - (1 - p) ** 2                                   # 缓出
            _downscale(_route_card(sg, big, pal, p), size).save(fdir / f"f{k:04d}.png")
        _run(["ffmpeg", "-y", "-framerate", str(fps), "-i", str(fdir / "f%04d.png"), *silent, "-t", f"{sg.secs:.2f}",
              "-vf", "fps=30,format=yuv420p", *_ENC, "-shortest", str(part)])
    elif sg.kind == "card":
        png = work / f"card{i:03d}.png"
        card_png(sg, size, png, pal)
        _run(["ffmpeg", "-y", "-loop", "1", "-t", f"{sg.secs:.2f}", "-i", str(png), *silent, "-t", f"{sg.secs:.2f}", *_ENC, "-shortest", str(part)])
    else:
        c = sg.clip
        ov = work / f"low{i:03d}.png"
        lower_png(sg.lower, size, ov, pal, tag=f"DAY {sg.day + 1}")
        cmd = ["ffmpeg", "-y", "-ss", f"{sg.offset:.2f}", "-t", f"{sg.secs:.2f}", "-i", c.path,
               "-loop", "1", "-framerate", "30", "-t", f"{sg.secs:.2f}", "-i", str(ov)]
        if not c.audio:
            cmd += silent[:2] + ["-t", f"{sg.secs:.2f}"] + silent[2:]
        same_ar = c.w and c.h and abs(c.w / c.h - W / H) < 0.02
        fit = f"scale={W}:{H}:force_original_aspect_ratio=decrease"
        if same_ar:
            base = f"[0:v]{fit},setsar=1,fps=30[fg]"
            comp = "[fg]"
        else:                                                      # 比例不一样：用放大模糊的同一画面铺底，而不是黑边
            base = (f"[0:v]split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                    f"scale={W // 8}:{H // 8},boxblur=3:2,scale={W}:{H},eq=brightness=-0.08[bg];[b]{fit},setsar=1[fg0];"
                    f"[bg][fg0]overlay=(W-w)/2:(H-h)/2,fps=30[fg]")
            comp = "[fg]"
        t_out = max(0.8, min(LOWER_SECS, sg.secs - 0.5))
        fc = (f"{base};{comp}eq=contrast=1.03:saturation=1.08[g];"
              f"[1:v]format=rgba,fade=t=in:st=0.35:d=0.35:alpha=1,fade=t=out:st={t_out:.2f}:d=0.35:alpha=1[ov];[g][ov]overlay=0:0,format=yuv420p[v]")
        if c.audio:
            fc += ";[0:a:0]loudnorm=I=-18:TP=-2:LRA=11,aresample=44100,aformat=channel_layouts=stereo[a]"
            amap = "[a]"
        else:
            amap = "2:a"
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", amap, *_ENC, "-t", f"{sg.secs:.2f}", str(part)]
        _run(cmd)
    return part


def render(segs: list["Seg"], out: Path, work: Path, size: tuple[int, int], style: str = "手账", progress=None) -> None:
    need_ffmpeg()
    work.mkdir(parents=True, exist_ok=True)
    pal = _pal(style)
    parts: list[Path] = []
    n = len(segs)
    for i, sg in enumerate(segs):
        parts.append(_render_part(i, sg, size, work, pal))
        if progress:
            progress(i + 1, n + 1)
    T = overlap_for(segs)
    if len(parts) == 1 or T <= 0:
        lst = work / "list.txt"
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out)])
    else:
        vf, af, acc = [], [], 0.0
        prev_v, prev_a = "[0:v]", "[0:a]"
        for k in range(1, len(parts)):
            acc += segs[k - 1].secs - T
            v, a = f"[v{k}]", f"[a{k}]"
            vf.append(f"{prev_v}[{k}:v]xfade=transition=fade:duration={T:.3f}:offset={acc:.3f}{v}")
            af.append(f"{prev_a}[{k}:a]acrossfade=d={T:.3f}:c1=tri:c2=tri{a}")
            prev_v, prev_a = v, a
        script = work / "graph.txt"
        script.write_text(";\n".join(vf + af), encoding="utf-8")
        cmd = ["ffmpeg", "-y"]
        for p in parts:
            cmd += ["-i", str(p)]
        cmd += ["-filter_complex_script", str(script), "-map", prev_v, "-map", prev_a, "-c:v", "libx264", "-preset", "medium", "-crf", "22",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)]
        _run(cmd)
    if progress:
        progress(n + 1, n + 1)
    try:                                                          # 封面：第一张卡片
        first = next((i for i, s in enumerate(segs) if s.kind == "card" and not s.points), None)
        if first is not None:
            card_png(segs[first], size, out.with_name("封面.png"), pal)
    except OSError:
        pass


def srt(segs: list[Seg], overlap: float = 0.0) -> str:
    """每个景点开头一条字幕（景点名），可以导进剪映或播放器；overlap 是成片里相邻段交叉淡化的秒数。"""
    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    out, n, last = [], 0, None
    for sg, t in zip(segs, timeline(segs, overlap)):
        if sg.kind == "clip" and sg.stop != last:
            n += 1
            out.append(f"{n}\n{ts(t + 0.35)} --> {ts(t + min(LOWER_SECS, sg.secs))}\n{sg.lower}\n")
            last = sg.stop
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
        us = lambda sec: int(round(float(sec) * 1_000_000))              # 全部用整数微秒：用字符串秒数时起点和时长各自四舍五入，相邻段会差 1 毫秒而被判“重叠”
        T = jy.Timerange
        t = 0
        for i, sg in enumerate(segs):
            dur = us(sg.secs)
            if sg.kind == "card":
                png = work / f"jycard{i:03d}.png"
                card_png(sg, size, png)
                script.add_segment(jy.VideoSegment(str(png), T(t, dur)))
            else:
                script.add_segment(jy.VideoSegment(sg.clip.path, T(t, dur), source_timerange=T(us(sg.offset), dur)))
                script.add_segment(jy.TextSegment(sg.lower, T(t, min(us(LOWER_SECS), dur)),
                                                  style=jy.TextStyle(size=6.0, color=(1.0, 1.0, 1.0)),
                                                  clip_settings=jy.ClipSettings(transform_y=-0.8)))
            t += dur
        script.save()
    except Exception as e:                                             # 库版本/剪映版本不匹配
        raise VideoError(f"生成剪映草稿失败：{e}")
    return str(drafts_dir / name)


def check_jianying_draft(draft_dir: Path) -> tuple[list[str], str]:
    """自检刚生成的剪映草稿（不需要剪映）：能不能读、轨道里的片段有没有重叠、素材文件在不在、
    取的片段有没有超出原视频长度、总时长对不对。返回 (问题列表, 一句话概况)。问题列表为空才算通过；
    这只能证明“草稿文件结构正常”，能不能在你的剪映版本里打开，还是要在剪映里点开看一眼。"""
    f = Path(draft_dir) / "draft_content.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"读不了 draft_content.json（{type(e).__name__}）：可能是剪映版本把草稿加密了，或没生成成功"], ""
    problems: list[str] = []
    mats = {m.get("id"): m for m in (d.get("materials") or {}).get("videos", [])}
    end_all = 0
    n_video = n_text = 0
    for tr in d.get("tracks") or []:
        segs = sorted(tr.get("segments") or [], key=lambda x: x["target_timerange"]["start"])
        prev_end = 0
        for sg in segs:
            tt = sg["target_timerange"]
            a, b = int(tt["start"]), int(tt["start"]) + int(tt["duration"])
            if tr.get("type") == "video":
                n_video += 1
                if a < prev_end:
                    problems.append(f"视频轨有重叠：{prev_end / 1e6:.2f}s 处")
                prev_end = max(prev_end, b)
                m = mats.get(sg.get("material_id")) or {}
                path = m.get("path") or ""
                if path and not Path(path).exists():
                    problems.append(f"素材不存在：{path}")
                src = sg.get("source_timerange") or {}
                if src and m.get("duration") and int(src.get("start", 0)) + int(src.get("duration", 0)) > int(m["duration"]) + 1000 and m.get("type") == "video":
                    problems.append(f"取的片段超出原视频长度：{Path(path).name}")
            elif tr.get("type") == "text":
                n_text += 1
            end_all = max(end_all, b)
    if not n_video:
        problems.append("草稿里没有视频轨")
    if abs(int(d.get("duration") or 0) - end_all) > 1000:
        problems.append(f"总时长对不上（草稿写 {int(d.get('duration') or 0) / 1e6:.1f}s，片段合计 {end_all / 1e6:.1f}s）")
    return problems, f"{n_video} 段画面（含卡片）、{n_text} 条字幕、总长约 {end_all / 1e6:.0f} 秒"
