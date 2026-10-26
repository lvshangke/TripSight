"""本机网页工作台：拖拽调整每天的景点、月历选日期，所有修改走现有的“提案 → 套用 → 撤销”。

安全：只监听 127.0.0.1；网址里带一次性随机令牌，没有令牌一律 404；检查 Host 和 Origin，防止别的网站偷偷调用；
修改请求必须带页面加载时的版本号，版本变了（agent 或别处改过）就拒绝，不会覆盖别人的修改。
网页不直接写文件：每次修改都是 commit（可 undo），并且和 agent 共用同一份行程文件。
"""

from __future__ import annotations

import hashlib
import re
import http.client
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from pydantic import TypeAdapter, ValidationError

from . import links as _links
from .mealgaps import meal_gaps
from . import daycard as _daycard
from . import photos as _ph
from . import share as _share
from . import tools_catalog as _tc
from . import mcp_server as ms
from . import workspace as ws
from .dates import apply_dates
from .mapview import build_map_data
from .models import Trip
from .proposals import (InvalidOperationError, LockedItemError, Op, StaleProposalError, apply_proposal,
                        describe_ops, make_proposal)
from .proposals import Proposal
from .state import NothingToUndo, undo as state_undo
from .validator import validate
from .webpage import page_html

_OPS = TypeAdapter(list[Op])
MAX_BODY = 100_000
MAX_BODY_BY_ROUTE = {"photo_add": 30_000_000}        # 照片上传（base64）
IDLE_SECONDS = 2 * 3600
_lock = threading.Lock()


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _issue_keys(trip: Trip) -> dict[tuple, str]:
    return {(i.code, i.day_index, i.place_id): f"{'第%d天：' % (i.day_index + 1) if i.day_index is not None else ''}{i.message}"
            for i in validate(trip) if i.severity in ("error", "warning")}


def _check_rev(body: dict, trip: Trip) -> None:
    if body.get("base_revision") != trip.revision:
        raise HttpError(409, "行程已经被别处修改过（版本变了），页面已刷新，请重新操作。")


def _rows(trip: Trip, timeline: list[dict], locked: dict[str, bool]) -> list[dict]:
    """把某一天的时间线整理成左栏的行：酒店、景点（可拖）、通勤、用餐点、航班/车次、提示。"""
    rows: list[dict] = []
    for e in timeline:
        t = e["type"]
        if t == "stop":
            rows.append({"t": "stop", "place_id": e["pid"], "n": e["n"], "name": e["name"], "locked": locked.get(e["pid"], False),
                         "time": f"{e['arrive']}–{e['leave']}", "lines": e.get("lines", [])})
        elif t == "leg":
            rows.append({"t": "leg", "minutes": e["minutes"], "mode": e["mode"], "km": e["km"], "real": e["real"],
                         "note": e.get("note", ""), "link": e.get("link", "")})
        elif t == "meal":
            rows.append({"t": "meal", "name": e["name"], "lines": e.get("lines", []), "link": e.get("web", "")})
        elif t == "hotel":
            rows.append({"t": "hotel", "role": e["role"], "time": e["time"], "name": e["name"]})
        elif t == "term":
            rows.append({"t": "info", "text": f"{e['icon']} {e['role']} {e['time']} {e['name']}：" + "；".join(e.get("lines", []))})
        elif t == "conn":
            rows.append({"t": "info", "text": e["text"]})
    return rows


_PREFIX = re.compile(r"^第\d+天(?:（[^）]*）)?")


def _issues_block(trip: Trip) -> dict[str, Any]:
    """页面显示用：每个景点、每天各自的错误/警告（info 不显示）。景点上的提示去掉“第N天（日期）”前缀，因为就显示在它下面。"""
    days: dict[str, list] = {}
    places: dict[str, list] = {}
    for i in validate(trip):
        if i.severity not in ("error", "warning") or i.day_index is None:
            continue
        if i.place_id:
            text = _PREFIX.sub("", i.message).lstrip("，, ")
            try:
                own = f"「{trip.place(i.place_id).name}」"
            except KeyError:
                own = ""
            if own and text.startswith(own):
                text = text[len(own):]
            places.setdefault(i.place_id, []).append({"sev": i.severity, "text": text})
        else:
            days.setdefault(str(i.day_index), []).append({"sev": i.severity, "text": i.message})
    return {"days": days, "places": places}


def snapshot() -> dict[str, Any]:
    trip = ms._load()
    mp = build_map_data(trip)
    by_day = {d["index"]: d for d in mp["days"]}
    days, placed = [], set()
    if trip.plan:
        for day in trip.plan.days:
            md = by_day.get(day.index, {"timeline": [], "color": "#4363d8"})
            locked = {it.place_id: it.locked for it in day.items}
            rows = _rows(trip, md["timeline"], locked)
            times = {r["place_id"]: r["time"] for r in rows if r["t"] == "stop"}
            dt = trip.day_date(day.index)
            items = []
            for it in day.items:
                placed.add(it.place_id)
                items.append({"place_id": it.place_id, "name": trip.place(it.place_id).name, "locked": it.locked,
                              "time": times.get(it.place_id, ""), "duration_min": trip.place(it.place_id).duration_min})
            days.append({"index": day.index, "label": f"第{day.index + 1}天" + (f" {dt.isoformat()}" if dt else ""),
                         "color": md["color"], "items": items, "rows": rows})
    reasons = {u.place_id: u.reason for u in (trip.plan.unscheduled if trip.plan else [])}
    unscheduled = [{"place_id": p.id, "name": p.name, "reason": reasons.get(p.id, ""), "duration_min": p.duration_min}
                   for p in trip.places if p.id not in placed and p.status.value in ("shortlist", "planned", "confirmed")]
    names = {p.id: p.name for p in trip.places}
    orphan_meals = [{"id": m.id, "name": m.name, "after": names.get(m.after_place_id, m.after_place_id)}
                    for m in trip.meals if m.after_place_id not in placed]
    m = trip.meta
    return {"title": m.name, "trip": _slug(), "issues": _issues_block(trip), "meal_gaps": {str(k): v for k, v in meal_gaps(trip).items()}, "link_sites": _links.templates(), **_daycard.build(trip, {d["index"]: d["timeline"] for d in mp["days"]}), "intros": {p.id: {"text": p.intro, "source": p.intro_source, "day": p.source_day} for p in trip.places if p.intro}, "city": (ms._load_context() or {}).get("city", ""), "revision": trip.revision, "can_undo": bool(trip.history), "days": days, "unscheduled": unscheduled,
            "orphan_meals": orphan_meals,
            "dates": {"start": m.start_date.isoformat() if m.start_date else None, "end": m.end_date.isoformat() if m.end_date else None,
                      "mode": m.date_mode.value, "num_days": m.num_days},
            "map": mp}


