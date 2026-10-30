"""把行程导出成本地文件：Obsidian 笔记文件夹（Markdown + 双链 + 附件）和日历 .ics。

只写文件，不连任何账号、不联网、不需要密钥。内容全部来自行程本身（景点、计划时间、营业时间、天气预报、用户照片）；
别人游记里的景点介绍（Place.intro）不是用户的经历，不导出。照片默认去掉 EXIF（位置/拍摄时间），用户可选保留。
导出目录已存在时不覆盖，新建 "-2"、"-3"… 子目录。
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .gpx import build_gpx
from .metrics import day_stats
from .models import Trip
from .timeline import day_visits

_BAD = re.compile(r'[\[\]#^|\\/:*?"<>\x00-\x1f]')
WEEK = "一二三四五六日"


def _safe(name: str, fallback: str = "未命名") -> str:
    s = _BAD.sub(" ", name or "").strip(" .")
    return re.sub(r"\s+", " ", s) or fallback


def _hm(m: int) -> str:
    m = int(m)
    return f"{m // 60 % 24:02d}:{m % 60:02d}"


def _y(v: Any) -> str:           # YAML 标量：JSON 字符串/数字都是合法 YAML
    return json.dumps(v, ensure_ascii=False)


def _fold(line: str) -> str:     # RFC 5545：每行不超过 75 字节，续行以空格开头
    out, cur, n = [], "", 0
    for ch in line:
        b = len(ch.encode())
        if n + b > 73:
            out.append(cur); cur, n = " " + ch, 1 + b
        else:
            cur += ch; n += b
    out.append(cur)
    return "\r\n".join(out)


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def build_ics(trip: Trip) -> str:
    """每个景点一个事件（浮动本地时间，不带时区，导入后按用户日历时区显示）。日期没定时无法导出。"""
    if trip.plan is None or trip.day_date(0) is None:
        raise ValueError("行程还没有确定日期，无法导出日历（先设定出发日期）")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TripSight//tripcore//ZH", "CALSCALE:GREGORIAN",
         f"X-WR-CALNAME:{_esc(trip.meta.name)}"]
    for day in trip.plan.days:
        d = trip.day_date(day.index)
        if d is None:
            continue
        visits, _ = day_visits(trip, day)
        for k, v in enumerate(visits):
            p = v.place
            s = datetime(d.year, d.month, d.day) + timedelta(minutes=v.arrive)
            e = datetime(d.year, d.month, d.day) + timedelta(minutes=v.leave)
            desc = [f"建议停留 {p.duration_min} 分钟（非预约）"]
            if p.opening_hours:
                desc.append(f"营业时间：{p.opening_hours}（来源：{p.hours_source or '未标注'}，以现场为准）")
            else:
                desc.append("营业时间：未核实")
            L += ["BEGIN:VEVENT", f"UID:{p.id}-d{day.index}-{k}@tripsight", f"DTSTAMP:{stamp}",
                  f"DTSTART:{s:%Y%m%dT%H%M%S}", f"DTEND:{e:%Y%m%dT%H%M%S}",
                  _fold("SUMMARY:" + _esc(p.name)), _fold("LOCATION:" + _esc(p.name)),
                  _fold("DESCRIPTION:" + _esc("\n".join(desc))), "END:VEVENT"]
    L.append("END:VCALENDAR")
    return "\r\n".join(L) + "\r\n"


def _copy_photo(src: Path, dst: Path, keep_exif: bool) -> None:
    if keep_exif:
        shutil.copy2(src, dst); return
    try:
        from PIL import Image, ImageOps
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)            # 先按方向转正，再丢掉全部元数据
            im.convert("RGB").save(dst, "JPEG", quality=92)
    except Exception:
        raise ValueError(f"照片无法处理：{src.name}")


def build_obsidian(trip: Trip, out_root: Path, *, photos: Optional[list[dict]] = None, photo_dir: Optional[Path] = None,
                   videos: Optional[dict[int, Path]] = None, include_photos: bool = True, include_videos: bool = False,
                   keep_exif: bool = False, with_gpx: bool = True, city: str = "") -> dict[str, Any]:
    """返回 {"folder": 路径, "files": [...], "skipped": [...]}。videos = {天序号(0 起): 视频文件}。"""
    if trip.plan is None or not trip.plan.days:
        raise ValueError("行程还没有排好，无法导出")
    base = _safe(trip.meta.name, "TripSight 行程")
    root = out_root / base
    n = 2
    while root.exists():
        root = out_root / f"{base}-{n}"; n += 1
    att = root / "attachments"
    (root / "景点").mkdir(parents=True)
    att.mkdir()
    files: list[str] = []
    skipped: list[str] = []

    def w(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8"); files.append(str(path.relative_to(root)))

    by_place: dict[str, list[dict]] = {}
    by_day: dict[int, list[dict]] = {}
    if include_photos and photos and photo_dir:
        for ph in photos:
            if ph.get("hide"):
                continue
            from . import photos as _phm
            src = _phm.resolve(Path(photo_dir), ph["file"])
            if src is None:
                skipped.append(f"照片缺失（原文件被移动或删除了？）：{ph['file']}"); continue
            dst_dir = att / "photos"; dst_dir.mkdir(exist_ok=True)
            dst = dst_dir / f"{ph['id']}.jpg"
            try:
                _copy_photo(src, dst, keep_exif)
            except ValueError as e:
                skipped.append(str(e)); continue
            files.append(str(dst.relative_to(root)))
            item = {"name": f"attachments/photos/{dst.name}", "caption": ph.get("caption", "")}
            if ph.get("place_id"):
                by_place.setdefault(ph["place_id"], []).append(item)
            elif ph.get("day") is not None:
                by_day.setdefault(int(ph["day"]), []).append(item)

    place_days: dict[str, list[int]] = {}
    day_links: list[str] = []
    total_km = 0.0
    for day in trip.plan.days:
        st = day_stats(trip, day)
        visits, _end = day_visits(trip, day)
        d = trip.day_date(day.index)
        title = f"第{day.index + 1}天"
        km = round(sum(l.distance_km for l in st.legs), 2); total_km += km
        wx = (trip.weather or {}).get(d.isoformat()) if d else None
        fm = ["---", f"title: {_y(title)}", f"trip: {_y(trip.meta.name)}"]
        if d:
            fm.append(f"date: {d.isoformat()}")
        if city:
            fm.append(f"city: {_y(city)}")
        fm += ["stops:"] + [f"  - {_y('[[' + _safe(v.place.name) + ']]')}" for v in visits]
        fm += [f"distance_km: {km}", "tags: [tripsight]", "---", ""]
        body = [f"# {title}" + (f" · {d.month}月{d.day}日 周{WEEK[d.weekday()]}" if d else ""), ""]
        if wx is not None and getattr(wx, "day_weather", ""):
            body += [f"天气预报：{wx.day_weather} {round(wx.day_temp)}°C（预报，非实况）", ""]
        if visits:
            body.append("路线：" + " → ".join(f"[[{_safe(v.place.name)}]]" for v in visits)); body.append("")
        for i, v in enumerate(visits):
            p = v.place
            place_days.setdefault(p.id, []).append(day.index)
            body += [f"## {i + 1}. [[{_safe(p.name)}]]  {_hm(v.arrive)}–{_hm(v.leave)}",
                     f"- 建议停留 {p.duration_min} 分钟",
                     ]
            if p.opening_hours:
                body.append(f"- 营业：{p.opening_hours}（{p.hours_source or '来源未标注'}）")
            for it in by_place.get(p.id, []):
                body.append(f"![{it['caption']}]({it['name']})" + (f"\n*{it['caption']}*" if it["caption"] else ""))
            if i < len(st.legs):
                lg = st.legs[i]
                body += ["", f"> 前往下一站：{lg.note or lg.mode} · {lg.distance_km} km · {lg.minutes} 分钟"
                             + ("" if lg.detail_level != "estimate" else "（估算）")]
            body.append("")
        for it in by_day.get(day.index, []):
            body.append(f"![{it['caption']}]({it['name']})" + (f"\n*{it['caption']}*" if it["caption"] else ""))
        if with_gpx:
            try:
                (att / f"day{day.index + 1}.gpx").write_text(build_gpx(trip, day.index), encoding="utf-8")
                files.append(f"attachments/day{day.index + 1}.gpx"); body.append(f"轨迹文件：[第{day.index + 1}天.gpx](attachments/day{day.index + 1}.gpx)")
            except Exception as e:
                skipped.append(f"第{day.index + 1}天 GPX：{e}")
        vid = (videos or {}).get(day.index)
        if include_videos and vid:
            vp = Path(vid)
            if vp.exists():
                (att / "video").mkdir(exist_ok=True)
                dst = att / "video" / f"vlog-day{day.index + 1}{vp.suffix}"
                shutil.copy2(vp, dst); files.append(str(dst.relative_to(root)))
                body += ["", f"![](attachments/video/{dst.name})"]
            else:
                skipped.append(f"视频缺失：{vp}")
        w(root / f"{title}.md", "\n".join(fm + body) + "\n")
        day_links.append(f"- [[{title}]]：" + "、".join(f"[[{_safe(v.place.name)}]]" for v in visits))

    for p in trip.places:
        if p.id not in place_days:
            continue
        fm = ["---", f"title: {_y(p.name)}", "type: place", f"lat: {p.lat}", f"lon: {p.lon}",
              "days: [" + ", ".join(str(i + 1) for i in place_days[p.id]) + "]", "tags: [tripsight, place]", "---", ""]
        body = [f"# {p.name}", "", f"- 建议停留 {p.duration_min} 分钟"]
        if p.opening_hours:
            body.append(f"- 营业：{p.opening_hours}（{p.hours_source or '来源未标注'}）")
        body += ["", "出现在：" + "、".join(f"[[第{i + 1}天]]" for i in place_days[p.id]), "", "## 我的笔记", ""]
        w(root / "景点" / f"{_safe(p.name)}.md", "\n".join(fm + body) + "\n")

    n_days = len(trip.plan.days)
    head = ["---", f"title: {_y(trip.meta.name)}", "type: trip", f"days: {n_days}", f"distance_km: {round(total_km, 2)}",
            "tags: [tripsight]", "---", "", f"# {trip.meta.name}", "", *day_links, "",
            "> 由 TripSight 导出。", ""]
    w(root / f"{_safe(trip.meta.name)}.md", "\n".join(head))
    try:
        (root / f"{base}.ics").write_text(build_ics(trip), encoding="utf-8", newline="")
        files.append(f"{base}.ics")
    except ValueError as e:
        skipped.append(f"日历：{e}")
    return {"folder": str(root), "files": files, "skipped": skipped}
