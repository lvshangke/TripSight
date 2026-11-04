"""工具调用的实时记录：任何 agent（nanobot、Claude 等）通过 MCP 或命令行调用 TripSight 工具，都会在这里留一条，
TripSight 页面轮询它来显示“助手正在做什么”。只记工具名、参数摘要、结果摘要；不记照片内容、不记密钥，文件只在本机。"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

MAX_LINES = 600
KEEP_LINES = 300
_SECRET = re.compile(r"key|token|secret|password|passwd|data|uri", re.I)

LABELS = {
    "import_photo_trip": "读取照片并还原行程", "list_photo_albums": "列出照片相册", "view_stop": "查看停留点的照片和候选地名",
    "autoname_stops": "给停留点查地名", "run_naming_job": "后台查地名和标注城市/区", "merge_stops": "合并停留点", "delete_stop": "删除停留点", "tag_regions": "标注所在城市/区",
    "save_stop_story": "保存介绍和感受", "set_day_title": "设置当天标题", "suggest_day_titles": "取出每天的地点，准备起标题",
    "export_handbook": "生成手册", "export_notes": "导出 Obsidian 笔记", "export_calendar": "导出日历", "update_place": "修改景点",
    "show_trip": "查看当前行程", "new_trip": "新建行程", "add_place": "添加景点", "schedule_days": "排每天的行程", "check_plan": "检查行程",
    "open_workbench": "打开 TripSight 页面", "undo": "撤销上一步", "list_trips": "列出行程", "switch_trip": "切换行程",
}


def _short(v: Any, n: int = 40) -> str:
    if isinstance(v, str):
        return v if len(v) <= n else v[:n] + "…"
    if isinstance(v, (list, tuple, set)):
        return f"{len(v)} 项"
    if isinstance(v, dict):
        return f"{len(v)} 个字段"
    return str(v)


def summarize_args(args: dict[str, Any]) -> str:
    parts = []
    for k, v in (args or {}).items():
        if _SECRET.search(str(k)) or v in ("", None):
            continue
        parts.append(f"{k}={_short(v)}")
    return "，".join(parts)[:120]


def summarize_result(res: Any) -> str:
    if isinstance(res, str):
        return (res.strip().splitlines() or [""])[0][:90]
    if isinstance(res, dict):
        return "返回 " + "、".join(list(res)[:5])
    if isinstance(res, (list, tuple)):
        for blk in res:
            if getattr(blk, "type", "") == "text":
                return (blk.text.strip().splitlines() or [""])[0][:90]
        return "完成"
    return "完成"


def label_of(name: str) -> str:
    if name in LABELS:
        return LABELS[name]
    try:
        from .tools_catalog import CATALOG
        return CATALOG[name][2].rstrip("。")[:22]
    except Exception:
        return name


def _append(path: Path, rec: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if path.stat().st_size > 400_000:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) > MAX_LINES:
                path.write_text("\n".join(lines[-KEEP_LINES:]) + "\n", encoding="utf-8")
    except OSError:
        pass                                    # 记录失败不影响工具本身


def start(path: Path, name: str, args: dict[str, Any]) -> str:
    cid = f"{time.time_ns() // 1000:x}"
    _append(path, {"id": cid, "ts": time.time(), "name": name, "label": label_of(name), "args": summarize_args(args), "state": "run"})
    return cid


def finish(path: Path, cid: str, name: str, ok: bool, summary: str, t0: float) -> None:
    _append(path, {"id": cid, "ts": time.time(), "name": name, "state": "ok" if ok else "err", "summary": summary[:120], "ms": int((time.time() - t0) * 1000)})


def read_since(path: Path, since: float = 0.0, limit: int = 40) -> list[dict]:
    """返回 since 之后有变化的调用（开始或结束），按开始先后排序，已合并成每个调用一条。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-MAX_LINES:]
    except OSError:
        return []
    merged: dict[str, dict] = {}
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        cur = merged.setdefault(r["id"], {})
        cur.update({k: v for k, v in r.items() if k != "ts"})
        cur.setdefault("t0", r["ts"])
        cur["ts"] = r["ts"]
    out = [v for v in merged.values() if v["ts"] > since]
    out.sort(key=lambda v: v["t0"])
    return out[-limit:]


_READONLY = {"restore_status", "list_trips", "show_trip", "list_photo_albums", "view_stop", "suggest_day_titles", "open_workbench", "tools_catalog"}


def running(path: Path, within: float = 420.0) -> list[dict]:
    """现在还在跑（只有开始、没有结束）的会改数据的调用。超过 within 秒还没结束的当作进程已经没了，不算。"""
    now = time.time()
    return [e for e in read_since(path, now - within, limit=200) if e.get("state") == "run" and e.get("name") not in _READONLY]


class Tracked:
    """with Tracked(path, name, args) as t: ...; t.result = 返回值。出错自动记成失败并继续向外抛。"""

    def __init__(self, path: Path, name: str, args: dict[str, Any]):
        self.path, self.name, self.args, self.result = path, name, args, None

    def __enter__(self) -> "Tracked":
        self.t0 = time.time()
        self.cid = start(self.path, self.name, self.args)
        return self

    def __exit__(self, et, ev, tb) -> bool:
        if et is None:
            finish(self.path, self.cid, self.name, True, summarize_result(self.result), self.t0)
        else:
            finish(self.path, self.cid, self.name, False, str(ev)[:90] or et.__name__, self.t0)
        return False
