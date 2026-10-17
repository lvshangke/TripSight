#!/usr/bin/env python3
"""把仓库里的 skills/ 安装到 nanobot 的工作区（默认 ~/.nanobot/workspace/skills/）。

用法：
    python scripts/install_skills.py            # 复制（已有的会先备份成 .bak）
    python scripts/install_skills.py --link     # 用符号链接，之后改仓库里的文件会立刻生效
    python scripts/install_skills.py --dest 路径  # 指定 nanobot 工作区的 skills 目录
    python scripts/install_skills.py --check    # 只检查已安装的是否与仓库一致，不改动

注意：rollinggo-hotel-booking（RollingGo 酒店）是第三方 skill，不在本仓库里，
请按 docs/SETUP.md 从它自己的仓库安装。
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "skills"
DEFAULT_DEST = Path.home() / ".nanobot" / "workspace" / "skills"


def skill_dirs() -> list[Path]:
    return sorted(p for p in SRC.iterdir() if (p / "SKILL.md").is_file())


def check(dest: Path) -> int:
    bad = 0
    for s in skill_dirs():
        f = dest / s.name / "SKILL.md"
        if not f.exists():
            print(f"缺少：{s.name}")
            bad += 1
        elif not filecmp.cmp(s / "SKILL.md", f, shallow=False):
            print(f"不一致：{s.name}（已安装的和仓库里的不同）")
            bad += 1
        else:
            print(f"一致：{s.name}")
    return 1 if bad else 0


def install(dest: Path, link: bool) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for s in skill_dirs():
        target = dest / s.name
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            backup = target.with_name(target.name + ".bak")
            if backup.exists():
                shutil.rmtree(backup)
            target.rename(backup)
            print(f"已备份旧版：{backup}")
        if link:
            target.symlink_to(s, target_is_directory=True)
            print(f"已链接：{target} -> {s}")
        else:
            shutil.copytree(s, target)
            print(f"已复制：{target}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    ap.add_argument("--link", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        return check(a.dest)
    install(a.dest, a.link)
    return 0


if __name__ == "__main__":
    sys.exit(main())
