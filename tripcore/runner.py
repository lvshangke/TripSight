"""命令行直接调用工具：`tripcore run <工具名> '<JSON 参数>'`。

和 MCP 调的是同一批函数，所以结果一样；用来配合“技能 + 命令行”的按需加载方式：
助手先读技能和 references 里的说明，再用这个命令执行，不用把全部工具说明常驻在上下文里。
返回图片的工具（如 view_stop）会把图存成文件，打印文件路径，让助手去读图。
"""
from __future__ import annotations

import base64
import inspect
import json
import typing
from pathlib import Path
from typing import Any


class RunError(Exception):
    pass


def tool_map() -> dict[str, Any]:
    from . import mcp_server as ms
    return {f.__name__: f for f in ms.TOOLS}


def _coerce(fn, args: dict[str, Any]) -> dict[str, Any]:
    from pydantic import TypeAdapter, ValidationError
    sig = inspect.signature(fn)
    hints = typing.get_type_hints(fn)
    unknown = sorted(set(args) - set(sig.parameters))
    if unknown:
        raise RunError(f"{fn.__name__} 没有这些参数：{'、'.join(unknown)}。可用参数：{'、'.join(sig.parameters) or '（无）'}")
    out = {}
    for k, v in args.items():
        try:
            out[k] = TypeAdapter(hints.get(k, Any)).validate_python(v)
        except ValidationError as e:
            raise RunError(f"参数 {k} 的值不对：{e.errors()[0].get('msg', e)}")
    missing = [p.name for p in sig.parameters.values() if p.default is inspect.Parameter.empty and p.name not in out]
    if missing:
        raise RunError(f"{fn.__name__} 缺少必填参数：{'、'.join(missing)}")
    return out


def run_tool(name: str, raw: str = "", out_dir: Path | None = None) -> str:
    from . import mcp_server as ms
    tools = tool_map()
    if name not in tools:
        near = [n for n in tools if name in n or n in name][:5]
        raise RunError(f"没有叫 {name} 的工具。" + (f"相近的：{'、'.join(near)}" if near else "用 tripcore tools 看全部。"))
    try:
        args = json.loads(raw) if raw.strip() else {}
    except ValueError as e:
        raise RunError(f"参数不是合法的 JSON：{e}")
    if not isinstance(args, dict):
        raise RunError("参数要写成 JSON 对象，例如 '{\"day\": 1}'。")
    fn = tools[name]
    try:
        res = fn(**_coerce(fn, args))
    except ms.ToolError as e:
        raise RunError(str(e))
    if isinstance(res, str):
        return res
    if isinstance(res, (list, tuple)):
        lines, n = [], 0
        for blk in res:
            kind = getattr(blk, "type", "")
            if kind == "text":
                lines.append(blk.text)
            elif kind == "image":
                d = out_dir or (ms.trip_path().with_name("run_out"))
                d.mkdir(parents=True, exist_ok=True)
                n += 1
                ext = "png" if "png" in getattr(blk, "mimeType", "") else "jpg"
                p = d / f"{name}-{n}.{ext}"
                p.write_bytes(base64.b64decode(blk.data))
                lines.append(f"[图片已存到 {p}，请读取这个文件来看]")
            else:
                lines.append(str(blk))
        return "\n".join(lines)
    return json.dumps(res, ensure_ascii=False, indent=2, default=str)


def list_tools(category: str = "") -> str:
    from .tools_catalog import CATALOG, CATEGORIES
    rows = []
    for cat in CATEGORIES:
        if category and category != cat:
            continue
        names = [n for n, v in CATALOG.items() if v[0] == cat]
        if names:
            rows.append(f"【{cat}】")
            rows += [f"  {n}：{CATALOG[n][2]}" for n in names]
    return "\n".join(rows) or f"没有这个类别：{category}（可用：{'、'.join(CATEGORIES)}）"


def help_tool(name: str) -> str:
    tools = tool_map()
    if name not in tools:
        raise RunError(f"没有叫 {name} 的工具。用 tripcore tools 看全部。")
    fn = tools[name]
    return f"{name}{inspect.signature(fn)}\n\n{inspect.getdoc(fn) or ''}"
