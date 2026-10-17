"""自动分天：把“入围”的景点分配到每一天，并排好每天的游览顺序。

思路（全部是确定性的规则，不用大模型，相同输入永远得到相同结果）：

1. 先把用户“锁定”的条目留在原来的那一天。
2. 用“最远点优先”挑出 N 个中心点（N = 天数），让每一天对应地图上的一小块区域。
3. 按“必去 > 重要程度”的顺序，把景点依次分给离它最近、且还有空位、且当天没闭馆的那一天。
4. 用每天的景点位置重新计算中心点，重复几轮直到稳定（类似 k-means）。
5. 每天内部排顺序：景点少时穷举找最省交通时间的顺序，多了就用“最近邻 + 2-opt”。
   如果当天有锁定条目，则保持它们的相对顺序，只把新景点插到最合适的位置。

这是“够用的启发式”，不是数学上最优解。真正的好坏由 validator 来检查。
"""

from __future__ import annotations

import itertools
from datetime import date
from typing import Optional

from .geo import estimate_leg, haversine_km
from .connections import DAY_END_MIN, DAY_START_MIN, day_window
from .metrics import PACE_LIMITS, PaceLimits
from .models import (
    SCHEDULABLE_STATUSES,
    DayItem,
    DayPlan,
    Place,
    PlaceStatus,
    Plan,
    Trip,
    Unscheduled,
)
from .state import commit

MAX_ITERATIONS = 10
BRUTE_FORCE_LIMIT = 7  # 一天景点数不超过这个数时，穷举所有顺序


Point = tuple[float, float]  # (纬度, 经度)


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _pt(p: Place) -> Point:
    return (p.lat, p.lon)


def _dist(a: Point, b: Point) -> float:
    return haversine_km(a[0], a[1], b[0], b[1])


def _mean(points: list[Point]) -> Point:
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def _closed_on(place: Place, day_date: Optional[date]) -> bool:
    return day_date is not None and day_date.weekday() in place.closed_weekdays


MIN_USABLE_MIN = 120      # 某天可用时间窗口不足这么多分钟，就不往里排景点


def day_limits(trip: Trip) -> list[PaceLimits]:
    """每天各自的容量：基准是节奏上限，再按当天可用时间窗口（到达/离开大交通）按比例缩小；
    窗口不足 MIN_USABLE_MIN 的那天容量为 0（不排景点）。"""
    base = PACE_LIMITS[trip.meta.pace]
    full = DAY_END_MIN - DAY_START_MIN
    out: list[PaceLimits] = []
    for i in range(trip.meta.num_days):
        ws, we, _ = day_window(trip, i)
        w = we - ws
        if w < MIN_USABLE_MIN:
            out.append(PaceLimits(max_places=0, max_total_minutes=0))
        elif w >= full:
            out.append(base)
        else:
            r = w / full
            out.append(PaceLimits(max_places=max(1, int(base.max_places * r + 0.5)),
                                  max_total_minutes=max(60, int(base.max_total_minutes * r))))
    return out


def _fits(day_members: list[Place], new: Place, limits: PaceLimits) -> bool:
    """这一天还放得下这个景点吗？（数量和游览时长两个上限）"""
    if len(day_members) + 1 > limits.max_places:
        return False
    if not day_members:
        return True  # 空的一天，哪怕单个景点很长也允许（例如长城）
    visit = sum(p.duration_min for p in day_members) + new.duration_min
    return visit <= limits.max_visit_minutes


# ---------------------------------------------------------------------------
# 核心集合：先决定“哪些景点有机会入选”
# ---------------------------------------------------------------------------

def _core_set(
    candidates: list[Place],
    limits: list[PaceLimits],
    used_count: int,
    used_visit: int,
) -> list[Place]:
    """按“必去 > 重要程度”挑出总容量放得下的景点。

    为什么需要它？如果直接用所有景点（包括很远、很不重要的）去选“每天的中心点”，
    一个偏远的低优先级景点就会占掉一整天的中心位置。先挑出核心集合，再选中心，就不会这样。
    """
    max_count = sum(l.max_places for l in limits) - used_count
    max_visit = sum(l.max_visit_minutes for l in limits) - used_visit
    core: list[Place] = []
    count, visit = 0, 0
    for p in sorted(candidates, key=lambda p: (not p.must_go, -p.priority, p.name, p.id)):
        if p.must_go or (count < max_count and visit + p.duration_min <= max_visit):
            core.append(p)
            count += 1
            visit += p.duration_min
    return core


