"""skill 和代码不能“漂移”：skill 里提到的工具必须真实存在，每个工具都要在 skill 里被提到，
skill 里 `参数=值` 形式的参数名必须是某个工具的真实参数。skill 正文不要超过 200 行（太长模型会漏看）。"""

import inspect
import re
from pathlib import Path

from tripcore.mcp_server import TOOLS

SKILL = Path(__file__).resolve().parent.parent / "skills" / "trip-planner" / "SKILL.md"
# skill 里出现的、不是 tripcore 工具的 snake_case 名字（返回字段、外部工具、数据字段等）
NOT_TOOLS = {
    "search_near",
    "web_search", "web_fetch", "confirm_code", "cost_reference", "opentime_week", "web_links",
    "closed_weekdays", "hours_source", "opening_hours", "reservation_required", "ticket_price",
    "terminal_name", "per_day", "user_food_preferences", "walk_max_min", "prefer_subway", "max_transfers",
    "taxi_ok", "lodging_budget_max", "avoid_food", "like_food", "from_day", "to_day", "lodging_id",
    "stay_per_stop_min", "price_source", "price_date", "from_name", "to_name", "arr_time", "dep_time",
}


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


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


def test_skill_body_length():
    assert len(_text().splitlines()) <= 200, "SKILL.md 超过 200 行，请拆分到 references/ 或精简"
