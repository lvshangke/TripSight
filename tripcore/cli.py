"""命令行入口。用法见 README.md。

    python -m tripcore demo
    python -m tripcore plan examples/beijing.json
    python -m tripcore geocode "故宫博物院" --city 北京
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .geocode import GeocodeError, geocode
from .lodging import rank_lodgings, suggest_stay_area
from .metrics import day_stats, estimate_cost
from .models import DateMode, Pace, Trip
from .scheduler import schedule
from .state import undo as undo_trip
from .storage import load_trip, save_trip
from .validator import validate

_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_MODE_NAMES = {"walk": "步行", "transit": "公共交通", "drive": "驾车"}
_SEV_ICON = {"error": "✗", "warning": "!", "info": "·"}
_DEMO_FILE = Path(__file__).resolve().parent.parent / "examples" / "beijing.json"


def _print_plan(trip: Trip) -> None:
    assert trip.plan is not None
    print(f"\n=== {trip.meta.name} ===")
    print(f"节奏：{trip.meta.pace.value}　交通偏好：{_MODE_NAMES[trip.meta.mode]}　共 {trip.meta.num_days} 天")
    lodging = trip.chosen_lodging
    if lodging:
        print(f"住宿：{lodging.name}")
    if trip.stays:
        names = {l.id: l.name for l in trip.lodgings}
        print("分段住宿：" + "；".join(f"第{a.from_day + 1}–{a.to_day + 1}晚 {names[a.lodging_id]}" for a in trip.stays))

    for day in trip.plan.days:
        st = day_stats(trip, day)
        d = trip.day_date(day.index)
        date_txt = f" {d.isoformat()}（{_WEEKDAYS[d.weekday()]}）" if d else ""
        print(f"\n第{day.index + 1}天{date_txt}  游览 {st.visit_min} 分钟 + 交通约 {st.travel_min} 分钟")
        if not st.places:
            print("  （空）")
            continue
        if st.lodging_out:
            print(f"  [住宿出发] ≈{st.lodging_out.minutes} 分钟（{_MODE_NAMES[st.lodging_out.mode]}）")
        for i, p in enumerate(st.places):
            lock = " 🔒" if day.items[i].locked else ""
            print(f"  {i + 1}. {p.name}（{p.duration_min} 分钟）{lock}")
            if i < len(st.legs):
                leg = st.legs[i]
                print(f"      ↓ 约 {leg.minutes} 分钟（{_MODE_NAMES[leg.mode]}，{leg.distance_km} km，估算）")
        if st.lodging_back:
            print(f"  [返回住宿] ≈{st.lodging_back.minutes} 分钟（{_MODE_NAMES[st.lodging_back.mode]}）")

    if trip.plan.unscheduled:
        print("\n未能安排：")
        for u in trip.plan.unscheduled:
            print(f"  - {trip.place(u.place_id).name}：{u.reason}")

    cost = estimate_cost(trip)
    print(f"\n粗略费用（仅门票+住宿）：{cost.total:.0f} {trip.meta.currency}")


def _print_issues(trip: Trip) -> None:
    issues = validate(trip)
    print("\n--- 检查结果 ---")
    if not issues:
        print("没有发现问题 ✓")
        return
    for i in issues:
        print(f"{_SEV_ICON[i.severity]} [{i.severity}] {i.message}")


def _cmd_plan(args: argparse.Namespace) -> int:
    trip = load_trip(args.file)
    if args.days:
        if trip.meta.date_mode == DateMode.EXACT and args.days != trip.meta.num_days:
            print(
                f"这个行程的日期已经确定（共 {trip.meta.num_days} 天），天数由日期决定。"
                "如需改天数，请修改 JSON 里的 start_date / end_date，或把 date_mode 改为 range / unknown。",
                file=sys.stderr,
            )
            return 2
        trip.meta.num_days = args.days
    if args.pace:
        trip.meta.pace = Pace(args.pace)
    if args.mode:
        trip.meta.mode = args.mode
    if args.lodging:
        ids = {l.id for l in trip.lodgings}
        if args.lodging not in ids:
            print(f"找不到住宿 id：{args.lodging}（可选：{', '.join(sorted(ids))}）", file=sys.stderr)
            return 2
        trip.chosen_lodging_id = args.lodging

    trip = schedule(trip)
    _print_plan(trip)
    _print_issues(trip)
    if args.out:
        save_trip(trip, args.out)
        print(f"\n已保存到 {args.out}")
    return 0


def _cmd_demo(_: argparse.Namespace) -> int:
    trip = load_trip(_DEMO_FILE)
    print("（示例数据：坐标和闭馆日为近似值，仅用于演示）")
    # 第一次：没选住宿
    trip = schedule(trip)
    _print_plan(trip)
    _print_issues(trip)
    # 住宿推荐
    area = suggest_stay_area(trip)
    if area:
        print(f"\n推荐住宿区域中心：({area.lat:.4f}, {area.lon:.4f})，半径约 {area.radius_km} km，"
              f"到各景点平均约 {area.avg_minutes_to_places} 分钟")
    print("\n候选住宿排名（按平均通勤）：")
    ranked = rank_lodgings(trip)
    for r in ranked:
        print(f"  - {r.lodging.name}：平均 {r.avg_commute_min} 分钟，最远 {r.worst_commute_min} 分钟，"
              f"每晚约 {r.price_mid:.0f} 元")
    # 选最优住宿后重排
    if ranked:
        trip.chosen_lodging_id = ranked[0].lodging.id
        trip = schedule(trip)
        print(f"\n>>> 选定「{ranked[0].lodging.name}」后重新安排：")
        _print_plan(trip)
        _print_issues(trip)
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    trip = load_trip(args.file)
    if trip.plan is None:
        print("这个文件里还没有行程，请先运行 plan。", file=sys.stderr)
        return 2
    _print_plan(trip)
    _print_issues(trip)
    return 0


def _cmd_undo(args: argparse.Namespace) -> int:
    trip = load_trip(args.file)
    trip = undo_trip(trip)
    save_trip(trip, args.file)
    print("已撤销最近一次修改。")
    return 0


def _cmd_geocode(args: argparse.Namespace) -> int:
    try:
        r = geocode(args.query, city=args.city)
    except GeocodeError as e:
        print(f"失败：{e}", file=sys.stderr)
        return 1
    print(f"{r['name']}: lat={r['lat']}, lon={r['lon']}")
    print(f"  来源地址：{r['display_name']}")
    print("  提示：请核对结果是否是你想要的那个地点。")
    return 0


def _cmd_web(args: argparse.Namespace) -> int:
    from .web import serve
    return serve(port=args.port, url_file=args.url_file, open_browser=args.open, idle_seconds=args.idle_minutes * 60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tripcore", description="旅行规划核心（里程碑 1：无 AI、无界面）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("demo", help="用示例数据完整演示一遍").set_defaults(func=_cmd_demo)

    p = sub.add_parser("plan", help="读取 JSON 文件，自动分天并检查")
    p.add_argument("file")
    p.add_argument("--days", type=int, help="覆盖天数")
    p.add_argument("--pace", choices=[x.value for x in Pace], help="覆盖节奏")
    p.add_argument("--mode", choices=["walk", "transit", "drive"], help="覆盖交通偏好")
    p.add_argument("--lodging", help="选定某个住宿 id")
    p.add_argument("--out", help="把结果保存到这个 JSON 文件")
    p.set_defaults(func=_cmd_plan)

    p = sub.add_parser("check", help="检查一个已有行程的 JSON 文件")
    p.add_argument("file")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("undo", help="撤销 JSON 文件里的最近一次修改")
    p.add_argument("file")
    p.set_defaults(func=_cmd_undo)

    p = sub.add_parser("geocode", help="查询地名的经纬度（需要联网）")
    p.add_argument("query")
    p.add_argument("--city")
    p.set_defaults(func=_cmd_geocode)

    p = sub.add_parser("web", help="启动本机网页工作台（拖拽调整行程、月历选日期）")
    p.add_argument("--port", type=int, default=0, help="端口，默认随机")
    p.add_argument("--url-file", help="把网址写到这个文件（供程序读取）")
    p.add_argument("--open", action="store_true", help="启动后自动用浏览器打开")
    p.add_argument("--idle-minutes", type=float, default=120, help="空闲多久自动退出")
    p.set_defaults(func=_cmd_web)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