def preview(body: dict) -> dict[str, Any]:
    trip = ms._load()
    _check_rev(body, trip)
    try:
        ops = _OPS.validate_python(body.get("ops"))
    except ValidationError:
        raise HttpError(400, "操作格式不对。")
    if not ops:
        raise HttpError(400, "没有操作。")
    prop = make_proposal(trip, "网页工作台调整", ops, created_by="user")
    try:
        lines = describe_ops(trip, prop)
        new = apply_proposal(trip, prop)
    except (KeyError, LockedItemError, InvalidOperationError, StaleProposalError) as e:
        raise HttpError(400, f"这个改动不能做：{e}")
    before, after = _issue_keys(trip), _issue_keys(new)
    store = ms._load_proposals()
    store[prop.id] = {"proposal": prop.model_dump(mode="json"), "confirm_code": secrets.token_hex(8)}   # 确认码不给任何人看：网页点“确认”才是用户确认
    ms._save_proposals(store)
    affected = sorted({d.index + 1 for t in (trip, new) if t.plan for d in t.plan.days
                       if any(it.place_id in {o.place_id for o in ops} for it in d.items)})
    return {"proposal_id": prop.id, "changes": lines, "new_issues": [m for k, m in after.items() if k not in before],
            "affected_days": affected}


def apply(body: dict) -> dict[str, Any]:
    trip = ms._load()
    _check_rev(body, trip)
    store = ms._load_proposals()
    entry = store.get(body.get("proposal_id"))
    if not entry:
        raise HttpError(404, "找不到这条预览（可能已过期），请重新操作。")
    prop = Proposal.model_validate(entry["proposal"])
    try:
        new = apply_proposal(trip, prop)
    except (StaleProposalError, LockedItemError, InvalidOperationError, KeyError) as e:
        raise HttpError(400, f"套用失败：{e}")
    ms._save(new)
    ms._save_proposals({})
    return {"revision": new.revision}


def undo(body: dict) -> dict[str, Any]:
    trip = ms._load()
    _check_rev(body, trip)
    try:
        new = state_undo(trip)
    except NothingToUndo as e:
        raise HttpError(400, str(e))
    ms._save(new)
    ms._save_proposals({})
    return {"revision": new.revision}


def refine(body: dict) -> dict[str, Any]:
    """给指定的某天（不填=所有天）查真实路线。只补还没查过的路段。没有地图 key 或查询失败时保持估算，不算出错。
    路线只是缓存：把这次更新并进上一步的撤销历史里，这样“撤销”一步就回到拖拽之前。"""
    trip = ms._load()
    _check_rev(body, trip)
    day = body.get("day")
    if day is not None and not isinstance(day, int):
        raise HttpError(400, "day 需要是整数。")
    try:
        msg = ms.refine_routes(day)
    except ms.ToolError as e:
        return {"ok": False, "message": str(e), "revision": trip.revision}
    new = ms._load()
    if new.revision != trip.revision:
        ms._save(new.model_copy(update={"history": trip.history}))
    return {"ok": True, "message": msg.splitlines()[0], "revision": ms._load().revision, "more": "还有部分路段没查" in msg}


def dates(body: dict) -> dict[str, Any]:
    trip = ms._load()
    _check_rev(body, trip)
    try:
        sd = date.fromisoformat(body["start"]) if body.get("start") else None
        ed = date.fromisoformat(body["end"]) if body.get("end") else None
        new, notes = apply_dates(trip, sd, ed)
    except (ValueError, TypeError) as e:
        raise HttpError(400, str(e))
    ms._save(new)
    ms._save_proposals({})
    head = "已清除日期。" if sd is None else f"已把日期设为 {sd.isoformat()} 至 {ed.isoformat()}（共 {new.meta.num_days} 天）。"
    return {"revision": new.revision, "message": head + "".join(notes)}


# ---- 聊天：转发到本机的 nanobot（OpenAI 兼容接口），用同一个 agent、skill 和工具 ----
NANOBOT_DEFAULT = "http://127.0.0.1:8900"
CHAT_SESSION = "tripsight-workbench"
MAX_CHAT = 4000
MAX_HISTORY = 200            # 每个行程最多保留多少条聊天记录
MAX_STORED = 8000            # 单条记录最多存多少字
_chat_lock = threading.Lock()
_LOOPBACK = ("127.0.0.1", "localhost", "::1")


def _nanobot() -> tuple[str, int]:
    """nanobot 接口地址（环境变量 NANOBOT_API_URL，默认 127.0.0.1:8900）。只允许本机，避免把行程和 key 发到别处。"""
    u = urlparse(os.environ.get("NANOBOT_API_URL", "").strip() or NANOBOT_DEFAULT)
    if u.scheme != "http" or (u.hostname or "") not in _LOOPBACK:
        raise HttpError(400, "NANOBOT_API_URL 只能是本机的 http 地址（127.0.0.1 或 localhost）。")
    return u.hostname, u.port or 8900


def _slug() -> Optional[str]:
    if ms._single_file_mode():
        return None
    return ws.active_slug(ms._root_dir())


def _session_id() -> str:
    """每个行程一个独立的 nanobot 会话（行程名转成哈希，避免中文名带来麻烦）；单文件模式沿用固定会话。"""
    slug = _slug()
    return CHAT_SESSION if slug is None else "tripsight-" + hashlib.sha1(slug.encode("utf-8")).hexdigest()[:10]


