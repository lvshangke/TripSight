"""行程回顾：旅行后记录实际去了哪些、花了多少，对比计划，并按固定规则给出可写入长期偏好的建议。

所有内容都来自用户的话；没记录的项目一律显示“未记录”，不估算、不编造。建议只展示，是否写入偏好由用户确认。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional

STATUS_ALIASES = {
    "visited": "visited", "去了": "visited", "去过": "visited",
    "skipped": "skipped", "没去": "skipped", "未去": "skipped", "跳过": "skipped",
    "changed": "changed", "临时改了": "changed", "改了": "changed", "改去别处": "changed",
}
STATUS_NAMES = {"visited": "去了", "skipped": "没去", "changed": "临时改了"}
COST_ALIASES = {
    "tickets": "tickets", "门票": "tickets",
    "food": "food", "餐饮": "food", "吃饭": "food",
    "transport": "transport", "交通": "transport",
    "lodging": "lodging", "住宿": "lodging",
    "other": "other", "其他": "other",
}
COST_NAMES = {"tickets": "门票", "food": "餐饮", "transport": "交通", "lodging": "住宿", "other": "其他"}
TIRED_WORDS = ("累", "走太多", "走不动", "太远")
MAX_NOTE = 100


def empty() -> dict[str, Any]:
    return {"places": {}, "costs": {}}


def load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty()
    if not isinstance(data, dict):
        return empty()
    return {"places": data.get("places") or {}, "costs": data.get("costs") or {}}


def save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def record_place(data: dict[str, Any], place_id: str, status: str, rating: Optional[int], note: str) -> dict[str, Any]:
    st = STATUS_ALIASES.get((status or "").strip())
    if st is None:
        raise ValueError("status 只能是 去了 / 没去 / 临时改了")
    if rating is not None and (isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5):
        raise ValueError("评分需要是 1~5 的整数")
    if len(note or "") > MAX_NOTE:
        raise ValueError(f"备注太长（最多 {MAX_NOTE} 字）")
    data["places"][place_id] = {"status": st, "rating": rating, "note": (note or "").strip()}
    return data


def record_cost(data: dict[str, Any], category: str, amount: float, note: str) -> float:
    cat = COST_ALIASES.get((category or "").strip())
    if cat is None:
        raise ValueError("category 只能是 门票 / 餐饮 / 交通 / 住宿 / 其他")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount < 0 or amount > 1_000_000:
        raise ValueError("金额需要是 0~1000000 的数字")
    c = data["costs"].setdefault(cat, {"amount": 0.0, "notes": []})
    c["amount"] = round(c["amount"] + float(amount), 2)
    if (note or "").strip():
        c["notes"].append(note.strip()[:MAX_NOTE])
    return c["amount"]


def suggestions(data: dict[str, Any], planned_ids: list[str], planned_lodging: float, nights: int) -> list[dict[str, Any]]:
    """按固定规则给偏好建议。每条：text（给用户看）+ category + value（可选，给 remember_preference 用）。"""
    out: list[dict[str, Any]] = []
    recorded = [(pid, data["places"][pid]) for pid in planned_ids if pid in data["places"]]
    skipped = [pid for pid, r in recorded if r["status"] == "skipped"]
    if len(recorded) >= 3 and len(skipped) * 3 > len(recorded):
        out.append({"category": "pace", "value": {"pace": "relaxed"},
                    "text": f"计划的 {len(recorded)} 个已记录景点里有 {len(skipped)} 个没去，下次建议把节奏设为悠闲（relaxed）。"})
    tired = [r for _, r in recorded if any(w in r["note"] for w in TIRED_WORDS) and "不累" not in r["note"]]
    if len(tired) >= 2:
        out.append({"category": "transport", "value": {"walk_max_min": 15},
                    "text": f"{len(tired)} 个景点的备注提到太累/太远，下次建议把单段步行上限调到 15 分钟。"})
    actual_l = data["costs"].get("lodging", {}).get("amount")
    if actual_l is not None and nights > 0 and planned_lodging > 0 and actual_l < planned_lodging * 0.7:
        per = int(math.ceil(actual_l / nights / 10.0) * 10)
        out.append({"category": "lodging", "value": {"lodging_budget_max": per},
                    "text": f"实际住宿花费（{actual_l:.0f} 元）明显低于计划（{planned_lodging:.0f} 元），下次建议把每晚住宿预算上限设为 {per} 元。"})
    return out


def report(data: dict[str, Any], names: dict[str, str], planned_ids: list[str], planned: dict[str, float], nights: int) -> str:
    lines = ["【行程回顾】"]
    lines.append("景点：")
    if not planned_ids:
        lines.append("  （计划里没有已排入的景点）")
    for pid in planned_ids:
        r = data["places"].get(pid)
        if r is None:
            lines.append(f"  - {names.get(pid, pid)}：未记录")
            continue
        extra = (f"，{r['rating']} 分" if r.get("rating") else "") + (f"，{r['note']}" if r.get("note") else "")
        lines.append(f"  - {names.get(pid, pid)}：{STATUS_NAMES[r['status']]}{extra}")
    extra_ids = [pid for pid in data["places"] if pid not in planned_ids]
    for pid in extra_ids:
        r = data["places"][pid]
        lines.append(f"  - {names.get(pid, pid)}（计划外）：{STATUS_NAMES[r['status']]}" + (f"，{r['note']}" if r.get("note") else ""))
    done = sum(1 for pid in planned_ids if data["places"].get(pid, {}).get("status") == "visited")
    rec = sum(1 for pid in planned_ids if pid in data["places"])
    lines.append(f"  已记录 {rec}/{len(planned_ids)} 个计划景点，其中去了 {done} 个。")
    lines.append("花费（元）：")
    total = 0.0
    for cat in ("tickets", "food", "transport", "lodging", "other"):
        a = data["costs"].get(cat, {}).get("amount")
        p = planned.get(cat)
        if a is None and p is None:
            lines.append(f"  - {COST_NAMES[cat]}：未记录")
            continue
        total += a or 0
        a_s = f"实际 {a:.0f}" if a is not None else "实际 未记录"
        if p is not None:
            diff = f"，{'超' if (a or 0) > p else '省'} {abs((a or 0) - p):.0f}" if a is not None else ""
            lines.append(f"  - {COST_NAMES[cat]}：计划 {p:.0f}，{a_s}{diff}")
        else:
            lines.append(f"  - {COST_NAMES[cat]}：{a_s}（计划里没有估算）")
    lines.append(f"  已记录实际花费合计 {total:.0f} 元。")
    return "\n".join(lines)
