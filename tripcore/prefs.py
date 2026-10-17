"""用户的长期偏好（跨行程共用）。

只记用户明确说过的话，不做推断。每条偏好有：类别、原话/概括、日期，以及可选的结构化值（value），
结构化值只允许下面 VALUE_KEYS 里的几项，这样代码才能直接使用。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Optional

CATEGORIES = ("transport", "pace", "lodging", "food", "interest", "other")
MAX_TEXT = 200

# 结构化值：键 → 校验函数（返回规整后的值，不合法抛 ValueError）
def _int(lo: int, hi: int):
    def f(v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError(f"需要 {lo}~{hi} 的整数")
        return v
    return f


def _bool(v: Any) -> bool:
    if not isinstance(v, bool):
        raise ValueError("需要 true/false")
    return v


def _pace(v: Any) -> str:
    if v not in ("relaxed", "normal", "packed"):
        raise ValueError("pace 只能是 relaxed / normal / packed")
    return v


def _strs(v: Any) -> list[str]:
    if not isinstance(v, list) or not v or not all(isinstance(x, str) and x.strip() and len(x) <= 20 for x in v):
        raise ValueError("需要非空的短文字列表")
    return [x.strip() for x in v]


def _price(v: Any) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        raise ValueError("需要大于 0 的数字（元/晚）")
    return float(v)


VALUE_KEYS = {
    "pace": _pace,
    "walk_max_min": _int(1, 120),
    "prefer_subway": _bool,
    "max_transfers": _int(0, 5),
    "taxi_ok": _bool,
    "avoid_food": _strs,
    "like_food": _strs,
    "lodging_budget_max": _price,
}
# 能直接落到出行偏好上的
TRANSPORT_KEYS = ("walk_max_min", "prefer_subway", "max_transfers", "taxi_ok")


def load(path: Path) -> list[dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, ValueError):
        return []


def save(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def add(items: list[dict[str, Any]], category: str, text: str, value: Optional[dict[str, Any]] = None,
        today: Optional[str] = None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """新增一条；返回 (新列表, 新条目, 被它取代的旧条目说明)。同一个结构化键只保留最新的一条。"""
    if category not in CATEGORIES:
        raise ValueError(f"category 只能是 {'/'.join(CATEGORIES)}")
    text = (text or "").strip()
    if not text:
        raise ValueError("text 不能为空（写用户的原话或简短概括）")
    if len(text) > MAX_TEXT:
        raise ValueError(f"text 太长（最多 {MAX_TEXT} 字）")
    clean: dict[str, Any] = {}
    for k, v in (value or {}).items():
        if k not in VALUE_KEYS:
            raise ValueError(f"不支持的结构化键 {k}；可用：{', '.join(VALUE_KEYS)}")
        clean[k] = VALUE_KEYS[k](v)
    replaced: list[str] = []
    kept: list[dict[str, Any]] = []
    for it in items:
        if clean and set(it.get("value") or {}) & set(clean) and set(it.get("value") or {}) <= set(clean):
            replaced.append(f"{it['id']} {it['text']}")
        else:
            kept.append(it)
    n = 1
    ids = {x["id"] for x in items}
    while f"pf{n}" in ids:
        n += 1
    entry = {"id": f"pf{n}", "category": category, "text": text, "value": clean,
             "date": today or date.today().isoformat()}
    return kept + [entry], entry, replaced


def forget(items: list[dict[str, Any]], pid: str) -> list[dict[str, Any]]:
    if all(x["id"] != pid for x in items):
        raise KeyError(pid)
    return [x for x in items if x["id"] != pid]


def merged_values(items: list[dict[str, Any]]) -> dict[str, Any]:
    """所有结构化值合并（后记的覆盖先记的）。"""
    out: dict[str, Any] = {}
    for it in items:
        out.update(it.get("value") or {})
    return out


def describe(items: list[dict[str, Any]]) -> str:
    return "；".join(f"[{x['id']}] {x['text']}" for x in items)
