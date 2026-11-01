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
import re
import os
import secrets
from datetime import date
from pathlib import Path
from typing import Any, Optional

from pydantic import TypeAdapter, ValidationError

from .amap import ROUTE_VERSION, AmapClient, AmapError
from .openmeteo import OpenMeteoClient, WeatherError
from .weather import bad_weather, fmt_snap, weather_spots
from .candidates import pick_hit as _pick_hit, similar_name as _similar_name, validate_items as _validate_items
from .geo import estimate_leg, haversine_km
from .hours import hours_for_date
from .geocode import GeocodeError, geocode as _geocode
from .gpx import build_gpx
from .mapview import build_map_data, build_map_html, day_marker_links, marker_link
from . import importplan as _importplan
from . import links as _links
from . import share as _share
from . import travelogue as _tl
from . import photos as _ph
from .lodging import day_trips, suggest_stay_segments, rank_lodgings, suggest_stay_area
from .metrics import day_budgets, day_stats, estimate_cost, leg_key, leg_mode
from .connections import day_window, is_night, leave_by, ready_time, terminal_depart_time, terminal_point, transfer_minutes, transfer_target
from . import prefs as _prefs
from . import workspace as _ws
from .gmaps import GoogleMapsClient
from .region import BACKENDS, pick_backend, trip_region
from . import review as _rv
from .dates import apply_dates as _apply_dates
from .textview import build_text as _build_text, guard_text as _guard_text
from .checklist import build_checklist as _build_checklist, render as _render_checklist
from .metrics import intercity_hint
from .stays import hint_text as _stay_hint
from .models import Stay, Connection, DateMode, Leg, Lodging, Meal, Pace, Place, Trip, TripMeta, Waypoint, WeatherSnap
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
from .routeplace import entry, exit_
from .scheduler import RELAXED_COMFORT, schedule
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

def _single_file_mode() -> bool:
    """设了 TRIPCORE_FILE 就是单文件模式（测试、演示用）：只有这一个行程，不做多行程管理。"""
    return bool(os.environ.get("TRIPCORE_FILE"))


def _root_dir() -> Path:
    """共用文件（偏好、高德调用日志）所在目录；多行程模式下各行程在 <根>/trips/<名字>/。"""
    p = os.environ.get("TRIPCORE_FILE")
    return Path(p).expanduser().parent if p else Path.home() / ".tripcore"


def export_root() -> Path:
    """所有导出（手册、Obsidian、日历、粗剪）统一放的文件夹：环境变量 TRIPCORE_EXPORT_DIR；
    否则 ~/Documents/TripSight（好找）；测试里用 TRIPCORE_FILE 时放在它旁边的 exports。"""
    e = os.environ.get("TRIPCORE_EXPORT_DIR")
    if e:
        return Path(e).expanduser()
    try:
        c = _export_dir_file().read_text(encoding="utf-8").strip()
    except OSError:
        c = ""
    if c:
        return Path(c).expanduser()
    if os.environ.get("TRIPCORE_FILE"):
        return trip_path().with_name("exports")
    return Path.home() / "Documents" / "TripSight"


def _export_dir_file() -> Path:
    return _root_dir() / "export_dir.txt"


def set_export_dir(path: str) -> str:
    """用户自己选的导出文件夹（工作台里“选择文件夹”）；空串 = 恢复默认。返回生效的路径。"""
    path = (path or "").strip()
    f = _export_dir_file()
    if not path:
        try:
            f.unlink()
        except OSError:
            try:
                f.write_text("", encoding="utf-8")
            except OSError:
                pass
        return str(export_root())
    d = Path(path).expanduser()
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".tripsight-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        raise ToolError(f"这个文件夹写不进去：{e}")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(str(d.resolve()), encoding="utf-8")
    return str(export_root())


def trip_path() -> Path:
    p = os.environ.get("TRIPCORE_FILE")
    if p:
        return Path(p).expanduser()
    root = _root_dir()
    _ws.migrate_legacy(root)                      # 旧版放在根目录的行程：第一次使用时复制进 trips/
    slug = _ws.active_slug(root)
    return _ws.trips_dir(root) / (slug or "_none") / "trip.json"


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


def _context_path() -> Path:
    return trip_path().with_name("context.json")


def _prefs_path() -> Path:
    return _root_dir() / "preferences.json"


def _load_context() -> dict:
    p = _context_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save_context(data: dict) -> None:
    p = _context_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


_BACKEND = {"name": "高德", "note": ""}


def _amap() -> Any:
    """选地图后端：行程指定的（set_provider）> 国内高德 / 境外 Google；缺 key 时用另一个并提醒。
    没有任何 key 返回 None。测试里会替换这个函数。"""
    log = _root_dir() / "amap_calls.log"
    a, g = AmapClient.from_env(log_path=log), GoogleMapsClient.from_env(log_path=log)
    trip = None
    try:
        if trip_path().exists():
            trip = load_trip(trip_path())
    except Exception:
        trip = None
    backend, note = pick_backend(trip.meta.map_provider if trip else None, trip_region(trip) if trip else "cn",
                                 a is not None, g is not None)
    client = a if backend == "amap" else g if backend == "google" else None
    _BACKEND["name"] = "Google" if backend == "google" else "高德"
    _BACKEND["note"] = note
    return client


def _is_google(client: Any) -> bool:
    return getattr(client, "provider", "amap") == "google"


def _bn(client: Any = None) -> str:
    return "Google" if (_is_google(client) if client is not None else _BACKEND["name"] == "Google") else "高德"


_NO_KEY = "没有可用的地图 key（国内行程配 AMAP_KEY，境外行程配 GOOGLE_MAPS_KEY）"


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
    pace: Optional[str] = None,
    mode: str = "transit",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    earliest_start: Optional[str] = None,
    latest_end: Optional[str] = None,
    budget_total: Optional[float] = None,
    city: Optional[str] = None,
    travelers: int = 1,
) -> str:
    """创建一个新行程并切换到它（原来的行程不会被覆盖，仍可用 list_trips 查看、switch_trip 切回；
    单文件模式 TRIPCORE_FILE 下才会覆盖）。创建前如果已有进行中的行程，先问用户是新建还是继续。travelers 是出行人数（用户没说就先问）。city 是目的地城市（如“哈尔滨”），之后查坐标会限定在这个城市附近。
    日期可不填；填 start_date+end_date 为确定日期，填 earliest_start+latest_end 为大致范围。
    pace 不填时，用用户之前说过的长期偏好（没有就是 normal）；用户长期偏好里的步行/地铁/换乘/打车设置也会自动套用到新行程，
    返回文字里会列出套用了什么。用户这次明确说的永远优先。"""
    saved = _prefs.merged_values(_prefs.load(_prefs_path()))
    applied: list[str] = []
    if pace is None:
        pace = saved.get("pace", "normal")
        if "pace" in saved:
            applied.append(f"节奏 {pace}")
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
            earliest_start=es, latest_end=le, budget_total=budget_total, travelers=travelers,
        )
    except (ValidationError, ValueError) as e:
        raise ToolError(f"参数不合法：{e}")
    if meta.num_days > 30:
        raise ToolError("行程最多 30 天。")
    tp = {k: saved[k] for k in _prefs.TRANSPORT_KEYS if k in saved}
    if tp:
        meta.transport_prefs = meta.transport_prefs.model_validate({**meta.transport_prefs.model_dump(), **tp})
        applied += [f"{k}={v}" for k, v in tp.items()]
    others = 0
    if not _single_file_mode():
        root = _root_dir()
        _ws.migrate_legacy(root)
        others = len(_ws.list_trips(root))
        slug = _ws.unique_slug(root, _ws.slugify(name))
        (_ws.trips_dir(root) / slug).mkdir(parents=True, exist_ok=True)
        _ws.set_active(root, slug)
    trip = Trip(meta=meta)
    _save(trip)
    _save_proposals({})
    _save_context({"city": city} if city else {})
    try:
        _food_path().write_text("{}", encoding="utf-8")      # 旧行程的候选餐厅作废
    except OSError:
        pass
    msg = f"已创建行程「{meta.name}」，共 {meta.num_days} 天，节奏 {meta.pace.value}，交通偏好 {_MODE_NAMES[meta.mode]}。"
    if others:
        msg += f"\n已切换到这个新行程；之前的 {others} 个行程都还在（list_trips 查看，switch_trip 切回）。"
    allp = _prefs.load(_prefs_path())
    if applied:
        msg += "\n按你之前的长期偏好套用了：" + "、".join(applied) + "（可随时改）。"
    if allp:
        msg += "\n已记住的长期偏好：" + _prefs.describe(allp)
    return msg


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
    source: str = "agent",
    verified: bool = False,
    opening_hours: str = "",
    hours_source: str = "",
    backups: Optional[list[str]] = None,
    category: str = "",
    outdoor: Optional[bool] = None,
) -> str:
    """添加一个景点。lat/lon 必须来自 lookup_coords 或用户，绝不能自己编。
    ticket_price（元）、duration_min、closed_weekdays 如果没有可靠来源，请保持默认（门票填 0），
    不要凭印象编数字；verified=False 时会在备注里标“待核实”，用户确认过的数据才传 verified=True。
    closed_weekdays：闭馆的星期，0=周一 … 6=周日。
    opening_hours：营业时间原文，必须同时写 hours_source（amap，或网页网址，或 user），没有来源就留空。
    backups：备选景点的 id 列表（需要预约、可能约不上时设置）。
    category：高德返回的类别文字（如“风景名胜;公园广场”），用来判断室内外，没有就留空；
    outdoor：明确知道室内(false)/户外(true)时才传，优先于类别推断；不确定就不传（未知的不会触发天气提醒）。"""
    trip = _load()
    for b in backups or []:
        if all(p.id != b for p in trip.places):
            raise ToolError(f"备选景点 {b} 不存在，请先添加或确认 id。")
    if opening_hours and not hours_source:
        raise ToolError("填营业时间必须同时填来源 hours_source（amap / 网址 / user）。")
    if not verified:
        notes = (notes + " " if notes else "") + "[门票/时长/闭馆日待核实]"
    pid = _next_id("p", [p.id for p in trip.places])
    try:
        place = Place(
            id=pid, name=name, lat=lat, lon=lon, duration_min=duration_min,
            priority=priority, must_go=must_go, ticket_price=ticket_price,
            closed_weekdays=closed_weekdays or [], reservation_required=reservation_required,
            notes=notes, source=source, opening_hours=opening_hours, hours_source=hours_source,
            backups=backups or [], category=category, outdoor=outdoor,
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
    price_source: str = "manual",
    price_date: Optional[str] = None,
) -> str:
    """添加候选住宿（价格为每晚，元）。choose=True 则同时设为本次选定的住宿。
    price_source 说明价格从哪来：manual（用户手填）/ rollinggo（参考价）/ amap（高德人均参考）；
    price_date 是查询日期或对应的入住日期。价格没有来源时不要填，留 0。"""
    if price_min or price_max:
        tag = f"[价格来源:{price_source}" + (f" {price_date}" if price_date else "") + "]"
        notes = (notes + " " if notes else "") + tag
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
    over = ""
    cap = _prefs.merged_values(_prefs.load(_prefs_path())).get("lodging_budget_max")
    if cap and price_max and price_max > cap:
        over = f" ⚠ 价格上限 {price_max:g} 超过你记下的住宿预算 {cap:g} 元/晚。"
    return f"已添加住宿「{name}」(id={lid})" + ("，并设为选定住宿。" if choose else "。") + over


def lookup_coords(query: str, city: Optional[str] = None) -> dict[str, Any]:
    """查询地点坐标，返回候选列表 candidates（第一条也展开在顶层字段里）。
    有地图 key 时用高德（国内）或 Google（境外，见 set_provider）（限定在行程城市内，附带地址、评分、人均/参考价格 cost、今日营业时间）；
    没有 key、不在国内或高德查不到时退回 OpenStreetMap。city 不填则用行程的目的地城市。
    候选不止一个且名称相近时，请把候选展示给用户确认，不要自己挑。坐标不能自己改。
    OSM 结果会检查离城市中心的距离：超过 60 km 时 warning 非空，说明可能查到了别处的同名地点。"""
    city = city or _load_context().get("city")
    amap_note = ""
    client = _amap()
    if client is not None:
        try:
            hits = client.search_places(query, city, limit=5)
        except AmapError as e:
            hits, amap_note = [], f"{_bn(client)}不可用（{e}），已退回 OpenStreetMap"
        else:
            if not hits:
                amap_note = f"{_bn(client)}没有找到，已退回 OpenStreetMap"
        if hits:
            cands = [{
                "name": h.name, "lat": round(h.lat, 6), "lon": round(h.lon, 6), "address": h.address,
                "district": h.district, "category": h.category, "rating": h.rating,
                "cost_reference": h.cost, "opentime_today": h.opentime_today,
                "opentime_week": h.opentime_week,
            } for h in hits]
            top = cands[0]
            return {"found": True, "source": "google" if _is_google(client) else "amap", "name": top["name"], "lat": top["lat"], "lon": top["lon"],
                    "display_name": f"{top['name']} {top['address']}".strip(), "warning": "",
                    "candidates": cands,
                    "note": f"cost_reference 是{_bn(client)}的人均/参考价，不是实时价格，也不一定是门票。"
                            + (f"注意：{_BACKEND['note']}。" if _BACKEND["note"] else "")}
    try:
        r = _geocode(query, city)
    except GeocodeError as e:
        return {"found": False, "source": "osm", "error": str(e), "note": amap_note}
    out: dict[str, Any] = {"found": True, "source": "osm", "name": r["name"], "lat": r["lat"], "lon": r["lon"],
                           "display_name": r["display_name"], "warning": "", "note": amap_note}
    if city:
        try:
            c = _geocode(city)
            d = haversine_km(r["lat"], r["lon"], c["lat"], c["lon"])
            out["distance_from_city_km"] = round(d, 1)
            if d > 60:
                out["warning"] = f"离“{city}”约 {d:.0f} km，可能查到了别处的同名地点；请换更具体的关键词，或向用户确认。"
        except GeocodeError:
            pass
    return out


def update_place(
    place_id: str,
    name: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    duration_min: Optional[int] = None,
    priority: Optional[int] = None,
    must_go: Optional[bool] = None,
    ticket_price: Optional[float] = None,
    closed_weekdays: Optional[list[int]] = None,
    reservation_required: Optional[bool] = None,
    notes: Optional[str] = None,
    opening_hours: Optional[str] = None,
    hours_source: Optional[str] = None,
    backups: Optional[list[str]] = None,
    category: Optional[str] = None,
    outdoor: Optional[bool] = None,
) -> str:
    """修改景点的资料（只改传入的字段）。这不改变它在行程里的位置；改完后请再 schedule_days。
    坐标/价格必须来自工具或用户。"""
    trip = _load()
    try:
        trip.place(place_id)
    except KeyError as e:
        raise ToolError(str(e))
    changes = {k: v for k, v in dict(
        name=name, lat=lat, lon=lon, duration_min=duration_min, priority=priority, must_go=must_go,
        ticket_price=ticket_price, closed_weekdays=closed_weekdays,
        reservation_required=reservation_required, notes=notes, opening_hours=opening_hours,
        hours_source=hours_source, backups=backups, category=category, outdoor=outdoor).items() if v is not None}
    if not changes:
        raise ToolError("没有传入要修改的字段。")
    for b in changes.get("backups", []):
        if b == place_id or all(p.id != b for p in trip.places):
            raise ToolError(f"备选景点 {b} 不存在或就是它自己。")
    if changes.get("opening_hours") and not (changes.get("hours_source") or trip.place(place_id).hours_source):
        raise ToolError("填营业时间必须同时填来源 hours_source（amap / 网址 / user）。")

    def mutate(t: Trip) -> None:
        old = t.place(place_id)
        new = Place.model_validate({**old.model_dump(), **changes})
        t.places[t.places.index(old)] = new

    try:
        new_trip_ = commit(trip, mutate)
    except ValidationError as e:
        raise ToolError(f"参数不合法：{e}")
    _save(new_trip_)
    return f"已更新景点 {place_id}：" + "、".join(changes) + "。"


def remove_place(place_id: str) -> str:
    """彻底删除一个景点（同时从行程里移出）。只是不想去了/暂时不去，优先用 propose_change 的 set_status=excluded。
    已锁定的景点不能删除。"""
    trip = _load()
    try:
        place = trip.place(place_id)
    except KeyError as e:
        raise ToolError(str(e))
    if trip.plan:
        for d in trip.plan.days:
            for it in d.items:
                if it.place_id == place_id and it.locked:
                    raise ToolError(f"「{place.name}」已锁定，不能删除。")

    def mutate(t: Trip) -> None:
        t.places = [p for p in t.places if p.id != place_id]
        for p in t.places:
            p.backups = [b for b in p.backups if b != place_id]
        if t.plan:
            for d in t.plan.days:
                d.items = [it for it in d.items if it.place_id != place_id]
            t.plan.unscheduled = [u for u in t.plan.unscheduled if u.place_id != place_id]

    _save(commit(trip, mutate))
    return f"已删除景点「{place.name}」({place_id})。"


MAX_ROUTE_REQUESTS = 25   # 单次最多请求次数，避免超过工具超时；没做完的下次再调用


def _transit_kwargs(prefs: Any) -> dict[str, Any]:
    """把用户的换乘/地铁偏好传给高德路线查询；没设置偏好时不传，沿用高德默认方案。"""
    kw: dict[str, Any] = {}
    if prefs.max_transfers is not None:
        kw["max_transfers"] = prefs.max_transfers
    if prefs.prefer_subway:
        kw["prefer_subway"] = True
    return kw


def _route_note(r: Any, prefs: Any = None) -> str:
    """路线说明：公交写线路、换乘、步行距离、票价；步行超过用户设的上限时提示；其余为空。"""
    if r.mode != "transit" or not getattr(r, "lines", None):
        return ""
    bits = ["→".join(r.lines), f"换乘{r.transfers}次" if r.transfers is not None else ""]
    if r.walking_km is not None:
        bits.append(f"步行{r.walking_km:g}km")
    if r.cost_yuan is not None:
        bits.append(f"票价{r.cost_yuan:g}元")
    if getattr(r, "warning", ""):
        bits.append("⚠ " + r.warning)
    mw = getattr(r, "max_walk_km", None)
    if prefs is not None and mw is not None:
        limit_km = prefs.walk_max_min / 60 * 5          # 按步行约 5 km/h 折算
        if mw > limit_km * 1.2:
            bits.append(f"⚠ 其中一段要连续步行约 {mw:g} km，超过你设的单段步行上限（{prefs.walk_max_min} 分钟）"
                        + ("；你接受打车，可以考虑改成打车" if getattr(prefs, "taxi_ok", False) else ""))
    return "，".join(b for b in bits if b)


def refine_routes(day: Optional[int] = None) -> str:
    """把已排好的行程里“估算”的交通时间升级为高德的真实路线时间（需要 AMAP_KEY）。
    day 是第几天（从 1 开始），不填则处理所有天。结果会缓存，重复调用只补没查过的路段。
    出行方式沿用行程设置；两点很近时自动按步行。"""
    client = _amap()
    if client is None:
        raise ToolError(f"{_NO_KEY}，无法查询真实路线。")
    trip = _load()
    if trip.plan is None:
        raise ToolError("还没有分天，请先 schedule_days。")
    if day is not None and not (1 <= day <= len(trip.plan.days)):
        raise ToolError(f"没有第 {day} 天（共 {len(trip.plan.days)} 天）")
    city = _load_context().get("city")

    wanted: list[tuple[Any, Any]] = []   # (起点对象, 终点对象)，对象有 id/lat/lon
    for d in trip.plan.days:
        if day is not None and d.index != day - 1:
            continue
        stops = [trip.place(it.place_id) for it in d.items]
        wanted += [(exit_(a), entry(b)) for a, b in zip(stops, stops[1:])]
        lod_m, lod_n = trip.morning_lodging(d.index), trip.lodging_for_day(d.index)
        if lod_m and lod_n and stops:
            wanted += [(lod_m, entry(stops[0])), (exit_(stops[-1]), lod_n)]
    for which in ("arrival", "departure"):
        tp, tg = terminal_point(trip, which), transfer_target(trip, which)
        if tp is not None and tg is not None:
            wanted.append((tp, tg) if which == "arrival" else (tg, tp))

    new_legs: dict[str, Leg] = {}
    failures: list[str] = []
    requested = skipped = 0
    all_keys: set[str] = set()
    for a, b in wanted:
        mode = leg_mode(trip, a.id, b.id)
        key = leg_key(a.id, a.lat, a.lon, b.id, b.lat, b.lon, mode)
        all_keys.add(key)
        cached = trip.route_overrides.get(key)
        when = terminal_depart_time(trip, "arrival") if a.id == "arrival" else (
            terminal_depart_time(trip, "departure") if b.id == "departure" else None)
        stamp = f"{when:%Y-%m-%d %H}" if when is not None else ""
        if (cached is not None and cached.path_checked and cached.depart_at == stamp and cached.route_ver >= ROUTE_VERSION) or key in new_legs:
            skipped += 1
            continue
        if requested >= MAX_ROUTE_REQUESTS:
            continue
        requested += 1
        if f"{a.id}>{b.id}" in trip.leg_modes:
            req_mode = mode          # 用户明确指定的方式，严格照办，不因距离近而改成步行
        else:
            req_mode = estimate_leg(a.id, a.lat, a.lon, b.id, b.lat, b.lon, mode).mode   # 默认段：很近就按步行
        try:
            pr = trip.meta.transport_prefs
            kw = _transit_kwargs(pr) if req_mode == "transit" else {}
            night_note = ""
            if when is not None and req_mode == "transit":
                if is_night(when) and pr.taxi_ok and f"{a.id}>{b.id}" not in trip.leg_modes:
                    req_mode, night_note = "drive", f"{when:%H:%M} 出发属深夜（约 23:00–05:30），公共交通多已停运，按打车计算"
                else:
                    kw["depart"] = when
            r = client.route(req_mode, a.lat, a.lon, b.lat, b.lon, city, **kw)
        except AmapError as e:
            failures.append(f"{a.name} → {b.name}：{e}")
            continue
        new_legs[key] = Leg(from_id=a.id, to_id=b.id, mode=r.mode, distance_km=r.distance_km,  # type: ignore[arg-type]
                            minutes=r.minutes, detail_level="route", path=[list(pt) for pt in r.path],
                            path_checked=True, depart_at=stamp, route_ver=ROUTE_VERSION,
                            note="；".join(x for x in (_route_note(r, pr), night_note, intercity_hint(r.distance_km, r.mode)) if x))

    if new_legs:
        _save(commit(trip, lambda t: t.route_overrides.update(new_legs)))
    todo = len([k for k in all_keys if k not in new_legs and not (k in trip.route_overrides and trip.route_overrides[k].path_checked and trip.route_overrides[k].route_ver >= ROUTE_VERSION)]) - len(failures)
    msg = f"已更新 {len(new_legs)} 段为{_bn(client)}真实路线，{skipped} 段此前已查过。"
    if _BACKEND["note"]:
        msg += f"\n注意：{_BACKEND['note']}。"
    if failures:
        msg += "\n失败：" + "；".join(failures[:5]) + "（这些路段仍用估算值）"
    if todo > 0 and requested >= MAX_ROUTE_REQUESTS:
        msg += f"\n还有部分路段没查，请再调用一次 refine_routes。"
    return msg + "\n" + _render(_load())


