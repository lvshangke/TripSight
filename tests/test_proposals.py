import pytest

from tripcore.models import PlaceStatus
from tripcore.proposals import (
    InvalidOperationError,
    LockedItemError,
    LockOp,
    MoveOp,
    Proposal,
    RemoveOp,
    SetStatusOp,
    StaleProposalError,
    apply_proposal,
    describe_ops,
    make_proposal,
)
from tripcore.scheduler import schedule
from tripcore.state import NothingToUndo, undo


def _find(t, pid):
    for d in t.plan.days:
        for pos, it in enumerate(d.items):
            if it.place_id == pid:
                return d.index, pos
    return None


@pytest.fixture
def planned(beijing):
    return schedule(beijing)


def test_move_changes_position_and_bumps_revision(planned):
    pid = planned.plan.days[1].items[0].place_id
    prop = make_proposal(planned, "挪到第 3 天末尾", [MoveOp(place_id=pid, to_day=2)])
    new = apply_proposal(planned, prop)
    assert _find(new, pid)[0] == 2
    assert new.revision == planned.revision + 1
    # 原对象不变
    assert _find(planned, pid)[0] == 1


def test_stale_proposal_rejected(planned):
    pid = planned.plan.days[1].items[0].place_id
    prop = make_proposal(planned, "x", [MoveOp(place_id=pid, to_day=2)])
    newer = apply_proposal(planned, make_proposal(planned, "y", [SetStatusOp(place_id=pid, status=PlaceStatus.CONFIRMED)]))
    with pytest.raises(StaleProposalError):
        apply_proposal(newer, prop)


def test_locked_item_cannot_be_moved(planned):
    pid = planned.plan.days[1].items[0].place_id
    locked = apply_proposal(planned, make_proposal(planned, "锁定", [LockOp(place_id=pid)]))
    with pytest.raises(LockedItemError):
        apply_proposal(locked, make_proposal(locked, "移动", [MoveOp(place_id=pid, to_day=0)]))
    with pytest.raises(LockedItemError):
        apply_proposal(locked, make_proposal(locked, "移出", [RemoveOp(place_id=pid)]))


def test_failed_proposal_changes_nothing(planned):
    pid = planned.plan.days[1].items[0].place_id
    prop = make_proposal(planned, "含非法操作", [MoveOp(place_id=pid, to_day=0), MoveOp(place_id=pid, to_day=99)])
    before = planned.model_dump_json()
    with pytest.raises(InvalidOperationError):
        apply_proposal(planned, prop)
    assert planned.model_dump_json() == before


def test_remove_returns_place_to_shortlist(planned):
    pid = planned.plan.days[1].items[0].place_id
    new = apply_proposal(planned, make_proposal(planned, "移出", [RemoveOp(place_id=pid)]))
    assert _find(new, pid) is None
    assert new.place(pid).status == PlaceStatus.SHORTLIST


def test_move_unscheduled_place_into_plan(planned):
    pid = planned.plan.unscheduled[0].place_id
    new = apply_proposal(planned, make_proposal(planned, "加入", [MoveOp(place_id=pid, to_day=0, to_position=0)]))
    assert _find(new, pid) == (0, 0)
    assert pid not in {u.place_id for u in new.plan.unscheduled}


def test_unknown_place_raises(planned):
    with pytest.raises(KeyError):
        apply_proposal(planned, make_proposal(planned, "x", [SetStatusOp(place_id="nope", status=PlaceStatus.IDEA)]))


def test_undo_restores_previous_state(planned):
    pid = planned.plan.days[1].items[0].place_id
    new = apply_proposal(planned, make_proposal(planned, "移动", [MoveOp(place_id=pid, to_day=2)]))
    back = undo(new)
    assert _find(back, pid) == _find(planned, pid)
    assert back.revision == new.revision + 1  # 撤销后版本号仍然增加，旧提案失效


def test_undo_with_no_history_raises(beijing):
    with pytest.raises(NothingToUndo):
        undo(beijing)


def test_describe_ops_is_readable(planned):
    pid = planned.plan.days[1].items[0].place_id
    prop = make_proposal(planned, "x", [MoveOp(place_id=pid, to_day=2), LockOp(place_id=pid)])
    lines = describe_ops(planned, prop)
    assert "移动" in lines[0] and "→" in lines[0]
    assert "锁定" in lines[1]


def test_proposal_json_roundtrip(planned):
    pid = planned.plan.days[1].items[0].place_id
    prop = make_proposal(planned, "x", [MoveOp(place_id=pid, to_day=2), LockOp(place_id=pid)], created_by="agent")
    again = Proposal.model_validate_json(prop.model_dump_json())
    assert again == prop
    assert isinstance(again.ops[0], MoveOp)


def test_excluding_a_place_also_removes_it_from_the_plan():
    from tripcore.proposals import SetStatusOp, apply_proposal, make_proposal
    from tripcore.scheduler import schedule
    from tripcore.models import PlaceStatus
    from tests.conftest import make_place, make_trip

    trip = schedule(make_trip([make_place("a"), make_place("b", lat=39.91)], num_days=1))
    assert any(it.place_id == "a" for d in trip.plan.days for it in d.items)
    prop = make_proposal(trip, "排除 a", [SetStatusOp(place_id="a", status=PlaceStatus.EXCLUDED)])
    new = apply_proposal(trip, prop)
    assert new.place("a").status == PlaceStatus.EXCLUDED
    assert all(it.place_id != "a" for d in new.plan.days for it in d.items)
