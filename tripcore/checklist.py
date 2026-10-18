"""定稿前清单：把“现在还有什么没弄清楚/没处理”一次列出来（确定性规则，不用模型）。

校验器的问题（check_plan）原样带上，再补一些校验器不管的“准备工作”类事项：
待核实的资料、没匹配到高德的点、仍是估算的交通、天气是否查过、到达/离开是否订了等。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from .mealgaps import meal_gaps
from .metrics import day_stats
from .models import DateMode, Trip
from .validator import validate

WEATHER_STALE_DAYS = 3      # 预报超过这么多天没刷新，提醒出发前再查


@dataclass(frozen=True)
class Item:
    severity: str            # error / warning / info
    category: str
    text: str


def build_checklist(trip: Trip, today: Optional[date] = None) -> list[Item]:
    today = today or date.today()
    out: list[Item] = []
    if trip.plan is None:
        return [Item("error", "行程", "还没有分天，请先 schedule_days。")]

    for i in validate(trip):
        out.append(Item(i.severity, "行程检查", i.message))

    placed = [trip.place(it.place_id) for d in trip.plan.days for it in d.items]

    # 住宿：每一晚都要有着落
    if trip.meta.num_days > 1:
        missing = [n + 1 for n in range(trip.meta.num_days - 1) if trip.lodging_for_day(n) is None]
        if missing:
            out.append(Item("warning", "住宿", f"第 {'、'.join(map(str, missing))} 晚还没有选定住宿。"))

    # 用餐：游览时段覆盖了饭点但还没选餐厅
    for idx, names in sorted(meal_gaps(trip).items()):
        out.append(Item("info", "用餐", f"第 {idx + 1} 天还没安排{'、'.join(names)}（用 suggest_food 在附近找，或 find_food 找指定的店）。"))

    # 大交通
    for label, c in (("到达", trip.arrival), ("离开", trip.departure)):
        if c is None:
            out.append(Item("info", "大交通", f"还没有设置{label}的大交通，第一天/最后一天的安排只能按全天估计。"))
        elif not c.booked:
            out.append(Item("warning", "大交通", f"{label}（{c.number or c.kind} {c.dep_time:%m-%d %H:%M}）还没有订。"))

    # 日期 / 天气
    if trip.meta.date_mode != DateMode.EXACT:
        out.append(Item("info", "日期", "出行日期还没定死，闭馆日、天气、大交通衔接的检查都不完整。"))
    else:
        dates = [trip.day_date(d.index) for d in trip.plan.days]
        dates = [x for x in dates if x]
        have = [trip.weather[x.isoformat()] for x in dates if x.isoformat() in trip.weather]
        if not have:
            out.append(Item("info", "天气", "还没有查过天气（日期确定后用 get_weather；超出预报范围的天会显示暂无预报）。"))
        else:
            old = [w for w in have if w.fetched and (today - date.fromisoformat(w.fetched)).days > WEATHER_STALE_DAYS]
            if old:
                out.append(Item("info", "天气", f"天气预报是 {old[0].fetched} 查的，已超过 {WEATHER_STALE_DAYS} 天，出发前请再查一次。"))
            nof = [x for x in dates if x.isoformat() not in trip.weather]
            if nof:
                out.append(Item("info", "天气", f"{len(nof)} 天还没有预报（超出预报范围，临近再查）。"))

    # 待核实的资料
    unverified = [p.name for p in placed if "待核实" in p.notes]
    if unverified:
        out.append(Item("info", "资料", f"这些景点的门票/时长/闭馆日还是“待核实”：{'、'.join(unverified[:8])}" + ("…" if len(unverified) > 8 else "")))
    nohours = [p.name for p in placed if not p.opening_hours and not p.waypoints]
    if nohours:
        out.append(Item("info", "资料", f"这些景点没有营业时间（可用 fill_hours 补）：{'、'.join(nohours[:8])}" + ("…" if len(nohours) > 8 else "")))

    # 地图点位 / 路线
    noid = [p.name for p in placed if not p.amap_id and not p.waypoints]
    if noid:
        out.append(Item("info", "地图", f"{len(noid)} 个景点还没匹配高德 POI，生成专属地图时可能被跳过：{'、'.join(noid[:6])}" + ("…" if len(noid) > 6 else "")))
    est = 0
    for d in trip.plan.days:
        st = day_stats(trip, d)
        est += sum(1 for leg in [*st.legs, st.lodging_out, st.lodging_back] if leg is not None and leg.detail_level == "estimate")
    if est:
        out.append(Item("info", "路线", f"有 {est} 段交通仍是估算值（直线换算），可用 refine_routes 换成高德真实路线。"))

    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda x: order[x.severity])
    return out


def render(items: list[Item]) -> str:
    if not items:
        return "✅ 没有发现需要处理的事项。"
    icon = {"error": "✗", "warning": "!", "info": "·"}
    n_err = sum(1 for i in items if i.severity == "error")
    n_warn = sum(1 for i in items if i.severity == "warning")
    head = f"定稿前清单：{n_err} 个必须处理，{n_warn} 个建议处理，{len(items) - n_err - n_warn} 个提示。"
    body = [f"{icon[i.severity]} [{i.category}] {i.text}" for i in items]
    return head + "\n" + "\n".join(body)