MAX_HOURS_LOOKUPS = 20


def fill_hours() -> str:
    """给还没有营业时间的景点，从高德自动补上营业时间（来源记为 amap，需要 AMAP_KEY）。
    只在高德结果的名字相符且位置很近（1.5 km 内）时才采用；匹配不上的保持“待核实”，已有营业时间的不覆盖。
    补不上的，才去联网搜索（必须附来源网址）或请用户确认，不要凭记忆填写。"""
    client = _amap()
    if client is None:
        raise ToolError(f"{_NO_KEY}，无法查询营业时间。")
    trip = _load()
    city = _load_context().get("city")
    filled: dict[str, str] = {}
    missed: list[str] = []
    asked = 0
    for p in trip.places:
        if p.opening_hours or p.waypoints:
            continue
        if asked >= MAX_HOURS_LOOKUPS:
            missed.append(f"{p.name}（本次查询已达上限，请再调用一次）")
            continue
        asked += 1
        try:
            hits = client.search_places(p.name, city, limit=5)
        except AmapError as e:
            missed.append(f"{p.name}（查询失败：{e}）")
            continue
        best = None
        for h in hits:
            if (p.name in h.name or h.name in p.name) and haversine_km(p.lat, p.lon, h.lat, h.lon) <= 1.5 \
                    and (h.opentime_week or h.opentime_today):
                best = h
                break
        if best is None:
            missed.append(f"{p.name}（{_bn(client)}没有匹配的营业时间）")
            continue
        filled[p.id] = best.opentime_week or best.opentime_today
    if filled:
        def mutate(t: Trip) -> None:
            for pid, text in filled.items():
                old = t.place(pid)
                t.places[t.places.index(old)] = Place.model_validate(
                    {**old.model_dump(), "opening_hours": text, "hours_source": "google" if _is_google(client) else "amap"})
        _save(commit(trip, mutate))
    msg = f"已补充 {len(filled)} 个景点的营业时间（来源 amap）。"
    if missed:
        msg += "\n仍待核实：" + "；".join(missed)
    if filled:
        bad = [i.message for i in validate(_load()) if i.place_id in filled and i.severity in ("error", "warning")
               and i.code in ("OUTSIDE_HOURS", "ARRIVE_BEFORE_OPEN", "LEAVE_AFTER_CLOSE")]
        if bad:
            msg += ("\n⚠ 补上营业时间后，现有行程有 " + str(len(bad)) + " 处对不上（这些景点是在没有营业时间时排的）：\n"
                    + "\n".join("· " + b for b in bad)
                    + "\n请如实告诉用户；征得同意后再 schedule_days 重排（已锁定的不会动）。")
    return msg + ("\n" + _render(_load()) if trip.plan else "")


def _food_path() -> Path:
    return trip_path().with_name("food_candidates.json")


def suggest_food(day: int, after_place_id: str, radius_m: int = 800, keyword: str = "") -> dict[str, Any]:
    """在某天某个景点附近搜候选餐厅（高德，需要 AMAP_KEY），返回名称、评分、人均参考、营业时间、距离。
    day 是第几天（从 1 开始）；radius_m 搜索半径（米，默认 800）；keyword 可选，如“面食”“清真”。
    这只是候选，不会改行程。请把候选展示给用户，由用户选定后再调用 choose_food(candidate_id)。
    评分和人均是高德的参考值，不是实时价格，不要说成准确价格。"""
    client = _amap()
    if client is None:
        raise ToolError(f"{_NO_KEY}，无法搜索餐厅。")
    trip = _load()
    if trip.plan is None:
        raise ToolError("还没有分天，请先 schedule_days。")
    if not (1 <= day <= len(trip.plan.days)):
        raise ToolError(f"没有第 {day} 天（共 {len(trip.plan.days)} 天）")
    try:
        pl = trip.place(after_place_id)
    except KeyError as e:
        raise ToolError(str(e))
    try:
        hits = client.search_around(pl.lat, pl.lon, radius_m=radius_m, keywords=keyword, limit=25)
    except AmapError as e:
        raise ToolError(f"搜索餐厅失败：{e}")
    cands = []
    for h in hits:
        dist = int(haversine_km(pl.lat, pl.lon, h.lat, h.lon) * 1000)
        if dist > radius_m * 1.2:
            continue
        cands.append({"name": h.name, "address": h.address, "lat": h.lat, "lon": h.lon, "rating": h.rating,
                      "cost_per_person": h.cost, "opening_hours": h.opentime_week or h.opentime_today,
                      "distance_m": dist, "amap_id": h.amap_id if h.source == "amap" else "", "source": h.source})
    cands.sort(key=lambda c: (-(c["rating"] or 0), c["distance_m"]))
    cands = cands[:8]
    stored = {}
    for i, c in enumerate(cands, 1):
        c["candidate_id"] = f"f{i}"
        stored[c["candidate_id"]] = {**c, "day": day - 1, "after_place_id": after_place_id}
    fp = _food_path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    shown = [{k: c[k] for k in ("candidate_id", "name", "address", "rating", "cost_per_person", "opening_hours", "distance_m")}
             for c in cands]
    res = {"place": pl.name, "day": day, "radius_m": radius_m, "candidates": shown,
           "note": f"评分/人均为{_bn(client)}参考值；营业时间为空表示{_bn(client)}无数据，需核实。请用户选择后调用 choose_food。"}
    fp_ = [x for x in _prefs.load(_prefs_path()) if x["category"] == "food"]
    if fp_:
        res["user_food_preferences"] = _prefs.describe(fp_)      # 只是提示，不自动过滤；请对照候选向用户说明
    return res


def find_food(name: str) -> dict[str, Any]:
    """用户自己想吃的店：按店名在高德搜索（限定目的地城市），并按已排好的行程，用代码算出离哪一天哪个景点最近，
    作为建议的安排位置 suggested。这只是候选，不改行程；请把候选和建议位置展示给用户确认，
    再调用 choose_food(candidate_id)（想换位置就传 day / after_place_id）。需要 AMAP_KEY。"""
    client = _amap()
    if client is None:
        raise ToolError(f"{_NO_KEY}，无法搜索餐厅。")
    trip = _load()
    city = _load_context().get("city")
    try:
        hits = client.search_places(name, city, limit=5)
    except AmapError as e:
        raise ToolError(f"搜索失败：{e}")
    stops = []
    if trip.plan:
        for d in trip.plan.days:
            for it in d.items:
                stops.append((d.index, trip.place(it.place_id)))
    stored, shown = {}, []
    for i, h in enumerate(hits, 1):
        cid = f"f{i}"
        entry = {"candidate_id": cid, "name": h.name, "address": h.address, "lat": h.lat, "lon": h.lon,
                 "rating": h.rating, "cost_per_person": h.cost,
                 "opening_hours": h.opentime_week or h.opentime_today, "amap_id": h.amap_id if h.source == "amap" else "", "source": h.source}
        sug = None
        if stops:
            di, pl = min(stops, key=lambda x: haversine_km(x[1].lat, x[1].lon, h.lat, h.lon))
            dist = int(haversine_km(pl.lat, pl.lon, h.lat, h.lon) * 1000)
            sug = {"day": di + 1, "after_place_id": pl.id, "after_place": pl.name, "distance_m": dist}
            if dist > 3000:
                sug["warning"] = "离所有景点都超过 3 公里，需要单独安排交通，请和用户确认是否真的要排。"
            entry.update(day=di, after_place_id=pl.id, distance_m=dist)
        stored[cid] = entry
        shown.append({**{k: entry[k] for k in ("candidate_id", "name", "address", "rating", "cost_per_person", "opening_hours")},
                      "suggested": sug})
    fp = _food_path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    note = "请用户确认是不是想去的那家店。" if hits else "高德没有找到这家店，请换个说法，或请用户提供地址。"
    if not stops:
        note += " 还没有分天，无法建议位置，请先 schedule_days。"
    return {"query": name, "candidates": shown, "note": note}


def choose_food(candidate_id: str, day: Optional[int] = None, after_place_id: Optional[str] = None) -> str:
    """把用户选定的候选餐厅记为用餐点（候选来自最近一次 suggest_food / find_food）。
    默认用候选里的建议位置；用户想换到别的天或别的景点后面，传 day（第几天，从 1 开始）和 after_place_id。
    只能在用户明确选定后调用；用餐点不占景点容量，可用 undo 撤销。"""
    fp = _food_path()
    try:
        stored = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else {}
    except (OSError, ValueError):
        stored = {}
    c = stored.get(candidate_id)
    if c is None:
        raise ToolError("没有这个候选，请先调用 suggest_food 或 find_food，并使用它返回的 candidate_id。")
    day0 = (day - 1) if day is not None else c.get("day")
    pid = after_place_id or c.get("after_place_id")
    if day0 is None or pid is None:
        raise ToolError("没有可用的安排位置，请先 schedule_days，或传入 day 和 after_place_id。")
    trip = _load()
    if trip.plan is None or not (0 <= day0 < len(trip.plan.days)):
        raise ToolError("day 超出行程天数。")
    try:
        pl = trip.place(pid)
    except KeyError as e:
        raise ToolError(str(e))
    placed_day = next((d.index for d in trip.plan.days if any(it.place_id == pid for it in d.items)), None)
    if placed_day is not None:
        day0 = placed_day                  # 用餐点跟着景点所在的那天
    if any(m.name == c["name"] and m.day == day0 for m in trip.meals):
        raise ToolError(f"「{c['name']}」已经在第 {day0 + 1} 天的用餐点里了。")
    dist = int(haversine_km(pl.lat, pl.lon, c["lat"], c["lon"]) * 1000)
    mid = _next_id("m", [m.id for m in trip.meals])
    meal = Meal(id=mid, day=day0, after_place_id=pid, name=c["name"], lat=c["lat"], lon=c["lon"],
                address=c.get("address") or "", cost_per_person=c.get("cost_per_person"), rating=c.get("rating"),
                opening_hours=c.get("opening_hours") or "", hours_source=c.get("source", "amap") if c.get("opening_hours") else "",
                distance_m=dist, amap_id=c.get("amap_id") or "")
    _save(commit(trip, lambda t: t.meals.append(meal)))
    extra = "（离该景点较远，注意交通）" if dist > 3000 else ""
    return f"已把「{meal.name}」记为第 {meal.day + 1} 天「{pl.name}」之后的用餐点（{meal.id}）{extra}。人均和评分是{_bn()}参考值。"


def export_map(share: bool = False) -> str:
    """生成地图页 HTML（景点按天分色并按顺序连线，另有住宿、用餐点；点标记可看营业时间等）。
    页面是单个自包含文件（地图脚本和行程数据都在里面，底图需要联网），手机上也是同样的页面（窄屏自动上下分栏）。
    share=False（默认）：写到 ~/.tripcore/map.html，让用户在电脑浏览器里打开。
    share=True：给手机/聊天用——写一个以行程名命名的文件（~/.tripcore/share/行程名.html），并先做外发检查
    （带 key、本机路径的内容不会输出）。在微信等聊天应用里，拿到路径后用 message 工具把这个文件作为附件（media）发给用户，
    并告诉他：收到后点开文件，选“用其他应用打开”→手机浏览器；这是发送那一刻的快照，行程改了要重新生成再发。
    需要先 schedule_days 才有行程线。"""
    trip = _load()
    base = trip_path().with_name("share") if share else trip_path().parent
    if share:
        import re as _re
        stem = _re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", trip.meta.name).strip("_") or "trip"
        path = base / f"{stem}.html"
    else:
        path = trip_path().with_name("map.html")
    try:
        html = build_map_html(trip)
        if share:
            bad = _guard_text(json.dumps(build_map_data(trip), ensure_ascii=False))
            if bad:
                raise ToolError("外发检查没通过，没有生成：" + "；".join(bad) + "。请检查景点名称/备注里是否混入了不该外发的内容。")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    except OSError as e:
        raise ToolError(f"写入地图文件失败：{e}")
    note = "" if trip.plan else "（还没有分天，地图上只有空白底图）"
    if share:
        return (f"手机版地图已生成：{path}{note}\n请用 message 工具把它作为附件发给用户，并说明：点开文件→“用其他应用打开”→手机浏览器；"
                "底图需要联网；这是此刻的快照，行程改了要重新生成再发。")
    return f"地图已生成：{path}{note}\n在浏览器里打开即可（macOS 可用 open 命令）；底图需要联网。"


MAX_POI_LOOKUPS = 25


_NAME_SUFFIXES = ("风景名胜区", "旅游风景区", "国家森林公园", "风景区", "旅游区", "景区", "名胜区", "博物馆")


def _norm_poi_name(s: str) -> str:
    import re
    s = re.sub(r"[（(].*?[）)]", "", s)                    # 去掉括号里的分店/备注
    s = re.sub(r"\s+", "", s)
    for suf in _NAME_SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf):
            s = s[: -len(suf)]
            break
    return s


def _poi_name_ok(name: str, hit_name: str) -> bool:
    if name in hit_name or hit_name in name:
        return True
    a, b = _norm_poi_name(name), _norm_poi_name(hit_name)
    return len(a) >= 2 and len(b) >= 2 and (a in b or b in a)


def _match_poi(client: Any, name: str, lat: float, lon: float, city: Optional[str], max_km: float = 1.5) -> Optional[str]:
    """按名称+距离在高德里找对应的 POI ID；名字不相符或太远就返回 None（宁缺毋滥）。
    先在行程城市里搜；找不到再不限城市搜（行程可能跨市，如西安+华阴），最后按坐标周边搜。"""
    def pick(hits: list) -> Optional[str]:
        best, best_d = None, 1e9
        for h in hits:
            if h.amap_id and _poi_name_ok(name, h.name):
                d = haversine_km(lat, lon, h.lat, h.lon)
                if d <= max_km and d < best_d:
                    best, best_d = h.amap_id, d
        return best

    for city_arg in ([city, None] if city else [None]):
        pid = pick(client.search_places(name, city_arg, limit=10))
        if pid:
            return pid
    around = getattr(client, "search_around", None)
    if around is not None:
        return pick(around(lat, lon, radius_m=int(max_km * 1000), types="", keywords=_norm_poi_name(name) or name, limit=10))
    return None


def personal_map_payload(day: Optional[int] = None) -> dict[str, Any]:
    """生成高德“专属地图”（maps_schema_personal_map）所需的参数：每天一条行程，从酒店出发经各景点回到酒店，
    用餐点挂在对应景点之后。景点名称、坐标（已转成高德坐标系）、POI ID 都由代码生成，需要 AMAP_KEY。
    POI ID 缺的会先按名称+距离到高德匹配，匹配不上的点会被跳过并列在 skipped 里。
    把返回的 arguments 原样（不要改动任何字段）传给 amap-maps 的 maps_schema_personal_map，
    再把它返回的链接给用户。day 从 1 开始，不填则所有天。"""
    client = _amap()
    if client is None or _is_google(client):
        raise ToolError("没有可用的高德 key（环境变量 AMAP_KEY），无法匹配高德 POI；高德专属地图只支持国内行程。")
    trip = _load()
    if trip.plan is None:
        raise ToolError("还没有分天，请先 schedule_days。")
    n = len(trip.plan.days)
    if day is not None and not (1 <= day <= n):
        raise ToolError(f"没有第 {day} 天（共 {n} 天）")
    city = _load_context().get("city")
    days = [d for d in trip.plan.days if (day is None or d.index == day - 1) and d.items]
    if not days:
        raise ToolError("没有可生成的行程。")
    # 1) 补 POI ID
    need: list[tuple[str, str, Any]] = []     # (种类, id, 对象)
    seen: set[tuple[str, str]] = set()
    for d in days:
        for it in d.items:
            pl = trip.place(it.place_id)
            if not pl.amap_id and ("p", pl.id) not in seen:
                seen.add(("p", pl.id)); need.append(("p", pl.id, pl))
        for m in trip.meals:
            if m.day == d.index and not m.amap_id and ("m", m.id) not in seen:
                seen.add(("m", m.id)); need.append(("m", m.id, m))
    for lod in {x.id: x for x in (trip.chosen_lodging, *(trip.lodging_for_day(d.index) for d in days),
                                   *(trip.morning_lodging(d.index) for d in days)) if x}.values():
        if not lod.amap_id:
            need.append(("l", lod.id, lod))
    found: dict[tuple[str, str], str] = {}
    for kind, oid, obj in need[:MAX_POI_LOOKUPS]:
        try:
            pid = _match_poi(client, obj.name, obj.lat, obj.lon, city, {"l": 1.0, "p": 3.0}.get(kind, 1.5))
        except AmapError:
            pid = None
        if pid:
            found[(kind, oid)] = pid
    if found:
        def mutate(t: Trip) -> None:
            for (kind, oid), pid in found.items():
                if kind == "p":
                    t.places[t.places.index(t.place(oid))] = t.place(oid).model_copy(update={"amap_id": pid})
                elif kind == "m":
                    m0 = next(x for x in t.meals if x.id == oid)
                    t.meals[t.meals.index(m0)] = m0.model_copy(update={"amap_id": pid})
                else:
                    l0 = next(x for x in t.lodgings if x.id == oid)
                    t.lodgings[t.lodgings.index(l0)] = l0.model_copy(update={"amap_id": pid})
        trip = commit(trip, mutate)
        _save(trip)
    # 2) 组装
    from .coords import wgs84_to_gcj02

    def point(obj: Any) -> Optional[dict[str, Any]]:
        if not obj.amap_id:
            return None
        g_lat, g_lon = wgs84_to_gcj02(obj.lat, obj.lon)
        return {"name": obj.name, "lon": round(g_lon, 6), "lat": round(g_lat, 6), "poiId": obj.amap_id}

    skipped: list[str] = []
    lines = []

    def add(pts: list, obj: Any, label: str) -> None:
        pt = point(obj)
        if pt:
            pts.append(pt)
        else:
            skipped.append(f"{label}：{obj.name}（高德里没有匹配到 POI，已跳过）")

    for d in days:
        pts: list[dict[str, Any]] = []
        lod_m, lod_n = trip.morning_lodging(d.index), trip.lodging_for_day(d.index)
        if lod_m:
            add(pts, lod_m, f"第{d.index + 1}天 酒店")
        for it in d.items:
            pl = trip.place(it.place_id)
            add(pts, pl, f"第{d.index + 1}天 景点")
            for m in trip.meals:
                if m.day == d.index and m.after_place_id == pl.id:
                    add(pts, m, f"第{d.index + 1}天 用餐")
        if lod_n:
            add(pts, lod_n, f"第{d.index + 1}天 酒店")
        dt = trip.day_date(d.index)
        lines.append({"title": f"第{d.index + 1}天" + (f" {dt.isoformat()}" if dt else ""), "pointInfoList": pts})
    return {
        "tool": "maps_schema_personal_map",
        "arguments": {"orgName": trip.meta.name, "lineList": lines},
        "skipped": skipped,
        "note": "arguments 请原样传给 amap-maps 的 maps_schema_personal_map，不要改动或补充任何字段；返回的链接给用户，"
                "在手机（装了高德 App）或浏览器里打开。坐标已转成高德坐标系。",
    }


AMAP_MCP_URL = "https://mcp.amap.com/mcp"


def _call_amap_mcp(tool: str, arguments: dict[str, Any], key: str) -> str:
    """直接请求高德官方 MCP（streamable HTTP）并返回文字结果。放在单独线程里跑，避免和服务自己的事件循环冲突。"""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    url = os.environ.get("AMAP_MCP_URL", AMAP_MCP_URL)

    async def run() -> str:
        async with streamablehttp_client(f"{url}?key={key}") as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(tool, arguments)
                text = "\n".join(getattr(c, "text", "") for c in res.content).strip()
                if res.isError:
                    raise RuntimeError(text or "高德 MCP 返回错误")
                return text

    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(asyncio.wait_for(run(), timeout=60))).result()


