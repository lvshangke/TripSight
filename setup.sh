#!/usr/bin/env bash
# TripSight 一键安装：创建虚拟环境并安装 → 检查 nanobot → 预览并确认后登记到 nanobot → 安装技能 → 自检。
# 不会写入任何 key，不会登录 flyai / rgh，不会自动安装 nanobot；改 nanobot 配置前先给你看并等你确认。
set -euo pipefail

TESTED_NANOBOT="0.3.5"
cd "$(dirname "$0")"
ROOT="$(pwd)"

say() { printf '\n==> %s\n' "$*"; }

say "1/5 创建虚拟环境并安装 TripSight"
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "需要 Python 3.10 或更新版本"' 
[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -e ".[dev]"
VENV_PY="$ROOT/.venv/bin/python"

say "2/5 检查 nanobot"
if command -v nanobot >/dev/null 2>&1; then
  NB_VER="$(nanobot --version 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
  echo "已找到 nanobot ${NB_VER:-（版本未知）}"
  if [ -n "${NB_VER:-}" ] && [ "$NB_VER" != "$TESTED_NANOBOT" ]; then
    echo "提示：本项目测试过的版本是 $TESTED_NANOBOT，你的是 $NB_VER，通常可用，出问题请先对照版本。"
  fi
  HAVE_NB=1
else
  echo "没有找到 nanobot 命令。本脚本不会自动安装它。"
  echo "请按 https://github.com/HKUDS/nanobot 的说明安装（测试过的版本：$TESTED_NANOBOT），装好后重新运行 ./setup.sh。"
  echo "只想用网页工作台和命令行的话，可以不装 nanobot。"
  HAVE_NB=0
fi

if [ "$HAVE_NB" = 1 ]; then
  say "3/5 把 tripcore 登记到 nanobot（先预览，不写入）"
  "$VENV_PY" scripts/merge_nanobot_config.py --python "$VENV_PY" || true
  printf '\n要把上面的改动写入你的 nanobot 配置吗？会先备份成 .bak，且不含任何 key。[y/N] '
  read -r ANS || ANS=""
  if [ "$ANS" = "y" ] || [ "$ANS" = "Y" ]; then
    "$VENV_PY" scripts/merge_nanobot_config.py --python "$VENV_PY" --apply
  else
    echo "已跳过。以后可以运行：python scripts/merge_nanobot_config.py --apply"
  fi

  say "4/5 安装技能"
  "$VENV_PY" scripts/install_skills.py
else
  say "3/5、4/5 已跳过（没有 nanobot）"
fi

say "5/5 自检"
"$VENV_PY" -m tripcore doctor || true

cat <<MSG

完成。接下来：
  source .venv/bin/activate
  tripcore web --open      # 打开本机网页工作台
  tripcore demo            # 示例演示
高德 / Google key 请自己填到 nanobot 配置里 tripcore 条目的 env 中（只放你本机，不要提交）。
flyai、rgh 需要你自己安装并登录，见 docs/SETUP.md。
MSG