# ---------------------------------------------------------------------------
# 中心点
# ---------------------------------------------------------------------------

def _init_centers(
    candidates: list[Place],
    fixed: list[Optional[Point]],
    anchor: Optional[Point],
    blocked: frozenset[int] = frozenset(),
) -> list[Optional[Point]]:
    """给每一天挑一个中心点（blocked 的天没有可用时间，不给中心点）。fixed[i] 不为 None 的天（有锁定条目）中心点已确定。"""
    centers: list[Optional[Point]] = list(fixed)
    chosen: list[Point] = [c for c in centers if c is not None]
    pool = [_pt(p) for p in candidates]
    generated: list[Point] = []

    free_slots = [i for i, c in enumerate(centers) if c is None and i not in blocked]
    if pool and free_slots:
        if not chosen:
            centroid = _mean(pool)
            first = max(pool, key=lambda q: (_dist(q, centroid), q))
            generated.append(first)
            chosen.append(first)
        while len(generated) < len(free_slots):
            remaining = [q for q in pool if q not in chosen]
            if not remaining:
                break
            nxt = max(remaining, key=lambda q: (min(_dist(q, c) for c in chosen), q))
            generated.append(nxt)
            chosen.append(nxt)

    # 把新生成的中心点按“最近邻路径”排序，让相邻的天在地理上也相邻
    ordered: list[Point] = []
    left = generated[:]
    if left:
        start_ref = anchor if anchor else left[0]
        cur = min(left, key=lambda q: (_dist(q, start_ref), q))
        ordered.append(cur)
        left.remove(cur)
        while left:
            cur = min(left, key=lambda q: (_dist(q, cur), q))
            ordered.append(cur)
            left.remove(cur)

    for slot, c in zip(free_slots, ordered):
        centers[slot] = c
    return centers


# ---------------------------------------------------------------------------
# 分配
# ---------------------------------------------------------------------------

def _assign(
    trip: Trip,
    candidates: list[Place],
    locked_members: list[list[Place]],
    centers: list[Optional[Point]],
    limits: list[PaceLimits],
) -> tuple[list[list[Place]], list[Unscheduled]]:
    n_days = len(centers)
    members: list[list[Place]] = [list(m) for m in locked_members]
    unscheduled: list[Unscheduled] = []

    order = sorted(candidates, key=lambda p: (not p.must_go, -p.priority, p.name, p.id))
    for p in order:
        ranked = sorted(
            (i for i in range(n_days) if centers[i] is not None),
            key=lambda i: (_dist(_pt(p), centers[i]), i),  # type: ignore[arg-type]
        )
        open_days = [i for i in ranked if not _closed_on(p, trip.day_date(i))]
        if not open_days:
            unscheduled.append(Unscheduled(place_id=p.id, reason="安排期内每一天都闭馆"))
            continue

        target = next((i for i in open_days if _fits(members[i], p, limits[i])), None)
        if target is None:
            if p.must_go:
                # 必去但放不下：放进当天游览时间最少的那天，让校验器提醒“太满”
                target = min(open_days, key=lambda i: (sum(x.duration_min for x in members[i]), i))
            else:
                unscheduled.append(
                    Unscheduled(place_id=p.id, reason="超出每日容量（可增加天数或调高节奏）")
                )
                continue
        members[target].append(p)
    return members, unscheduled


# ---------------------------------------------------------------------------
# 天内排序
# ---------------------------------------------------------------------------

def _route_minutes(seq: list[Place], anchor: Optional[Point], mode: str) -> int:
    """按这个顺序走完一天的交通总分钟（有住宿就算往返，没有就是开放路径）。"""
    total = 0
    for a, b in zip(seq, seq[1:]):
        total += estimate_leg(a.id, a.lat, a.lon, b.id, b.lat, b.lon, mode).minutes  # type: ignore[arg-type]
    if anchor and seq:
        f, l = seq[0], seq[-1]
        total += estimate_leg("A", anchor[0], anchor[1], f.id, f.lat, f.lon, mode).minutes  # type: ignore[arg-type]
        total += estimate_leg(l.id, l.lat, l.lon, "A", anchor[0], anchor[1], mode).minutes  # type: ignore[arg-type]
    return total


