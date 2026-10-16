"""MCP 服务：把 tripcore 包装成一组工具，让 nanobot 等 Agent 通过聊天来操作行程。

设计要点
- 本文件只“包装”，不改 tripcore 原有逻辑：分天、检查、提案、撤销全部调用现有函数。
- 状态存在磁盘上（默认 ~/.tripcore/trip.json），每个工具都是 读文件 → 处理 → 存文件，
  所以服务重启也不会丢数据。可用环境变量 TRIPCORE_FILE 换位置。
- 待确认的提案存在同目录的 proposals.json。提案记录了 base_revision，
  行程一旦变化（包括加景点、撤销），旧提案会自动过期。
- 坐标、价格这类“事实”必须由工具或用户给出，模型不应自己编。

运行：python -m tripcore.mcp_server        （stdio 方式，由 nanobot 拉起）
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Optional

from pydantic import TypeAdapter, ValidationError

from .geocode import GeocodeError, geocode as _geocode
from .lodging import rank_lodgings, suggest_stay_area
from .metrics import day_stats, estimate_cost
from .models import DateMode, Lodging, Pace, Place, Trip, TripMeta
from .proposals import (
    InvalidOperationError,
    LockedItemError,
    Op,
    Proposal,
    StaleProposalError,
    apply_proposal as _apply_proposal,
    describe_ops,
    make_proposal,
)
from .scheduler import schedule
from .state import NothingToUndo, commit
from .state import undo as _undo
from .storage import load_trip, save_trip
from .validator import validate

_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_MODE_NAMES = {"walk": "步行", "transit": "公共交通", "drive": "驾车"}
_OP_ADAPTER = TypeAdapter(Op)


class ToolError(Exception):
    """给用户/模型看的错误说明。"""


# ---------------------------------------------------------------------------
# 存取
# ---------------------------------------------------------------------------

def trip_path() -> Path:
    p = os.environ.get("TRIPCORE_FILE")
    return Path(p).expanduser() if p else Path.home() / ".tripcore" / "trip.json"


def _proposals_path() -> Path:
    return trip_path().with_name("proposals.json")


def _load() -> Trip:
    p = trip_path()
    if not p.exists():
        raise ToolError("还没有行程，请先调用 new_trip 创建。")
    return load_trip(p)


def _save(trip: Trip) -> None:
    trip_path().parent.mkdir(parents=True, exist_ok=True)
    save_trip(trip, trip_path())


def _load_proposals() -> dict[str, dict]:
    p = _proposals_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _save_proposals(data: dict[str, dict]) -> None:
    p = _proposals_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def _next_id(prefix: str, existing: list[str]) -> str:
    n = 1
    while f"{prefix}{n}" in existing:
        n += 1
    return f"{prefix}{n}"


def _parse_date(s: Optional[str], field: str) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise ToolError(f"{field} 需要 YYYY-MM-DD 格式，收到：{s}")


# ---------------------------------------------------------------------------
# 工具实现（普通函数，方便直接测试）
# ---------------------------------------------------------------------------

def new_trip(
    name: str = "我的旅行",
    num_days: int = 3,
    pace: str = "normal",
    mode: str = "transit",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    earliest_start: Optional[str] = None,
    latest_end: Optional[str] = None,
    budget_total: Optional[float] = None,
) -> str:
    """创建一个新行程（会覆盖当前行程）。日期可不填；填 start_date+end_date 为确定日期，
    填 earliest_start+latest_end 为大致范围。"""
    sd, ed = _parse_date(start_date, "start_date"), _parse_date(end_date, "end_date")
    es, le = _parse_date(earliest_start, "earliest_start"), _parse_date(latest_end, "latest_end")
    if sd or ed:
        date_mode = DateMode.EXACT
    elif es or le:
        date_mode = DateMode.RANGE
    else:
        date_mode = DateMode.UNKNOWN
    try:
        meta = TripMeta(
            name=name, num_days=num_days, pace=Pace(pace), mode=mode,  # type: ignore[arg-type]
            date_mode=date_mode, start_date=sd, end_date=ed,
            earliest_start=es, latest_end=le, budget_total=budget_total,
        )
    except (ValidationError, ValueError) as e:
        raise ToolError(f"参数不合法：{e}")
    trip = Trip(meta=meta)
    _save(trip)
    _save_proposals({})
    return f"已创建行程「{meta.name}」，共 {meta.num_days} 天，节奏 {meta.pace.value}，交通偏好 {_MODE_NAMES[meta.mode]}。"


def add_place(
    name: str,
    lat: float,
    lon: float,
    duration_min: int = 90,
    priority: int = 3,
    must_go: bool = False,
    ticket_price: float = 0,
    closed_weekdays: Optional[list[int]] = None,
    reservation_required: bool = False,
    notes: str = "",
    source: str = "user",
) -> str:
    """添加一个景点。lat/lon 必须来自 lookup_coords 或用户，不要自己编。
    closed_weekdays：闭馆的星期，0=周一 … 6=周日。"""
    trip = _load()
    pid = _next_id("p", [p.id for p in trip.places])
    try:
        place = Place(
            id=pid, name=name, lat=lat, lon=lon, duration_min=duration_min,
            priority=priority, must_go=must_go, ticket_price=ticket_price,
            closed_weekdays=closed_weekdays or [], reservation_required=reservation_required,
            notes=notes, source=source,
        )
    except ValidationError as e:
        raise ToolError(f"景点参数不合法：{e}")
    new = commit(trip, lambda t: t.places.append(place))
    _save(new)
    return f"已添加景点「{name}」(id={pid})，当前共 {len(new.places)} 个景点。还没分天的话请调用 schedule_days。"


def add_lodging(
    name: str,
    lat: float,
    lon: float,
    price_min: float = 0,
    price_max: float = 0,
    choose: bool = False,
    notes: str = "",
) -> str:
    """添加候选住宿（价格为每晚，元）。choose=True 则同时设为本次选定的住宿。"""
    trip = _load()
    lid = _next_id("l", [l.id for l in trip.lodgings])
    try:
        lodging = Lodging(id=lid, name=name, lat=lat, lon=lon, price_min=price_min, price_max=price_max, notes=notes)
    except ValidationError as e:
        raise ToolError(f"住宿参数不合法：{e}")

    def mutate(t: Trip) -> None:
        t.lodgings.append(lodging)
        if choose:
            t.chosen_lodging_id = lid

    _save(commit(trip, mutate))
    return f"已添加住宿「{name}」(id={lid})" + ("，并设为选定住宿。" if choose else "。")


def lookup_coords(query: str, city: Optional[str] = None) -> dict[str, Any]:
    """查询地点坐标（目前用 OpenStreetMap，第 2 步会换成高德）。找不到时返回 found=false。"""
    try:
        r = _geocode(query, city)
    except GeocodeError as e:
        return {"found": False, "error": str(e)}
    return {"found": True, "name": r["name"], "lat": r["lat"], "lon": r["lon"], "display_name": r["display_name"]}


def schedule_days(keep_locked: bool = True) -> str:
    """自动把入围景点分到各天并排好顺序（确定性算法，已锁定的条目不会动）。"""
    trip = _load()
    if not trip.places:
        raise ToolError("还没有景点，请先 add_place。")
    new = schedule(trip, keep_locked=keep_locked)
    _save(new)
    msg = f"已分天（版本 {new.revision}）。"
    assert new.plan is not None
    if new.plan.unscheduled:
        names = "、".join(f"{trip.place(u.place_id).name}（{u.reason}）" for u in new.plan.unscheduled)
        msg += f"\n未能安排：{names}"
    return msg + "\n" + _render(new)


def check_plan() -> dict[str, Any]:
    """检查行程，返回 {"ok": 是否没有 error/warning, "issues": 问题清单}（severity: error/warning/info）。"""
    issues = [
        {"code": i.code, "severity": i.severity, "message": i.message,
         "day": None if i.day_index is None else i.day_index + 1, "place_id": i.place_id}
        for i in validate(_load())
    ]
    return {"ok": not any(i["severity"] in ("error", "warning") for i in issues), "issues": issues}


def suggest_lodging() -> dict[str, Any]:
    """推荐住宿区域，并把候选住宿按通勤排序（时间为估算值）。"""
    trip = _load()
    area = suggest_stay_area(trip)
    return {
        "stay_area": None if area is None else {
            "lat": round(area.lat, 5), "lon": round(area.lon, 5), "radius_km": area.radius_km,
            "avg_minutes_to_places": area.avg_minutes_to_places,
        },
        "ranked_lodgings": [
            {"id": r.lodging.id, "name": r.lodging.name, "avg_commute_min": r.avg_commute_min,
             "worst_commute_min": r.worst_commute_min, "price_per_night_mid": r.price_mid}
            for r in rank_lodgings(trip)
        ],
        "chosen_lodging_id": trip.chosen_lodging_id,
    }


def propose_change(summary: str, ops: list[dict[str, Any]], rationale: str = "") -> dict[str, Any]:
    """生成修改提案（不会真正修改行程）。ops 是操作列表，每项形如：
    {"kind":"move","place_id":"p1","to_day":1,"to_position":0}  （to_day 从 0 开始；to_position 可省）
    {"kind":"remove","place_id":"p2"}
    {"kind":"set_status","place_id":"p3","status":"excluded"}  （idea/shortlist/planned/confirmed/excluded）
    {"kind":"lock","place_id":"p1","locked":true}
    返回提案 id 和“改前→改后”说明；用户确认后再调用 apply_proposal。"""
    trip = _load()
    try:
        parsed = [_OP_ADAPTER.validate_python(o) for o in ops]
    except ValidationError as e:
        raise ToolError(f"操作格式不对：{e}")
    if not parsed:
        raise ToolError("ops 不能为空。")
    try:
        lines = describe_ops(trip, make_proposal(trip, summary, parsed))
    except KeyError as e:
        raise ToolError(str(e))
    proposal = make_proposal(trip, summary, parsed, rationale=rationale, created_by="agent")
    store = _load_proposals()
    store[proposal.id] = proposal.model_dump(mode="json")
    _save_proposals(store)
    return {"proposal_id": proposal.id, "summary": summary, "changes": lines,
            "base_revision": proposal.base_revision,
            "next": "请把 changes 展示给用户，用户明确同意后再调用 apply_proposal。"}


def apply_proposal(proposal_id: str) -> str:
    """套用已确认的提案。只有用户明确同意后才能调用。过期、被锁定或不合法时会报错且不改动行程。"""
    store = _load_proposals()
    if proposal_id not in store:
        raise ToolError(f"找不到提案 {proposal_id}（可能已套用或已被清除）。")
    proposal = Proposal.model_validate(store[proposal_id])
    trip = _load()
    try:
        new = _apply_proposal(trip, proposal)
    except StaleProposalError as e:
        raise ToolError(str(e))
    except (LockedItemError, InvalidOperationError, KeyError) as e:
        raise ToolError(f"提案无法套用：{e}")
    _save(new)
    _save_proposals({})  # 版本变了，其余提案都已过期
    return f"已套用提案「{proposal.summary}」，当前版本 {new.revision}。\n" + _render(new)


def undo() -> str:
    """撤销最近一次修改（可连续撤销）。"""
    trip = _load()
    try:
        new = _undo(trip)
    except NothingToUndo as e:
        raise ToolError(str(e))
    _save(new)
    _save_proposals({})
    return f"已撤销，当前版本 {new.revision}。\n" + _render(new)


def show_trip() -> str:
    """查看当前行程：每天的景点、交通估算、未安排项、粗略费用。"""
    return _render(_load())


# ---------------------------------------------------------------------------
# 文字渲染
# ---------------------------------------------------------------------------

def _render(trip: Trip) -> str:
    m = trip.meta
    out = [f"【{m.name}】{m.num_days} 天，节奏 {m.pace.value}，交通偏好 {_MODE_NAMES[m.mode]}，版本 {trip.revision}"]
    if trip.chosen_lodging:
        out.append(f"住宿：{trip.chosen_lodging.name}")
    if trip.plan is None:
        if trip.places:
            out.append("还没有分天。景点：" + "、".join(f"{p.name}({p.id})" for p in trip.places))
        else:
            out.append("还没有景点。")
        return "\n".join(out)
    for day in trip.plan.days:
        st = day_stats(trip, day)
        d = trip.day_date(day.index)
        date_txt = f" {d.isoformat()}（{_WEEKDAYS[d.weekday()]}）" if d else ""
        out.append(f"第{day.index + 1}天{date_txt}：游览 {st.visit_min} 分钟 + 交通约 {st.travel_min} 分钟")
        if not st.places:
            out.append("  （空）")
            continue
        for i, p in enumerate(st.places):
            lock = " 🔒" if day.items[i].locked else ""
            out.append(f"  {i + 1}. {p.name}({p.id}) {p.duration_min}分钟{lock}")
            if i < len(st.legs):
                leg = st.legs[i]
                out.append(f"     ↓ 约 {leg.minutes} 分钟（{_MODE_NAMES[leg.mode]}，{leg.distance_km} km，估算）")
    if trip.plan.unscheduled:
        out.append("未安排：" + "；".join(f"{trip.place(u.place_id).name}：{u.reason}" for u in trip.plan.unscheduled))
    c = estimate_cost(trip)
    out.append(f"粗略费用（仅门票+住宿）：{c.total:.0f} {m.currency}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# MCP 注册
# ---------------------------------------------------------------------------

TOOLS = [
    new_trip, add_place, add_lodging, lookup_coords, schedule_days, check_plan,
    suggest_lodging, propose_change, apply_proposal, undo, show_trip,
]


def build_server():
    """创建 MCP 服务对象。工具出错时抛出的 ToolError 会以文字形式返回给模型。"""
    import functools

    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("tripcore")

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*a, **kw):
            try:
                return fn(*a, **kw)
            except ToolError as e:
                raise ValueError(str(e)) from None
        return inner

    for fn in TOOLS:
        mcp.tool(name=fn.__name__)(wrap(fn))
    return mcp


def main() -> None:
    build_server().run()  # 默认 stdio


if __name__ == "__main__":
    main()