def _audit_mcp(line: str) -> None:
    try:
        p = _root_dir() / "amap_calls.log"
        with p.open("a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"{datetime.now().isoformat(timespec='seconds')} | mcp.amap.com | {line}\n")
    except OSError:
        pass


def create_amap_map(day: Optional[int] = None, per_day: bool = True) -> dict[str, Any]:
    """生成高德 App 里的专属地图并返回链接（需要 AMAP_KEY）。参数由代码生成，直接请求高德官方 MCP，
    不经过模型，所以不会丢坐标精度或漏掉某一天。day 从 1 开始，不填则所有天。
    默认 per_day=True：每天单独生成一个链接，因为实测高德 App 的专属地图一次只显示第一条行程；
    per_day=False 才把所有天放进同一张地图。
    链接是高德 App 的专用地址，要在装了高德的手机上打开。"""
    key = os.environ.get("AMAP_KEY", "").strip()
    if not key:
        raise ToolError("没有配置高德 key（环境变量 AMAP_KEY）。")
    if day is not None or not per_day:
        jobs = [(day, personal_map_payload(day))]
    else:
        n = len(_load().plan.days) if _load().plan else 0
        jobs = []
        for d in range(1, n + 1):
            try:
                jobs.append((d, personal_map_payload(d)))
            except ToolError:
                continue                       # 空的一天跳过
        if not jobs:
            raise ToolError("没有可生成的行程。")
    out, skipped = [], []
    for d, payload in jobs:
        args = payload["arguments"]
        pts = sum(len(x["pointInfoList"]) for x in args["lineList"])
        try:
            text = _call_amap_mcp("maps_schema_personal_map", args, key)
        except Exception as e:                  # 不回显异常原文，避免带出含 key 的网址
            _audit_mcp(f"maps_schema_personal_map | 行程{len(args['lineList'])}条 点{pts}个 | 失败 {type(e).__name__}")
            raise ToolError(f"调用高德专属地图失败：{type(e).__name__}。请检查网络和 key 是否有效。")
        _audit_mcp(f"maps_schema_personal_map | 行程{len(args['lineList'])}条 点{pts}个 | OK")
        import re
        m = re.search(r"[a-zA-Z][a-zA-Z0-9+.-]*://\S+", text)
        entry_ = {"day": d if d is not None else "全部", "link": m.group(0) if m else text,
                  "lines": len(args["lineList"]), "points": pts}
        if d is not None:
            entry_["web_links"] = day_marker_links(_load(), d - 1)
        out.append(entry_)
        skipped += payload["skipped"]
    return {"maps": out, "skipped": skipped,
            "note": "link 是高德 App 的专用地址（amapuri://），要在装了高德 App 的手机上打开，电脑浏览器打不开；链接可能有有效期。"
                    "微信等聊天应用里这种地址通常点不开：把它单独放一行，让用户长按复制后到手机浏览器或高德里打开；"
                    "同时给出 web_links（https 网页链接，每站一个，微信里可以直接点开）。skipped 里的点要如实告诉用户原因。"}


def export_text(day: Optional[int] = None, links: bool = True) -> str:
    """生成适合手机/聊天（微信）发送的纯文字行程：每天的出发时间、各站停留和营业时间、交通方式和时长、预约、用餐、天气，
    每站可附一个 https 地图链接（links=False 则不附）。day 从 1 开始，不填则全程（每天之间有分隔线，发到聊天里请按天分条发）。
    内容由代码按当前行程生成，和地图页一致；发出的文字留在手机聊天记录里，不依赖电脑开着。
    行程改动后要重新生成。内含外发检查：如果文字里带有 key、本机路径，会直接报错，不会输出。"""
    trip = _load()
    if trip.plan is None:
        raise ToolError("还没有分天，请先 schedule_days。")
    n = len(trip.plan.days)
    if day is not None and not (1 <= day <= n):
        raise ToolError(f"没有第 {day} 天（共 {n} 天）")
    try:
        text = _build_text(trip, day, links)
    except ValueError as e:
        raise ToolError(str(e))
    bad = _guard_text(text)
    if bad:
        raise ToolError("外发检查没通过，没有输出：" + "；".join(bad) + "。请检查景点备注/名称里是否混入了不该外发的内容。")
    return text


def _make_basemap(trip: Any) -> tuple[Any, str]:
    """只在用户要求时才建：国内行程 + 有 AMAP_KEY。返回 (Basemap 或 None, 说明)。"""
    from .amap import AmapClient
    from .basemap import Basemap
    if trip_region(trip) != "cn":
        return None, "境外行程不支持高德底图"
    client = AmapClient.from_env(log_path=_root_dir() / "amap_calls.log")
    if client is None:
        return None, "没有 AMAP_KEY（在你自己的配置里设置，不要发给我）"
    return Basemap(client, trip_path().with_name("share") / "basemap-cache"), ""


def _basemap_report(bm: Any, note: str) -> str:
    if bm is None:
        return f"没有加底图：{note}。路线图照常（无底图）。"
    msg = f"底图：向高德请求了 {bm.requests} 张静态图（缓存命中 {bm.hits} 张）"
    return msg + (f"；有 {len(bm.failures)} 类失败：{'；'.join(bm.failures)}，对应的图已退回无底图" if bm.failures else "") + "。"


def export_share(show_lodging: bool = False, show_costs: bool = False, image: bool = True, show_photos: bool = False,
                 theme: str = "default", gif: bool = False, basemap: bool = False) -> str:
    """生成可分享的行程成品：单文件 HTML（手机直接打开）和长图 PNG（微信里最方便发）。
    内容是按天的卡片：日期块、景点数/路程/用时、每站时间和营业时间、两站之间的交通、天气，每站有地图链接。
    默认**不公开酒店和花费**，因为分享出去之前该由用户决定：show_lodging=true 才带酒店名（和从酒店出发/回酒店的路段），
    show_costs=true 才带门票、餐饮人均和住宿估价，show_photos=true 才把用户用 add_photo 挂上的照片放在各站下面（照片已去掉定位信息，但画面里可能有人脸或隐私，所以默认不带）。必须先问用户要不要公开，用户没说就用默认。
    航班/车次号不会出现，页面不带任何 key，也不嵌地图；生成前有外发检查。
    theme 是版面风格：default 默认、magazine 杂志编辑、cream 奶油温柔、journal 手账贴纸、botanical 植物清新、ink 新中式墨韵、dopamine 多巴胺、swiss 瑞士极简（都是浅色底，只换配色和字体）。
    页面顶部有路线图（SVG，每天一种颜色，不带街道底图，不联网），每天的卡片里还有当天的放大路线图；网页里点“播放路线”会按天画出来。
    basemap=true 给路线图加高德街道底图（默认关闭）：会联网，用用户自己的 AMAP_KEY，只把“中心点、缩放、图片大小”发给高德，不发景点/酒店名和路线；
    图片内嵌进页面，别人打开不需要联网；范围内的酒店名可能出现在底图上，所以要先问用户。只支持国内行程；失败会如实说明并照常生成无底图版本。
    gif=true 把这个“按天画出来”的动画录成 GIF（需要 playwright 和 Pillow）。
    长图需要可选依赖 playwright（没装 Chromium 会自动试本机的 Chrome）；没装就只出 HTML 并如实告诉用户。需要先 schedule_days。
    拿到路径后用 message 工具把文件（优先 PNG）作为附件发给用户；这是此刻的快照，行程改了要重新生成。"""
    trip = _load()
    if trip.plan is None:
        raise ToolError("还没有分天，请先 schedule_days。")
    import re as _re
    stem = _re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", trip.meta.name).strip("_") or "trip"
    folder = trip_path().with_name("share")
    html_path, png_path = folder / f"{stem}-share.html", folder / f"{stem}-share.png"
    bm, bm_note = None, ""
    if basemap:
        bm, bm_note = _make_basemap(trip)
    try:
        photos = _ph.for_share(_photo_dir(), _ph.load(_photo_index())) if show_photos else None
        html = _share.build_share_html(trip, show_lodging=show_lodging, show_costs=show_costs, photos=photos, theme=theme, basemap=bm)
    except ValueError as e:
        raise ToolError(str(e))
    bad = _share.guard_html(html)
    if bad:
        raise ToolError("外发检查没通过，没有生成：" + "；".join(bad) + "。请检查景点名称/备注里是否混入了不该外发的内容。")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html, encoding="utf-8")
    except OSError as e:
        raise ToolError(f"写入分享页失败：{e}")
    shown = "、".join(x for x, on in (("酒店", show_lodging), ("花费", show_costs), ("照片", show_photos)) if on) or "不含酒店、花费和照片"
    msg = f"分享页已生成（{shown}）：{html_path}"
    if basemap:
        msg += "\n" + _basemap_report(bm, bm_note)
    if image:
        why = _share.render_png(html_path, png_path)
        msg += f"\n长图：{png_path}" if why is None else f"\n没有生成长图：{why}。HTML 照常可用。"
    if gif:
        gif_path = folder / f"{stem}-route.gif"
        why = _share.render_gif(html_path, gif_path)
        msg += f"\n路线动画：{gif_path}" if why is None else f"\n没有生成路线动画：{why}。HTML 里点“播放路线”照常可看。"
    return msg + "\n这是此刻的快照，行程改了要重新生成。"


def export_gpx(day: Optional[int] = None) -> str:
    """把某一天（day 从 1 开始，不填则每一天）的闭环路线导出成 GPX 文件，可导入其他地图或运动类 App。
    有高德真实路线形状的段用真实形状，没有的用直线（文件里会标“估算”）；建议先 refine_routes。"""
    trip = _load()
    if trip.plan is None:
        raise ToolError("还没有分天，请先 schedule_days。")
    n = len(trip.plan.days)
    if day is not None and not (1 <= day <= n):
        raise ToolError(f"没有第 {day} 天（共 {n} 天）")
    folder = trip_path().with_name("gpx")
    written = []
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for i in ([day - 1] if day else range(n)):
            if not trip.plan.days[i].items:
                continue
            f = folder / f"day-{i + 1}.gpx"
            f.write_text(build_gpx(trip, i), encoding="utf-8")
            written.append(str(f))
    except OSError as e:
        raise ToolError(f"写入 GPX 失败：{e}")
    if not written:
        raise ToolError("这一天没有景点，没有可导出的路线。")
    return "已导出 GPX（坐标为标准 WGS84）：\n" + "\n".join(written)


def export_notes(include_photos: bool = True, video_path: str = "", video_day: Optional[int] = None, folder: str = "") -> str:
    """把行程导出成本地文件：一个 Obsidian 笔记文件夹（每天一篇、每个景点一篇、[[双链]]、路线轨迹、你挂过的照片）和一个日历 .ics 文件。
    默认写到本机 ~/Documents/TripSight/；用户想直接放进自己的 Obsidian 库时，让他给出库里的文件夹路径填到 folder（必须是已存在的文件夹，
    不要自己去找用户的库），会在里面新建一个行程文件夹。不联网、不连任何账号；日历要用户自己双击导入。时间只是估算，营业时间标了来源。
    video_path 是用户电脑上某天的 vlog 视频路径，video_day 是它属于第几天（从 1 起），两个都给才会放进笔记；不给就不带视频。
    已有同名导出文件夹时不会覆盖，会新建 -2、-3。行程没设日期时只导出笔记，不导出日历。"""
    trip = _load()
    if trip.plan is None or not trip.plan.days:
        raise ToolError("还没有分天，请先 schedule_days。")
    videos = None
    if video_path or video_day is not None:
        n = len(trip.plan.days)
        if not video_path or video_day is None or not (1 <= video_day <= n):
            raise ToolError(f"video_path 和 video_day（1~{n}）要一起给。")
        vp = Path(video_path).expanduser()
        if not vp.is_file():
            raise ToolError(f"找不到视频文件：{video_path}")
        videos = {video_day - 1: vp}
    from .export_notes import build_obsidian
    target = export_root()
    if folder:
        target = Path(folder).expanduser()
        if not target.is_dir():
            raise ToolError(f"文件夹不存在：{folder}（不会自动创建，请确认路径）。")
    items = _ph.load(_photo_index()) if include_photos else []
    try:
        res = build_obsidian(trip, target, photos=items, photo_dir=_photo_dir(),
                             videos=videos, include_photos=include_photos, include_videos=videos is not None,
                             city="")
    except (OSError, ValueError) as e:
        raise ToolError(f"导出失败：{e}")
    msg = f"已导出到：{res['folder']}\n共 {len(res['files'])} 个文件；用 Obsidian 的“打开文件夹作为库”即可查看，日历文件双击导入。"
    if res["skipped"]:
        msg += "\n没有导出的部分：" + "；".join(res["skipped"])
    return msg


def _video_stops() -> tuple[list[dict], list[dict]]:
    """行程里的景点：(用于归片的 stops, 按行程顺序的 order)。时段来自照片还原的记录，没有就只能靠位置。"""
    import datetime as _dt
    trip = _load()
    if trip.plan is None or not any(d.items for d in trip.plan.days):
        raise ToolError("行程还没有分天（或这一天没有景点），先排好行程或用照片还原行程。")
    side = {x["place_id"]: x for x in _load_json_file(_photo_trip_path()).get("stops", [])}
    stops, order = [], []
    for i, d in enumerate(trip.plan.days):
        dd = trip.day_date(i)
        for it in d.items:
            pl = trip.place(it.place_id)
            rec = side.get(pl.id)
            stops.append({"id": pl.id, "day": dd, "lat": pl.lat, "lon": pl.lon,
                          "start": _dt.datetime.fromisoformat(rec["start"]) if rec else None,
                          "end": _dt.datetime.fromisoformat(rec["end"]) if rec else None})
            order.append({"id": pl.id, "name": pl.name, "day": i, "date": dd.isoformat() if dd else "", "lat": pl.lat, "lon": pl.lon})
    return stops, order


def _video_scan(folder: str):
    from . import video as _v
    root = Path(folder).expanduser()
    if not root.is_dir():
        raise ToolError(f"文件夹不存在：{folder}（请让用户确认路径；不会自动查找）。")
    try:
        clips, bad = _v.scan(root)
    except _v.VideoError as e:
        raise ToolError(str(e))
    if not clips:
        raise ToolError("文件夹里没有读到视频（支持 .mov / .mp4 / .m4v，不递归子文件夹）。")
    stops, order = _video_stops()
    n = _v.assign(clips, stops)
    return _v, clips, bad, n, order


def scan_videos(folder: str) -> str:
    """整理用户的视频素材：扫描 folder（用户给的文件夹，不递归）里的 .mov/.mp4/.m4v，读拍摄时间、位置（iPhone 视频自带）、时长，
    按拍摄时间和位置归到行程里的各个景点，返回每个景点有几段、多长，以及归不上的。只读元数据，不看画面内容；需要本机装好 ffmpeg。
    归不上的多半是没带位置、时间又对不上，让用户检查或手动指定；要出粗剪片用 export_rough_cut。"""
    _v, clips, bad, n, order = _video_scan(folder)
    names = {o["id"]: o["name"] for o in order}
    per: dict[str, list] = {}
    for c in clips:
        per.setdefault(c.stop or "", []).append(c)
    lines = [f"读到 {len(clips)} 段视频（共 {sum(c.dur for c in clips) / 60:.1f} 分钟）" + (f"，另有 {bad} 个读不了" if bad else "") + f"，归到景点 {n} 段。"]
    for o in order:
        cs = per.get(o["id"])
        if cs:
            lines.append(f"第{o['day'] + 1}天 {o['id']} {o['name']}：{len(cs)} 段，{sum(c.dur for c in cs):.0f} 秒")
    lost = per.get("", [])
    if lost:
        lines.append(f"归不上的 {len(lost)} 段：" + "、".join(c.file for c in lost[:10]) + ("…" if len(lost) > 10 else ""))
    return "\n".join(lines)