def _two_opt(seq: list[Place], anchor: Optional[Point], mode: str) -> list[Place]:
    best = seq[:]
    best_cost = _route_minutes(best, anchor, mode)
    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                cand = best[:i] + best[i : j + 1][::-1] + best[j + 1 :]
                cost = _route_minutes(cand, anchor, mode)
                if cost < best_cost:
                    best, best_cost, improved = cand, cost, True
    return best


def order_day(
    fixed: list[Place],
    new: list[Place],
    anchor: Optional[Point],
    mode: str,
) -> list[Place]:
    """给一天排顺序。

    fixed：锁定的条目（保持它们的相对顺序）；new：待安排的新景点。
    """
    if not fixed:
        items = sorted(new, key=lambda p: p.id)  # 先排序，保证结果可重复
        if len(items) <= 1:
            return items
        if len(items) <= BRUTE_FORCE_LIMIT:
            best, best_cost = None, None
            for perm in itertools.permutations(items):
                cost = _route_minutes(list(perm), anchor, mode)
                if best_cost is None or cost < best_cost:
                    best, best_cost = list(perm), cost
            return best  # type: ignore[return-value]
        # 景点很多：最近邻 + 2-opt
        start = anchor or _pt(items[0])
        left = items[:]
        cur = min(left, key=lambda p: (_dist(_pt(p), start), p.id))
        seq = [cur]
        left.remove(cur)
        while left:
            cur = min(left, key=lambda p: (_dist(_pt(p), _pt(cur)), p.id))
            seq.append(cur)
            left.remove(cur)
        return _two_opt(seq, anchor, mode)

    # 有锁定条目：保持相对顺序，把新景点逐个插到“交通增加最少”的位置
    seq = fixed[:]
    for p in sorted(new, key=lambda p: (-p.priority, p.id)):
        best_pos, best_cost = 0, None
        for pos in range(len(seq) + 1):
            cand = seq[:pos] + [p] + seq[pos:]
            cost = _route_minutes(cand, anchor, mode)
            if best_cost is None or cost < best_cost:
                best_pos, best_cost = pos, cost
        seq.insert(best_pos, p)
    return seq


# ---------------------------------------------------------------------------
# 局部优化：在不同天之间移动/交换景点，减少总交通时间
# ---------------------------------------------------------------------------

def _improve(
    trip: Trip,
    members: list[list[Place]],
    locked_members: list[list[Place]],
    limits: list[PaceLimits],
    anchor: Optional[Point],
    mode: str,
    max_rounds: int = 6,
) -> list[list[Place]]:
    """反复尝试“移动一个景点到别的天”或“和别的天交换一个景点”，
    只要总交通分钟明显减少、并且不违反容量/闭馆/锁定规则，就采纳。
    规则：不会把某一天掏空；被锁定的条目不会被动。
    """
    n = len(members)
    members = [list(m) for m in members]
    locked_ids = {p.id for m in locked_members for p in m}
    cache: dict[tuple, int] = {}

    def cost(i: int, mem: list[Place]) -> int:
        if not mem:
            return 0
        key = (i, tuple(sorted(p.id for p in mem)))
        if key not in cache:
            fixed = locked_members[i]
            fixed_ids = {p.id for p in fixed}
            new = [p for p in mem if p.id not in fixed_ids]
            cache[key] = _route_minutes(order_day(fixed, new, anchor, mode), anchor, mode)
        return cache[key]

    def ok(i: int, mem: list[Place]) -> bool:
        d = trip.day_date(i)
        if any(_closed_on(p, d) for p in mem):
            return False
        if mem and limits[i].max_places == 0:
            return False
        if len(mem) <= 1:
            return True
        if len(mem) > limits[i].max_places:
            return False
        return sum(p.duration_min for p in mem) <= limits[i].max_visit_minutes

    for _ in range(max_rounds):
        changed = False
        for i in range(n):
            for p in sorted(members[i], key=lambda x: x.id):
                if p.id in locked_ids or p not in members[i]:
                    continue
                cur_i = members[i]
                # (a) 移动 p 到别的天
                for j in range(n):
                    if j == i or p not in members[i]:
                        continue
                    new_i = [x for x in members[i] if x.id != p.id]
                    new_j = members[j] + [p]
                    if not new_i or not ok(j, new_j) or not ok(i, new_i):
                        continue
                    delta = cost(i, new_i) + cost(j, new_j) - cost(i, members[i]) - cost(j, members[j])
                    if delta < -1:
                        members[i], members[j] = new_i, new_j
                        changed = True
                        break
                if p not in members[i]:
                    continue
                # (b) 和别的天的某个景点交换
                for j in range(n):
                    if j == i or p not in members[i]:
                        continue
                    for q in sorted(members[j], key=lambda x: x.id):
                        if q.id in locked_ids:
                            continue
                        new_i = [x for x in members[i] if x.id != p.id] + [q]
                        new_j = [x for x in members[j] if x.id != q.id] + [p]
                        if not ok(i, new_i) or not ok(j, new_j):
                            continue
                        delta = cost(i, new_i) + cost(j, new_j) - cost(i, members[i]) - cost(j, members[j])
                        if delta < -1:
                            members[i], members[j] = new_i, new_j
                            changed = True
                            break
        if not changed:
            break
    return members


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

