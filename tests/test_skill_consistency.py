"""skill 和代码不能“漂移”：skill 里提到的工具必须真实存在，每个工具都要在 skill 里被提到，
skill 里 `参数=值` 形式的参数名必须是某个工具的真实参数。skill 正文不要超过 200 行（太长模型会漏看）。"""

import inspect
import re
from pathlib import Path

from tripcore.mcp_server import TOOLS

SKILLS = Path(__file__).resolve().parent.parent / "skills"
TRIP_SKILLS = sorted(d for d in SKILLS.iterdir() if d.name.startswith("trip-"))
# skill 里出现的、不是 tripcore 工具的 snake_case 名字（返回字段、外部工具、数据字段等）
NOT_TOOLS = {
    "search_near", "not_found", "source_days", "suggested_tags", "unmapped_days",
    "web_search", "web_fetch", "confirm_code", "cost_reference", "opentime_week", "web_links",
    "closed_weekdays", "hours_source", "opening_hours", "reservation_required", "ticket_price",
    "terminal_name", "per_day", "user_food_preferences", "walk_max_min", "prefer_subway", "max_transfers",
    "taxi_ok", "lodging_budget_max", "avoid_food", "like_food", "from_day", "to_day", "lodging_id",
    "stay_per_stop_min", "price_source", "price_date", "from_name", "to_name", "arr_time", "dep_time",
}


def _text() -> str:
    """所有 trip-* 技能合在一起（工具按场景分散在不同技能里）。"""
    return "\n".join((d / "SKILL.md").read_text(encoding="utf-8") for d in TRIP_SKILLS)


def test_every_tool_is_mentioned_and_no_unknown_tool_referenced():
    txt = _text()
    names = {f.__name__ for f in TOOLS}
    missing = sorted(n for n in names if n not in txt)
    assert not missing, f"skill 没提到这些工具：{missing}"
    refs = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)(?:\(|`|\s)", txt))
    params = {p for f in TOOLS for p in inspect.signature(f).parameters}
    unknown = sorted(r for r in refs if r not in names and r not in params and r not in NOT_TOOLS)
    assert not unknown, f"skill 里提到了不存在的工具或参数：{unknown}"


def test_parameter_assignments_exist():
    txt = _text()
    params = {p for f in TOOLS for p in inspect.signature(f).parameters} | NOT_TOOLS
    used = set(re.findall(r"`[^`]*?\b([a-z]+(?:_[a-z]+)*)=(?:True|False|\d|\")", txt))
    bad = sorted(u for u in used if u not in params)
    assert not bad, f"skill 里 `参数=值` 的参数名不存在：{bad}"


def test_each_skill_is_short_and_routable():
    assert {d.name for d in TRIP_SKILLS} >= {"trip-planner", "trip-routes", "trip-hours-weather", "trip-food", "trip-sources", "trip-export", "trip-review"}
    for d in TRIP_SKILLS:
        txt = (d / "SKILL.md").read_text(encoding="utf-8")
        assert len(txt.splitlines()) <= 200, f"{d.name} 超过 200 行，请拆分或精简"
        m = re.match(r"---\nname: " + d.name + r"\ndescription: (.+)\n", txt)
        assert m and len(m.group(1)) >= 30, f"{d.name} 的 description 要写清触发场景"


def test_only_planner_is_always_loaded_and_safety_rules_travel_with_skills():
    for d in TRIP_SKILLS:
        txt = (d / "SKILL.md").read_text(encoding="utf-8")
        assert ("always: true" in txt) == (d.name == "trip-planner")
        if d.name != "trip-planner":
            assert "tripcore run" in txt and "事实只来自工具或用户" in txt, f"{d.name} 要说明命令行调用方式和基本规则"
