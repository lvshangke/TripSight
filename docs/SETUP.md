# 安装与接入 nanobot

tripcore 本身是一个 MCP 服务（92 个工具）。要在聊天里使用它，需要一个能连 MCP 的 Agent；本项目用 [nanobot](https://github.com/HKUDS/nanobot)（MIT 协议）。**nanobot 不在本仓库里**，请自己安装；本仓库只提供接入需要的 skill、配置样例和脚本。

测试过的版本：nanobot 0.3.5，Python 3.10–3.12，mcp 1.x。

## 1. 安装 tripcore

**方式一：一键脚本（推荐）**

```bash
git clone https://github.com/lvshangke/TripSight.git tripcore && cd tripcore
./setup.sh
```

脚本会：创建 `.venv` 并安装 → 检查 nanobot（没有就只提示怎么装，**不会自动安装**）→ 预览要写入 nanobot 配置的改动，**你确认后才写**（先备份成 `.bak`，不含任何 key）→ 安装技能 → 运行 `tripcore doctor`。它不会登录 flyai / rgh，也不会写入任何 key。

**方式二：手动安装**

```bash
git clone https://github.com/lvshangke/TripSight.git tripcore && cd tripcore
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # 装好后有 tripcore 和 tripcore-mcp 两个命令
python -m pytest -q              # 应全部通过
tripcore doctor                  # 自检，缺什么会告诉你怎么补
```

只想用网页工作台和命令行的话，到这里就够了：`tripcore web --open`。

## 2. 申请高德 Web 服务 key

到高德开放平台创建应用，添加「Web 服务」类型的 key。**key 只放在你本机的 nanobot 配置里**，不要提交到仓库，不要发给别人（包括 AI 对话）。tripcore 不带 key 也能运行，只是没有真实路线、营业时间、天气和餐厅搜索。

## 3. 把 tripcore 登记到 nanobot

可以运行 `python scripts/merge_nanobot_config.py` 预览改动、加 `--apply` 写入（先备份、不含 key、已有 tripcore 条目不覆盖）；也可以手动把 `nanobot/config.example.json` 里 `tools.mcpServers` 下的 `tripcore`（和可选的 `amap-maps`）合并进你自己的 `~/.nanobot/config.json`，把路径和 key 换成你自己的。重启 nanobot 后，应能看到 tripcore 的工具。

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

`~/.tripcore/`：`trip.json`（行程）、`proposals.json`（待确认的提案）、`candidates.json`（游记候选）、`chat.json`（工作台聊天记录，每个行程一份）、`map.html`、`gpx/`、`amap_calls.log`（高德调用记录，不含 key）。环境变量 `TRIPCORE_FILE` 可改行程文件位置。

## 7. 可选：用微信和它聊天

nanobot 自带 `weixin` 渠道（二维码登录的个人微信，长轮询，不需要装微信电脑版）。tripcore 的工具和 skill 不用改，只是多了一个对话入口。以下步骤**必须由你本人在自己的电脑上完成**（扫码登录、批准配对）：

1. 启用渠道：`nanobot plugins enable weixin`
2. 在 `~/.nanobot/config.json` 里加上（见 `nanobot/config.example.json`）：`"channels": {"weixin": {"enabled": true}}`。先**不要写 `allowFrom`**，这样是“只能配对”模式：第一次给机器人发私聊消息时，它只回一个配对码，没有批准前不会执行任何工具。
3. 登录：`nanobot channels login weixin`，用微信扫终端里的二维码（重新登录加 `--force`）。登录状态等同账号访问权限，不要放进仓库，也不要给别人。
4. 启动：`nanobot gateway`，保持运行。
5. 用微信给机器人发一条私聊消息，会收到配对码。在你自己电脑上执行 `nanobot agent -m "/pairing approve 配对码"`（只批准你自己的码）。再发一次消息就能对话了。
6. 之后想用固定白名单，可以把日志里看到的你的微信 ID 写进 `allowFrom`。

注意：
- **行程数据在 tripcore 里，是全局的一份**（`~/.tripcore/trip.json`），所以电脑终端和微信看到的是同一个行程，偏好也共用；但 nanobot 的聊天记录按渠道分开。只批准你自己的微信，不要用 `["*"]`，否则任何人都能改你的行程。
- 微信里看不到电脑上的文件路径。想看地图，用 `create_amap_map` 生成高德 App 链接；本地的 `map.html` 只能回电脑上打开。
- 微信聊天里不渲染 markdown 表格，skill 里已提示用短句和编号。

## 8. 可选：境外行程用 Google Maps
国内行程用高德；目的地在境外（含港澳台）时可以改用 Google Maps：
1. 在 Google Cloud 新建项目，开通 **Places API (New)** 和 **Routes API**（需要绑定付款方式，每月有免费额度）。
2. 创建 API key，限制它只能调用这两个 API，并设一个预算提醒。
3. 把 `GOOGLE_MAPS_KEY` 写进 nanobot 配置里 `tripcore` 的 `env`（和 `AMAP_KEY` 同一处，只放你本机，不要提交）。
4. 创建境外行程后，对 agent 说“这个行程用 Google”，或让它调用 `set_provider("google")`。不设置时按景点位置自动选：大陆用高德、境外用 Google，缺哪个 key 就用另一个并提醒。
说明：Google 后端没有天气接口，天气始终用 Open-Meteo；高德专属地图只支持国内行程；境外地图页的底图是 OpenStreetMap，分享链接是 Google Maps 网页链接。

## 9. 可选：网页工作台的聊天栏
工作台（`open_workbench` 或 `python -m tripcore web`）右侧的“助手”聊天栏需要 nanobot 的本机接口：
1. `nanobot plugins enable api`，然后运行 `nanobot serve`（也可以在 nanobot WebUI 的“设置 → 系统”里启动接口）。默认只监听 127.0.0.1:8900，不需要 key。
2. 如果你给接口设了 key，启动工作台前设置环境变量 `NANOBOT_API_KEY`；接口地址不是默认值时设置 `NANOBOT_API_URL`（只允许 127.0.0.1 / localhost）。
3. 没启动接口时聊天栏显示“未连接”，其他功能（拖拽、日期、撤销）不受影响。
注意：接口单次回复默认最多等 120 秒；超时或中断不会撤销 agent 已经做完的动作，聊天栏会提示“回复可能不完整”。
聊天按行程分开：每个行程有自己的助手会话，聊天记录存在该行程目录的 `chat.json`（最近 200 条，不在 `trip.json` 里，不影响版本和撤销）；切换行程时聊天栏跟着换成那个行程的记录，助手回复中不能切换。只有从工作台聊天栏发的对话会记在这里，微信等其他渠道的对话在 nanobot 自己的会话里。

## 10. 接入其他支持 MCP 的 Agent（未逐个测试）

tripcore 是标准 MCP 服务（stdio），不依赖 nanobot。其他 Agent（Claude Code、Claude Desktop、Cursor 等）理论上按各自的 MCP 配置方式添加即可，作者目前只在 nanobot 上测试过：

1. 先按第 1 节安装，装好后有 `tripcore-mcp` 命令（等价于 `python -m tripcore.mcp_server`）。
2. 在该 Agent 的 MCP 配置里添加一个 stdio 服务，命令填 `tripcore-mcp`（或虚拟环境里 python 的绝对路径加 `-m tripcore.mcp_server`），`env` 里放你自己的 `AMAP_KEY`（可选 `GOOGLE_MAPS_KEY`）。各 Agent 的配置文件位置和字段名不同，请看它自己的文档；可参考 `nanobot/config.example.json` 里 `tripcore` 那一项。
3. 让助手读 `skills/trip-planner/SKILL.md`（用法、流程和铁律）：复制到该 Agent 的指令/技能位置，或在对话开头让它先读。没有这份说明，助手知道有 92 个工具，但不知道该按什么顺序用、什么时候必须先请你确认。
4. 重启 Agent，应能看到 tripcore 的工具；对它说“打开工作台”测试。

如果你在别的 Agent 上接通了，欢迎告诉我们具体步骤。

## 改 skill 时

以仓库里的 `skills/` 为准，改完用 `scripts/install_skills.py` 同步到 nanobot（或用 `--link` 一次链好）。
