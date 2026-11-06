# 接入 WorkBuddy

WorkBuddy 支持自定义 MCP 连接和自定义技能，TripSight（tripcore）是标准的 MCP 服务，所以按“**登记 MCP 服务 + 安装技能**”两步接入即可。

> 状态：按 WorkBuddy 官方文档的 MCP 配置方式（`~/.workbuddy/mcp.json`）整理，**作者尚未在真实 WorkBuddy 上逐项验证**；如果某一步和你看到的界面不一致，以 WorkBuddy 自己的界面为准，并欢迎提 issue。

## 1. 安装 TripSight

```bash
git clone https://github.com/lvshangke/TripSight.git tripcore && cd tripcore
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
tripcore doctor      # 自检，缺什么会告诉你怎么补
```

记下两个绝对路径（下面要用）：

```bash
which tripcore-mcp   # 例如 /Users/你/tripcore/.venv/bin/tripcore-mcp
pwd                  # 例如 /Users/你/tripcore
```

## 2. 登记 MCP 服务

在 WorkBuddy 里打开 **连接（Connections）→ 自定义连接 → Configure MCP**（会打开 `~/.workbuddy/mcp.json`），把下面这一项加进 `mcpServers`（已有别的服务就合并，不要覆盖）：

```json
{
  "mcpServers": {
    "tripsight": {
      "command": "/绝对路径/到/.venv/bin/tripcore-mcp",
      "args": [],
      "env": {
        "AMAP_KEY": "在这里填你自己的高德 Web 服务 key（可选，只放在你本机）"
      }
    }
  }
}
```

保存后在 **My MCP** 里确认 `tripsight` 已列出并打开开关；工具没出现就把开关关掉再打开一次。

说明：
- `AMAP_KEY` 可以不填，没有它就没有真实路线、营业时间、天气和餐厅搜索，其余功能照常。key 只放在这里，不要提交到仓库，也不要发进聊天。
- 默认只暴露“规划核心 + 恢复行程/手册”两档工具，省上下文；想要全部 89 个工具，在 `env` 里加 `"TRIPCORE_TOOLS": "full"`。
- 如果 WorkBuddy 的 MCP 配置只接受 `command` 加 `args` 的写法，也可以写成 `"command": "/绝对路径/到/.venv/bin/python", "args": ["-m", "tripcore.mcp_server"]`。
- 行程数据在 `~/.tripcore/`，不会因为换 Agent 而丢失。

## 3. 安装技能（让助手知道流程和铁律）

技能是给助手的“说明书”：什么时候用哪些工具、哪些事不能自己编。把仓库里的 `skills/` 复制到 WorkBuddy 的技能目录：

```bash
python scripts/install_skills.py --dest ~/.workbuddy/skills          # 复制
python scripts/install_skills.py --dest ~/.workbuddy/skills --check  # 检查是否一致
```

（Windows 如果提示找不到技能，目录可能是 `%APPDATA%\WorkBuddy\skills\`。）也可以在 WorkBuddy 的 **个人中心 → Claw 设置 → Skills 管理** 里查看是否出现 `trip-planner`、`trip-restore` 等。`trip-planner` 是主技能，其余按场景触发。

## 4. 试一试

新建一个任务，依次试：

1. “用 TripSight 看看我现在有哪些行程”——能列出行程说明工具已接通。
2. “我想去苏州玩 3 天，想逛拙政园、狮子林、平江路”——应该先查坐标、再分天，并给出检查结果。
3. “用 TripSight 恢复行程：把 ~/Pictures/某文件夹 的照片还原成行程”——走恢复流程。
4. “打开 TripSight 工作台”——助手会返回一个带一次性令牌、只在本机有效的网址，在这台电脑的浏览器里打开即可（也可以直接运行 `tripcore web --open`）。

## 常见问题

| 现象 | 处理 |
|---|---|
| `tripsight` 没出现在 My MCP | 确认 `mcp.json` 是合法 JSON；`command` 必须是绝对路径；在终端里直接运行该命令不应立刻报错 |
| 工具出现了但助手不会用 | 技能没装好：重新执行第 3 步，重启 WorkBuddy |
| 调用报超时 | 起地名、补照片这类步骤较慢；工作台里的“自动执行”会让它们在后台跑。可在 WorkBuddy 的 MCP 设置里把超时调大（若有该选项） |
| 想让助手少占上下文 | 保持默认的 `core,restore`；需要其他功能时按技能指引用 `tripcore run 工具名 '{...}'` 命令行调用 |

> 注意：WorkBuddy 的聊天记录和 TripSight 的行程数据是分开的；TripSight 的行程是本机全局一份，所以在 WorkBuddy、命令行和工作台里看到的是同一个行程。
