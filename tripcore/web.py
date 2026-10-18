"""本机网页工作台：拖拽调整每天的景点、月历选日期，所有修改走现有的“提案 → 套用 → 撤销”。

安全：只监听 127.0.0.1；网址里带一次性随机令牌，没有令牌一律 404；检查 Host 和 Origin，防止别的网站偷偷调用；
修改请求必须带页面加载时的版本号，版本变了（agent 或别处改过）就拒绝，不会覆盖别人的修改。
网页不直接写文件：每次修改都是 commit（可 undo），并且和 agent 共用同一份行程文件。
"""

from __future__ import annotations

import http.client
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from pydantic import TypeAdapter, ValidationError

from . import mcp_server as ms
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
                              "time": times.get(it.place_id, "")})
            days.append({"index": day.index, "label": f"第{day.index + 1}天" + (f" {dt.isoformat()}" if dt else ""),
                         "color": md["color"], "items": items, "rows": rows})
    reasons = {u.place_id: u.reason for u in (trip.plan.unscheduled if trip.plan else [])}
    unscheduled = [{"place_id": p.id, "name": p.name, "reason": reasons.get(p.id, "")}
                   for p in trip.places if p.id not in placed and p.status.value in ("shortlist", "planned", "confirmed")]
    names = {p.id: p.name for p in trip.places}
    orphan_meals = [{"id": m.id, "name": m.name, "after": names.get(m.after_place_id, m.after_place_id)}
                    for m in trip.meals if m.after_place_id not in placed]
    m = trip.meta
    return {"title": m.name, "revision": trip.revision, "can_undo": bool(trip.history), "days": days, "unscheduled": unscheduled,
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


def rev() -> dict[str, Any]:
    return {"revision": ms._load().revision}


def chat_status() -> dict[str, Any]:
    try:
        host, port = _nanobot()
        conn = http.client.HTTPConnection(host, port, timeout=1.5)
        conn.request("GET", "/health")
        ok = conn.getresponse().status == 200
        conn.close()
    except HttpError as e:
        return {"connected": False, "message": e.message}
    except Exception:
        ok = False
    return {"connected": ok, "message": "" if ok else "没连上 nanobot。先启动它的接口：nanobot plugins enable api，然后 nanobot serve。"}


ROUTES_GET = {"state": lambda: snapshot(), "rev": rev, "chat_status": chat_status}
ROUTES_POST = {"preview": preview, "apply": apply, "undo": undo, "dates": dates, "refine": refine}


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
            self._run(lambda: ROUTES_POST[rest[4:]](body), write=True)

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
        if _alive(int(cur["pid"])):
            with urllib.request.urlopen(cur["url"] + "api/state", timeout=2):
                pass
            return _msg(cur["url"], reused=True)
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
            "页面里：拖动景点调整顺序或跨天移动（松手后先预览，点“确认”才生效，并自动补真实路线），月历选日期，右上角可以撤销；"
            "右侧“助手”聊天栏连的是 nanobot 本机接口（需要先运行 nanobot serve），加景点、选酒店、查车票机票都可以在里面说。")
