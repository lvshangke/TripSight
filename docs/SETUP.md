# 安装与接入

TripSight（tripcore）是一个标准的 stdio MCP 服务。先装好它，再接到你用的聊天 Agent。

- 需要：Python 3.10+；测试过 nanobot 0.3.5、mcp 1.x
- nanobot 不在本仓库里，请按 [它的说明](https://github.com/HKUDS/nanobot) 自己安装
- 接 WorkBuddy 见 [WORKBUDDY.md](WORKBUDDY.md)

## 1. 安装

```bash
git clone https://github.com/lvshangke/TripSight.git tripcore && cd tripcore
./setup.sh
source .venv/bin/activate
```

`setup.sh` 依次：创建 `.venv` 并安装 → 检查 nanobot → 预览 nanobot 配置改动，**你确认后才写入**（先备份 `.bak`）→ 安装技能 → `tripcore doctor` 自检。它不装 nanobot、不写 key、不登录任何服务。

<details>
<summary>手动安装</summary>

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q
tripcore doctor
```

</details>

只用网页工作台和命令行的话，到这里就够了：`tripcore web --open`。

## 2. 配置高德 key（推荐）

1. 在 [高德开放平台](https://console.amap.com/) 创建应用，添加「Web 服务」类型的 key。
2. 写进 `~/.nanobot/config.json` 里 `tripcore` 条目的 `env`：`"AMAP_KEY": "你的 key"`。

不填也能运行，只是没有真实路线、营业时间、天气和餐厅搜索。key 只放在本机，不要提交，也不要发进聊天。

## 3. 接入 nanobot

`setup.sh` 已经做完这一步。想手动做：

```bash
python scripts/merge_nanobot_config.py           # 预览改动
python scripts/merge_nanobot_config.py --apply   # 写入（先备份，不含 key，不覆盖已有条目）
python scripts/install_skills.py                 # 技能复制到 ~/.nanobot/workspace/skills/
```

重启 nanobot，能看到 tripcore 的工具即接通。对它说“打开工作台”试一下。

技能说明：`trip-planner` 常驻，规定流程和铁律；其余按场景触发。改了仓库里的 `skills/` 后，重新运行 `install_skills.py` 同步（或首次用 `--link` 链接，`--check` 检查是否一致）。

## 其他 MCP Agent

Claude Code、Claude Desktop、Cursor 等按同样方式接入（作者只在 nanobot 和 WorkBuddy 上测试过）：

1. 在该 Agent 的 MCP 配置里加一个 stdio 服务：命令填 `tripcore-mcp` 的绝对路径（`which tripcore-mcp`），`env` 里放 `AMAP_KEY`。可参考 `nanobot/config.example.json` 里的 `tripcore` 条目。
2. 安装技能：`python scripts/install_skills.py --dest <该 Agent 的技能目录>`。没有技能，助手不知道该按什么顺序用工具、什么时候必须先请你确认。
3. 重启 Agent，说“打开工作台”测试。

默认只暴露“规划核心 + 恢复行程”约 50 个工具；要全部 92 个，在 `env` 里加 `"TRIPCORE_TOOLS": "full"`。

## 可选功能

### 网页工作台的聊天栏

工作台右侧的聊天栏需要 nanobot 的本机接口：

```bash
nanobot plugins enable api
nanobot serve        # 默认监听 127.0.0.1:8900
```

- 给接口设了 key：启动工作台前设 `NANOBOT_API_KEY`；地址不是默认值时设 `NANOBOT_API_URL`（只允许本机）。
- 接口没启动时聊天栏显示“未连接”，拖拽、改日期、撤销照常可用。
- 每个行程有自己的聊天记录（行程目录下的 `chat.json`，最近 200 条）。

### 用微信聊天

以下步骤需要你本人操作（扫码、批准配对）：

```bash
nanobot plugins enable weixin
```

1. 在 `~/.nanobot/config.json` 加 `"channels": {"weixin": {"enabled": true}}`，先**不要**写 `allowFrom`（只能配对模式）。
2. `nanobot channels login weixin`，用微信扫码。
3. `nanobot gateway`，保持运行。
4. 给机器人发一条私聊，收到配对码后在电脑上执行 `nanobot agent -m "/pairing approve 配对码"`。

注意：只批准你自己的微信，不要用 `["*"]`；微信里打不开本机文件，看地图请让助手生成高德 App 链接（`create_amap_map`）。

### 境外行程用 Google Maps

1. 在 Google Cloud 开通 **Places API (New)** 和 **Routes API**，创建只限这两个 API 的 key，并设预算提醒。
2. 在 `tripcore` 的 `env` 里加 `GOOGLE_MAPS_KEY`。
3. 对助手说“这个行程用 Google”。不说时按位置自动选：大陆用高德，境外用 Google。

天气始终用 Open-Meteo；高德专属地图只支持国内行程。

### 机票、火车、酒店参考价（只读）

- flyai：`npm i -g @fly-ai/flyai-cli`，按它的文档登录。
- RollingGo 酒店：按 [rollinggo-hotel-skill-CN](https://github.com/RollingGo-AI/rollinggo-hotel-skill-CN) 的说明安装。

技能只允许查询，不会预订或付款。

## 数据在哪

都在 `~/.tripcore/`：行程 `trip.json`、待确认提案、游记候选、聊天记录、导出的地图和 GPX、高德调用日志（不含 key）。用环境变量 `TRIPCORE_FILE` 可改行程文件位置。
