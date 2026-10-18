"""本机网页工作台：拖拽调整每天的景点、月历选日期，所有修改走现有的“提案 → 套用 → 撤销”。

安全：只监听 127.0.0.1；网址里带一次性随机令牌，没有令牌一律 404；检查 Host 和 Origin，防止别的网站偷偷调用；
修改请求必须带页面加载时的版本号，版本变了（agent 或别处改过）就拒绝，不会覆盖别人的修改。
网页不直接写文件：每次修改都是 commit（可 undo），并且和 agent 共用同一份行程文件。
"""

from __future__ import annotations

import hashlib
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

from . import mcp_server as ms
from . import workspace as ws
from .dates import apply_dates
from .lodging import rank_lodgings
from .mapview import build_map_data
from .models import Stay, Trip
from .proposals import (InvalidOperationError, LockedItemError, Op, StaleProposalError, apply_proposal,
                        describe_ops, make_proposal)
from .proposals import Proposal
from .state import NothingToUndo, commit, undo as state_undo
from .validator import validate
from .webpage import page_html

_OPS = TypeAdapter(list[Op])
MAX_BODY = 100_000
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
    try:
        ranked = {r.lodging.id: r for r in rank_lodgings(trip)}
        order = [r.lodging.id for r in ranked.values()] + [l.id for l in trip.lodgings if l.id not in ranked]
    except Exception:
        ranked, order = {}, [l.id for l in trip.lodgings]
    byid = {l.id: l for l in trip.lodgings}
    lodging = {"nights": max(m.num_days - 1, 1), "chosen": trip.chosen_lodging_id,
               "stays": [{"lodging_id": a.lodging_id, "from_day": a.from_day + 1, "to_day": a.to_day + 1} for a in sorted(trip.stays, key=lambda z: z.from_day)],
               "items": [{"id": i, "name": byid[i].name, "price_min": byid[i].price_min, "price_max": byid[i].price_max,
                          "avg_commute_min": ranked[i].avg_commute_min if i in ranked else None} for i in order]}
    return {"title": m.name, "trip": _slug(), "lodging": lodging, "revision": trip.revision, "can_undo": bool(trip.history), "days": days, "unscheduled": unscheduled,
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
    return {"ok": True, "message": msg.splitlines()[0], "revision": ms._load().revision}


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


# ---- 住宿：预览 → 确认（和拖拽一样可撤销）；新增酒店只能从查询结果里选 ----
_LPEND: "dict[str, dict]" = {}


def _lodging_change(trip: Trip, body: dict) -> tuple[Trip, list[str]]:
    """按页面提交的“全程住宿 + 分段住宿”算出新版本和“改前→改后”说明（不保存）。"""
    names = {l.id: l.name for l in trip.lodgings}
    sets_chosen = "chosen" in body
    chosen = body.get("chosen")
    if sets_chosen and chosen is not None and chosen not in names:
        raise HttpError(400, "找不到这家住宿。")
    stays: Optional[list[Stay]] = None
    if "stays" in body:
        raw = body.get("stays")
        if not isinstance(raw, list) or len(raw) > 20:
            raise HttpError(400, "分段住宿格式不对。")
        stays = []
        n = trip.meta.num_days
        for x in raw:
            try:
                fd, td, lid = x["from_day"], x["to_day"], x["lodging_id"]
                if isinstance(fd, bool) or isinstance(td, bool) or not isinstance(fd, int) or not isinstance(td, int) or not isinstance(lid, str):
                    raise TypeError
            except (KeyError, TypeError):
                raise HttpError(400, "分段住宿格式不对。")
            if lid not in names:
                raise HttpError(400, "分段住宿里有不存在的酒店。")
            if not 1 <= fd <= td <= n:
                raise HttpError(400, f"天数超出范围：第 {fd}–{td} 晚（行程共 {n} 天）。")
            stays.append(Stay(lodging_id=lid, from_day=fd - 1, to_day=td - 1))
    if not sets_chosen and stays is None:
        raise HttpError(400, "没有要修改的住宿。")

    def mutate(t: Trip) -> None:
        if sets_chosen:
            t.chosen_lodging_id = chosen
        if stays is not None:
            t.stays = stays

    try:
        new = commit(trip, mutate)
        Trip.model_validate(new.model_dump())              # 校验：各段不重叠等
    except (ValidationError, ValueError):
        raise HttpError(400, "住宿设置不合法（分段之间不能重叠）。")
    lines: list[str] = []
    if sets_chosen and chosen != trip.chosen_lodging_id:
        lines.append(f"全程住宿：{names.get(trip.chosen_lodging_id, '未选')} → {names.get(chosen, '未选')}")
    if stays is not None:
        def fmt(ss):
            return "；".join(f"第{a.from_day + 1}–{a.to_day + 1}晚 {names[a.lodging_id]}" for a in sorted(ss, key=lambda z: z.from_day)) or "无"
        if fmt(trip.stays) != fmt(stays):
            lines.append(f"分段住宿：{fmt(trip.stays)} → {fmt(stays)}")
    if not lines:
        raise HttpError(400, "住宿没有变化。")
    return new, lines


def lodging_preview(body: dict) -> dict[str, Any]:
    trip = ms._load()
    _check_rev(body, trip)
    new, lines = _lodging_change(trip, body)
    before, after = _issue_keys(trip), _issue_keys(new)
    pid = secrets.token_hex(6)
    _LPEND[pid] = {"rev": trip.revision, "body": {k: body[k] for k in ("chosen", "stays") if k in body}}
    while len(_LPEND) > 20:
        _LPEND.pop(next(iter(_LPEND)))
    return {"proposal_id": pid, "changes": lines, "new_issues": [m for k, m in after.items() if k not in before],
            "affected_days": []}


def lodging_apply(body: dict) -> dict[str, Any]:
    trip = ms._load()
    _check_rev(body, trip)
    entry = _LPEND.pop(body.get("proposal_id"), None) if isinstance(body.get("proposal_id"), str) else None
    if not entry or entry["rev"] != trip.revision:
        raise HttpError(404, "找不到这条预览（可能已过期），请重新操作。")
    new, _ = _lodging_change(trip, entry["body"])
    ms._save(new)
    ms._save_proposals({})
    return {"revision": new.revision, "message": "已套用住宿设置，往返路线按各天酒店重算。"}


def add_lodging_web(body: dict) -> dict[str, Any]:
    cand = _CANDS.get(body.get("cid")) if isinstance(body.get("cid"), str) else None
    if cand is None:
        raise HttpError(400, "请先查找并从结果里选一家（坐标只能来自查询结果）。")
    prices = []
    for k in ("price_min", "price_max"):
        v = body.get(k)
        if v in (None, ""):
            prices.append(0.0)
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100000:
            prices.append(float(v))
        else:
            raise HttpError(400, "价格要填 0 到 100000 之间的数字，不知道就留空。")
    if prices[1] and prices[0] > prices[1]:
        raise HttpError(400, "最低价不能高于最高价。")
    if prices[0] and not prices[1]:
        prices[1] = prices[0]
    trip = ms._load()
    _check_rev(body, trip)
    for l in trip.lodgings:
        if l.name == cand["name"] and abs(l.lat - cand["lat"]) < 0.001 and abs(l.lon - cand["lon"]) < 0.001:
            raise HttpError(400, f"「{l.name}」已经在候选里了。")
    ms.add_lodging(cand["name"], cand["lat"], cand["lon"], price_min=prices[0], price_max=prices[1], price_source="manual")
    ms._save_proposals({})
    return {"revision": ms._load().revision, "message": f"已添加候选酒店「{cand['name']}」" + ("" if prices[1] else "（价格未填，不会自动估价）") + "。"}


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


_VERSION_FILES = ("web.py", "webpage.py", "mapview.py", "dates.py", "proposals.py", "state.py", "mcp_server.py")


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


ROUTES_GET = {"state": lambda: snapshot(), "rev": rev, "trips": trips, "chat_status": chat_status, "version": lambda: {"version": CODE_VERSION}}
ROUTES_POST = {"switch": switch, "new_trip": new_trip, "add_place": add_place_web, "lookup": lookup, "lodging_preview": lodging_preview, "lodging_apply": lodging_apply, "add_lodging": add_lodging_web, "preview": preview, "apply": apply, "undo": undo, "dates": dates, "refine": refine}


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
            if not 0 <= n <= MAX_BODY:
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
            self._run(lambda: ROUTES_POST[rest[4:]](body), write=rest[4:] != "lookup")

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
            payload = json.dumps({"messages": [{"role": "user", "content": msg}], "session_id": CHAT_SESSION, "stream": True})
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
                    self.wfile.write(line)
                    self.wfile.flush()
                    state["last"] = time.time()
            except Exception:
                pass                                           # 页面断开或 nanobot 中途结束：页面按“没收到 [DONE]”处理
            finally:
                conn.close()

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