def export_rough_cut(folder: str, target_seconds: int = 0, clip_max: int = 8, cards: bool = True,
                     jianying_dir: str = "", draft_name: str = "") -> str:
    """把用户的视频素材按行程顺序粗剪成一条片子：每个景点取中间一段（最多 clip_max 秒），景点开头显示地名，每天前插一张“第N天”卡片和一张当天真实路线的小卡片。
    target_seconds=0 表示不限长度，否则自动按素材量缩短每段、必要时每个景点删几段。输出到 ~/Documents/TripSight/粗剪/：粗剪.mp4、字幕 .srt、片段清单 .md。
    jianying_dir 是用户剪映的草稿文件夹路径（用户给，不要自己找），给了就同时生成一份剪映草稿（需要 pip install pyJianYingDraft；草稿格式随剪映版本变，打不开就用 mp4+srt）。
    不自带音乐、不加特效，创意部分留给用户在剪映里做；视频内容不会交给模型。需要本机 ffmpeg，素材多时会跑一会儿。调用前先让用户确认长度。"""
    import datetime as _dt
    _v, clips, bad, n, order = _video_scan(folder)
    try:
        segs = _v.plan(clips, order, target_s=float(target_seconds), clip_max=float(max(2, min(int(clip_max), 30))), cards=bool(cards))
        size = _v._canvas(clips)
        out_dir = export_root() / "粗剪"
        out_dir.mkdir(parents=True, exist_ok=True)
        mp4 = out_dir / "粗剪.mp4"
        _v.render(segs, mp4, out_dir / "_work", size)
        (out_dir / "粗剪.srt").write_text(_v.srt(segs), encoding="utf-8")
        total = sum(s.secs for s in segs)
        rows = [f"# 粗剪片段清单（共 {total:.0f} 秒）", ""] + [
            f"- 第{s.day + 1}天 {s.lower}：{s.clip.file} 从 {s.offset:.0f}s 取 {s.secs:.1f}s" for s in segs if s.kind == "clip"]
        (out_dir / "片段清单.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
        draft = ""
        if jianying_dir:
            jd = Path(jianying_dir).expanduser()
            if not jd.is_dir():
                raise ToolError(f"剪映草稿文件夹不存在：{jianying_dir}（请让用户确认路径）。")
            try:
                draft = _v.jianying_draft(segs, size, jd, draft_name or f"{_load().meta.name}-粗剪", out_dir / "_work")
            except _v.VideoError as e:
                draft = f"（没生成剪映草稿：{e}）"
    except _v.VideoError as e:
        raise ToolError(str(e))
    except OSError as e:
        raise ToolError(f"写入失败：{e}")
    msg = f"已粗剪：{mp4}（{total:.0f} 秒，{size[0]}×{size[1]}，用了 {sum(1 for s in segs if s.kind == 'clip')} 段）\n字幕 {out_dir / '粗剪.srt'}，清单 {out_dir / '片段清单.md'}。"
    if n < len(clips):
        msg += f"\n另有 {len(clips) - n} 段没归到景点，没放进去。"
    if draft:
        msg += f"\n剪映草稿：{draft}"
    return msg + "\n这是粗剪，没有音乐和特效，剪映里再调；视频若含人脸或路人，发布前提醒用户。"


def footprint(basemap: bool = False) -> str:
    """足迹统计与地图：把去过的行程合起来——几趟、几天、到过几个城市、大约走了多少公里，并生成一张所有去过的地方的地图页（~/.tripcore/足迹.html）。
    只算“去过”的：用“恢复行程”从照片还原的行程；计划行程和复盘不算。公里数是每天按先后顺序的直线距离累加，只是下限；
    城市来自 tag_regions，没标过的行程不会猜。默认只读本机文件、不联网。
    basemap=true 给地图加高德街道底图（仅国内、需要用户自己的 AMAP_KEY）：会联网，只把“地图中心点、缩放级别、图片大小”发给高德，
    不发地名；但中心点大致反映去过的范围，用之前告诉用户并等他同意。"""
    from . import footprint as _fp
    if _single_file_mode():
        root = trip_path().parent
        feet = _fp.collect_dirs([root])
    else:
        root = _root_dir()
        _ws.migrate_legacy(root)
        feet = _fp.collect(_ws.trips_dir(root))
    text = _fp.summary(feet)
    if not feet:
        return text
    bm, note = None, ""
    if basemap:
        from .amap import AmapClient
        from .basemap import Basemap
        pts = [(p[1], p[2]) for f in feet for p in f.points]
        if not all(18 <= la <= 54 and 73 <= lo <= 136 for la, lo in pts):
            note = "有境外的地方，高德底图只支持国内"
        else:
            client = AmapClient.from_env(log_path=_root_dir() / "amap_calls.log")
            if client is None:
                note = "没有 AMAP_KEY（在你自己的配置里设置，不要发给我）"
            else:
                bm = Basemap(client, root / "basemap-cache")
    out = root / "足迹.html"
    try:
        out.write_text(_fp.build_html(feet, bm), encoding="utf-8")
    except OSError as e:
        raise ToolError(f"地图页写入失败：{e}")
    tail = _basemap_report(bm, note) if basemap else "没有底图，点位按经纬度展开（footprint(basemap=true) 可加高德底图）。"
    return text + f"\n地图页：{out}。{tail}"


def export_calendar(folder: str = "") -> str:
    """把行程导出成日历文件（.ics）：每个景点一个事件（到达—离开时间），备注里有建议停留时长和营业时间来源。行程必须已有确定日期。
    默认写到 ~/Documents/TripSight/；folder 是用户给的已存在的文件夹（不要自己去找）。只生成文件，不连任何账号、不会写进用户的日历；
    用户自己双击文件导入（苹果日历 / Google 日历都行）。时间是按停留时长和交通估算的，不是预约，导入后提醒用户出发前核实。"""
    from .export_notes import _safe, build_ics
    trip = _load()
    target = export_root()
    if folder:
        target = Path(folder).expanduser()
        if not target.is_dir():
            raise ToolError(f"文件夹不存在：{folder}（不会自动创建，请确认路径）。")
    try:
        text = build_ics(trip)
        target.mkdir(parents=True, exist_ok=True)
        out = target / f"{_safe(trip.meta.name, 'TripSight 行程')}.ics"
        out.write_text(text, encoding="utf-8", newline="")
    except ValueError as e:
        raise ToolError(str(e))
    except OSError as e:
        raise ToolError(f"写入失败：{e}")
    return f"已导出日历文件：{out}（{text.count('BEGIN:VEVENT')} 个事件）。双击导入你的日历；时间是估算的，出发前请核实。"


def export_handbook(show_photos: bool = True, video_path: str = "", video_place: str = "", cards: bool = True, basemap: bool = False, pdf: bool = False, style: str = "手账",
                    show_spending: bool = False, spending_categories: Optional[list[str]] = None, card_photos: int = 3, thumb_pins: bool = False) -> str:
    """生成一份行程手册：一个本地网页文件夹（封面、每天路线图和时间表、每站一张手账卡），加每天一张 3:4 卡片图和一份发布文案，可自己发小红书或存进知识库。
    只写本机 ~/Documents/TripSight/，不联网、不连账号，也不会替用户发布。时间只是估算，营业时间标了来源；酒店和花费不会出现。
    默认会放用户挂过的照片（含人像；已去掉定位）；用户说要不露脸、或要公开分享前不想带照片时传 show_photos=false；视频只用用户给的原文件：video_path 是视频路径，
    video_place 是它属于哪个景点，两个都给才放，原样复制不转码，文件可能很大。cards=false 可跳过卡片图（卡片图需要 playwright）。basemap=true 给每天路线图加高德街道底图（会联网，用用户自己的 AMAP_KEY，只发中心点、缩放和图片大小，不发景点名；失败时自动退回无底图）。style 是版式风格：手账（默认）/ 杂志 / 清新 / 胶片 / 海边，只换配色字体，网页、卡片图、PDF 都跟着变。show_spending=true 在手册最后加一页“后记：这一趟的花费”（只有总额和各类别金额，没有商户和明细；数据来自 import_bills 导入的账单，默认不放；放之前要问用户，花费属于隐私），spending_categories 可以只选某几类（门票/餐饮/交通/住宿/购物/其他）。pdf=true 另存一份 PDF（同样需要 playwright）。每个景点最多展示 6 张照片。card_photos=1–5 是每张卡片图放几张照片（默认 3，轮流取这一天各站的照片；没那么多就放有的）。thumb_pins=true 让路线图上有照片的点用圆形缩略图当图钉（没照片的点仍是数字圆点，需要 show_photos）。已有导出不会被覆盖。"""
    trip = _load()
    if trip.plan is None or not trip.plan.days:
        raise ToolError("还没有分天，请先 schedule_days。")
    videos = None
    if video_path or video_place:
        if not video_path or not video_place:
            raise ToolError("video_path 和 video_place 要一起给。")
        vp = Path(video_path).expanduser()
        if not vp.is_file():
            raise ToolError(f"找不到视频文件：{video_path}")
        videos = {_find_place_ref(trip, video_place).id: vp}
    from .handbook import THEMES, build_handbook
    if style not in THEMES:
        raise ToolError("style 只能是：" + "、".join(THEMES))
    items = _ph.load(_photo_index()) if show_photos else []
    bm, bm_note = _make_basemap(trip) if basemap else (None, "")
    spend = None
    if show_spending:
        from . import bills as _bl
        led = _bl.load(_ledger_path())
        if not led:
            raise ToolError("还没有导入账单，不能放花费：先 import_bills。")
        bad = [c for c in (spending_categories or []) if c not in _bl.CATEGORIES]
        if bad:
            raise ToolError("类别只能是：" + "、".join(_bl.CATEGORIES))
        spend = _bl.summarize(led, spending_categories or None)
    try:
        res = build_handbook(trip, export_root(), photos=items, photo_dir=_photo_dir(),
                             show_photos=show_photos, videos=videos, cards=cards, stories=_load_json_file(_stories_path()), basemap=bm, pdf=pdf, style=style, regions=_chapter_labels(), spending=spend, thumb_pins=thumb_pins, card_photos=card_photos)
    except (OSError, ValueError) as e:
        raise ToolError(f"生成失败：{e}")
    if basemap:
        res["skipped"].append(_basemap_report(bm, bm_note))
    msg = f"手册已生成：{res['folder']}\n用浏览器打开其中的 index.html；cards/ 里是每天一张 3:4 图，caption.txt 是文案草稿，发布要用户自己操作。"
    if res["skipped"]:
        msg += "\n没有生成的部分：" + "；".join(res["skipped"])
    return msg


def _amap_hours_lookup(client, city, p) -> Optional[str]:
    """用和 fill_hours 同样的规则（名字相符、1.5 km 内）查一个景点现在的营业时间，查不到返回 None。"""
    try:
        hits = client.search_places(p.name, city, limit=5)
    except AmapError:
        return None
    for h in hits:
        if (p.name in h.name or h.name in p.name) and haversine_km(p.lat, p.lon, h.lat, h.lon) <= 1.5 and (h.opentime_week or h.opentime_today):
            return h.opentime_week or h.opentime_today
    return None


def check_trip_changes(temp_delta: float = 5.0) -> dict[str, Any]:
    """出发前复查：重新查天气和（有高德 key 时）营业时间，只返回和之前记下的相比有实际影响的变化。只读，不改行程。
    天气只报雨雪/高温这类影响户外的因素出现或消失，以及白天气温变化超过 temp_delta（默认 5°C）；第一次调用只建立基线，不算变化。
    营业时间只复查来源为高德的景点，变了也不自动改。把变化如实告诉用户，要调整请用 propose_change 提出，由用户确认。
    出发前 3 天和前 1 天各查一次比较合适；助手支持定时任务的话可以设提醒。"""
    from .changes import hours_changes, weather_changes
    trip0 = _load()
    if trip0.plan is None:
        raise ToolError("还没有分天，请先 schedule_days。")
    old = dict(trip0.weather)
    notes: list[str] = []
    try:
        get_weather()
    except ToolError as e:
        notes.append(f"天气没能更新：{e}")
    trip = _load()
    wc = weather_changes(trip, old, trip.weather, temp_delta)
    today = date.today()
    baseline = sum(1 for d in trip.plan.days if (dt := trip.day_date(d.index)) and dt >= today
                   and dt.isoformat() in trip.weather and dt.isoformat() not in old)
    hc, unchecked = [], []
    client = _amap()
    if client is None:
        notes.append(f"{_NO_KEY}，营业时间没有复查")
    elif _is_google(client):
        notes.append("当前地图后端是 Google，营业时间复查只支持高德来源的数据")
    else:
        city = _load_context().get("city")
        cand = [p for p in trip.places if p.opening_hours and p.hours_source == "amap" and not p.waypoints][:MAX_HOURS_LOOKUPS]
        fresh = {p.id: _amap_hours_lookup(client, city, p) for p in cand}
        hc, unchecked = hours_changes(cand, fresh)
    return {"weather_changes": wc, "hours_changes": hc, "hours_unchecked": unchecked, "baseline_days": baseline, "notes": notes,
            "summary": ("没有需要注意的变化。" if not wc and not hc else f"天气变化 {len(wc)} 处，营业时间变化 {len(hc)} 处。") +
                       (f"（{baseline} 天是第一次记录预报，只作为之后对比的基线。）" if baseline else "")}


def _photo_trip_path() -> Path:
    return trip_path().with_name("photo_trip.json")


def _stories_path() -> Path:
    return trip_path().with_name("stories.json")


def _load_json_file(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def _stop_names(keep: list) -> tuple[list[str], int]:
    """给每个停留点起名：高德反查（景区/小区/最近地标/街道）；没有 key 或查不到就写“区县 · 时间”，不猜。
    同名的点加上时间区分。返回 (名字列表, 查到真实名字的个数)。只发每个点的坐标，不发照片。"""
    client = None
    try:
        client = AmapClient.from_env(log_path=_root_dir() / "amap_calls.log")
    except Exception:
        client = None
    names: list[str] = []
    found = 0
    for sp in keep:
        w = None
        if client is not None:
            try:
                w = client.where(sp.lat, sp.lon)
            except Exception:
                w = None
        nm = (w or {}).get("name", "")
        if nm:
            found += 1
        else:
            area = (w or {}).get("district") or (w or {}).get("city") or ""
            nm = f"{area} · {sp.start:%H:%M}" if area else f"{sp.start:%m-%d %H:%M}"
        names.append(nm[:40])
    cnt: dict[str, int] = {}
    for nm in names:
        cnt[nm] = cnt.get(nm, 0) + 1
    return [f"{nm} {sp.start:%H:%M}" if cnt[nm] > 1 and found else nm for nm, sp in zip(names, keep)], found


def import_photo_trip(folder: str = "", name: str = "", min_photos: int = 3, include_passing: bool = False,
                      radius_m: int = 300, photos_per_stop: int = 6, album: str = "",
                      track: str = "", tz_hours: float = 8.0, link_photos: bool = False, auto_name: bool = True) -> str:
    """从用户的一个照片文件夹还原一段已经走过的旅程：读照片的拍摄时间和 GPS，同一天、300 米内、时间连续的照片聚成"停留点"，
    每个点（默认 3 张以上）变成一个景点，按实际拍摄时间排进对应的天。folder 必须是用户给出的文件夹路径（不要自己去找用户的相册；
    macOS 照片 App 要先"导出未修改原片"并勾选位置信息）。只在本机读取，不联网；会新建并切换到一个新行程，原行程仍在（调用前先让用户确认）。
    在 Mac 上也可以不给文件夹，改给 album=照片 App 里的相册名，直接只读地读照片库（先用 list_photo_albums 看有哪些相册；需要装 osxphotos 并给终端"完全磁盘访问权限"，不会修改照片库）。
    track=GPX/KML 轨迹文件（或放了这些文件的文件夹）：用户有运动 App/手表导出的轨迹时，没有定位的照片会按拍摄时间在轨迹上补出位置（时间在轨迹相邻两点之间就插值，否则取 10 分钟内最近的点）；
    轨迹里的时间是 UTC，照片是当地时间，tz_hours 是当地与 UTC 的时差（默认 8）。轨迹只用来给照片定位，不会单独变成景点。
    link_photos=true 时照片只引用不复制（不在行程目录存副本，省磁盘）：记下原文件路径，导出时才现场缩小并去掉定位；
    原文件之后被移动或删除，对应的图就缺了（导出会提示）。默认 false，复制一份缩小去定位的副本。
    景点名：有高德 key 时按每个点的坐标反查景区/小区/最近地标（auto_name=true，只发坐标；不想发就设 false）；查不到写“区县 · 时间”，再靠 view_stop 看图和候选地名、用 update_place 改成真实名字，不要猜。
    每个点会挑最清晰的 photos_per_stop 张挂到景点上（重新编码、去掉定位）。返回摘要，不返回逐张照片。聚类参数只是经验值，结果要给用户确认。"""
    from . import phototrip as _pt
    from .models import DayItem, DayPlan, Plan, PlaceStatus
    if album:
        from . import photoslib as _pl
        root = Path("/")                       # 相册模式下 Photo.file 是绝对路径，Path("/") / 绝对路径 就是它本身
        try:
            photos, untagged, st = _pl.read_album(album)
        except _pl.PhotosLibError as e:
            raise ToolError(str(e))
    else:
        if not folder:
            raise ToolError("要给照片文件夹 folder，或者（Mac 上）照片 App 的相册名 album。")
        root = Path(folder).expanduser()
        if not root.is_dir():
            raise ToolError(f"文件夹不存在：{folder}（请让用户确认路径；不会自动查找）。")
        try:
            photos, untagged, st = _pt.read_all(root)
        except ValueError as e:
            raise ToolError(str(e))
    tracked_n = 0
    if track and untagged:
        from . import trackfile as _tf
        try:
            pts = _tf.read_tracks(track, float(tz_hours))
        except _tf.TrackError as e:
            raise ToolError(str(e))
        got, untagged = _tf.locate(pts, untagged)
        tracked_n = len(got)
        photos = sorted(photos + got, key=lambda x: (x.taken, x.file))
    if not photos:
        raise ToolError(f"没有找到带拍摄时间和位置的照片（统计：{st}）。照片要有 GPS，导出时记得勾选位置信息。")
    stops = _pt.cluster(photos, radius_m=max(50, min(int(radius_m), 2000)))
    guessed_n = _pt.assign_untagged(stops, untagged)
    keep = [s for s in stops if include_passing or s.n >= max(1, int(min_photos))]
    if not keep:
        raise ToolError(f"聚成了 {len(stops)} 个点，但没有一个达到 {min_photos} 张。可以降低 min_photos 或设 include_passing=true。")
    first, last = keep[0].day, keep[-1].day
    ndays = (last - first).days + 1
    if ndays > 30:
        raise ToolError(f"照片跨度 {ndays} 天，超过行程上限 30 天。请先把照片分到不同文件夹。")
    new_trip(name=name or f"照片还原 {first:%m.%d}-{last:%m.%d}", num_days=ndays, start_date=first.isoformat(),
             end_date=last.isoformat(), mode="drive")
    ids: list[str] = []
    stop_names, named = _stop_names(keep) if auto_name else ([f"{sp.start:%m-%d %H:%M} 停留点" for sp in keep], 0)

    def mutate(t: Trip) -> None:
        days = [DayPlan(index=i) for i in range(ndays)]
        for sp, nm in zip(keep, stop_names):
            pid = _next_id("p", [p.id for p in t.places])
            t.places.append(Place(
                id=pid, name=nm, lat=sp.lat, lon=sp.lon, status=PlaceStatus.CONFIRMED,
                duration_min=max(15, min(720, sp.minutes + 10)), source="photo", tags=["photo"],
                notes=f"从照片还原：{sp.n} 张照片，{sp.start:%H:%M}–{sp.end:%H:%M}"))
            days[(sp.day - first).days].items.append(DayItem(place_id=pid, locked=True))
            ids.append(pid)
        t.plan = Plan(days=days)
    _save(commit(_load(), mutate))
    items = _ph.load(_photo_index())
    attached = failed = 0
    for pid, sp in zip(ids, keep):
        for f in _pt.best_files(root, sp.files, max(0, min(int(photos_per_stop), 6))):
            if len(items) >= _ph.MAX_TOTAL:
                break
            try:
                (_ph.add_ref if link_photos else _ph.add)(_photo_dir(), items, str(root / f), pid, None, "")
                attached += 1
            except _ph.PhotoError:
                failed += 1
    _ph.save(_photo_index(), items)
    _photo_trip_path().write_text(json.dumps({"folder": str(root), "album": album, "stops": [
        {"place_id": pid, "day": sp.day.isoformat(), "start": sp.start.isoformat(), "end": sp.end.isoformat(), "n": sp.n, "files": sp.files, "guessed": sp.guessed}
        for pid, sp in zip(ids, keep)]}, ensure_ascii=False), encoding="utf-8")
    lines = [f"已从照片还原行程（已新建并切换到它，之前的行程都还在）：读到 {len(photos)} 张带位置的照片"
             f"（另有无定位 {st['no_gps']}、缺时间 {st['no_time']}、HEIC 未解码 {st['heic_skipped']}、读不了 {st['unreadable']}），"
             f"聚成 {len(stops)} 个停留点，保留 {len(keep)} 个（自动起名 {named} 个）；挂上照片 {attached} 张" + (f"（{failed} 张没挂上）" if failed else "") + "。"]
    if tracked_n:
        lines.append(f"其中 {tracked_n} 张本来没有定位，是按拍摄时间在轨迹文件上补出的位置（取决于手机时间和轨迹时间是否一致、tz_hours 是否对）。")
    if guessed_n:
        lines.append(f"另有 {guessed_n} 张没有定位的照片，按拍摄时间挂到了时间上最近的点（是推测，可能不准，手册里可以删）。")
    if len(stops) > len(keep):
        lines.append(f"其余 {len(stops) - len(keep)} 个是路过的零散点，没放进行程（include_passing=true 可保留）。")
    for d in range(ndays):
        row = [f"{pid} {sp.start:%H:%M}–{sp.end:%H:%M} {sp.n}张" for pid, sp in zip(ids, keep) if (sp.day - first).days == d]
        lines.append(f"第{d + 1}天 {first.fromordinal(first.toordinal() + d).isoformat()}：" + ("；".join(row) if row else "（这天没有保留的停留点）"))
    lines.append("下一步：对每个点用 view_stop 看缩略图和候选地名，向用户确认后用 update_place 改名；介绍和描写用 save_stop_story 写；最后 export_handbook。")
    return "\n".join(lines)


def merge_stops(place_ids: list[str], name: str = "") -> str:
    """把同一天里几个从照片还原的停留点合并成一个（比如神仙居景区里的七仙女、神女峰、如意桥其实都在一个景区）。
    保留第一个，其余的照片、拍摄时段并进来，景点位置取各点的加权中心，其余景点从行程里移除。必须是同一天、都是照片还原出来的点；
    调用前先和用户确认合并哪几个。name 不填就沿用第一个的名字。"""
    import datetime as _dt
    ids = list(dict.fromkeys(place_ids))
    if len(ids) < 2:
        raise ToolError("至少要两个景点才能合并。")
    side = _load_json_file(_photo_trip_path())
    recs = {x["place_id"]: x for x in side.get("stops", [])}
    trip = _load()
    for pid in ids:
        try:
            pl = trip.place(pid)
        except KeyError as e:
            raise ToolError(str(e))
        if pid not in recs or pl.source != "photo":
            raise ToolError(f"{pid} 不是从照片还原出来的景点，不能合并。")
    if len({recs[i]["day"] for i in ids}) != 1:
        raise ToolError("只能合并同一天的停留点。")
    bad = name and _guard_text(name)
    if bad:
        raise ToolError("名字" + "；".join(bad))
    keep, rest = ids[0], ids[1:]
    allrec = [recs[i] for i in ids]
    files = [f for r in allrec for f in r["files"]]
    guessed = [f for r in allrec for f in r.get("guessed", [])]
    n = sum(r["n"] for r in allrec)
    start = min(r["start"] for r in allrec)
    end = max(r["end"] for r in allrec)
    minutes = int((_dt.datetime.fromisoformat(end) - _dt.datetime.fromisoformat(start)).total_seconds() // 60)
    wsum = sum(trip.place(i).lat * recs[i]["n"] for i in ids) / n
    wlon = sum(trip.place(i).lon * recs[i]["n"] for i in ids) / n

    def mutate(t: Trip) -> None:
        k = t.place(keep)
        k.lat, k.lon = wsum, wlon
        k.duration_min = max(15, min(720, minutes + 10))
        k.notes = f"从照片还原：{n} 张照片，{start[11:16]}–{end[11:16]}（合并了 {len(ids)} 个停留点）"
        if name:
            k.name = name
        t.places = [p for p in t.places if p.id not in rest]
        for p in t.places:
            p.backups = [b for b in p.backups if b not in rest]
        if t.plan:
            for d in t.plan.days:
                d.items = [it for it in d.items if it.place_id not in rest]
            t.plan.unscheduled = [u for u in t.plan.unscheduled if u.place_id not in rest]

    _save(commit(trip, mutate))
    photos = _ph.load(_photo_index())
    for x in photos:
        if x.get("place_id") in rest:
            x["place_id"] = keep
    _ph.save(_photo_index(), photos)
    recs[keep].update({"files": files, "guessed": guessed, "n": n, "start": start, "end": end})
    side["stops"] = [x for x in side["stops"] if x["place_id"] not in rest]
    _photo_trip_path().write_text(json.dumps(side, ensure_ascii=False), encoding="utf-8")
    stories = _load_json_file(_stories_path())
    if any(i in stories for i in rest):
        for i in rest:
            stories.pop(i, None)
        _stories_path().write_text(json.dumps(stories, ensure_ascii=False), encoding="utf-8")
    return f"已把 {'、'.join(ids)} 合并成 {keep}（{n} 张照片，{start[11:16]}–{end[11:16]}）。原来这些点上写的介绍和描写已清掉，需要的话对合并后的点重新写。"


def delete_stop(place_id: str) -> str:
    """工作台用：从还原出来的行程里删掉一个停留点（景点、它的照片、拍摄记录、文字一并去掉；原照片文件不动）。
    不受“锁定”限制——锁定只是防止被自动改期，用户自己点删除就是要删。"""
    trip = _load()
    try:
        place = trip.place(place_id)
    except KeyError as e:
        raise ToolError(str(e))

    def mutate(t: Trip) -> None:
        t.places = [p for p in t.places if p.id != place_id]
        for p in t.places:
            p.backups = [b for b in p.backups if b != place_id]
        if t.plan:
            for d in t.plan.days:
                d.items = [it for it in d.items if it.place_id != place_id]
            t.plan.unscheduled = [u for u in t.plan.unscheduled if u.place_id != place_id]

    _save(commit(trip, mutate))
    items = _ph.load(_photo_index())
    n = 0
    for x in [x for x in items if x.get("place_id") == place_id]:
        try:
            _ph.remove(_photo_dir(), items, x["id"])
            n += 1
        except _ph.PhotoError:
            pass
    _ph.save(_photo_index(), items)
    side = _load_json_file(_photo_trip_path())
    if side.get("stops"):
        side["stops"] = [x for x in side["stops"] if x["place_id"] != place_id]
        _photo_trip_path().write_text(json.dumps(side, ensure_ascii=False), encoding="utf-8")
    stories = _load_json_file(_stories_path())
    if stories.pop(place_id, None) is not None:
        _stories_path().write_text(json.dumps(stories, ensure_ascii=False), encoding="utf-8")
    return f"已删除「{place.name}」（{n} 张照片的副本一并去掉；你相册里的原照片没动）。"


def autoname_stops() -> str:
    """给名字还是“…停留点”（旧版还原留下的）或“区县 · 时间”的还原点重新起名：高德反查（你自己的 key，只发坐标）。
    没有 key 或查不到就改成“区县 · 时间”，不猜。用户手动改过的名字不会动。"""
    from types import SimpleNamespace as NS
    import datetime as _dt
    side = _load_json_file(_photo_trip_path())
    recs = {x["place_id"]: x for x in side.get("stops", [])}
    trip = _load()
    todo = [p for p in trip.places if p.id in recs and (p.name.endswith("停留点") or " · " in p.name or re.fullmatch(r"\d\d-\d\d \d\d:\d\d", p.name))]
    if not todo:
        return "没有需要重新起名的点（名字都是手动改过或已经查到地名的）。"
    keep = [NS(lat=p.lat, lon=p.lon, start=_dt.datetime.fromisoformat(recs[p.id]["start"])) for p in todo]
    names, found = _stop_names(keep)
    mp = {p.id: nm for p, nm in zip(todo, names)}

    def mutate(t: Trip) -> None:
        for p in t.places:
            if p.id in mp:
                p.name = mp[p.id]
    _save(commit(trip, mutate))
    if found:
        return f"重新起名 {len(todo)} 个点，其中 {found} 个查到了真实地名，其余写成“区县 · 时间”（可以手动改）。"
    return f"重新起名 {len(todo)} 个点，但一个都没查到真实地名（没配高德 key 或查询失败），先写成“区县 · 时间”或日期时间，可以手动改。配好 AMAP_KEY 后再点一次。"


def _regions_path() -> Path:
    return trip_path().with_name("regions.json")


def _chapter_labels() -> dict[str, str]:
    from .regions import chapter_labels
    return chapter_labels(_load_json_file(_regions_path()))


def tag_regions() -> str:
    """给行程里每个景点标上所在的城市/区县，手册用它分章（比如临海、仙居、天台）。用高德坐标反查：只把每个点的坐标发给高德（用户自己的 key），
    结果存在本机，已查过的不再查。没有 key 或某个点查不到就不标、不猜，手册照常按天排。调用前告诉用户会把各点坐标发给高德。"""
    from .regions import chapter_labels, order_of_appearance
    trip = _load()
    client = _amap()
    if client is None or _is_google(client):
        raise ToolError("没有可用的高德 key，不能反查城市/区县；手册会按天分，不会乱猜。key 要用户在自己的配置里设置，不要发给我。")
    ids = [it.place_id for d in (trip.plan.days if trip.plan else []) for it in d.items]
    cache = _load_json_file(_regions_path())
    new = fail = 0
    for pid in ids:
        if pid in cache:
            continue
        pl = trip.place(pid)
        try:
            r = client.regeo(pl.lat, pl.lon)
        except AmapError:
            fail += 1
            continue
        if r:
            cache[pid] = r
            new += 1
    try:
        _regions_path().write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        raise ToolError(f"保存失败：{e}")
    labels = chapter_labels(cache)
    chapters = order_of_appearance(ids, labels)
    return (f"已标注 {new} 个点" + (f"，{fail} 个没查到" if fail else "") + "。" +
            ("章节：" + " → ".join(chapters) + "。" if chapters else "还没有可用的章节。"))


def list_photo_albums() -> str:
    """列出 Mac 照片 App 里的相册（名字和照片张数），只读，不联网，不返回照片。给 import_photo_trip(album=...) 选相册用。
    只在 macOS 上、装了 osxphotos 时可用；没装或没权限会说明怎么办。"""
    from . import photoslib as _pl
    try:
        rows = _pl.list_albums()
    except _pl.PhotosLibError as e:
        raise ToolError(str(e))
    if not rows:
        return "照片 App 里没有找到有照片的相册。"
    return "照片 App 里的相册：\n" + "\n".join(f"- {r['name']}（{r['count']} 张）" for r in rows)


def _ledger_path() -> Path:
    return trip_path().with_name("expenses.json")


def _rules_path() -> Path:
    return _root_dir() / "merchant_rules.json"


def _trip_range(trip: Trip) -> tuple[Any, Any]:
    a, b = trip.day_date(0), trip.day_date(trip.meta.num_days - 1)
    if a is None or b is None:
        raise ToolError("这个行程还没有定具体日期，没法从账单里筛出旅行期间的消费。请先 set_dates。")
    return a, b


def _bills_pool_path() -> Path:
    return _root_dir() / "bills_pool.json"


def _bills_report_path() -> Path:
    return trip_path().with_name("bills_report.json")


def _trip_range_or_none(trip: Trip):
    try:
        return _trip_range(trip)
    except ToolError:
        return None


def _ingest_bill_files(trip: Trip, files: list[Path]) -> tuple[dict[str, int], list[str]]:
    from . import bills as _bl
    rng = _trip_range_or_none(trip)                          # 行程没有具体日期也能导入：只记进账单池，不进行程账本
    a, b = rng if rng else (date(1, 1, 1), date(1, 1, 1))
    ledger = _bl.load(_ledger_path())
    names = {pl.id: pl.name for pl in trip.places}
    rules = _bl.load_rules(_rules_path())
    tot = {"added": 0, "outside": 0, "duplicate": 0}
    notes: list[str] = []
    pool = _bl.load(_bills_pool_path())                    # 账单池：不管日期，导入的消费都记在这里，工作台“全部账单/自选日期”统计用
    rep_files: list[dict[str, Any]] = []
    for f in files:
        try:
            if f.suffix.lower() == ".txt":
                txns = _bl.parse_applepay(f.read_text(encoding="utf-8", errors="ignore"))
                st = {"rows": len(txns)}
            else:
                txns, st = _bl.parse(_bl.read_rows(f))
        except (_bl.BillError, OSError) as e:
            notes.append(f"{f.name}：{e}")
            continue
        r = _bl.add_to_ledger(ledger, txns, a, b, names, rules) if rng else {"added": 0, "outside": len(txns), "duplicate": 0}
        _bl.add_to_ledger(pool, txns, date(1, 1, 1), date(9999, 12, 31), {}, rules)
        for k in tot:
            tot[k] += r[k]
        label = {"wechat": "微信", "alipay": "支付宝", "applepay": "Apple Pay"}.get(txns[0].source, "") if txns else ""
        dts = sorted(x.when.date().isoformat() for x in txns)
        notes.append(f"{f.name}：{label}账单，读到 {st['rows']} 笔" + (f"，消费日期 {dts[0]}～{dts[-1]}" if dts else ""))
        rep_files.append({"name": f.name, "source": label, "rows": st["rows"], "first": dts[0] if dts else "", "last": dts[-1] if dts else "",
                          "added": r["added"], "outside": r["outside"], "duplicate": r["duplicate"]})
    _bl.save(_ledger_path(), ledger)
    try:
        _bl.save(_bills_pool_path(), pool)
    except OSError:
        pass
    try:                                                                  # 记下这次导入的情况，工作台“花费”页一直显示，不会因为没记进账本就什么都看不到
        from datetime import datetime as _dt
        _bills_report_path().write_text(json.dumps({"at": _dt.now().strftime("%Y-%m-%d %H:%M"), "trip_start": a.isoformat() if rng else "", "trip_end": b.isoformat() if rng else "",
                                                    "files": rep_files, "notes": notes, **tot}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return tot, notes


def import_bills(path: str = "") -> str:
    """导入微信/支付宝导出的账单文件，筛出这次行程期间的消费放进本机账本，之后用 spending_summary 看统计。
    path 是用户给的账单文件，或一个文件夹（会在里面找账单文件，不递归；不给就看用户的“下载”文件夹）。支持微信 .xlsx/.csv、支付宝 .csv/.xlsx/.numbers。
    只在本机解析；账单内容不会出现在返回里（只有笔数），也不要让用户把账单内容贴给你。不计入：收入、不计收支、关闭/失败的交易；
    个人转账和群收款单独列出不计入总额。重复导入同一份账单不会重复记。行程要有具体日期。"""
    from . import bills as _bl
    trip = _load()
    rng = _trip_range_or_none(trip)
    a, b = rng if rng else (None, None)
    p = Path(path).expanduser() if path.strip() else Path.home() / "Downloads"
    if p.is_dir():
        files = [f for f in sorted(p.iterdir()) if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in _bl.SUFFIXES and _bl.sniff(f)]
        if not files:
            raise ToolError(f"在 {p} 里没有找到微信/支付宝的账单文件。")
    elif p.is_file():
        files = [p]
    else:
        raise ToolError(f"找不到：{p}（请让用户确认路径；不会自动查找）。")
    tot, notes = _ingest_bill_files(trip, files)
    if rng is None:
        return ("账单已读入账单池，但这个行程还没有具体日期，没有记进行程账本。工作台“花费”页选“全部账单”或“自选日期”可以看统计；"
                "给行程设了日期再导入一次，就会按行程期间统计。\n" + "\n".join(notes))
    return (f"账单已导入：行程期间（{a}～{b}）新记 {tot['added']} 笔，期间之外 {tot['outside']} 笔没记（仍可在“全部账单”里统计），重复 {tot['duplicate']} 笔。\n"
            + "\n".join(notes) + "\n用 spending_summary 看统计；商户明细只在工作台里给用户看，需要改分类让用户去工作台改。")


def _watch_path() -> Path:
    return _root_dir() / "bills_watch.json"


def _watch_folders() -> list[Path]:
    from . import bills as _bl
    cfg = _load_json_file(_watch_path()).get("folders")
    if isinstance(cfg, list) and cfg:
        return [Path(x).expanduser() for x in cfg if isinstance(x, str)]
    ic = _bl.icloud_folder()
    return [ic] if ic.is_dir() else []


def set_bills_watch(folders: list[str]) -> str:
    """设置要“盯着”的账单文件夹（用户给的路径，必须已存在）：之后每次扫描会把里面新出现的微信/支付宝账单和 Apple Pay 记录自动导入。
    推荐：iPhone 把账单文件存进 iCloud 云盘的“TripSight账单”文件夹，Mac 上盯这个文件夹。传空列表就恢复默认（有 iCloud 的 TripSight账单 文件夹就盯它）。
    只读这些文件夹，不会移动或删除里面的文件。"""
    out = []
    for f in folders:
        p = Path(f).expanduser()
        if not p.is_dir():
            raise ToolError(f"不是已存在的文件夹：{f}")
        out.append(str(p))
    try:
        _watch_path().write_text(json.dumps({"folders": out}, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        raise ToolError(f"保存失败：{e}")
    return "已设置盯这些文件夹：" + ("、".join(out) if out else "（默认）") + "。"


def scan_bills() -> str:
    """扫描“盯着”的文件夹，把新出现的账单（微信/支付宝导出文件、iPhone 快捷指令追加的 Apple Pay 记录）自动导入当前行程的账本。
    每个文件只处理一次（文件没变就不重复读）；Apple Pay 记录文件是不断追加的，每次都会读，但已记过的不会重复。只读，不移动不删除文件。
    返回只有笔数。可以让用户在工作台“花费”页点“立即扫描”，或用 `python -m tripcore bills-scan` 定时跑。"""
    from . import bills as _bl
    trip = _load()
    _trip_range(trip)
    folders = _watch_folders()
    if not folders:
        raise ToolError("还没有设置要盯的文件夹：用 set_bills_watch 设置，或在 iCloud 云盘里建一个“TripSight账单”文件夹。")
    seen_p = _root_dir() / "bills_seen.json"
    seen = _load_json_file(seen_p)
    files: list[Path] = []
    for fo in folders:
        if not fo.is_dir():
            continue
        for f in sorted(fo.iterdir()):
            if not f.is_file() or f.name.startswith(".") or f.suffix.lower() not in _bl.SUFFIXES:
                continue
            sig = f"{f}|{f.stat().st_size}|{int(f.stat().st_mtime)}"
            if seen.get(str(f)) == sig and f.suffix.lower() != ".txt":
                continue
            kind = _bl.sniff(f)
            seen[str(f)] = sig
            if kind:
                files.append(f)
    try:
        seen_p.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    if not files:
        return "没有新的账单。"
    tot, notes = _ingest_bill_files(trip, files)
    return f"扫描到 {len(files)} 个账单文件，新记 {tot['added']} 笔（期间之外 {tot['outside']}，重复 {tot['duplicate']}）。\n" + "\n".join(notes)


def spending_summary() -> str:
    """这次旅行的消费统计：总额、按类别、按天，以及和行程里估算（门票、住宿）的对比。只有汇总数字，没有商户和明细。
    数据来自 import_bills 导入的账单，没导入就是空的。金额是用户的真实消费，只如实转述，不要做理财建议。"""
    from . import bills as _bl
    from .metrics import estimate_cost
    trip = _load()
    ledger = _bl.load(_ledger_path())
    if not ledger:
        return "还没有导入账单：先让用户用 import_bills 导入微信/支付宝账单文件。"
    s = _bl.summarize(ledger)
    est = estimate_cost(trip)
    lines = [f"旅行期间共 {s['count']} 笔消费，合计 {s['total']:g} 元。"]
    lines.append("按类别：" + "，".join(f"{k} {v:g}" for k, v in sorted(s["by_category"].items(), key=lambda kv: -kv[1])) + "。")
    lines.append("按天：" + "，".join(f"{k[5:]} {v:g}" for k, v in s["by_day"].items()) + "。")
    cmp = []
    if est.tickets:
        cmp.append(f"门票估算 {est.tickets:g}，实际 {s['by_category'].get('门票', 0):g}")
    if est.lodging:
        cmp.append(f"住宿估算 {est.lodging:g}，实际 {s['by_category'].get('住宿', 0):g}")
    if cmp:
        lines.append("和估算对比：" + "；".join(cmp) + "（估算只含已排入行程的门票和已选酒店；账单里没标明用途的归“其他”，对不上很正常）。")
    if s["excluded_count"]:
        lines.append(f"另有 {s['excluded_count']} 笔（{s['excluded_total']:g} 元）是个人转账/群收款，没计入，用户可在工作台里改。")
    return "\n".join(lines)


def view_stop(place_id: str):
    """看一个从照片还原出来的停留点：返回文字（时间、张数、候选地名）和一张缩略联系图，用来认出这是哪里、写描写。
    候选地名只有在配置了高德 key 时才有：会把这个点的坐标发给高德（用户自己的 key）查 200 米内的景点，候选只是参考，不要直接当真，
    要和用户确认。图里的人脸、路人不要识别、不要猜是谁。照片内容会发给你背后的模型，所以每点只给一张缩小的拼图。"""
    from . import phototrip as _pt
    import base64
    from mcp.types import ImageContent, TextContent
    trip = _load()
    try:
        place = trip.place(place_id)
    except KeyError as e:
        raise ToolError(str(e))
    side = _load_json_file(_photo_trip_path())
    rec = next((x for x in side.get("stops", []) if x["place_id"] == place_id), None)
    if rec is None or place.source != "photo":
        raise ToolError("这个景点不是从照片还原出来的。")
    root = Path(side["folder"])
    if not root.is_dir():
        raise ToolError(f"原照片文件夹不在了：{root}")
    try:
        data = _pt.contact_sheet(root, rec["files"])
    except ValueError as e:
        raise ToolError(str(e))
    text = [f"{place.name}（{place_id}）：{rec['n']} 张照片，{rec['start'][11:16]}–{rec['end'][11:16]}，{rec['day']}"]
    client = _amap()
    if client is None or _is_google(client):
        text.append("没有可用的高德 key，没有候选地名，请向用户询问这是哪里。")
    else:
        try:
            hits = client.search_around(place.lat, place.lon, radius_m=200, types="110000", limit=5)
            cand = [f"{h.name}（约 {round(haversine_km(place.lat, place.lon, h.lat, h.lon) * 1000)} 米）" for h in hits]
            text.append("200 米内的景点候选（来自高德，仅供参考）：" + ("；".join(cand) if cand else "没有"))
        except AmapError as e:
            text.append(f"候选地名查询失败：{e}")
    # 直接返回内容块（不是 FastMCP 的 Image 对象）：有返回类型注解时 FastMCP 会尝试把结果序列化成结构化输出，Image 对象会报序列化错误
    return [TextContent(type="text", text="\n".join(text)),
            ImageContent(type="image", data=base64.b64encode(data).decode(), mimeType="image/jpeg")]


def save_stop_story(place_id: str, impression: str = "", facts: Optional[list[dict[str, str]]] = None) -> str:
    """给一个景点保存两种内容，手册里会分开显示：
    facts = 地点介绍，每条 {"text": 一句话, "source": 网址或"高德地图"}，必须有来源，没有来源的不要写、不要凭记忆写；
    impression = 根据照片写的一两句感受（≤300 字），只描写画面里看得到的光线、天气、色彩、气氛，不写画面外的事实和事件，
    不推测照片里的人在想什么；手册里会标注"AI 根据照片的描写"。两者可只传一个。不会写进景点的 intro 字段（那里只放游记原文或用户自己的话）。"""
    trip = _load()
    try:
        trip.place(place_id)
    except KeyError as e:
        raise ToolError(str(e))
    if not impression.strip() and facts is None:
        raise ToolError("没有要保存的内容：impression 和 facts 至少给一个。")
    if len(impression) > 300:
        raise ToolError("描写太长（最多 300 字）。")
    bad = _guard_text(impression or "")
    if bad:
        raise ToolError("描写里" + "；".join(bad))
    clean = []
    for f in facts or []:
        text, src = (f.get("text") or "").strip(), (f.get("source") or "").strip()
        if not text or not src:
            raise ToolError("每条介绍都要有 text 和 source（网址或地图服务名）；没有来源的不要写。")
        if len(text) > 200:
            raise ToolError("单条介绍太长（最多 200 字）。")
        bad = _guard_text(text)
        if bad:
            raise ToolError("介绍里" + "；".join(bad))
        clean.append({"text": text, "source": src})
    data = _load_json_file(_stories_path())
    ent = data.setdefault(place_id, {})
    if impression.strip():
        ent["impression"] = impression.strip()
    if facts is not None:
        ent["facts"] = clean
    try:
        _stories_path().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        raise ToolError(f"保存失败：{e}")
    return f"已保存「{trip.place(place_id).name}」的" + ("描写" if impression.strip() else "") + ("、" if impression.strip() and facts is not None else "") + (f"{len(clean)} 条介绍" if facts is not None else "") + "。"


def _parse_dt(text: str, label: str):
    from datetime import datetime
    try:
        return datetime.fromisoformat(text.strip().replace("/", "-").replace(" ", "T"))
    except ValueError:
        raise ToolError(f"{label} 格式不对，请用 2026-10-19 14:30 这样的写法。")


def set_connection(
    which: str,
    kind: str,
    from_name: str,
    to_name: str,
    dep_time: str,
    arr_time: str,
    number: str = "",
    price_per_person: Optional[float] = None,
    price_source: str = "",
    price_date: str = "",
    booked: bool = False,
    note: str = "",
    terminal_name: str = "",
) -> str:
    """记录到达或离开目的地的大交通（航班/火车）。which：arrival（到达）/ departure（离开）；
    kind：flight / train / other；时间写成 2026-10-19 14:30（当地时间）。
    所有字段必须来自用户选定的方案或查询工具的原始结果，逐字照抄，不要估算或编造；
    价格（每人）必须同时写来源 price_source（如 flyai / user）和日期 price_date，否则不要填。
    booked 只有用户明确说已经订好才能填 True。
terminal_name：目的地这一侧的机场/车站名（到达填到达的机场/站，离开填出发的机场/站，如“咸阳国际机场”“西安北站”），
工具会用高德查出位置，并用 refine_routes 查它与酒店之间的真实路程时间；查不到位置时，该时间用经验值兜底。工具会据此缩短第一天/最后一天可玩的时间，并在 check_plan 里提醒。"""
    if which not in ("arrival", "departure"):
        raise ToolError("which 只能是 arrival 或 departure")
    if price_per_person is not None and not (price_source and price_date):
        raise ToolError("填价格必须同时填 price_source 和 price_date；没有来源就不要填价格。")
    trip = _load()
    try:
        conn = Connection(kind=kind, number=number, from_name=from_name, to_name=to_name,  # type: ignore[arg-type]
                          dep_time=_parse_dt(dep_time, "dep_time"), arr_time=_parse_dt(arr_time, "arr_time"),
                          price_per_person=price_per_person, price_source=price_source, price_date=price_date,
                          booked=booked, note=note)
    except (ValidationError, ValueError) as e:
        raise ToolError(f"参数不合法：{e}")
    term_msg = ""
    if terminal_name:
        conn.terminal_name = terminal_name
        client = _amap()
        if client is None:
            term_msg = "没有高德 key，查不到机场/车站位置，路程时间先用经验值。"
        else:
            want = "机场" if kind == "flight" else ("火车站" if kind == "train" else "")
            try:
                hits = client.search_places(terminal_name, None, limit=8)
            except AmapError as e:
                hits, term_msg = [], f"高德查机场/车站位置失败（{e}），路程时间先用经验值。"
            pick = next((h for h in hits if want and want in h.category and terminal_name[:2] in h.name), None) \
                or next((h for h in hits if want and want in h.category), None) \
                or (hits[0] if hits and not want else None)
            if pick is not None:
                conn.terminal_name, conn.terminal_lat, conn.terminal_lon = pick.name, pick.lat, pick.lon
                term_msg = f"位置：{pick.name}（高德，{pick.address or pick.district}）。"
            elif not term_msg:
                term_msg = f"高德没有找到「{terminal_name}」这个{want or '地点'}，路程时间先用经验值，请核对名称。"
    new = commit(trip, lambda t: setattr(t, which, conn))
    _save(new)
    mins, src = transfer_minutes(new, which)
    if which == "arrival":
        r = ready_time(new)
        return (f"已记录到达：{conn.number or conn.kind} {conn.from_name}→{conn.to_name}，{conn.arr_time:%m-%d %H:%M} 到，"
                f"约 {r:%H:%M} 后才能开始游玩（含机场/车站到酒店约 {mins} 分钟，{src}）。{term_msg}"
                + (" 请 refine_routes 查真实路程。" if conn.terminal_lat is not None else ""))
    lv = leave_by(new)
    return (f"已记录离开：{conn.number or conn.kind} {conn.from_name}→{conn.to_name}，{conn.dep_time:%m-%d %H:%M} 出发，"
            f"最晚 {lv:%H:%M} 就要从酒店动身（含去机场/车站约 {mins} 分钟，{src}）。{term_msg}"
            + (" 请 refine_routes 查真实路程。" if conn.terminal_lat is not None else ""))


def clear_connection(which: str) -> str:
    """删除已记录的到达或离开大交通（which：arrival / departure），可用 undo 撤销。"""
    if which not in ("arrival", "departure"):
        raise ToolError("which 只能是 arrival 或 departure")
    trip = _load()
    if getattr(trip, which) is None:
        raise ToolError("没有这条记录。")
    _save(commit(trip, lambda t: setattr(t, which, None)))
    return "已删除。"


def _review_path() -> Path:
    return trip_path().with_name("review.json")


def _find_place_ref(trip: Trip, ref: str):
    q = (ref or "").strip()
    for p in trip.places:
        if q in (p.id, p.name):
            return p
    hit = [p for p in trip.places if q and q in p.name]
    if len(hit) == 1:
        return hit[0]
    raise ToolError(f"找不到景点「{ref}」。" if not hit else "匹配到多个景点：" + "、".join(p.name for p in hit) + "，请说得更具体。")


def record_review(place: str, status: str, rating: Optional[int] = None, note: str = "") -> str:
    """旅行结束后，记录某个景点的实际情况（只记用户说的，不要替用户编）。place：景点名或 id；
    status：去了 / 没去 / 临时改了；rating 可选 1~5 分；note 可选一句话备注（如“排队太久”“走得累”）。
    同一景点再次记录会覆盖上一次。不会改行程本身。"""
    trip = _load()
    p = _find_place_ref(trip, place)
    data = _rv.load(_review_path())
    try:
        _rv.record_place(data, p.id, status, rating, note)
    except ValueError as e:
        raise ToolError(f"没有记下：{e}")
    _rv.save(_review_path(), data)
    return f"已记下「{p.name}」：{_rv.STATUS_NAMES[data['places'][p.id]['status']]}。"


def record_actual_cost(category: str, amount: float, note: str = "") -> str:
    """记录一笔实际花费（元）。category：门票 / 餐饮 / 交通 / 住宿 / 其他；同一类别多次记录会累加。
    只记用户说的金额，不要估算。"""
    _load()
    data = _rv.load(_review_path())
    try:
        total = _rv.record_cost(data, category, amount, note)
    except ValueError as e:
        raise ToolError(f"没有记下：{e}")
    _rv.save(_review_path(), data)
    cat = _rv.COST_NAMES[_rv.COST_ALIASES[category.strip()]]
    return f"已记下{cat} {amount:g} 元，{cat}累计 {total:g} 元。"


def _photo_dir() -> Path:
    return trip_path().with_name("photos")


def _photo_index() -> Path:
    return trip_path().with_name("photos.json")


def add_photo(path: str, place: str = "", day: Optional[int] = None, caption: str = "", link: bool = False) -> str:
    """把用户自己拍的一张照片挂到某个景点（place：景点名或 id）或某一天（day 从 1 起），二选一。path 是用户电脑上的图片路径（jpg/png/webp，≤20MB）。
    存入时会重新编码、去掉拍摄定位等元数据并缩小；没有安装 Pillow 就拒绝保存。只用用户给的照片，不要自己去网上找图；
    link=true 只引用不复制（不存副本、省磁盘，导出时才现场缩小去定位；原文件被移走就缺图），默认复制。说明 caption 只写用户说的话，不要替照片编内容。照片不会自动公开：export_share 要 show_photos=true、游记里只引用编号和说明。"""
    trip = _load()
    pid = _find_place_ref(trip, place).id if place.strip() else None
    if day is not None and not (1 <= day <= trip.meta.num_days):
        raise ToolError(f"没有第 {day} 天（行程共 {trip.meta.num_days} 天）")
    bad = _guard_text(caption or "")
    if bad:
        raise ToolError("说明里" + "；".join(bad))
    items = _ph.load(_photo_index())
    try:
        rec = (_ph.add_ref if link else _ph.add)(_photo_dir(), items, path, pid, day, caption)
        _ph.save(_photo_index(), items)
    except _ph.PhotoError as e:
        raise ToolError(f"没有保存：{e}")
    where = f"「{trip.place(pid).name}」" if pid else f"第 {day} 天"
    return f"已把照片（编号 {rec['id']}）挂在{where}，" + ("只记了原文件路径，没有复制（原文件移走或删除后会缺图）；导出时才去掉定位。" if link else "已去掉定位信息。") + "默认不会公开，分享时要你同意。"


def remove_photo(photo_id: str) -> str:
    """删除一张照片（编号来自 add_photo 或 draft_travelogue）。只删本机保存的副本，不动用户的原图。"""
    _load()
    items = _ph.load(_photo_index())
    try:
        _ph.remove(_photo_dir(), items, photo_id.strip())
    except _ph.PhotoError as e:
        raise ToolError(str(e))
    _ph.save(_photo_index(), items)
    return "已删除。"


def draft_travelogue(style: str = "通用", show_lodging: bool = False, show_costs: bool = False) -> dict[str, Any]:
    """只读：把写游记需要的**事实骨架**整理出来（按天的景点、去了/没去/未记录、评分和备注、计划时间），自己写游记前先调用它。
    事实只来自行程和用户用 record_review / record_actual_cost 记下的话；别人游记里的景点介绍不是用户的经历，不会出现。
    写作规则：只用骨架里的事实；status 为“未记录”的景点先问用户去没去、感觉如何，再写；“没去”的不要写成去过；
    没有记录的感受、花费、实际时间不要编，写“待补充”；计划时间不是实际时间。style：通用 / 小红书 / 朋友圈，返回对应的结构模板（段落、语气、长度提示），小红书还会给只由事实生成的话题标签 suggested_tags；用户挂过的照片会列在对应景点/天下面（只有编号和说明）。
    默认不含酒店和花费（要发出去的内容，由用户决定）：show_lodging / show_costs 用户同意才开。写完用 check_travelogue 自查。"""
    trip = _load()
    try:
        return _tl.build_facts(trip, _rv.load(_review_path()), style, show_lodging, show_costs,
                               _ph.load(_photo_index()), (_load_context() or {}).get("city", ""))
    except ValueError as e:
        raise ToolError(str(e) + "，请先 schedule_days。")


def check_travelogue(text: str, show_costs: bool = False) -> dict[str, Any]:
    """只读：检查写好的游记草稿里**能确定**的问题——提到了没去/没记录的景点、金额或时间在记录里找不到、出现酒店名。
    返回 {"problems": [...], "note": ...}。没问题不代表文字都对：感受和形容无法核实，请原样交给用户读、由用户改。
    有问题就改草稿再查，不要为了通过检查去编记录。"""
    trip = _load()
    bad = _guard_text(text)
    if bad:
        raise ToolError("文字里" + "；".join(bad) + "，不能放进游记。")
    probs = _tl.check(trip, _rv.load(_review_path()), text, show_costs)
    return {"problems": probs, "note": "只检查能确定的部分；感受和形容无法核实，请用户自己读一遍。"}


def show_review() -> str:
    """只读：回顾报告（计划 vs 实际：景点去了几个、各类花费偏差、评分备注），并按固定规则给出可写入长期偏好的建议。
    没记录的项目显示“未记录”。建议只是展示：用户明确说“记下来”后，才用 remember_preference 写入。"""
    trip = _load()
    data = _rv.load(_review_path())
    planned_ids: list[str] = []
    if trip.plan:
        for day in trip.plan.days:
            for it in day.items:
                if it.place_id not in planned_ids:
                    planned_ids.append(it.place_id)
    est = estimate_cost(trip)
    planned = {"tickets": est.tickets, "lodging": est.lodging}
    names = {p.id: p.name for p in trip.places}
    text = _rv.report(data, names, planned_ids, planned, est.nights)
    sug = _rv.suggestions(data, planned_ids, est.lodging, est.nights)
    if sug:
        text += "\n\n偏好建议（还没写入，你说“记下来”我再记）：\n" + "\n".join(f"  {i}. {s['text']}" for i, s in enumerate(sug, 1))
    else:
        text += "\n\n暂时没有偏好建议。"
    return text


def set_travelers(n: int) -> str:
    """设置出行人数（门票、餐饮按人数估算）。"""
    if not (1 <= n <= 50):
        raise ToolError("人数需要在 1~50 之间。")
    trip = _load()
    _save(commit(trip, lambda t: setattr(t.meta, "travelers", n)))
    return f"已设置出行人数为 {n} 人。"


def remove_food(meal_id: str) -> str:
    """取消一个已选的用餐点（可用 undo 撤销）。"""
    trip = _load()
    m = next((x for x in trip.meals if x.id == meal_id), None)
    if m is None:
        raise ToolError(f"找不到用餐点：{meal_id}")
    _save(commit(trip, lambda t: t.meals.remove(next(x for x in t.meals if x.id == meal_id))))
    return f"已取消用餐点「{m.name}」。"


def _openmeteo():
    """Open-Meteo（免费、无需 key）。测试里会替换这个函数；返回 None 表示不用它。"""
    return OpenMeteoClient()


def get_weather() -> str:
    """查行程各天的天气预报。只有设置了具体日期的那几天才查。
    来源：先用高德（国内，约未来 4 天，需要 AMAP_KEY 和目的地 city）；高德没有的日期、或境外目的地，
    改用 Open-Meteo（免费，全球，最长约 16 天）。每天的预报都标明来源和查询日期。超出所有来源范围的天直接说“暂无预报”，
    不要自行编造天气，也不要用往年气候代替。"""
    trip = _load()
    if trip.plan is None:
        raise ToolError("还没有分天，请先 schedule_days。")
    wanted = {trip.day_date(d.index).isoformat(): d.index for d in trip.plan.days if trip.day_date(d.index)}
    if not wanted:
        return "还没有设置具体出行日期，无法查询天气。日期确定后再查。"
    amap_client, om_client = _amap(), _openmeteo()
    if _is_google(amap_client):
        amap_client = None             # Google 后端没有天气接口：只用 Open-Meteo
    city = _load_context().get("city")
    spots = weather_spots(trip)
    multi = len(spots) > 1
    day_spot = {i: sp for sp in spots for i in sp.days}
    notes: list[str] = []
    cast: dict[str, tuple[Any, str]] = {}          # 日期 → (预报, 来源)

    def from_amap() -> None:
        if amap_client is None:
            notes.append("没有配置高德 key")
            return
        if not city:
            notes.append("不知道目的地城市（new_trip 时填 city 才能用高德天气）")
            return
        try:
            code = amap_client.adcode(city)
            if not code:
                notes.append(f"高德找不到城市「{city}」")
                return
            for w in amap_client.forecast(code):
                cast.setdefault(w.date, (w, "amap"))
            if multi:
                notes.append(f"行程跨多个地点，高德只能按城市「{city}」查，其中远处地点的预报仅供参考")
        except AmapError as e:
            notes.append(f"高德天气查询失败：{e}")

    def from_open_meteo() -> None:
        if om_client is None:
            return
        for sp in spots:
            need = [k for k, i in wanted.items() if i in sp.days and k not in cast]
            if not need:
                continue
            try:
                fc = {w.date: w for w in om_client.forecast(sp.lat, sp.lon)}
            except WeatherError as e:
                notes.append(f"「{sp.label}」一带：{e}")
                continue
            for k in need:
                if k in fc:
                    cast[k] = (fc[k], "open-meteo")

    if multi:      # 多个地点：按地点分别用 Open-Meteo（按坐标，含海拔），查不到的再用高德补
        from_open_meteo()
        if any(k not in cast for k in wanted):
            from_amap()
    else:
        from_amap()
        from_open_meteo()
    if amap_client is None and om_client is None:
        raise ToolError("没有可用的天气来源（没有高德 key，也没有启用 Open-Meteo）。")
    lines, hit = [], 0
    snaps: dict[str, WeatherSnap] = {}
    today = date.today().isoformat()
    for d in trip.plan.days:
        dt = trip.day_date(d.index)
        if dt is None:
            continue
        got = cast.get(dt.isoformat())
        if got is None:
            lines.append(f"第{d.index + 1}天 {dt.isoformat()}：暂无预报（超出可用来源的预报范围）")
            continue
        w, src = got
        hit += 1
        sp_ = day_spot.get(d.index)
        snap = WeatherSnap(day_weather=w.day_weather, night_weather=w.night_weather, day_temp=w.day_temp,
                           night_temp=w.night_temp, fetched=today, source=src,
                           location=(sp_.label if multi and sp_ and src == "open-meteo" else ""))
        snaps[dt.isoformat()] = snap
        tips = []
        if bad_weather(w.day_weather, w.night_weather, w.day_temp):
            tips.append("有雨雪或高温，户外景点建议与室内景点调换、备好雨具或避开正午")
        if w.night_temp is not None and w.night_temp <= 0:
            tips.append("低温，注意保暖")
        lines.append(f"第{d.index + 1}天 {dt.isoformat()}：{fmt_snap(snap)}" + ("；" + "；".join(tips) if tips else ""))
    if snaps:  # 天气只是缓存，不算一次修改：不进历史、不让提案失效
        _save(trip.model_copy(update={"weather": {**trip.weather, **snaps}}))
    out = "\n".join(lines)
    if notes:
        out += "\n（" + "；".join(notes) + "）"
    if hit == 0:
        return "出行日期不在可用天气来源的预报范围内（高德约未来 4 天，Open-Meteo 约 16 天），暂不提供天气。\n" + out
    return out + "\n（已记录，之后 show_trip / check_plan 会按这份预报提醒哪天的户外安排受影响；如要调整，请用 propose_change 提出，由用户确认。）"


def _point(trip: Trip, pid: str):
    if pid in ("arrival", "departure"):
        tp = terminal_point(trip, pid)
        if tp is not None:
            return tp
    for x in [*trip.places, *trip.lodgings]:
        if x.id == pid:
            return x
    raise ToolError(f"找不到地点或住宿：{pid}")


def set_transport_prefs(
    walk_max_min: Optional[int] = None,
    prefer_subway: Optional[bool] = None,
    max_transfers: Optional[int] = None,
    taxi_ok: Optional[bool] = None,
    notes: Optional[str] = None,
) -> str:
    """设置出行偏好（只改传入的项）：单段步行最多几分钟、是否更愿意坐地铁、最多换乘几次、是否接受打车、其他说明
    （如带老人/小孩）。这些偏好会用于 compare_transport 的建议，但不会自动改行程。"""
    trip = _load()
    changes = {k: v for k, v in dict(walk_max_min=walk_max_min, prefer_subway=prefer_subway,
                                     max_transfers=max_transfers, taxi_ok=taxi_ok, notes=notes).items() if v is not None}
    if not changes:
        p = trip.meta.transport_prefs
        return f"当前出行偏好：{p.model_dump()}"

    def mutate(t: Trip) -> None:
        t.meta.transport_prefs = t.meta.transport_prefs.model_validate({**t.meta.transport_prefs.model_dump(), **changes})
        if "max_transfers" in changes or "prefer_subway" in changes:      # 换乘/地铁偏好变了，旧的公交路线缓存作废
            for k in [k for k, v in t.route_overrides.items() if v.mode == "transit"]:
                del t.route_overrides[k]

    try:
        new = commit(trip, mutate)
    except ValidationError as e:
        raise ToolError(f"参数不合法：{e}")
    _save(new)
    hint = "（换乘/地铁偏好已变，之前查过的公交路线已清除，请再调用 refine_routes 按新偏好重查）" if (
        "max_transfers" in changes or "prefer_subway" in changes) else ""
    return f"已更新出行偏好：{new.meta.transport_prefs.model_dump()}{hint}"


def set_leg_mode(from_id: str, to_id: str, mode: str) -> str:
    """指定某一段（从 from_id 到 to_id，景点或住宿的 id）的出行方式：walk / transit / drive；
    填 default 则恢复为行程的默认方式。指定后请再调用 refine_routes 更新这一段的真实时间。
    应该是用户选定后再调用。"""
    if mode not in ("walk", "transit", "drive", "default"):
        raise ToolError("mode 只能是 walk / transit / drive / default")
    trip = _load()
    a, b = _point(trip, from_id), _point(trip, to_id)
    key = f"{from_id}>{to_id}"

    def mutate(t: Trip) -> None:
        if mode == "default":
            t.leg_modes.pop(key, None)
        else:
            t.leg_modes[key] = mode  # type: ignore[assignment]

    _save(commit(trip, mutate))
    label = {"walk": "步行", "transit": "公共交通", "drive": "驾车", "default": "默认方式"}[mode]
    return f"已把「{a.name}」→「{b.name}」设为{label}。"


def compare_transport(from_id: str, to_id: str, transit_strategy: str = "fastest") -> dict[str, Any]:
    """用高德同时查两点之间的步行、公交/地铁、驾车，返回各自的时间、距离，公交还有换乘次数、步行距离、
    票价、线路和是否含地铁，并按用户的出行偏好给出建议 recommended 和理由。需要 AMAP_KEY。
    transit_strategy：fastest / cheapest / fewest_transfers / least_walking / no_subway。
    建议只是参考，请把对比展示给用户，由用户选定后再调用 set_leg_mode。"""
    client = _amap()
    if client is None:
        raise ToolError("没有配置高德 key（环境变量 AMAP_KEY），无法比较出行方式。")
    trip = _load()
    a, b = _point(trip, from_id), _point(trip, to_id)
    city = _load_context().get("city")
    options: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for m in ("walk", "transit", "drive"):
        try:
            options[m] = client.route(m, a.lat, a.lon, b.lat, b.lon, city, transit_strategy=transit_strategy,
                                      **_transit_kwargs(trip.meta.transport_prefs)) \
                if m == "transit" else client.route(m, a.lat, a.lon, b.lat, b.lon, city)
        except AmapError as e:
            errors[m] = str(e)
    prefs = trip.meta.transport_prefs
    rec, reason = _recommend(options, prefs)
    shown = {}
    for m, r in options.items():
        d: dict[str, Any] = {"minutes": r.minutes, "distance_km": r.distance_km}
        if m == "transit":
            d.update(transfers=r.transfers, walking_km=r.walking_km, cost_yuan=r.cost_yuan,
                     lines=r.lines, uses_subway=r.uses_subway)
        shown[m] = d
    cur = leg_mode(trip, from_id, to_id)
    return {"from": a.name, "to": b.name, "current_mode": cur, "options": shown, "errors": errors,
            "recommended": rec, "reason": reason,
            "note": "时间来自高德，是路线规划的估算值，高峰期和实际走法可能有差异。"}


def _recommend(options: dict[str, Any], prefs) -> tuple[Optional[str], str]:
    """按偏好给出建议（确定性规则，只是参考）。"""
    walk, tr, drive = options.get("walk"), options.get("transit"), options.get("drive")
    if walk and walk.minutes <= prefs.walk_max_min:
        return "walk", f"步行约 {walk.minutes} 分钟，在你能接受的 {prefs.walk_max_min} 分钟以内"
    if tr is not None:
        transfers_ok = prefs.max_transfers is None or tr.transfers is None or tr.transfers <= prefs.max_transfers
        faster_by_car = drive is not None and prefs.taxi_ok and drive.minutes * 1.6 < tr.minutes
        if transfers_ok and not (faster_by_car and not (prefs.prefer_subway and tr.uses_subway)):
            tail = "，含地铁" if tr.uses_subway else ""
            return "transit", f"公共交通约 {tr.minutes} 分钟，换乘 {tr.transfers if tr.transfers is not None else '?'} 次{tail}"
    if drive is not None and prefs.taxi_ok:
        why = "公共交通换乘超过你的上限" if tr is not None else "没有可用的公共交通方案"
        if tr is not None and (prefs.max_transfers is None or tr.transfers is None or tr.transfers <= prefs.max_transfers):
            why = f"驾车约 {drive.minutes} 分钟，明显快于公共交通 {tr.minutes} 分钟"
        return "drive", why
    if tr is not None:
        return "transit", "没有更合适的方式；公共交通换乘可能超出你的上限"
    if walk:
        return "walk", f"只有步行方案，约 {walk.minutes} 分钟，超过了你能接受的 {prefs.walk_max_min} 分钟"
    return None, "没有查到任何路线"


def schedule_days(keep_locked: bool = True, relaxed: bool = False) -> str:
    """自动把入围景点分到各天并排好顺序（确定性算法，已锁定的条目不会动）。
    每天的容量按“游览时间 + 当天实际路上时间”不超过节奏上限来算；放不下的景点会尽量塞回别的天，实在放不下才列入“未能安排”。
    relaxed=true 是轻松版：每天总时间只用上限的 80%，会排得更松、可能多落下几个景点。
    排完后可先用 relaxed_alternative 给用户看轻松版和当前版的差别，用户想要再用 relaxed=true 应用。"""
    trip = _load()
    if not trip.places:
        raise ToolError("还没有景点，请先 add_place。")
    new = schedule(trip, keep_locked=keep_locked, comfort=RELAXED_COMFORT if relaxed else 1.0)
    _save(new)
    msg = f"已分天（{'轻松版，' if relaxed else ''}版本 {new.revision}）。"
    assert new.plan is not None
    if new.plan.unscheduled:
        names = "、".join(f"{trip.place(u.place_id).name}（{u.reason}）" for u in new.plan.unscheduled)
        msg += f"\n未能安排：{names}"
    return msg + "\n" + _render(new)


def relaxed_alternative(keep_locked: bool = True) -> dict[str, Any]:
    """只读：试算一份“轻松版”分天（每天总时间 ≤ 上限的 80%），和当前行程对比，不修改任何数据。
    返回 {"current": 每天的景点/游览分钟/路上分钟/总分钟, "relaxed": 同上, "dropped": 轻松版里排不下的景点名,
    "added_back": 轻松版里多出来的景点名}。用户同意后再调用 schedule_days(relaxed=true) 应用（可 undo）。
    路上时间是我们自己的估算，不是高德实时路线；应用后可用 refine_routes 取真实路线。"""
    trip = _load()
    if not trip.places:
        raise ToolError("还没有景点，请先 add_place。")

    def rows(t: Trip) -> list[dict[str, Any]]:
        out = []
        for d in (t.plan.days if t.plan else []):
            st = day_stats(t, d)
            out.append({"day": d.index + 1, "places": [p.name for p in st.places],
                        "visit_min": st.visit_min, "travel_min": st.travel_min, "total_min": st.total_min})
        return out

    alt = schedule(trip, keep_locked=keep_locked, comfort=RELAXED_COMFORT)
    cur_ids = {it.place_id for d in (trip.plan.days if trip.plan else []) for it in d.items}
    alt_ids = {it.place_id for d in (alt.plan.days if alt.plan else []) for it in d.items}
    return {
        "current": rows(trip), "relaxed": rows(alt),
        "dropped": [trip.place(i).name for i in sorted(cur_ids - alt_ids)],
        "added_back": [trip.place(i).name for i in sorted(alt_ids - cur_ids)],
    }


def check_plan() -> dict[str, Any]:
    """检查行程，返回 {"ok": 是否没有 error/warning, "issues": 问题清单}（severity: error/warning/info）。"""
    issues = [
        {"code": i.code, "severity": i.severity, "message": i.message,
         "day": None if i.day_index is None else i.day_index + 1, "place_id": i.place_id}
        for i in validate(_load())
    ]
    return {"ok": not any(i["severity"] in ("error", "warning") for i in issues), "issues": issues}


def set_stays(stays: list[dict[str, Any]]) -> str:
    """设置分段住宿（长途旅行换酒店）。stays 每项形如 {"lodging_id":"l1","from_day":1,"to_day":3}，
    天数从 1 起、含两端，表示第 from_day 晚到第 to_day 晚住这家（最后一天没有“今晚”，跟随覆盖它的那段）。
    各段不能重叠；没覆盖到的天沿用已选住宿（add_lodging choose=true）。住宿必须先用 add_lodging 添加（坐标来自工具或用户）。
    换酒店当天早上仍从旧酒店出发、晚上回新酒店；到达日去第一家，离开日从前一晚那家出发。
    这会改变行程，只能在用户确认之后调用。设置后建议 schedule_days 与 refine_routes 重新算一遍。"""
    trip = _load()
    n = trip.meta.num_days
    items: list[Stay] = []
    for x in stays:
        try:
            fd, td = int(x["from_day"]), int(x["to_day"])
            st = Stay(lodging_id=str(x["lodging_id"]), from_day=fd - 1, to_day=td - 1)
        except (KeyError, ValueError, ValidationError) as e:
            raise ToolError(f"住宿段格式不对（需要 lodging_id、from_day、to_day，天数从 1 起）：{e}")
        if not (1 <= fd <= td <= n):
            raise ToolError(f"天数超出范围：第 {fd}–{td} 天（行程共 {n} 天）。")
        items.append(st)
    try:
        new = commit(trip, lambda t: setattr(t, "stays", items))
        Trip.model_validate(new.model_dump())     # 校验：住宿存在、各段不重叠
    except (ValidationError, ValueError) as e:
        raise ToolError(f"住宿设置不合法：{e}")
    _save(new)
    names = {l.id: l.name for l in new.lodgings}
    return "已设置分段住宿：" + "；".join(f"第{a.from_day + 1}–{a.to_day + 1}晚 {names[a.lodging_id]}" for a in sorted(items, key=lambda z: z.from_day)) \
        + "。请重新 schedule_days 和 refine_routes，往返路线才会按各天的酒店重算。"


def clear_stays() -> str:
    """清除分段住宿，恢复成全程住已选住宿。需用户确认。"""
    trip = _load()
    if not trip.stays:
        return "当前没有分段住宿。"
    _save(commit(trip, lambda t: setattr(t, "stays", [])))
    return "已清除分段住宿。"


def remember_preference(category: str, text: str, value: Optional[dict[str, Any]] = None) -> str:
    """记下用户明确表达的长期偏好（跨行程保存，换会话/重启也在）。只在用户明确说“我不喜欢/我总是/以后都/我一般”这类
    长期偏好时调用；一次性的要求（“这次想住近点”）、你自己的推断、健康/证件/账号等隐私信息都不要记。记完要用一句话告诉用户记了什么。
    category：transport / pace / lodging / food / interest / other；text：用户的原话或简短概括。
    value 可选，用来让代码直接使用，只允许这些键：pace(relaxed/normal/packed)、walk_max_min(整数分钟)、prefer_subway(bool)、
    max_transfers(0-5)、taxi_ok(bool)、avoid_food(忌口列表)、like_food(爱吃列表)、lodging_budget_max(元/晚)。
    同一个结构化键只保留最新的一条。"""
    items = _prefs.load(_prefs_path())
    try:
        new, entry, replaced = _prefs.add(items, category, text, value)
    except ValueError as e:
        raise ToolError(f"没有记下：{e}")
    _prefs.save(_prefs_path(), new)
    return f"已记住 [{entry['id']}] {entry['text']}" + (f"（取代了：{'；'.join(replaced)}）" if replaced else "") \
        + "。新建行程时会自动套用；用 forget_preference 可以删除。"


def list_preferences() -> str:
    """列出已记下的长期偏好。"""
    items = _prefs.load(_prefs_path())
    if not items:
        return "还没有记下任何长期偏好。"
    return "\n".join(f"[{x['id']}] ({x['category']}) {x['text']}  — {x['date']}"
                     + (f"  值：{x['value']}" if x.get("value") else "") for x in items)


def forget_preference(pref_id: str) -> str:
    """删除一条长期偏好（用户说“忘掉/不用记这个”时）。"""
    items = _prefs.load(_prefs_path())
    try:
        new = _prefs.forget(items, pref_id)
    except KeyError:
        raise ToolError(f"没有这条偏好：{pref_id}")
    _prefs.save(_prefs_path(), new)
    return f"已删除偏好 {pref_id}。"


def final_check() -> str:
    """定稿前清单：把“现在还有什么没弄清楚/没处理”一次列清，分为必须处理（✗）、建议处理（!）、提示（·）。
    包含 check_plan 的所有问题，另外补：住宿是否每晚都有、到达/离开大交通是否订了、天气是否查过或已过期、待核实的资料、
    没匹配到高德的点、仍是估算的交通。只读，不改行程。用户说“检查一下/可以定稿了吗/出发前还要做什么”时调用，
    把清单按类别简要转述，并逐条问用户要不要处理。"""
    return _render_checklist(_build_checklist(_load()))


def list_trips() -> str:
    """列出所有行程（名字、天数、景点数、版本，标出当前正在用的）和已归档的数量。用户问“我有哪些行程”时调用。只读。"""
    if _single_file_mode():
        p = trip_path()
        if not p.exists():
            return "还没有行程。"
        t = load_trip(p)
        return f"（单文件模式）当前行程：{t.meta.name}，{t.meta.num_days} 天，{len(t.places)} 个景点。"
    root = _root_dir()
    _ws.migrate_legacy(root)
    items = _ws.list_trips(root)
    if not items:
        return "还没有行程，请先 new_trip。"
    lines = [f"{'▶' if i['active'] else ' '} {i['name']}（{i['slug']}）：{i['num_days']} 天，{i['places']} 个景点，版本 {i['revision']}" for i in items]
    arch = len(_ws.list_trips(root, archived=True))
    return "\n".join(lines) + (f"\n（另有 {arch} 个已归档行程，在 trips/_archive/ 里，文件都还在）" if arch else "")


def switch_trip(name: str) -> str:
    """切换到另一个行程（按行程名或目录名，名字相近时需要说得更具体）。切换后所有工具都作用于这个行程；
    待确认的提案、候选景点、地图文件都是各行程自己的，不会串。需要用户明确要求切换才调用。"""
    if _single_file_mode():
        raise ToolError("当前是单文件模式（设置了 TRIPCORE_FILE），不能切换行程。")
    root = _root_dir()
    _ws.migrate_legacy(root)
    try:
        slug = _ws.resolve(root, name)
    except KeyError:
        raise ToolError(f"找不到行程「{name}」。现有行程：" + "、".join(i["name"] for i in _ws.list_trips(root)))
    except ValueError as e:
        raise ToolError(f"「{name}」匹配到多个行程：{e}。请说得更具体。")
    _ws.set_active(root, slug)
    t = _load()
    return f"已切换到「{t.meta.name}」（{t.meta.num_days} 天，{len(t.places)} 个景点，版本 {t.revision}）。"


def archive_trip(name: str) -> str:
    """把一个行程归档（移到 trips/_archive/，不删除任何文件，之后可以手动移回）。当前正在用的行程不能归档。
    需要用户明确要求才调用。"""
    if _single_file_mode():
        raise ToolError("当前是单文件模式（设置了 TRIPCORE_FILE），不能归档。")
    root = _root_dir()
    _ws.migrate_legacy(root)
    try:
        slug = _ws.resolve(root, name)
        dest = _ws.archive(root, slug)
    except KeyError:
        raise ToolError(f"找不到行程「{name}」。")
    except ValueError as e:
        raise ToolError(str(e))
    return f"已归档「{name}」（文件移到了 trips/_archive/{dest.name}，没有删除）。"


def set_dates(start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
    """修改（或清除）行程的确定日期，格式 YYYY-MM-DD；开始和结束要一起填，都不填表示清除日期。
    天数会按日期重新计算；如果天数变了且已经分过天，会自动按新天数重新分天（已锁定且仍在范围内的景点保持原位，其余重排，
    排不下的进“未安排”）；旧的天气快照会作废。
    这会改变行程，只能在用户明确要求并说清影响之后调用；可以 undo。"""
    trip = _load()
    sd = _parse_date(start_date or None, "start_date")
    ed = _parse_date(end_date or None, "end_date")
    try:
        new, notes = _apply_dates(trip, sd, ed)
    except ValueError as e:
        raise ToolError(str(e))
    _save(new)
    _save_proposals({})
    head = "已清除日期。" if sd is None else f"已把日期设为 {sd.isoformat()} 至 {ed.isoformat()}（共 {new.meta.num_days} 天）。"
    return head + ("\n" + "\n".join(notes) if notes else "")


def open_workbench() -> str:
    """打开本机网页工作台（拖拽调整每天的景点顺序/跨天移动，月历选日期，带校验预览和撤销）。
    返回网址，让用户在这台电脑的浏览器里打开；网址带一次性令牌，只在本机有效，不要转发给别人。
    服务空闲 2 小时自动退出。用户要求“打开工作台/想拖一下行程/想点选日期”时调用。"""
    _load()
    from .web import launch
    try:
        return launch(_root_dir())
    except RuntimeError as e:
        raise ToolError(str(e))


def set_provider(provider: str) -> str:
    """设置当前行程用哪个地图后端：amap（高德）、google（Google Maps）或 auto（自动：国内高德、境外 Google）。
    境外行程建议创建后马上设为 google（需要环境变量 GOOGLE_MAPS_KEY）。只在用户要求或创建境外行程时调用。"""
    p = (provider or "").strip().lower()
    if p not in (*BACKENDS, "auto"):
        raise ToolError("provider 只能是 amap / google / auto")
    trip = _load()
    _save(commit(trip, lambda t: setattr(t.meta, "map_provider", None if p == "auto" else p)))
    client = _amap()
    name = {"auto": "自动选择", "amap": "高德", "google": "Google"}[p]
    msg = f"已把这个行程的地图后端设为{name}（目的地在{'中国大陆' if trip_region(trip) == 'cn' else '境外'}）。"
    if client is None:
        msg += f"\n但{_NO_KEY}。"
    elif _BACKEND["note"]:
        msg += f"\n注意：{_BACKEND['note']}。"
    return msg


def search_links(keyword: str, kind: str = "guide", sites: Optional[list[str]] = None) -> dict[str, Any]:
    """生成“去别的平台看别人攻略/点评”的搜索链接（小红书、大众点评、马蜂窝、百度、Google），由用户自己点开、用自己的账号登录。
    keyword 是景点名或想查的内容（会自动补上行程的目的地城市）；kind：guide 看攻略/游记，food 看美食点评，hotel 看酒店价格和口碑（携程、大众点评、小红书；酒店价格和日期、房型有关，链接不带日期，用户要自己选日期）；
    sites 可选，指定平台 id（xiaohongshu / dianping / mafengwo / baidu / google）。
    不抓取、不读取这些平台的内容，也不碰任何账号；用户看到合适的攻略后，把正文复制回聊天，再走 submit_candidates 流程。
    链接格式没有用真实账号逐一验证，打不开或搜不准时如实告诉用户。"""
    if kind not in (_links.GUIDE, _links.FOOD, _links.HOTEL):
        raise ToolError("kind 只能是 guide、food 或 hotel。")
    try:
        city = _load_context().get("city")
    except Exception:
        city = None
    try:
        res = _links.search_links(keyword, city, kind, sites)
    except ValueError as e:
        raise ToolError(str(e))
    return {"links": res, "note": "这些是搜索链接，请用户自己点开并登录自己的账号；看到合适的攻略，把正文复制回来即可。"}


def suggest_lodging() -> dict[str, Any]:
    """推荐住宿区域，并把候选住宿按通勤排序（时间为估算值）。
    segments 是按每晚/每段给的推荐：景点分布在不同区域或城市时会分成几段（建议中途换酒店），每段给出中心坐标、
    search_near（搜酒店时用“某某附近”）和相关景点；有 segments 时优先按它去搜酒店，再 add_lodging / set_stays。"""
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
        "segments": [
            {"nights": f"第{g.from_night + 1}–{g.to_night + 1}晚" if g.to_night > g.from_night else f"第{g.from_night + 1}晚",
             "from_night": g.from_night + 1, "to_night": g.to_night + 1,
             "center": {"lat": round(g.lat, 5), "lon": round(g.lon, 5)}, "radius_km": g.radius_km,
             "search_near": g.near_place, "related_places": g.place_names,
             "avg_minutes_to_places": g.avg_minutes_to_places,
             "current_lodging": (lambda l: None if l is None else l.name)(trip.lodging_for_day(g.from_night))}
            for g in suggest_stay_segments(trip)
        ],
        "day_trips": [
            {"day": d + 1, "places": names, "km_from_main_area": km,
             "note": "按一日游处理，酒店仍建议住主区域；如果打算当晚住在那边，请告诉我再重算"}
            for d, (names, km) in sorted(day_trips(trip).items())
        ],
    }


def propose_change(summary: str, ops: list[dict[str, Any]], rationale: str = "") -> dict[str, Any]:
    """生成修改提案（不会真正修改行程）。ops 是操作列表，每项形如：
    {"kind":"move","place_id":"p1","to_day":1,"to_position":0}  （to_day 从 0 开始；to_position 可省）
    {"kind":"remove","place_id":"p2"}
    {"kind":"set_status","place_id":"p3","status":"excluded"}  （idea/shortlist/planned/confirmed/excluded）
    {"kind":"lock","place_id":"p1","locked":true}
    {"kind":"set_duration","place_id":"p1","minutes":120}  （改停留时长，10–720 分钟）
    返回提案 id、confirm_code 和“改前→改后”说明。
    必须把 changes 和 confirm_code 展示给用户，请用户回复该确认码；用户回复后才能调用 apply_proposal。
    绝对不能自己代填确认码或在用户没回复时套用。"""
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
    code = f"{secrets.randbelow(10000):04d}"
    store = _load_proposals()
    store[proposal.id] = {"proposal": proposal.model_dump(mode="json"), "confirm_code": code}
    _save_proposals(store)
    return {"proposal_id": proposal.id, "confirm_code": code, "summary": summary, "changes": lines,
            "base_revision": proposal.base_revision,
            "next": f"请把 changes 展示给用户，并告诉用户：回复“确认 {code}”即可执行。用户回复前不要调用 apply_proposal。"}


def apply_proposal(proposal_id: str, confirm_code: str) -> str:
    """套用提案。confirm_code 必须是用户在聊天里亲自回复的 4 位确认码（propose_change 返回的那个），
    不能自己代填。过期、被锁定或不合法时会报错且不改动行程。"""
    store = _load_proposals()
    if proposal_id not in store:
        raise ToolError(f"找不到提案 {proposal_id}（可能已套用或已被清除）。")
    if str(confirm_code).strip() != store[proposal_id]["confirm_code"]:
        raise ToolError("确认码不对。请把改动展示给用户，让用户回复确认码后再套用。")
    proposal = Proposal.model_validate(store[proposal_id]["proposal"])
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

def _meal_text(ml: Meal) -> str:
    bits = [ml.name]
    if ml.rating is not None:
        bits.append(f"评分{ml.rating:g}")
    bits.append(f"人均约{ml.cost_per_person:.0f}元（参考）" if ml.cost_per_person is not None else "人均待核实")
    if ml.distance_m is not None:
        bits.append(f"距景点约{ml.distance_m}米")
    bits.append(f"营业：{ml.opening_hours}（来源：{ml.hours_source}）" if ml.opening_hours else "营业时间待核实")
    return f"{ml.id} " + "，".join(bits)


def _hours_line(p: Place, d: Optional[date]) -> str:
    if not p.opening_hours:
        return "营业时间：待核实（暂无来源）"
    src = p.hours_source or "来源未注明"
    base = f"营业时间：{p.opening_hours}（来源：{src}）"
    if d is not None:
        r = hours_for_date(p.opening_hours, d)
        if r == "闭馆":
            return base + f" ⚠ {_WEEKDAYS[d.weekday()]}可能闭馆"
        if r:
            return base + f" → {_WEEKDAYS[d.weekday()]}：{r}"
        return base + "（当天时段无法自动判断，待核实）"
    return base


def _render(trip: Trip) -> str:
    m = trip.meta
    if m.date_mode == DateMode.EXACT and m.start_date and m.end_date:
        when = f"{m.start_date.isoformat()} 至 {m.end_date.isoformat()}"
    elif m.date_mode == DateMode.RANGE and m.earliest_start and m.latest_end:
        when = f"大致 {m.earliest_start.isoformat()} 至 {m.latest_end.isoformat()} 之间"
    else:
        when = "日期未定"
    try:
        city = _load_context().get("city")
    except Exception:
        city = None
    out = [f"【{m.name}】{m.num_days} 天，{when}，{m.travelers} 人，" + (f"目的地 {city}，" if city else "目的地未填，")
           + f"节奏 {m.pace.value}，交通偏好 {_MODE_NAMES[m.mode]}，版本 {trip.revision}"]
    if trip.stays:
        names = {l.id: l.name for l in trip.lodgings}
        out.append("住宿（分段）：" + "；".join(f"第{a.from_day + 1}–{a.to_day + 1}晚 {names.get(a.lodging_id, a.lodging_id)}"
                                              for a in sorted(trip.stays, key=lambda z: z.from_day))
                   + (f"；其余晚 {trip.chosen_lodging.name}" if trip.chosen_lodging else ""))
    elif trip.chosen_lodging:
        out.append(f"住宿：{trip.chosen_lodging.name}")
    for label, c in (("到达", trip.arrival), ("离开", trip.departure)):
        if c is not None:
            price = f"，约 {c.price_per_person:g} 元/人（{c.price_source} {c.price_date}，参考价）" if c.price_per_person is not None else ""
            out.append(f"{label}：{c.number or c.kind} {c.from_name}→{c.to_name} {c.dep_time:%m-%d %H:%M}→{c.arr_time:%m-%d %H:%M}"
                       f"{'（已订）' if c.booked else '（未订）'}{price}")
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
        _ws, _we, _why = day_window(trip, day.index)
        if _why:
            out.append(f"  ⏱ {'；'.join(_why)}，可玩约 {_we - _ws} 分钟")
        _w = trip.weather.get(d.isoformat()) if d else None
        if _w:
            out.append("  🌤 " + fmt_snap(_w))
        if not st.places:
            out.append("  （空）")
            continue
        for i, p in enumerate(st.places):
            lock = " 🔒" if day.items[i].locked else ""
            out.append(f"  {i + 1}. {p.name}({p.id}) {p.duration_min}分钟{lock}")
            if p.waypoints:
                out.append("     路线：" + "→".join(w.name for w in p.waypoints)
                           + f"（步行约 {sum(w.next_minutes for w in p.waypoints)} 分钟；各点营业时间请自行核实）")
            else:
                out.append("     " + _hours_line(p, d))
            for ml in trip.meals:
                if ml.day == day.index and ml.after_place_id == p.id:
                    out.append("     🍜 " + _meal_text(ml))
            if p.reservation_required:
                bk = [trip.place(b).name for b in p.backups if any(x.id == b for x in trip.places)]
                out.append("     需预约；备选：" + ("、".join(bk) if bk else "未设置"))
            if i < len(st.legs):
                leg = st.legs[i]
                src = "高德路线" if leg.detail_level == "route" else "估算"
                out.append(f"     ↓ 约 {leg.minutes} 分钟（{_MODE_NAMES[leg.mode]}，{leg.distance_km} km，{src}）")
    orphan = [ml for ml in trip.meals if not any(ml.day == dd.index and any(it.place_id == ml.after_place_id for it in dd.items)
                                                   for dd in trip.plan.days)]
    for ml in orphan:
        out.append(f"🍜 第{ml.day + 1}天用餐点（⚠ 挂靠的景点已不在这一天）：{_meal_text(ml)}")
    if trip.plan.unscheduled:
        out.append("未安排：" + "；".join(f"{trip.place(u.place_id).name}({u.place_id})：{u.reason}" for u in trip.plan.unscheduled))
    c = estimate_cost(trip)
    costs = [ml.cost_per_person for ml in trip.meals if ml.cost_per_person is not None]
    n = m.travelers
    if costs:
        out.append(f"餐饮（已选 {len(trip.meals)} 处）人均参考合计 {sum(costs):.0f} 元/人")
    out.append(f"粗略费用（仅门票+住宿，门票按 1 人计）：{c.total:.0f} {m.currency}")
    if n > 1 or costs or trip.arrival or trip.departure:
        food = sum(costs) * n
        fare = sum(x.price_per_person for x in (trip.arrival, trip.departure) if x and x.price_per_person is not None) * n
        total = c.tickets * n + food + c.lodging + fare
        out.append(f"按 {n} 人估算：门票 {c.tickets * n:.0f} + 已选餐厅 {food:.0f} + 大交通 {fare:.0f} + 住宿 {c.lodging:.0f}（按整间/整晚价，未乘人数）"
                   f" = 约 {total:.0f} {m.currency}（未含交通和未选的餐食，均为参考值）")
    if any(b.tickets or b.meals for b in day_budgets(trip)):
        out.append("按天（门票 + 已选餐厅，按 " + f"{n} 人）：" + "；".join(
            f"第{b.index + 1}天 门票 {b.tickets:.0f}" + (f" + 餐饮 {b.meals:.0f}" if b.meals_chosen else "（餐饮未选）")
            for b in day_budgets(trip)))
    hint = _stay_hint(trip)
    if hint:
        out.append("💡 " + hint)
    return "\n".join(out)



# ---------------------------------------------------------------------------
# 游记 / 攻略 → 候选景点
# ---------------------------------------------------------------------------

def _cand_path() -> Path:
    return trip_path().with_name("candidates.json")


def _load_cands() -> list[dict[str, Any]]:
    p = _cand_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _save_cands(items: list[dict[str, Any]]) -> None:
    p = _cand_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


MAX_PRECHECK = 30       # 提交游记时最多顺手查多少个地点（每个一次地图请求）


def _guide_links(name: str) -> dict[str, str]:
    try:
        city = _load_context().get("city")
    except Exception:
        city = None
    try:
        return {x["name"]: x["url"] for x in _links.search_links(name, city, _links.GUIDE)}
    except ValueError:
        return {}


def _precheck(trip: Optional[Trip], cand: dict[str, Any], budget: int) -> dict[str, Any]:
    """提交游记时顺手查一下地图，只做标注（已匹配 / 有歧义 / 没找到），不加入行程。判断规则和 adopt_candidates 完全一样。"""
    if cand["kind"] not in ("attraction", "area"):
        return {"status": "n/a", "why": "餐饮/其他类不按景点查坐标"}
    if _amap() is None:
        return {"status": "unchecked", "why": "没有配置地图 key，加入时再查（只有 OpenStreetMap 结果不会自动采用）"}
    if budget <= 0:
        return {"status": "unchecked", "why": f"一次最多预查 {MAX_PRECHECK} 个，加入时再查"}
    try:
        pick, why, hits = _resolve_name(cand["name"])
    except Exception as e:
        return {"status": "unchecked", "why": f"预查失败：{e}"}
    if pick is None:
        return {"status": "ambiguous" if "多个同名" in why else "not_found", "why": why,
                "options": [{"name": h["name"], "address": h.get("address") or ""} for h in hits[:3]]}
    lat, lon = round(pick["lat"], 6), round(pick["lon"], 6)
    return {"status": "matched", "name": pick["name"], "address": pick.get("address") or "", "lat": lat, "lon": lon,
            "link": marker_link(pick["name"], lat, lon, trip_region(trip) if trip else "cn")}


def submit_candidates(text: str, items: list[dict[str, Any]], source: str = "游记") -> dict[str, Any]:
    """把用户粘贴的游记/攻略里提到的地点整理成候选清单（不加入行程）。
    text：用户粘贴的原文，必须完整原样传入；source：给这篇游记起个简短名字。
    items：每项 {name, kind, quote, passage, clues}。name 是地点名；kind 是 attraction（景点）/area（街区、步道）/food（餐馆、小吃）/other；
    quote 必须是原文里逐字摘录的一句话，且包含 name；passage 是原文里讲这个地点的那一段（逐字摘录，包含 name，最多 300 字，
    会作为景点的可展开介绍显示给用户；没有就不填，用 quote 代替）；clues 是原文里逐字摘录的价格、时间、建议等片段（没有就留空），
    它们只是“待核实线索”。代码会核对 quote、passage 和 clues 是否真在原文里，对不上的拒收，所以不要改写、不要补充原文没有的内容。
    候选按它们在原文中出现的先后排序（游记若是一条顺路路线，这就是游览顺序）。
    原文里的“第N天 / Day N / D2”标记由代码识别，每个候选会带上它属于游记的第几天（day）。
    有地图 key 时，代码会顺手查地图，给每个景点候选标注 match：matched（找到了，附地址和地图链接）/ ambiguous（有同名，需用户确认）/ not_found，
    并附上去小红书等平台看攻略的跳转链接 links。这些只是标注，景点还没加入行程；之后由用户挑选，再调用 adopt_candidates。"""
    if not text.strip():
        raise ToolError("text 不能为空，请把用户粘贴的游记原文完整传入。")
    ok, rejected = _validate_items(text, items)
    trip = None
    try:
        trip = _load()
    except ToolError:
        pass
    existing = _load_cands()
    have = [c["name"] for c in existing if c["status"] != "dropped"] + ([p.name for p in trip.places] if trip else [])
    added, dup = [], []
    n = max([int(c["id"][1:]) for c in existing] or [0])
    budget = MAX_PRECHECK
    for e in ok:
        if any(_similar_name(e["name"], h) for h in have):
            dup.append(e["name"])
            continue
        n += 1
        cand = {"id": f"c{n}", "name": e["name"], "kind": e["kind"], "quote": e["quote"], "clues": e["clues"],
                "passage": e["passage"], "day": e["day"],
                "source": source, "order": e["order"], "status": "pending", "place_id": ""}
        cand["match"] = _precheck(trip, cand, budget)
        if cand["match"]["status"] in ("matched", "ambiguous", "not_found"):
            budget -= 1
        existing.append(cand)
        added.append({**cand, "links": _guide_links(cand["name"]) if cand["kind"] in ("attraction", "area") else {},
                      **({"dropped_clues": e["dropped_clues"]} if e.get("dropped_clues") else {})})
        have.append(e["name"])
    _save_cands(existing)
    days = sorted({c["day"] for c in added if c.get("day")})
    return {"added": added, "skipped_duplicates": dup, "rejected": rejected,
            "source_days": days,
            "note": "这些只是候选，还没加入行程。请把候选、原文出处和 match 结果展示给用户（matched 的给地图链接，ambiguous/not_found 如实说明），"
                    "由用户选择后再调用 adopt_candidates；clues 只是游记里的说法，价格和营业时间不要当作事实。"
                    + ("原文有分天（第 " + "、".join(map(str, days)) + " 天）：加入景点后，可用 compare_with_source 对照，"
                       "用户明确要求“按游记原样排”时才用 follow_source_days。" if days else "")}


def list_candidates(status: str = "pending") -> list[dict[str, Any]]:
    """列出游记候选。status：pending（待选，默认）/ added（已加入）/ dropped（已放弃）/ all。"""
    items = _load_cands()
    return [c for c in items if status == "all" or c["status"] == status]


def drop_candidates(ids: list[str]) -> str:
    """把用户不要的候选标记为放弃（候选清单里不再提示，也不会被重复提取）。"""
    items = _load_cands()
    hit = [c for c in items if c["id"] in ids]
    if not hit:
        raise ToolError("没有找到这些候选 id。")
    for c in hit:
        c["status"] = "dropped"
    _save_cands(items)
    return "已放弃：" + "、".join(c["name"] for c in hit)


def _resolve_name(name: str) -> tuple[Optional[dict[str, Any]], str, list[dict[str, Any]]]:
    """按名字在地图上确定一个位置：只自动采用高德结果（名字相符且无歧义）；OpenStreetMap 结果精度低，不自动采用。"""
    res = lookup_coords(name)
    hits = res.get("candidates") or ([{"name": res["name"], "lat": res["lat"], "lon": res["lon"]}] if res.get("found") else [])
    if res.get("found") and res.get("source") not in ("amap", "google"):
        return None, "高德没有找到（只有 OpenStreetMap 结果，精度低，不自动采用）", hits
    pick, why = _pick_hit(name, hits)
    return pick, why, hits


MAX_ADOPT = 10


def adopt_candidates(ids: list[str]) -> str:
    """把用户选中的候选（attraction / area）加入行程：用地图查坐标，名字相符且不歧义才加入；
    坐标之外的信息（游记里的价格、时间）只作为“待核实线索”写进备注，不当事实。
    查不到、有多个同名地点、或和已有景点太近的，不会加入，会说明原因让用户决定。food 类请用 find_food 搜餐厅。
    加入后请再调用 schedule_days 重新分天。需要 AMAP_KEY（没有则退回 OpenStreetMap，精度较低）。"""
    if len(ids) > MAX_ADOPT:
        raise ToolError(f"一次最多加入 {MAX_ADOPT} 个，请分批。")
    items = _load_cands()
    by_id = {c["id"]: c for c in items}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise ToolError(f"没有这些候选：{'、'.join(missing)}")
    trip = _load()
    lines: list[str] = []
    foods: list[tuple[int, dict[str, Any]]] = []
    for cid in ids:
        c = by_id[cid]
        if c["status"] == "added":
            lines.append(f"· {c['name']}：此前已加入（{c['place_id']}）")
            continue
        if c["kind"] in ("food", "other"):
            lines.append(f"· {c['name']}：是{'餐饮' if c['kind'] == 'food' else '其他'}类，请用 find_food 搜店后 choose_food 安排，没有加入景点")
            if c["kind"] == "food":
                foods.append((len(lines) - 1, c))
            continue
        pick, why, hits = _resolve_name(c["name"])
        if pick is None:
            show = "；".join(f"{h['name']}({h['lat']:.4f},{h['lon']:.4f})" for h in hits[:3])
            lines.append(f"· {c['name']}：没有加入——{why}" + (f"。地图候选：{show}" if show else ""))
            continue
        near = next((p for p in _load().places
                     if _similar_name(p.name, c["name"]) or haversine_km(p.lat, p.lon, pick["lat"], pick["lon"]) < 0.3), None)
        if near is not None:
            lines.append(f"· {c['name']}：没有加入——和已有景点「{near.name}」({near.id}) 重合或相距不到 300 米")
            continue
        clue = f"[游记线索，待核实：{'；'.join(c['clues'])}] " if c["clues"] else ""
        hrs = pick.get("opentime_week") or pick.get("opentime_today") or ""       # 地图这次已经返回了营业时间，一并记下，分天时才知道几点关门
        cl = _amap()
        msg = add_place(pick["name"], round(pick["lat"], 6), round(pick["lon"], 6), source=f"{c['source']}（{c['id']}）",
                        notes=f"{clue}游记原话：{c['quote']}", category=pick.get("category") or "",
                        opening_hours=hrs, hours_source=(("google" if _is_google(cl) else "amap") if hrs else ""))
        pid = msg.split("id=")[1].split(")")[0]

        def _tag(t: Trip, pid: str = pid, c: dict[str, Any] = c) -> None:
            pl = t.place(pid)
            pl.intro = c.get("passage") or c["quote"]            # 游记原文的逐字摘录，不是模型写的
            pl.intro_source = f"游记《{c['source']}》（他人说法，未核实）"
            pl.source_name, pl.source_day = c["source"], c.get("day")

        _save(commit(_load(), _tag))
        c["status"], c["place_id"] = "added", pid
        lines.append(f"· {c['name']}：已加入（地图点：{pick['name']}，{pick.get('address') or ''}；{pid}）")
    _save_cands(items)
    cur = _load()
    for li, c in foods:                       # 餐饮：游记里它前面最近的那个已加入的景点，就是找店的锚点
        prev = [x for x in items if x["source"] == c["source"] and x["status"] == "added" and x["order"] < c["order"] and x["place_id"]]
        if not prev:
            continue
        a = max(prev, key=lambda x: x["order"])
        day = next((d.index + 1 for d in (cur.plan.days if cur.plan else []) for it in d.items if it.place_id == a["place_id"]), None)
        where = f"第 {day} 天" if day else "它所在的那天（先 schedule_days）"
        lines[li] += (f"。游记里它排在「{a['name']}」({a['place_id']}) 之后：没有店名或高德搜不到时，用 suggest_food(day={day or '?'}, "
                      f"after_place_id=\"{a['place_id']}\", keyword=\"餐饮类型，如铁锅炖\") 在那附近按关键词搜（{where}），"
                      "把几家候选给用户选；它们是附近的同类餐厅，不一定是游记里那家，要如实说明")
    return "\n".join(lines) + "\n请再调用 schedule_days 重新分天（门票、时长、营业时间仍待核实，可用 fill_hours 补营业时间）。"


def add_route_place(name: str, waypoints: list[str], stay_per_stop_min: int = 15, notes: str = "", source: str = "agent") -> str:
    """添加一个“路线型景点”（如 citywalk）：按顺序给出途经点的名字（也可以直接用 submit_candidates 得到的候选 id，如 "c2"）。
    每个途经点的坐标由地图查询，名字不符、有歧义或查不到的会报错并列出，不会创建；用户要先确认或换更准确的名字。
    相邻途经点之间的步行路线和时间由高德查（没有 key 时按直线估算并标注）；总时长 = 步行时间 + 每站 stay_per_stop_min 分钟，
    这是估算，可用 update_place 改。排程里它是一项：进入它的路段到第一个途经点，离开它的路段从最后一个途经点出发。
    加入后请再调用 schedule_days，再 refine_routes。"""
    if not (2 <= len(waypoints) <= 12):
        raise ToolError("途经点需要 2~12 个。")
    trip = _load()
    cands = {c["id"]: c for c in _load_cands()}
    resolved: list[tuple[str, dict[str, Any], Optional[dict[str, Any]]]] = []
    problems: list[str] = []
    for w in waypoints:
        cand = cands.get(w)
        wname = cand["name"] if cand else w
        pick, why, hits = _resolve_name(wname)
        if pick is None:
            show = "；".join(f"{h['name']}({h['lat']:.4f},{h['lon']:.4f})" for h in hits[:3])
            problems.append(f"{wname}：{why}" + (f"。地图候选：{show}" if show else ""))
        else:
            resolved.append((wname, pick, cand))
    if problems:
        raise ToolError("有途经点没能确定位置，没有创建：\n" + "\n".join(problems))
    client = _amap()
    wps: list[Waypoint] = []
    for k, (wname, pick, _c) in enumerate(resolved):
        wp = Waypoint(name=pick["name"], lat=round(pick["lat"], 6), lon=round(pick["lon"], 6), amap_id=pick.get("amap_id", "") or "")
        if k > 0:
            prev = wps[-1]
            real = False
            try:
                if client is None:
                    raise AmapError("no key")
                r = client.route("walk", prev.lat, prev.lon, wp.lat, wp.lon, None)
                prev.next_minutes, prev.next_km, prev.next_real = r.minutes, r.distance_km, True
                prev.next_path = [list(pt) for pt in r.path]
                real = True
            except AmapError:
                pass
            if not real:
                leg = estimate_leg("a", prev.lat, prev.lon, "b", wp.lat, wp.lon, "walk")
                prev.next_minutes, prev.next_km, prev.next_real = leg.minutes, leg.distance_km, False
        wps.append(wp)
    walk = sum(w.next_minutes for w in wps)
    duration = max(10, min(720, walk + stay_per_stop_min * len(wps)))
    clat = sum(w.lat for w in wps) / len(wps)
    clon = sum(w.lon for w in wps) / len(wps)
    clue_txt = "；".join(c for _n, _p, cd in resolved if cd for c in cd["clues"])
    note = (f"路线型景点：{'→'.join(w.name for w in wps)}。时长按步行约 {walk} 分钟 + 每站 {stay_per_stop_min} 分钟估算。"
            + (f" [游记线索，待核实：{clue_txt}]" if clue_txt else "") + (" " + notes if notes else "") + " [门票/时长/闭馆日待核实]")
    pid = _next_id("p", [p.id for p in trip.places])
    try:
        place = Place(id=pid, name=name, lat=clat, lon=clon, duration_min=duration, notes=note, source=source, waypoints=wps)
    except ValidationError as e:
        raise ToolError(f"参数不合法：{e}")
    _save(commit(trip, lambda t: t.places.append(place)))
    items = _load_cands()
    used = {cd["id"] for _n, _p, cd in resolved if cd}
    for c in items:
        if c["id"] in used:
            c["status"], c["place_id"] = "added", pid
    if used:
        _save_cands(items)
    overlap = [p.name for p in trip.places if any(haversine_km(p.lat, p.lon, w.lat, w.lon) < 0.3 for w in wps)]
    warn = f"\n注意：途经点离已有景点「{'、'.join(overlap)}」不到 300 米，可能重复，请和用户确认是否保留。" if overlap else ""
    listing = "；".join(f"{k + 1}.{w.name}（{pk.get('address') or pk.get('district') or ''}，{pk.get('category') or '类别未知'}）"
                      for k, (w, (_n, pk, _c)) in enumerate(zip(wps, resolved)))
    return (f"已添加路线型景点「{name}」(id={pid})，地图上匹配到的点：{listing}。请把这些点展示给用户核对。\n{len(wps)} 个途经点，步行约 {walk} 分钟，估算总时长 {duration} 分钟"
            f"（{'步行路线来自高德' if all(w.next_real for w in wps[:-1]) else '部分路段为直线估算'}）。请再 schedule_days。{warn}")

def compare_with_source(source: str = "") -> dict[str, Any]:
    """对照游记的分天和我们的行程（只读，不改任何东西）：游记第 N 天的景点，在我们的行程里落在哪一天、有没有被拆开，
    拆开的原因（闭馆、相距太远，或排程为了整体路程更顺）。source 是游记名（submit_candidates 的 source），不填就看全部游记。
    需要景点来自 adopt_candidates 且游记原文里有“第N天/Day N”标记。把结果如实告诉用户，由用户决定要不要调整。"""
    res = _importplan.compare(_load(), source)
    if not res:
        raise ToolError("没有带分天信息的游记景点。要先用 submit_candidates 提交带“第N天/Day N”标记的游记，再 adopt_candidates 加入景点。")
    return {"groups": res, "note": "这是对照，没有修改行程。想完全按游记的分天来排，需要用户明确说“按游记原样排”，再用 follow_source_days。"}


def follow_source_days(source: str, day_map: Optional[dict[str, int]] = None) -> dict[str, Any]:
    """照搬式：把游记第 N 天的景点放到我们的第 N 天（锁定），天内顺序由排程优化。只有用户明确说“按游记原样排 / 照这篇排”才能调用。
    source：游记名。day_map：可选，游记天数 → 我们的天数，如 {"1": 2, "2": 3}（键用字符串）；不给就同号，超出我们天数的不放并列出来让用户选。
    已被用户锁定的景点不动；去不了的（闭馆、营业时间对不上）照放，但列在 conflicts 里，要如实告诉用户由他决定。
    结果里的 issues 是用我们自己的校验器核查出来的问题。这个操作是一个版本，可以 undo；放进去的景点是锁定状态，之后的 schedule_days 不会再动它们。"""
    trip = _load()
    try:
        dm = {int(k): int(v) for k, v in (day_map or {}).items()}
    except (TypeError, ValueError):
        raise ToolError("day_map 的键和值都要是天数（整数），如 {\"1\": 2}。")
    try:
        new, report = _importplan.follow(trip, source, dm)
    except ValueError as e:
        raise ToolError(str(e))
    _save(new)
    return {"report": report, "plan": _render(new),
            "note": "已按游记分天放置并锁定。conflicts 和 issues 请如实转述；不满意可以 undo。"}


# ---------------------------------------------------------------------------
# MCP 注册
# ---------------------------------------------------------------------------

TOOLS = [
    new_trip, add_place, update_place, remove_place, add_lodging, lookup_coords, refine_routes,
    set_transport_prefs, set_leg_mode, export_text, export_share, draft_travelogue, check_travelogue, add_photo, remove_photo, compare_transport, fill_hours, suggest_food, find_food, choose_food, search_links, remove_food, set_connection, clear_connection, set_travelers, export_map, export_gpx, export_notes, export_handbook, export_calendar, footprint, scan_videos, export_rough_cut, check_trip_changes, import_photo_trip, list_photo_albums, import_bills, spending_summary, scan_bills, set_bills_watch, tag_regions, merge_stops, view_stop, save_stop_story, personal_map_payload, create_amap_map, get_weather, schedule_days, relaxed_alternative, check_plan,
    set_dates, open_workbench, set_provider, list_trips, switch_trip, archive_trip, record_review, record_actual_cost, show_review, final_check, remember_preference, list_preferences, forget_preference, suggest_lodging, set_stays, clear_stays, propose_change, apply_proposal, undo, show_trip,
    submit_candidates, list_candidates, drop_candidates, adopt_candidates, add_route_place, compare_with_source, follow_source_days,
]


_PROFILES = {
    "core": ["行程基础", "景点与住宿", "排程与检查", "路线与交通"],
    "plan": ["行程基础", "景点与住宿", "排程与检查", "路线与交通", "餐食", "攻略与导入", "偏好"],
    "review": ["行程基础", "分享与导出", "复盘与游记"],
}


def _selected_tools(spec: Optional[str] = None) -> list:
    """环境变量 TRIPCORE_TOOLS 可以只暴露一部分工具来省上下文：写档位名（core / plan / review）或目录里的类别名，逗号分隔；
    不设或写 full 就是全部。open_workbench 总是保留，这样没暴露的功能仍可在工作台里用。"""
    from .tools_catalog import CATALOG, CATEGORIES
    spec = (os.environ.get("TRIPCORE_TOOLS", "") if spec is None else spec).strip()
    if not spec or spec.lower() == "full":
        return list(TOOLS)
    want: set[str] = set()
    for part in [x.strip() for x in spec.replace("，", ",").split(",") if x.strip()]:
        if part in _PROFILES:
            want.update(_PROFILES[part])
        elif part in CATEGORIES:
            want.add(part)
        else:
            raise ValueError(f"TRIPCORE_TOOLS 里的 {part!r} 不认识。可用档位：{'、'.join(_PROFILES)}、full；或类别：{'、'.join(CATEGORIES)}。")
    return [f for f in TOOLS if f.__name__ == "open_workbench" or CATALOG[f.__name__][0] in want]


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

    for fn in _selected_tools():
        mcp.tool(name=fn.__name__)(wrap(fn))
    return mcp


def main() -> None:
    build_server().run()  # 默认 stdio


if __name__ == "__main__":
    main()
