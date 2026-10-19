#!/usr/bin/env python3
"""把 tripcore 登记到 nanobot 的配置里（tools.mcpServers.tripcore）。

默认只显示将要做的改动（dry-run），不写文件；加 --apply 才会写，并且先把原配置备份成 .bak。
已经有 tripcore 条目时不覆盖（加 --force 才覆盖）；不会写入任何 key——密钥请自己填到 env 里。

用法：
    python scripts/merge_nanobot_config.py                 # 只看改动
    python scripts/merge_nanobot_config.py --apply         # 备份后写入
    python scripts/merge_nanobot_config.py --config 路径 --python 路径
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = Path.home() / ".nanobot" / "config.json"


def server_entry(python: str, repo: Path) -> dict:
    return {
        "command": python,
        "args": ["-m", "tripcore.mcp_server"],
        "cwd": str(repo),
        "env": {},
        "toolTimeout": 30,
    }


def merge(cfg: dict, python: str, repo: Path, force: bool = False) -> tuple[dict, str]:
    """返回 (新配置, 说明)。不修改传入的 cfg。"""
    new = json.loads(json.dumps(cfg))
    servers = new.setdefault("tools", {}).setdefault("mcpServers", {})
    if "tripcore" in servers and not force:
        return new, "已存在 tripcore 条目，未改动（要覆盖请加 --force；原有的 env/key 会丢失，请先确认）"
    note = "覆盖已有的 tripcore 条目" if "tripcore" in servers else "新增 tripcore 条目"
    old_env = (servers.get("tripcore") or {}).get("env")
    servers["tripcore"] = server_entry(python, repo)
    if force and isinstance(old_env, dict) and old_env:
        servers["tripcore"]["env"] = old_env          # 覆盖时保留你原来填的 env（key 不丢）
        note += "（保留原来的 env）"
    return new, note


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG), help="nanobot 配置文件路径")
    ap.add_argument("--python", default=sys.executable, help="运行 tripcore 的 python 路径（默认当前这个）")
    ap.add_argument("--apply", action="store_true", help="真正写入（先备份成 .bak）")
    ap.add_argument("--force", action="store_true", help="已有 tripcore 条目时覆盖")
    args = ap.parse_args(argv)

    path = Path(args.config).expanduser()
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"读不懂 {path}（不是合法 JSON）：{e}；没有做任何改动。", file=sys.stderr)
            return 1
    else:
        cfg = {}
    new, note = merge(cfg, args.python, REPO, args.force)
    print(f"配置文件：{path}\n{note}")
    if new == cfg:
        return 0
    print("将写入 tools.mcpServers.tripcore：")
    print(json.dumps(new["tools"]["mcpServers"]["tripcore"], ensure_ascii=False, indent=2))
    print("（不包含任何 key；AMAP_KEY 等请自己填到这个条目的 env 里）")
    if not args.apply:
        print("\n这只是预览，没有写入。确认无误后加 --apply。")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        bak = path.with_name(path.name + ".bak")
        shutil.copy2(path, bak)
        print(f"已备份原配置：{bak}")
    path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("已写入。重启 nanobot 后生效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
