"""状态管理：每次修改都留快照（可撤销），并让版本号 +1。

核心规则：任何修改都不直接改原对象，而是“复制一份 → 改 → 版本号 +1 → 旧版本存进历史”。
这样撤销很简单，而且过期的提案（基于旧版本生成的）可以被检测出来。
"""

from __future__ import annotations

from typing import Callable

from .models import Trip

MAX_HISTORY = 20


class NothingToUndo(Exception):
    pass


def _snapshot(trip: Trip) -> dict:
    return trip.model_dump(mode="json", exclude={"history"})


def commit(trip: Trip, mutate: Callable[[Trip], None]) -> Trip:
    """复制 trip，对副本执行 mutate，然后返回新版本（版本号 +1，旧版本进入历史）。"""
    new = trip.model_copy(deep=True)
    snapshot = _snapshot(trip)
    mutate(new)
    new.history = (trip.history + [snapshot])[-MAX_HISTORY:]
    new.revision = trip.revision + 1
    return new


def undo(trip: Trip) -> Trip:
    """撤销最近一次修改。版本号仍然 +1，这样撤销前生成的提案会失效。"""
    if not trip.history:
        raise NothingToUndo("没有可以撤销的历史")
    *rest, last = trip.history
    restored = Trip.model_validate(last)
    restored.history = rest
    restored.revision = trip.revision + 1
    return restored