def _chat_file() -> Path:
    """这个行程的聊天记录：放在行程目录里、不在 trip.json 里，所以不影响版本号、撤销和行程快照。"""
    return ms.trip_path().with_name("chat.json")


def _read_chat(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [m for m in data if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("text"), str)] if isinstance(data, list) else []


def _append_chat(path: Path, role: str, text: str, partial: bool = False) -> None:
    if not text.strip():
        return
    with _chat_lock:
        msgs = _read_chat(path)
        item: dict[str, Any] = {"role": role, "text": text[:MAX_STORED], "ts": int(time.time())}
        if partial:
            item["partial"] = True
        msgs.append(item)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(msgs[-MAX_HISTORY:], ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass                                           # 记录失败不影响聊天本身


def chat_history() -> dict[str, Any]:
    """页面加载或切换行程时用：当前行程的聊天记录（只含从工作台聊天栏发的对话）。"""
    return {"trip": _slug(), "messages": _read_chat(_chat_file())}


def new_trip(body: dict) -> dict[str, Any]:
    """页面上的“新建行程”：走和 agent 一样的 new_trip（长期偏好自动套用，原来的行程不动，创建后切换过去）。"""
    if ms._single_file_mode():
        raise HttpError(400, "当前是单文件模式，新建会覆盖现有行程，已禁用。请在 agent 里操作，或取消 TRIPCORE_FILE。")
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise HttpError(400, "请填写行程名称。")
    name = name.strip()
    if len(name) > 40:
        raise HttpError(400, "行程名称最多 40 个字。")
    city = body.get("city")
    if city is not None and (not isinstance(city, str) or len(city.strip()) > 40):
        raise HttpError(400, "目的地城市不合法。")
    city = (city or "").strip() or None
    sd, ed = body.get("start") or None, body.get("end") or None
    if bool(sd) != bool(ed):
        raise HttpError(400, "日期要同时填出发日和结束日，或者都不填。")
    for v in (sd, ed):
        if v is not None and not isinstance(v, str):
            raise HttpError(400, "日期格式不对。")
    nd, tv = body.get("num_days", 3), body.get("travelers", 1)
    if not (isinstance(nd, int) and not isinstance(nd, bool) and 1 <= nd <= 30):
        raise HttpError(400, "天数要在 1 到 30 之间。")
    if not (isinstance(tv, int) and not isinstance(tv, bool) and 1 <= tv <= 50):
        raise HttpError(400, "出行人数要在 1 到 50 之间。")
    pace = body.get("pace") or None
    if pace is not None and pace not in ("relaxed", "normal", "packed"):
        raise HttpError(400, "节奏只能是悠闲、正常或紧凑。")
    msg = ms.new_trip(name=name, num_days=nd, pace=pace, start_date=sd, end_date=ed, city=city, travelers=tv)
    t = ms._load()
    return {"trip": _slug(), "title": t.meta.name, "revision": t.revision, "message": msg.splitlines()[0]}


# ---- 加景点：先查（lookup），再从结果里选一个（add_place）。坐标只能来自查询结果，页面不能手填 ----
_CANDS: "dict[str, dict]" = {}
_CANDS_MAX = 60


def lookup(body: dict) -> dict[str, Any]:
    q = body.get("query")
    if not isinstance(q, str) or not q.strip():
        raise HttpError(400, "请输入要查找的地点名称。")
    if len(q.strip()) > 60:
        raise HttpError(400, "名称太长（最多 60 个字）。")
    r = ms.lookup_coords(q.strip())
    if not r.get("found"):
        return {"candidates": [], "message": r.get("error") or "没有找到，换个关键词试试。", "note": r.get("note", "")}
    raw = r.get("candidates") or [{"name": r["name"], "lat": r["lat"], "lon": r["lon"], "address": r.get("display_name", ""),
                                  "category": "", "rating": None, "opentime_today": ""}]
    out = []
    for c in raw[:5]:
        cid = secrets.token_hex(6)
        _CANDS[cid] = {"name": c["name"], "lat": c["lat"], "lon": c["lon"], "category": c.get("category") or "", "source": r["source"]}
        while len(_CANDS) > _CANDS_MAX:
            _CANDS.pop(next(iter(_CANDS)))
        out.append({"cid": cid, "name": c["name"], "address": c.get("address") or "", "category": c.get("category") or "",
                    "rating": c.get("rating"), "opentime_today": c.get("opentime_today") or ""})
    warn = r.get("warning") or ""
    if r["source"] == "osm":
        warn = (warn + " " if warn else "") + "这是 OpenStreetMap 的结果，位置可能不如地图服务准确，请核对。"
    return {"candidates": out, "source": r["source"], "warning": warn, "note": r.get("note", "")}


def add_place_web(body: dict) -> dict[str, Any]:
    cand = _CANDS.get(body.get("cid")) if isinstance(body.get("cid"), str) else None
    if cand is None:
        raise HttpError(400, "请先查找并从结果里选一个地点（坐标只能来自查询结果）。")
    dm = body.get("duration_min", 90)
    if not (isinstance(dm, int) and not isinstance(dm, bool) and 10 <= dm <= 720):
        raise HttpError(400, "停留时间要在 10 到 720 分钟之间。")
    trip = ms._load()
    _check_rev(body, trip)
    for p in trip.places:
        if p.name == cand["name"] and abs(p.lat - cand["lat"]) < 0.001 and abs(p.lon - cand["lon"]) < 0.001:
            raise HttpError(400, f"「{p.name}」已经在行程里了。")
    msg = ms.add_place(cand["name"], cand["lat"], cand["lon"], duration_min=dm, category=cand["category"], source=cand["source"])
    ms._save_proposals({})
    return {"revision": ms._load().revision, "message": f"已添加「{cand['name']}」，放在“未安排”里，拖到某一天即可。"}


def rev() -> dict[str, Any]:
    return {"revision": ms._load().revision, "trip": _slug()}


def trips() -> dict[str, Any]:
    """行程下拉框用：所有行程和当前行程。单文件模式只有一个，不能切换。"""
    if ms._single_file_mode():
        t = ms._load()
        return {"single": True, "current": None, "trips": [{"slug": "", "name": t.meta.name, "num_days": t.meta.num_days, "places": len(t.places)}]}
    root = ms._root_dir()
    ws.migrate_legacy(root)
    return {"single": False, "current": ws.active_slug(root),
            "trips": [{k: it[k] for k in ("slug", "name", "num_days", "places")} for it in ws.list_trips(root)]}


def switch(body: dict) -> dict[str, Any]:
    """切换当前行程（只改 active.json，不动任何行程文件）。agent 和聊天栏之后也针对这个行程。"""
    if ms._single_file_mode():
        raise HttpError(400, "当前是单文件模式，不能切换行程。")
    name = body.get("slug")
    if not isinstance(name, str) or not name.strip():
        raise HttpError(400, "缺少行程。")
    root = ms._root_dir()
    try:
        slug = ws.resolve(root, name)
    except KeyError:
        raise HttpError(404, "找不到这个行程。")
    except ValueError:
        raise HttpError(400, "匹配到多个行程，请从列表里选。")
    ws.set_active(root, slug)
    t = ms._load()
    return {"trip": slug, "title": t.meta.name, "revision": t.revision}


_API_ROUTE_OK = (200, 400, 401, 403, 405, 415, 422)       # 聊天接口存在（只是不接受这种请求）；404 才是没开启


def chat_status() -> dict[str, Any]:
    """两步确认：nanobot 在运行（/health），并且聊天接口已开启（/v1/chat/completions 不是 404）。"""
    try:
        host, port = _nanobot()
    except HttpError as e:
        return {"connected": False, "message": e.message}
    down = "没连上 nanobot。先启动它的接口：nanobot plugins enable api，然后 nanobot serve。"
    try:
        conn = http.client.HTTPConnection(host, port, timeout=1.5)
        conn.request("GET", "/health")
        r = conn.getresponse()
        r.read()
        conn.close()
        if r.status != 200:
            return {"connected": False, "message": down}
        conn = http.client.HTTPConnection(host, port, timeout=1.5)
        conn.request("GET", "/v1/chat/completions")
        r = conn.getresponse()
        r.read()
        conn.close()
    except Exception:
        return {"connected": False, "message": down}
    if r.status not in _API_ROUTE_OK:
        return {"connected": False, "message": "nanobot 在运行，但聊天接口没有开启。先运行 nanobot plugins enable api，再重启 nanobot serve。"}
    return {"connected": True, "message": ""}


_VERSION_FILES = ("web.py", "share.py", "photos.py", "tools_catalog.py", "travelogue.py", "webpage.py", "mapview.py", "dates.py", "proposals.py", "state.py", "mcp_server.py", "mealgaps.py", "daycard.py", "timeline.py", "hours.py", "scheduler.py", "lodging.py", "validator.py")


def code_version() -> str:
    """工作台相关代码的指纹。启动时算一次：用来识别“后台还在跑的是旧代码的工作台”。"""
    h = hashlib.sha1()
    for n in _VERSION_FILES:
        try:
            h.update((Path(__file__).with_name(n)).read_bytes())
        except OSError:
            pass
    return h.hexdigest()[:12]


CODE_VERSION = code_version()


def tools() -> dict[str, Any]:
    """“能力”页：全部工具的目录（类别、性质、一句话说明、示例话术）和承诺。"""
    return {"total": len(_tc.CATALOG), "blocks": _tc.catalog_rows(), "promises": _tc.PROMISES}


_BM_NOTE = {"text": ""}


def _share_html(body: dict) -> str:
    trip = ms._load()
    if trip.plan is None:
        raise HttpError(400, "还没有分天，先排好行程再分享。")
    photos = _ph.for_share(ms._photo_dir(), _ph.load(ms._photo_index())) if body.get("photos") else None
    bm = None
    if body.get("basemap"):
        bm, why = ms._make_basemap(trip)
        if bm is None:
            raise HttpError(400, "没有加底图：" + why)
    try:
        html = _share.build_share_html(trip, show_lodging=bool(body.get("lodging")), show_costs=bool(body.get("costs")), photos=photos,
                                       theme=str(body.get("theme") or "default"), route_map=body.get("route_map", True) is not False, basemap=bm)
    except ValueError as e:
        raise HttpError(400, str(e))
    if bm is not None and bm.failures:
        _BM_NOTE["text"] = "；".join(bm.failures)
    bad = _share.guard_html(html)
    if bad:
        raise HttpError(400, "外发检查没通过：" + "；".join(bad) + "。请检查景点名称/备注里是否混入了不该外发的内容。")
    return html


def share_preview(body: dict) -> dict[str, Any]:
    import importlib.util
    _BM_NOTE["text"] = ""
    html = _share_html(body)
    return {"html": html, "bm_note": _BM_NOTE["text"], "key_ok": bool(os.environ.get("AMAP_KEY", "").strip()), "png_ok": importlib.util.find_spec("playwright") is not None,
            "photo_count": len(_ph.load(ms._photo_index())),
            "gif_ok": importlib.util.find_spec("playwright") is not None and importlib.util.find_spec("PIL") is not None,
            "themes": [{"id": k, "label": v["label"]} for k, v in _share.THEMES.items()]}


def share_image(body: dict) -> dict[str, Any]:
    import base64
    html = _share_html(body)
    folder = ms._photo_dir().with_name("share")
    folder.mkdir(parents=True, exist_ok=True)
    h, p = folder / "workbench-share.html", folder / "workbench-share.png"
    h.write_text(html, encoding="utf-8")
    why = _share.render_png(h, p)
    if why:
        raise HttpError(400, "没有生成长图：" + why)
    return {"png": "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode("ascii")}


def share_gif(body: dict) -> dict[str, Any]:
    import base64
    html = _share_html(body)
    folder = ms._photo_dir().with_name("share")
    folder.mkdir(parents=True, exist_ok=True)
    h, g = folder / "workbench-share.html", folder / "workbench-route.gif"
    h.write_text(html, encoding="utf-8")
    why = _share.render_gif(h, g)
    if why:
        raise HttpError(400, "没有生成动画：" + why)
    return {"gif": "data:image/gif;base64," + base64.b64encode(g.read_bytes()).decode("ascii")}


def photos_list() -> dict[str, Any]:
    folder = ms._photo_dir()
    return {"photos": [{"id": x["id"], "place_id": x.get("place_id"), "day": x.get("day"), "caption": x.get("caption", ""),
                        "thumb": _ph.thumb_uri(folder, x["file"])} for x in _ph.load(ms._photo_index())]}


def photo_add(body: dict) -> dict[str, Any]:
    import base64
    import binascii
    trip = ms._load()
    pid = body.get("place_id")
    if not isinstance(pid, str) or not any(p.id == pid for p in trip.places):
        raise HttpError(400, "找不到这个景点。")
    try:
        raw = base64.b64decode(body.get("data") or "", validate=True)
    except (binascii.Error, ValueError):
        raise HttpError(400, "图片数据不对。")
    cap = str(body.get("caption") or "")
    bad = ms._guard_text(cap)
    if bad:
        raise HttpError(400, "说明里" + "；".join(bad))
    items = _ph.load(ms._photo_index())
    try:
        rec = _ph.add_bytes(ms._photo_dir(), items, raw, pid, None, cap)
    except _ph.PhotoError as e:
        raise HttpError(400, f"没有保存：{e}")
    _ph.save(ms._photo_index(), items)
    return {"id": rec["id"]}


def photo_full(body: dict) -> dict[str, Any]:
    """放大查看用：1400 边的大图（data URI），只读。"""
    pid = str(body.get("id") or "")
    row = next((x for x in _ph.load(ms._photo_index()) if x["id"] == pid), None)
    if row is None:
        raise HttpError(404, "找不到这张照片")
    uri = _ph.thumb_uri(ms._photo_dir(), row["file"], 1400, 80)
    if not uri:
        raise HttpError(404, "照片读不出来")
    return {"uri": uri}


def photo_remove(body: dict) -> dict[str, Any]:
    items = _ph.load(ms._photo_index())
    try:
        _ph.remove(ms._photo_dir(), items, str(body.get("id") or ""))
    except _ph.PhotoError as e:
        raise HttpError(404, str(e))
    _ph.save(ms._photo_index(), items)
    return {"ok": True}


def travelogue(body: dict) -> dict[str, Any]:
    return ms.draft_travelogue(style=str(body.get("style") or "通用"), show_lodging=bool(body.get("lodging")), show_costs=bool(body.get("costs")))


def travelogue_check(body: dict) -> dict[str, Any]:
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HttpError(400, "先把草稿粘贴进来。")
    if len(text) > 20_000:
        raise HttpError(400, "草稿太长（最多 2 万字）。")
    return ms.check_travelogue(text, show_costs=bool(body.get("costs")))


# ---------- 手册：恢复行程（从相册）和手册编辑、最终导出 ----------

def _stories() -> dict:
    return ms._load_json_file(ms._stories_path())


def _write_stories(data: dict) -> None:
    try:
        ms._stories_path().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        raise HttpError(500, f"保存失败：{e}")


def hb_state() -> dict[str, Any]:
    from . import vision as _vi
    trip = ms._load()
    folder = ms._photo_dir()
    photos = _ph.load(ms._photo_index())
    stories = _stories()
    side = ms._load_json_file(ms._photo_trip_path())
    recs = {x["place_id"]: x for x in side.get("stops", [])}
    order = {}
    if trip.plan:
        for d in trip.plan.days:
            for it in d.items:
                order[it.place_id] = d.index
    rows = []
    for p in sorted(trip.places, key=lambda q: (order.get(q.id, 99), 0)):
        if p.id not in order:
            continue
        rows.append({"id": p.id, "name": p.name, "day": order[p.id] + 1, "restored": p.id in recs,
                     "start": (recs.get(p.id) or {}).get("start", "")[11:16], "end": (recs.get(p.id) or {}).get("end", "")[11:16],
                     "photos": [{"id": x["id"], "thumb": _ph.thumb_uri(folder, x["file"], 200, 65)} for x in photos if x.get("place_id") == p.id],
                     "story": stories.get(p.id) or {}})
    labels = ms._chapter_labels()
    for r in rows:
        r["region"] = labels.get(r["id"], "")
    return {"name": trip.meta.name, "stops": rows, "restored": bool(recs), "folder": side.get("folder", ""), "album": side.get("album", ""),
            "vision": bool(_vi.config()), "max_photos": 6}


def hb_import(body: dict) -> dict[str, Any]:
    folder = str(body.get("folder") or "").strip()
    album = str(body.get("album") or "").strip()
    if not folder and not album:
        raise HttpError(400, "先填照片文件夹的路径，或选一个照片 App 的相册。")
    try:
        radius = int(body.get("radius_m") or 300)
    except (TypeError, ValueError):
        raise HttpError(400, "半径要是数字。")
    try:
        msg = ms.import_photo_trip(folder, radius_m=radius, min_photos=int(body.get("min_photos") or 3), album=album)
    except ms.ToolError as e:
        raise HttpError(400, str(e))
    return {"message": msg}


def hb_edit(body: dict) -> dict[str, Any]:
    pid = str(body.get("place_id") or "")
    if not any(p.id == pid for p in ms._load().places):
        raise HttpError(404, "找不到这个景点。")
    try:
        name = body.get("name")
        if isinstance(name, str) and name.strip():
            ms.update_place(pid, name=name.strip())
        data = _stories()
        ent = data.get(pid) or {}
        if "impression" in body:
            text = str(body.get("impression") or "").strip()
            if text:
                ms.save_stop_story(pid, impression=text)       # 复用同样的长度和内容检查
                data = _stories(); ent = data.get(pid) or {}
                ent["by"] = "user"
            else:
                ent.pop("impression", None); ent.pop("by", None)
        if "facts" in body:
            facts = [{"text": str(f.get("text") or ""), "source": str(f.get("source") or "")} for f in (body.get("facts") or []) if isinstance(f, dict) and (f.get("text") or f.get("source"))]
            if facts:
                ms.save_stop_story(pid, facts=facts)
                data = _stories(); ent_f = data.get(pid) or {}
                ent["facts"] = ent_f.get("facts", [])
            else:
                ent.pop("facts", None)
        if ent:
            data[pid] = ent
        else:
            data.pop(pid, None)
        _write_stories(data)
    except ms.ToolError as e:
        raise HttpError(400, str(e))
    return {"ok": True}


def hb_regions(body: dict) -> dict[str, Any]:
    try:
        return {"message": ms.tag_regions()}
    except ms.ToolError as e:
        raise HttpError(400, str(e))


def hb_merge(body: dict) -> dict[str, Any]:
    ids = body.get("place_ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise HttpError(400, "要选至少两个景点。")
    try:
        return {"message": ms.merge_stops(ids, name=str(body.get("name") or ""))}
    except ms.ToolError as e:
        raise HttpError(400, str(e))


def hb_photo_move(body: dict) -> dict[str, Any]:
    """在同一个景点的照片里调整顺序：to = "front"（设为封面）| "left" | "right"。"""
    pid, to = str(body.get("id") or ""), str(body.get("to") or "")
    items = _ph.load(ms._photo_index())
    row = next((x for x in items if x["id"] == pid), None)
    if row is None or to not in ("front", "left", "right"):
        raise HttpError(404, "找不到这张照片。")
    group = [x for x in items if x.get("place_id") == row.get("place_id")]
    i = group.index(row)
    j = 0 if to == "front" else (i - 1 if to == "left" else i + 1)
    if not 0 <= j < len(group) or j == i:
        return {"ok": True}
    group.insert(j, group.pop(i))
    it = iter(group)
    items = [next(it) if x.get("place_id") == row.get("place_id") else x for x in items]
    _ph.save(ms._photo_index(), items)
    return {"ok": True}


def hb_describe(body: dict) -> dict[str, Any]:
    """用用户配置的视觉模型给这个点的缩略拼图写描写。只在点按钮时调用；返回草稿，不保存。"""
    from . import phototrip as _pt, vision as _vi
    import io
    pid = str(body.get("place_id") or "")
    trip = ms._load()
    try:
        place = trip.place(pid)
    except KeyError:
        raise HttpError(404, "找不到这个景点。")
    if _vi.config() is None:
        raise HttpError(400, "还没有配置视觉模型（环境变量 DASHSCOPE_API_KEY 和 TRIPSIGHT_VISION_MODEL，模型必须能读图）。")
    side = ms._load_json_file(ms._photo_trip_path())
    rec = next((x for x in side.get("stops", []) if x["place_id"] == pid), None)
    try:
        if rec is not None and Path(side["folder"]).is_dir():
            sheet = _pt.contact_sheet(Path(side["folder"]), rec["files"])
        else:
            folder = ms._photo_dir()
            files = [x["file"] for x in _ph.load(ms._photo_index()) if x.get("place_id") == pid]
            if not files:
                raise HttpError(400, "这个景点还没有照片。")
            sheet = _pt.contact_sheet(folder, files)
        return {"draft": _vi.describe(sheet, place.name)}
    except ValueError as e:
        raise HttpError(400, str(e))
    except _vi.VisionError as e:
        raise HttpError(502, str(e))


def hb_export(body: dict) -> dict[str, Any]:
    fm = set(body.get("formats") or [])
    if not fm <= {"html", "cards", "pdf", "obsidian"} or not fm:
        raise HttpError(400, "至少选一种导出格式。")
    out: list[str] = []
    try:
        if fm & {"html", "cards", "pdf"}:
            out.append(ms.export_handbook(show_photos=bool(body.get("photos", True)), cards="cards" in fm, basemap=bool(body.get("basemap")), pdf="pdf" in fm, style=str(body.get("style") or "手账")))
        if "obsidian" in fm:
            out.append(ms.export_notes(include_photos=bool(body.get("photos", True))))
    except ms.ToolError as e:
        raise HttpError(400, str(e))
    return {"message": "\n\n".join(out)}


def ms_photoslib_error():
    from . import photoslib as _pl
    return _pl.PhotosLibError


def hb_albums(body: dict) -> dict[str, Any]:
    from . import photoslib as _pl
    ok, why = _pl.available()
    if not ok:
        raise HttpError(400, why)
    try:
        return {"albums": _pl.list_albums()}
    except _pl.PhotosLibError as e:
        raise HttpError(400, str(e))


def hb_preview(body: dict) -> dict[str, Any]:
    """导入前预览：按这个半径会聚出几处、每处在哪、有多少张；不新建行程、不写任何文件。"""
    from . import phototrip as _pt
    album = str(body.get("album") or "").strip()
    folder = Path(str(body.get("folder") or "").strip()).expanduser()
    if not album and (not str(body.get("folder") or "").strip() or not folder.is_dir()):
        raise HttpError(400, "找不到这个文件夹，请填完整路径。")
    try:
        radius = max(50, min(int(body.get("radius_m") or 300), 2000))
        mn = max(1, int(body.get("min_photos") or 3))
    except (TypeError, ValueError):
        raise HttpError(400, "半径要是数字。")
    try:
        if album:
            from . import photoslib as _pl
            photos, untagged, st = _pl.read_album(album)
        else:
            photos, untagged, st = _pt.read_all(folder)
    except (ValueError, ms_photoslib_error()) as e:
        raise HttpError(400, str(e))
    if not photos:
        raise HttpError(400, f"没有找到带位置的照片（统计：{st}）。")
    stops = _pt.cluster(photos, radius_m=radius)
    keep = [x for x in stops if x.n >= mn]
    guessed = _pt.assign_untagged(stops, untagged)
    return {"radius_m": radius, "total": len(stops), "kept": len(keep), "dropped": len(stops) - len(keep), "photos": len(photos),
            "untagged": len(untagged), "guessed": guessed, "stats": st,
            "stops": [{"lat": x.lat, "lon": x.lon, "n": x.n, "day": x.day.isoformat(), "start": x.start.strftime("%H:%M"), "end": x.end.strftime("%H:%M")} for x in keep]}


def bills_state() -> dict[str, Any]:
    from . import bills as _bl
    trip = ms._load()
    led = _bl.load(ms._ledger_path())
    return {"rows": led, "summary": _bl.summarize(led) if led else None, "categories": _bl.CATEGORIES + [_bl.TRANSFER],
            "places": [{"id": p.id, "name": p.name} for p in trip.places], "has_dates": trip.day_date(0) is not None,
            "rules": len(_bl.load_rules(ms._rules_path())), "watch": [str(x) for x in ms._watch_folders()],
            "shortcut": _bl.SHORTCUT_STEPS, "icloud": str(_bl.icloud_folder())}


def bills_import(body: dict) -> dict[str, Any]:
    try:
        return {"message": ms.import_bills(str(body.get("path") or ""))}
    except ms.ToolError as e:
        raise HttpError(400, str(e))


def bills_scan(body: dict) -> dict[str, Any]:
    try:
        return {"message": ms.scan_bills()}
    except ms.ToolError as e:
        raise HttpError(400, str(e))


def bills_watch(body: dict) -> dict[str, Any]:
    fs = body.get("folders")
    if not isinstance(fs, list) or not all(isinstance(x, str) for x in fs):
        raise HttpError(400, "文件夹列表格式不对。")
    try:
        return {"message": ms.set_bills_watch([x.strip() for x in fs if x.strip()])}
    except ms.ToolError as e:
        raise HttpError(400, str(e))


def bills_edit(body: dict) -> dict[str, Any]:
    from . import bills as _bl
    led = _bl.load(ms._ledger_path())
    kw: dict[str, Any] = {}
    if "category" in body:
        kw["category"] = str(body["category"])
    if "place_id" in body:
        pid = body["place_id"]
        if pid and not any(p.id == pid for p in ms._load().places):
            raise HttpError(400, "找不到这个景点。")
        kw["place_id"] = pid or None
    if "excluded" in body:
        kw["excluded"] = bool(body["excluded"])
    try:
        row = _bl.edit(led, str(body.get("id") or ""), **kw)
    except _bl.BillError as e:
        raise HttpError(400, str(e))
    if body.get("remember") and "category" in kw and kw["category"] in _bl.CATEGORIES:
        rules = _bl.load_rules(ms._rules_path())
        rules[row["merchant"]] = kw["category"]
        ms._rules_path().write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
        for x in led:                                   # 同一商户已有的消费一起改（被用户单独改过类别的也跟着，所以只改还没排除的）
            if x["merchant"] == row["merchant"] and not x.get("excluded"):
                x["category"] = kw["category"]
    _bl.save(ms._ledger_path(), led)
    return {"ok": True}


ROUTES_GET = {"state": lambda: snapshot(), "rev": rev, "trips": trips, "chat_status": chat_status, "chat_history": chat_history, "version": lambda: {"version": CODE_VERSION}, "tools": tools, "photos": photos_list, "hb_state": hb_state, "bills_state": bills_state}
ROUTES_POST = {"switch": switch, "new_trip": new_trip, "add_place": add_place_web, "lookup": lookup,  "preview": preview, "apply": apply, "undo": undo, "dates": dates, "refine": refine,
               "share_preview": share_preview, "share_image": share_image, "share_gif": share_gif, "photo_add": photo_add, "photo_remove": photo_remove, "photo_full": photo_full,
               "travelogue": travelogue, "travelogue_check": travelogue_check,
               "bills_import": bills_import, "bills_edit": bills_edit, "bills_scan": bills_scan, "bills_watch": bills_watch, "hb_preview": hb_preview, "hb_albums": hb_albums, "hb_import": hb_import, "hb_edit": hb_edit, "hb_merge": hb_merge, "hb_regions": hb_regions, "hb_photo_move": hb_photo_move, "hb_describe": hb_describe, "hb_export": hb_export}


def make_handler(token: str, state: dict):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TripSight"

        def log_message(self, *a):          # 不往终端打日志（网址里有令牌）
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj: Any) -> None:
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _guard(self) -> Optional[str]:
            """返回令牌之后的子路径；不合法返回 None（调用方回 404/403）。"""
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            if host not in ("127.0.0.1", "localhost"):
                self._json(403, {"error": "forbidden"})
                return None
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
                self._json(403, {"error": "forbidden"})
                return None
            parts = urlparse(self.path).path.split("/", 2)       # ['', token, rest]
            if len(parts) < 2 or not secrets.compare_digest(parts[1], token):
                self._json(404, {"error": "not found"})
                return None
            state["last"] = time.time()
            return parts[2] if len(parts) > 2 else ""

        def do_GET(self) -> None:
            rest = self._guard()
            if rest is None:
                return
            if rest == "":
                self._send(200, page_html().encode("utf-8"), "text/html; charset=utf-8")
            elif rest.startswith("api/") and rest[4:] in ROUTES_GET:
                self._run(ROUTES_GET[rest[4:]])
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            rest = self._guard()
            if rest is None:
                return
            if not rest.startswith("api/") or (rest[4:] not in ROUTES_POST and rest[4:] != "chat"):
                self._json(404, {"error": "not found"})
                return
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                self._json(415, {"error": "需要 JSON"})
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if not 0 <= n <= MAX_BODY_BY_ROUTE.get(rest[4:], MAX_BODY):
                self._json(413, {"error": "请求太大"})
                return
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                self._json(400, {"error": "JSON 格式不对"})
                return
            if rest[4:] == "chat":
                self._chat(body)
                return
            self._run(lambda: ROUTES_POST[rest[4:]](body), write=rest[4:] not in ("lookup", "share_preview", "share_image", "share_gif", "travelogue", "travelogue_check", "photo_full", "hb_describe", "hb_preview", "hb_albums"))

        def _chat(self, body: dict) -> None:
            """把一条消息转给 nanobot 并把流式回复原样转给页面。不带 key 给页面，错误只给友好提示。"""
            msg = body.get("message")
            if not isinstance(msg, str) or not msg.strip():
                self._json(400, {"error": "消息不能为空。"})
                return
            if len(msg) > MAX_CHAT:
                self._json(400, {"error": f"消息太长（最多 {MAX_CHAT} 字）。"})
                return
            try:
                host, port = _nanobot()
            except HttpError as e:
                self._json(e.status, {"error": e.message})
                return
            headers = {"Content-Type": "application/json"}
            key = os.environ.get("NANOBOT_API_KEY", "").strip()
            if key:
                headers["Authorization"] = "Bearer " + key
            cfile, sid = _chat_file(), _session_id()          # 先定下是哪个行程：回复中途即使切换了行程，也记在原来那个里
            payload = json.dumps({"messages": [{"role": "user", "content": msg}], "session_id": sid, "stream": True})
            try:
                conn = http.client.HTTPConnection(host, port, timeout=130)
                conn.request("POST", "/v1/chat/completions", payload.encode("utf-8"), headers)
                resp = conn.getresponse()
            except Exception:
                self._json(502, {"error": "没连上 nanobot。先启动它的接口：nanobot plugins enable api，然后 nanobot serve。"})
                return
            if resp.status != 200:
                resp.read()
                conn.close()
                hint = "nanobot 接口需要 key：启动工作台前设置环境变量 NANOBOT_API_KEY。" if resp.status == 401 else f"nanobot 返回了错误（HTTP {resp.status}）。"
                self._json(502, {"error": hint})
                return
            _append_chat(cfile, "user", msg)
            got, finished = [], False
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                while True:
                    line = resp.readline()
                    if not line:
                        break
                    if line.startswith(b"data:"):
                        data = line[5:].strip()
                        if data == b"[DONE]":
                            finished = True
                        else:
                            try:
                                got.append(((json.loads(data).get("choices") or [{}])[0].get("delta") or {}).get("content") or "")
                            except (ValueError, AttributeError, TypeError):
                                pass
                    self.wfile.write(line)
                    self.wfile.flush()
                    state["last"] = time.time()
            except Exception:
                pass                                           # 页面断开或 nanobot 中途结束：页面按“没收到 [DONE]”处理
            finally:
                conn.close()
                _append_chat(cfile, "assistant", "".join(got), partial=not finished)

        def _run(self, fn, write: bool = False) -> None:
            try:
                if write:
                    with _lock:
                        out = fn()
                else:
                    out = fn()
            except HttpError as e:
                self._json(e.status, {"error": e.message})
            except ms.ToolError as e:
                self._json(400, {"error": str(e)})
            except Exception as e:                           # 不把内部细节（路径等）发给页面
                self._json(500, {"error": f"内部错误：{type(e).__name__}"})
            else:
                self._json(200, out)

    return Handler


def serve(port: int = 0, url_file: Optional[str] = None, open_browser: bool = False,
          idle_seconds: float = IDLE_SECONDS) -> int:
    token = secrets.token_urlsafe(16)
    state = {"last": time.time()}
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(token, state))
    url = f"http://127.0.0.1:{httpd.server_address[1]}/{token}/"
    if url_file:
        tmp = Path(url_file + ".tmp")
        tmp.write_text(url, encoding="utf-8")
        tmp.replace(url_file)
    else:
        print(url, flush=True)
    if open_browser:
        import webbrowser
        webbrowser.open(url)

    def watchdog() -> None:
        while True:
            time.sleep(min(30, max(idle_seconds / 4, 0.05)))
            if time.time() - state["last"] > idle_seconds:
                httpd.shutdown()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
    return 0


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def launch(root: Path) -> str:
    """在后台启动工作台并返回说明（含网址）。已经在跑就复用同一个网址。"""
    root.mkdir(parents=True, exist_ok=True)
    info = root / "workbench.json"
    try:
        cur = json.loads(info.read_text(encoding="utf-8"))
        pid, url = int(cur["pid"]), str(cur["url"])
        if _alive(pid):
            try:
                with urllib.request.urlopen(url + "api/version", timeout=2) as r:
                    same = json.loads(r.read().decode("utf-8")).get("version") == CODE_VERSION
                if same:
                    return _msg(url, reused=True)
                stale = True                       # 是工作台，但代码版本不同
            except urllib.error.HTTPError as e:
                stale = e.code == 404              # 老版本的工作台没有 version 接口
            except Exception:
                stale = False                      # 连不上：不确定这个 pid 还是不是工作台，不去杀
            if stale:
                try:
                    with urllib.request.urlopen(url + "api/state", timeout=2):
                        pass                       # 能回答 state：确认是我们自己的工作台，才结束它
                    os.kill(pid, signal.SIGTERM)
                    for _ in range(30):
                        if not _alive(pid):
                            break
                        time.sleep(0.1)
                except Exception:
                    pass
    except Exception:
        pass
    url_file = root / "workbench.url"
    url_file.unlink(missing_ok=True)
    proc = subprocess.Popen([sys.executable, "-m", "tripcore", "web", "--url-file", str(url_file), "--open"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True, env=os.environ.copy())
    for _ in range(80):
        if url_file.exists():
            url = url_file.read_text(encoding="utf-8").strip()
            info.write_text(json.dumps({"pid": proc.pid, "url": url}), encoding="utf-8")
            url_file.unlink(missing_ok=True)
            return _msg(url, reused=False)
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    raise RuntimeError("工作台没能启动，请在终端运行 python -m tripcore web 看具体报错。")


def _msg(url: str, reused: bool) -> str:
    return (f"工作台{'已在运行' if reused else '已启动'}：{url}\n"
            "在这台电脑的浏览器里打开（刚启动时会自动打开）。网址带一次性令牌，只在本机有效，不要转发给别人；空闲 2 小时自动退出。\n"
            "页面默认是“查看模式”（信息和地图页一样全：按天分页签、每个点的详情、通勤、用餐、点击联动地图）；点“编辑”才出现拖拽（松手后先预览，点“确认”才生效，并自动补真实路线）、月历选日期、撤销；"
            "右侧“助手”聊天栏连的是 nanobot 本机接口（需要先运行 nanobot serve），加景点、选酒店、查车票机票都可以在里面说。")
