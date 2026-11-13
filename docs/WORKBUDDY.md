# 接入 WorkBuddy

两步：**登记 MCP 服务 + 安装技能**。已在真实 WorkBuddy 上接通；界面文字以你看到的为准。

## 1. 安装 TripSight

```bash
git clone https://github.com/lvshangke/TripSight.git tripcore && cd tripcore
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
tripcore doctor
which tripcore-mcp     # 记下这个绝对路径，下一步要用
```

## 2. 登记 MCP 服务

1. WorkBuddy 里打开 **专家技能 → 连接器 → 新增连接器**，会打开 `~/.workbuddy-ai/mcp.json`。
2. 填入下面的 JSON（已有其他服务的话，只把 `"tripsight"` 这一项加进 `mcpServers`）：

   ```json
   {
     "mcpServers": {
       "tripsight": {
         "command": "/绝对路径/.venv/bin/tripcore-mcp",
         "args": [],
         "env": { "AMAP_KEY": "你的高德 Web 服务 key（可选）" }
       }
     }
   }
   ```

3. 保存，确认连接器列表里 `tripsight` 已出现且开关打开（工具没出现就关掉再打开一次）。

说明：

- `command` 用上一步 `which tripcore-mcp` 的结果。
- 不填 `AMAP_KEY` 也能用（`"env": {}`），只是没有真实路线、营业时间、天气和餐厅搜索。
- 默认约 50 个工具；要全部 92 个，在 `env` 里加 `"TRIPCORE_TOOLS": "full"`。

## 3. 安装技能

```bash
python scripts/install_skills.py --dest ~/.workbuddy-ai/skills
python scripts/install_skills.py --dest ~/.workbuddy-ai/skills --check
```

重启 WorkBuddy，在 **个人中心 → Claw 设置 → Skills 管理** 里能看到 `trip-planner`、`trip-restore` 等即可。Windows 上技能目录可能是 `%APPDATA%\WorkBuddy\skills\`。

## 4. 试一试

新建任务，依次说：

1. “用 TripSight 看看我现在有哪些行程”
2. “我想去苏州玩 3 天，想逛拙政园、狮子林、平江路”
3. “用 TripSight 把 ~/Pictures/某文件夹 的照片还原成行程”
4. “打开 TripSight 工作台”

回答里出现调用 `tripsight` 工具的卡片，说明接通了；只有文字回答说明没连上。

## 常见问题

| 现象 | 处理 |
|---|---|
| 连接器里没有 `tripsight` | 检查 `mcp.json` 是否是合法 JSON、`command` 是否是绝对路径；在终端直接运行该命令不应立刻报错 |
| 有工具但助手不会用 | 重新执行第 3 步，重启 WorkBuddy |
| 调用超时 | 起地名、补照片较慢，在工作台打开“自动执行”让它们后台运行 |

行程数据在本机 `~/.tripcore/`，WorkBuddy、命令行和工作台看到的是同一份。
