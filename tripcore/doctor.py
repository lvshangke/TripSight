"""`python -m tripcore doctor`：只读自检，告诉你还缺什么、怎么补。

只检查「有没有配置」，绝不打印 key / token 的内容，也不修改任何文件、不联网。
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent
OK, WARN, FAIL = "ok", "warn", "fail"
_ICON = {OK: "✓", WARN: "!", FAIL: "✗"}


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    fix: str = ""


def _nanobot_config() -> dict:
    p = Path(os.environ.get("NANOBOT_CONFIG", "") or Path.home() / ".nanobot" / "config.json")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _tripcore_env(cfg: dict) -> dict:
    servers = (cfg.get("tools") or {}).get("mcpServers") or {}
    env = (servers.get("tripcore") or {}).get("env")
    return env if isinstance(env, dict) else {}


def _has_key(name: str, cfg_env: dict) -> bool:
    """环境变量或 nanobot 配置里是否填了真实值（占位说明文字不算）。"""
    for v in (os.environ.get(name, ""), cfg_env.get(name, "")):
        if isinstance(v, str) and v.strip() and not v.strip().startswith(("在这里", "可选")):
            return True
    return False


def check_python() -> Check:
    v = sys.version_info
    if v >= (3, 10):
        return Check("Python", OK, f"{v.major}.{v.minor}.{v.micro}")
    return Check("Python", FAIL, f"{v.major}.{v.minor}", "需要 Python 3.10 或更新版本")


def check_deps() -> list[Check]:
    out = []
    for mod, pip in (("pydantic", "pydantic>=2.5"), ("mcp", "mcp>=1.8,<2")):
        try:
            m = importlib.import_module(mod)
            out.append(Check(f"依赖 {mod}", OK, getattr(m, "__version__", "")))
        except ImportError:
            out.append(Check(f"依赖 {mod}", FAIL, "未安装", f"pip install -r requirements.txt（缺 {pip}）"))
    return out


def check_data_dir() -> Check:
    f = os.environ.get("TRIPCORE_FILE", "").strip()
    d = Path(f).expanduser().parent if f else Path.home() / ".tripcore"   # 与 mcp_server 的规则一致
    probe = d if d.exists() else d.parent
    if os.access(probe, os.W_OK):
        return Check("数据目录", OK, f"{d}（{'已存在' if d.exists() else '首次使用时创建'}）")
    return Check("数据目录", FAIL, f"{d} 不可写", "检查目录权限")


def check_nanobot(cfg: dict) -> list[Check]:
    out = []
    exe = shutil.which("nanobot")
    out.append(Check("nanobot 命令", OK, exe) if exe else Check("nanobot 命令", WARN, "未找到", "不用聊天助手可忽略；要用请按 docs/SETUP.md 安装 nanobot"))
    p = Path(os.environ.get("NANOBOT_CONFIG", "") or Path.home() / ".nanobot" / "config.json")
    if not cfg:
        out.append(Check("nanobot 配置", WARN, f"没读到 {p}", "把 nanobot/config.example.json 里的 tripcore 部分合并进你的配置"))
    else:
        servers = (cfg.get("tools") or {}).get("mcpServers") or {}
        if "tripcore" in servers:
            out.append(Check("nanobot 配置", OK, "已注册 tripcore MCP 服务"))
        else:
            out.append(Check("nanobot 配置", FAIL, "没有注册 tripcore", "把 nanobot/config.example.json 里 tools.mcpServers.tripcore 合并进去"))
    return out


def check_skills() -> list[Check]:
    dest = Path(os.environ.get("NANOBOT_SKILLS_DIR", "") or Path.home() / ".nanobot" / "workspace" / "skills")
    out = []
    src = REPO / "skills"
    if not src.is_dir():
        return [Check("技能", WARN, "找不到 skills 目录（pip 安装的包里不含技能）", "在源码目录里运行：git clone 后 pip install -e .，再 python scripts/install_skills.py")]
    import filecmp

    for s in sorted(p for p in src.iterdir() if (p / "SKILL.md").is_file()):
        f = dest / s.name / "SKILL.md"
        if not f.exists():
            out.append(Check(f"技能 {s.name}", FAIL, "未安装", "python scripts/install_skills.py"))
        elif not filecmp.cmp(s / "SKILL.md", f, shallow=False):
            out.append(Check(f"技能 {s.name}", WARN, "和仓库版本不一致", "python scripts/install_skills.py（旧版会备份）"))
        else:
            out.append(Check(f"技能 {s.name}", OK, "已安装且一致"))
    return out


def check_keys(cfg_env: dict) -> list[Check]:
    out = []
    if _has_key("AMAP_KEY", cfg_env):
        out.append(Check("高德 key", OK, "已配置（内容不显示）"))
    else:
        out.append(Check("高德 key", WARN, "未配置", "国内行程建议配置：在 nanobot 配置的 tripcore.env 里填 AMAP_KEY（只放你本机）"))
    if _has_key("GOOGLE_MAPS_KEY", cfg_env):
        out.append(Check("Google Maps key", OK, "已配置（内容不显示）"))
    else:
        out.append(Check("Google Maps key", WARN, "未配置", "只有境外行程才需要；没有时会用 OpenStreetMap 兜底"))
    return out


def check_tools() -> list[Check]:
    out = []
    for cmd, why, fix in (
        ("flyai", "机票/火车票/酒店参考价（可选）", "npm i -g @fly-ai/flyai-cli，并按它的文档登录"),
        ("rgh", "RollingGo 酒店搜索（可选）", "按 docs/SETUP.md 安装并 rgh login"),
    ):
        exe = shutil.which(cmd)
        out.append(Check(f"{cmd} 命令", OK, f"{why}：{exe}") if exe else Check(f"{cmd} 命令", WARN, f"未找到（{why}）", fix))
    return out


def check_api_port() -> Check:
    host, port = "127.0.0.1", 8900
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return Check("nanobot 接口 (8900)", OK, "可连接，网页里的聊天可用")
    except OSError:
        return Check("nanobot 接口 (8900)", WARN, "连不上", "要在网页里聊天：nanobot plugins enable api，再 nanobot serve")


def run_checks() -> list[Check]:
    cfg = _nanobot_config()
    cfg_env = _tripcore_env(cfg)
    checks: list[Check] = [check_python(), *check_deps(), check_data_dir(), *check_nanobot(cfg), *check_skills(),
                           *check_keys(cfg_env), *check_tools(), check_api_port()]
    return checks


def format_report(checks: list[Check]) -> str:
    lines = ["TripSight 自检（只读，不显示任何 key 内容）", ""]
    for c in checks:
        lines.append(f"{_ICON[c.status]} {c.name}" + (f"：{c.detail}" if c.detail else ""))
        if c.status != OK and c.fix:
            lines.append(f"    → {c.fix}")
    n = {s: sum(1 for c in checks if c.status == s) for s in (OK, WARN, FAIL)}
    lines += ["", f"通过 {n[OK]} 项，建议处理 {n[WARN]} 项，必须处理 {n[FAIL]} 项"]
    return "\n".join(lines)


def main(printer: Callable[[str], None] = print) -> int:
    checks = run_checks()
    printer(format_report(checks))
    return 1 if any(c.status == FAIL for c in checks) else 0
