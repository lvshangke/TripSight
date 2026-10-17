# 安装与接入 nanobot

tripcore 本身是一个 MCP 服务（35 个工具）。要在聊天里使用它，需要一个能连 MCP 的 Agent；本项目用 [nanobot](https://github.com/HKUDS/nanobot)（MIT 协议）。**nanobot 不在本仓库里**，请自己安装；本仓库只提供接入需要的 skill、配置样例和脚本。

测试过的版本：nanobot 0.3.5，Python 3.10–3.12，mcp 1.x。

## 1. 安装 tripcore

```bash
git clone https://github.com/lvshangke/TripSight.git tripcore && cd tripcore
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q          # 应全部通过
```

## 2. 申请高德 Web 服务 key

到高德开放平台创建应用，添加「Web 服务」类型的 key。**key 只放在你本机的 nanobot 配置里**，不要提交到仓库，不要发给别人（包括 AI 对话）。tripcore 不带 key 也能运行，只是没有真实路线、营业时间、天气和餐厅搜索。

## 3. 把 tripcore 登记到 nanobot

把 `nanobot/config.example.json` 里 `tools.mcpServers` 下的 `tripcore`（和可选的 `amap-maps`）合并进你自己的 `~/.nanobot/config.json`，把路径和 key 换成你自己的。重启 nanobot 后，应能看到 tripcore 的工具。

## 4. 安装 skill

```bash
python scripts/install_skills.py            # 复制到 ~/.nanobot/workspace/skills/
python scripts/install_skills.py --link     # 或用符号链接，改仓库里的文件立即生效
python scripts/install_skills.py --check    # 检查已安装的是否和仓库一致
```

- `trip-planner`：主 skill（`always: true`），规定模型怎么用 tripcore 的工具、哪些事不能自己编。
- `flyai-search`：只读地查机票、火车票、酒店参考价（飞猪 flyai 命令行），禁止预订。

## 5. 可选：机票、火车、酒店查询

- **flyai**：`npm i -g @fly-ai/flyai-cli`，按它自己的文档登录/配置。skill 规定只能用 `search-flight`、`search-train`、`search-hotel` 三个只读命令。
- **RollingGo 酒店（rgh）**：第三方 skill，来自 https://github.com/RollingGo-AI/rollinggo-hotel-skill-CN ，请按它自己的说明安装和登录（本仓库不含它的内容）。

## 6. 运行时数据在哪

`~/.tripcore/`：`trip.json`（行程）、`proposals.json`（待确认的提案）、`candidates.json`（游记候选）、`map.html`、`gpx/`、`amap_calls.log`（高德调用记录，不含 key）。环境变量 `TRIPCORE_FILE` 可改行程文件位置。

## 改 skill 时

以仓库里的 `skills/` 为准，改完用 `scripts/install_skills.py` 同步到 nanobot（或用 `--link` 一次链好）。