def build_plan(trip: Trip, keep_locked: bool = True) -> Plan:
    """根据当前景点池生成一份新行程（不修改 trip，只返回 Plan）。"""
    n_days = trip.meta.num_days
    limits = day_limits(trip)
    blocked = frozenset(i for i, l in enumerate(limits) if l.max_places == 0)
    lodging = trip.lodging_for_day(0)
    anchor: Optional[Point] = (lodging.lat, lodging.lon) if lodging else None
    if len({s.lodging_id for s in trip.stays}) > 1:
        anchor = None     # 多家酒店时没有单一的锚点，分天只看景点本身的远近
    mode = trip.meta.mode

    # 1. 保留锁定条目
    locked_members: list[list[Place]] = [[] for _ in range(n_days)]
    locked_ids: set[str] = set()
    if keep_locked and trip.plan:
        for d in trip.plan.days:
            if d.index >= n_days:
                continue
            for it in d.items:
                if it.locked:
                    locked_members[d.index].append(trip.place(it.place_id))
                    locked_ids.add(it.place_id)

    candidates = [
        p for p in trip.places if p.status in SCHEDULABLE_STATUSES and p.id not in locked_ids
    ]

    # 2. 中心点：有锁定条目的天，中心点取锁定景点的平均位置
    fixed: list[Optional[Point]] = [
        _mean([_pt(p) for p in m]) if m else None for m in locked_members
    ]
    used_count = sum(len(m) for m in locked_members)
    used_visit = sum(p.duration_min for m in locked_members for p in m)
    core = _core_set(candidates, limits, used_count, used_visit)
    centers = _init_centers(core, fixed, anchor, blocked)

    # 3~4. 分配 → 重算中心 → 重复，直到不再变化
    members: list[list[Place]] = locked_members
    unscheduled: list[Unscheduled] = []
    prev_signature: Optional[list[list[str]]] = None
    for _ in range(MAX_ITERATIONS):
        members, unscheduled = _assign(trip, candidates, locked_members, centers, limits)
        signature = [sorted(p.id for p in m) for m in members]
        if signature == prev_signature:
            break
        prev_signature = signature
        for i, m in enumerate(members):
            if m:
                centers[i] = _mean([_pt(p) for p in m])

    # 4.5 局部优化：跨天移动/交换景点，减少总交通时间
    members = _improve(trip, members, locked_members, limits, anchor, mode)

    # 5. 天内排序
    days: list[DayPlan] = []
    for i in range(n_days):
        fixed_here = locked_members[i]
        fixed_ids = {p.id for p in fixed_here}
        new_here = [p for p in members[i] if p.id not in fixed_ids]
        seq = order_day(fixed_here, new_here, anchor, mode)
        items = [DayItem(place_id=p.id, locked=p.id in fixed_ids) for p in seq]
        days.append(DayPlan(index=i, items=items))

    return Plan(days=days, unscheduled=unscheduled)


def schedule(trip: Trip, keep_locked: bool = True) -> Trip:
    """生成行程并写入一个新版本的 Trip（可撤销）。已安排的景点状态会变为 planned。"""
    plan = build_plan(trip, keep_locked=keep_locked)

    def mutate(t: Trip) -> None:
        t.plan = plan
        scheduled = {it.place_id for d in plan.days for it in d.items}
        for p in t.places:
            if p.id in scheduled:
                if p.status == PlaceStatus.SHORTLIST:
                    p.status = PlaceStatus.PLANNED
            elif p.status == PlaceStatus.PLANNED:
                p.status = PlaceStatus.SHORTLIST  # 之前排了、这次没排上，退回“入围”

    return commit(trip, mutate)
