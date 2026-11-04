"""离开日：先回早上的酒店取行李，再去车站；当晚（到站后）住的酒店在“离开”之后才出现。"""
from pathlib import Path

from tripcore.mapview import build_map_data
from tripcore.metrics import day_stats
from tripcore.models import Trip

FIX = Path(__file__).parent / "data" / "departure_night.json"


def _trip():
    return Trip.model_validate_json(FIX.read_text(encoding="utf-8"))


def test_night_hotel_after_departure():
    tl = build_map_data(_trip())["days"][-1]["timeline"]
    roles = [(e["type"], e.get("role")) for e in tl if e["type"] in ("hotel", "term")]
    assert roles[-2:] == [("term", "离开"), ("hotel", "入住")]
    assert not [e for e in tl if e["type"] == "hotel" and e["role"] == "返回"]     # 行李随身，不回酒店
    assert "汉庭" in tl[-1]["name"] and tl[-1]["time"] == "20:40"


def test_no_return_leg_on_departure_day():
    t = _trip()
    st = day_stats(t, t.plan.days[-1])
    assert st.lodging_back is None
