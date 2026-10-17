"""提案（Proposal）：Agent（或你自己）想做的修改，先写成“提案”，确认后才真正执行。

为什么要这样设计？
- 大模型可能会提出不合理的修改，让人先看一眼“改前 → 改后”再决定，更安全。
- 提案记录了它基于哪个版本（base_revision）生成。如果行程在此期间已经变了，
  提案就过期了，不能再套用，避免把别人刚改好的东西覆盖掉。
- 用户锁定的条目不允许被提案移动。

目前支持 4 种操作：move（移动）、remove（移出行程）、set_status（改状态）、lock（锁定/解锁）。
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

from .models import DayItem, DayPlan, PlaceStatus, Plan, Trip
from .state import commit


class StaleProposalError(Exception):
    """提案基于的版本已经过期。"""


class LockedItemError(Exception):
    """试图移动被锁定的条目。"""


class InvalidOperationError(Exception):
    """操作本身不合法（景点或天数不存在等）。"""


class MoveOp(BaseModel):
    kind: Literal["move"] = "move"
    place_id: str
    to_day: int = Field(ge=0)
    to_position: Optional[int] = Field(default=None, ge=0, description="放在当天第几个；不填就放最后")


class RemoveOp(BaseModel):
    kind: Literal["remove"] = "remove"
    place_id: str


class SetStatusOp(BaseModel):
    kind: Literal["set_status"] = "set_status"
    place_id: str
    status: PlaceStatus


class LockOp(BaseModel):
    kind: Literal["lock"] = "lock"
    place_id: str
    locked: bool = True


Op = Annotated[Union[MoveOp, RemoveOp, SetStatusOp, LockOp], Field(discriminator="kind")]


class Proposal(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    summary: str
    ops: list[Op]
    base_revision: int
    rationale: str = ""
    created_by: str = "user"


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _find(plan: Plan, place_id: str) -> Optional[tuple[int, int]]:
    """返回 (第几天, 第几个)；不在行程里返回 None。"""
    for d in plan.days:
        for pos, it in enumerate(d.items):
            if it.place_id == place_id:
                return d.index, pos
    return None


def _get_item(plan: Plan, place_id: str) -> Optional[DayItem]:
    loc = _find(plan, place_id)
    if loc is None:
        return None
    return plan.days[loc[0]].items[loc[1]]


def _ensure_plan(t: Trip) -> Plan:
    if t.plan is None:
        t.plan = Plan(days=[DayPlan(index=i) for i in range(t.meta.num_days)])
    return t.plan


def _apply_one(t: Trip, op: Op) -> None:
    t.place(op.place_id)  # 不存在会抛 KeyError

    if isinstance(op, SetStatusOp):
        # 设为“排除/想法”的景点不该继续留在行程里：一并移出（锁定的不允许）
        if op.status in (PlaceStatus.EXCLUDED, PlaceStatus.IDEA) and t.plan is not None:
            loc = _find(t.plan, op.place_id)
            if loc is not None:
                if t.plan.days[loc[0]].items[loc[1]].locked:
                    raise LockedItemError(f"「{t.place(op.place_id).name}」已锁定，不能排除")
                t.plan.days[loc[0]].items.pop(loc[1])
        t.place(op.place_id).status = op.status
        return

    plan = _ensure_plan(t)

    if isinstance(op, MoveOp):
        if op.to_day >= len(plan.days):
            raise InvalidOperationError(f"没有第 {op.to_day + 1} 天（共 {len(plan.days)} 天）")
        existing = _get_item(plan, op.place_id)
        if existing is not None and existing.locked:
            raise LockedItemError(f"「{t.place(op.place_id).name}」已锁定（用户确认过的安排默认锁定），不能移动；要改的话在同一个提案里先加一条 lock 操作（locked=false）解锁，再移动")
        loc = _find(plan, op.place_id)
        if loc is not None:
            plan.days[loc[0]].items.pop(loc[1])
        target = plan.days[op.to_day].items
        pos = len(target) if op.to_position is None else min(op.to_position, len(target))
        target.insert(pos, DayItem(place_id=op.place_id, locked=True))   # 用户确认过的安排默认锁定，之后的自动分天不会再改
        if t.place(op.place_id).status == PlaceStatus.SHORTLIST:
            t.place(op.place_id).status = PlaceStatus.PLANNED
        plan.unscheduled = [u for u in plan.unscheduled if u.place_id != op.place_id]

    elif isinstance(op, RemoveOp):
        existing = _get_item(plan, op.place_id)
        if existing is None:
            raise InvalidOperationError(f"「{t.place(op.place_id).name}」不在行程中")
        if existing.locked:
            raise LockedItemError(f"「{t.place(op.place_id).name}」已锁定，不能移出")
        loc = _find(plan, op.place_id)
        assert loc is not None
        plan.days[loc[0]].items.pop(loc[1])
        if t.place(op.place_id).status == PlaceStatus.PLANNED:
            t.place(op.place_id).status = PlaceStatus.SHORTLIST

    elif isinstance(op, LockOp):
        existing = _get_item(plan, op.place_id)
        if existing is None:
            raise InvalidOperationError(f"「{t.place(op.place_id).name}」不在行程中，无法锁定")
        existing.locked = op.locked


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------

def make_proposal(trip: Trip, summary: str, ops: list[Op], rationale: str = "", created_by: str = "user") -> Proposal:
    """基于当前版本创建一个提案。"""
    return Proposal(summary=summary, ops=ops, base_revision=trip.revision, rationale=rationale, created_by=created_by)


def apply_proposal(trip: Trip, proposal: Proposal) -> Trip:
    """套用提案，返回新版本的 Trip（原来的 trip 不变）。

    任何一步失败，整个提案都不会生效（因为是在副本上操作，失败就丢弃副本）。
    """
    if proposal.base_revision != trip.revision:
        raise StaleProposalError(
            f"提案基于版本 {proposal.base_revision}，但当前已是版本 {trip.revision}，请重新生成提案。"
        )

    def mutate(t: Trip) -> None:
        for op in proposal.ops:
            _apply_one(t, op)

    return commit(trip, mutate)


def describe_ops(trip: Trip, proposal: Proposal) -> list[str]:
    """把提案翻译成“改前 → 改后”的人话，供用户确认前查看。"""

    def where(plan: Optional[Plan], pid: str) -> str:
        if plan is None:
            return "未安排"
        loc = _find(plan, pid)
        return "未安排" if loc is None else f"第{loc[0] + 1}天第{loc[1] + 1}个"

    lines: list[str] = []
    for op in proposal.ops:
        name = trip.place(op.place_id).name
        if isinstance(op, MoveOp):
            pos = "最后" if op.to_position is None else f"第{op.to_position + 1}个"
            lines.append(f"移动「{name}」：{where(trip.plan, op.place_id)} → 第{op.to_day + 1}天{pos}")
        elif isinstance(op, RemoveOp):
            lines.append(f"移出「{name}」：{where(trip.plan, op.place_id)} → 未安排")
        elif isinstance(op, SetStatusOp):
            lines.append(f"「{name}」状态：{trip.place(op.place_id).status.value} → {op.status.value}")
        elif isinstance(op, LockOp):
            lines.append(f"{'锁定' if op.locked else '解锁'}「{name}」")
    return lines
