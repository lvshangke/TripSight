import pytest

from tripcore import mcp_server as s
from tripcore import prefs as P


def test_add_validates():
    with pytest.raises(ValueError):
        P.add([], "bogus", "x")
    with pytest.raises(ValueError):
        P.add([], "food", "")
    with pytest.raises(ValueError):
        P.add([], "transport", "x", {"walk_max_min": 999})
    with pytest.raises(ValueError):
        P.add([], "other", "x", {"password": "abc"})
    with pytest.raises(ValueError):
        P.add([], "transport", "x", {"prefer_subway": "yes"})


def test_same_key_replaces():
    items, a, _ = P.add([], "transport", "步行别超过15分钟", {"walk_max_min": 15})
    items, b, rep = P.add(items, "transport", "其实20分钟也行", {"walk_max_min": 20})
    assert len(items) == 1 and items[0]["id"] == b["id"] and rep and P.merged_values(items) == {"walk_max_min": 20}
    items, _, rep = P.add(items, "food", "不吃辣")           # 没有结构化值：累加
    assert len(items) == 2 and not rep


def test_remember_list_forget_roundtrip():
    s.remember_preference("food", "不吃辣", {"avoid_food": ["辣"]})
    assert "不吃辣" in s.list_preferences()
    s.forget_preference("pf1")
    assert "还没有" in s.list_preferences()
    with pytest.raises(s.ToolError):
        s.forget_preference("pf9")
    with pytest.raises(s.ToolError):
        s.remember_preference("food", "x", {"bad": 1})


def test_new_trip_applies_prefs_and_explicit_wins():
    s.remember_preference("pace", "我喜欢悠闲", {"pace": "relaxed"})
    s.remember_preference("transport", "步行不超过12分钟,爱坐地铁", {"walk_max_min": 12, "prefer_subway": True})
    msg = s.new_trip(num_days=3, city="北京")
    t = s._load()
    assert t.meta.pace.value == "relaxed" and t.meta.transport_prefs.walk_max_min == 12 and t.meta.transport_prefs.prefer_subway
    assert "按你之前的长期偏好套用了" in msg
    s.new_trip(num_days=3, city="北京", pace="packed")           # 用户这次明说的优先
    assert s._load().meta.pace.value == "packed"
    # 偏好跨行程保留
    assert "悠闲" in s.list_preferences()


def test_no_prefs_defaults():
    s.new_trip(num_days=2)
    assert s._load().meta.pace.value == "normal"


def test_lodging_budget_warning():
    s.remember_preference("lodging", "每晚不超过400", {"lodging_budget_max": 400})
    s.new_trip(num_days=2)
    assert "超过你记下的住宿预算" in s.add_lodging("贵店", 39.9, 116.4, price_min=500, price_max=600)
    assert "超过" not in s.add_lodging("平价店", 39.9, 116.4, price_min=200, price_max=300)
