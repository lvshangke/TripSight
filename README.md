# tripcore —— 旅行规划核心（里程碑 1）

一个**没有界面、没有 AI** 的旅行规划小程序，只用规则完成这些事：

1. 你给出一批想去的景点（带经纬度）、天数、节奏；
2. 程序自动把景点分到每一天，并排好每天的游览顺序；
3. 估算相邻景点之间的交通时间；
4. 推荐住在哪一带，并给候选酒店按通勤排序；
5. 检查问题：太赶、闭馆、没预约、路上太久、超预算……
6. 所有修改都可以先写成“提案”，确认后才生效，并且**可以撤销**。

> 为什么先不做 AI、不做界面？因为要先确认“数据怎么表示、规则对不对”。
> 这一层稳定了，后面接大模型、接地图、做网页，都只是在它上面加东西。

---

## 一、第一次运行（约 5 分钟）

需要 Python 3.10 或更新版本（本项目在 Python 3.12 上测试通过）。

```bash
# 1. 进入项目文件夹
cd tripcore

# 2.（推荐）创建独立环境，避免污染系统
python3 -m venv .venv
source .venv/bin/activate          # Windows 用：.venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 运行完整演示
python -m tripcore demo

# 5. 运行测试（应显示全部通过）
python -m pytest -q
```

> Windows 上如果 `python3` 不可用，请改用 `python`。

`demo` 会用 `examples/beijing.json` 演示完整流程：分天 → 检查 → 推荐住宿 → 选定住宿后重新安排。
**示例里的坐标、闭馆日、预约信息都是近似值，只用于演示，真实出行请以官方信息为准。**

---

## 二、常用命令

```bash
# 读取你自己的 JSON，自动分天并检查
python -m tripcore plan examples/beijing.json

# 指定节奏 / 交通方式 / 住宿，并把结果保存下来
python -m tripcore plan examples/beijing.json --pace relaxed --mode transit --lodging hotel_qianmen --out my_trip.json

# 检查一个已保存的行程
python -m tripcore check my_trip.json

# 撤销最近一次修改（会直接改写这个文件）
python -m tripcore undo my_trip.json

# 查某个地名的经纬度（需要联网，用的是 OpenStreetMap 的免费服务）
export TRIPCORE_CONTACT="你的邮箱或项目地址"   # 使用政策要求带上可联系的标识
python -m tripcore geocode "故宫博物院" --city 北京
```

---

## 三、怎么写你自己的行程（JSON）

复制 `examples/beijing.json`，改成你自己的。关键字段：

**meta（整体设置）**

| 字段 | 含义 |
|---|---|
| `date_mode` | `exact` 日期已定 / `range` 只有范围 / `unknown` 还没定 |
| `start_date` `end_date` | 日期已定时填写，天数由它们决定 |
| `num_days` | 日期没定时填写天数 |
| `pace` | `relaxed` 悠闲（每天 ≤2 个）/ `normal`（≤3 个）/ `packed`（≤5 个） |
| `mode` | 交通偏好：`walk` / `transit` / `drive` |
| `budget_total` | 总预算，可不填 |

**places（景点）**

| 字段 | 含义 |
|---|---|
| `id` | 唯一标识，英文或拼音，不能重复 |
| `name` `lat` `lon` | 名称、纬度、经度（WGS84） |
| `status` | `idea` 想法 / `shortlist` 入围（默认）/ `planned` 已安排 / `confirmed` 已确认 / `excluded` 排除。其中 `shortlist`、`planned`、`confirmed` 会参与自动分天；`idea` 和 `excluded` 不会 |
| `duration_min` | 预计游览分钟数 |
| `priority` | 重要程度 1~5，名额不够时优先保留高的 |
| `must_go` | 必去。必去景点即使放不下也会硬塞进去，并由检查提醒“太满” |
| `closed_weekdays` | 每周闭馆日，0=周一 … 6=周日（仅在日期已定时生效） |
| `reservation_required` `reserved` | 是否需要预约 / 是否已约好 |
| `ticket_price` | 门票（元） |

**lodgings（候选住宿）**：`id` `name` `lat` `lon` `price_min` `price_max`（每晚）。

---

## 四、代码结构（想读代码从这里开始）

```
tripcore/
├── models.py      数据结构：景点、住宿、行程、旅行（先读这个）
├── geo.py         距离计算 + 通勤时间估算
├── metrics.py     每天的统计（游览/交通分钟、费用）和各节奏的上限
├── scheduler.py   自动分天 + 天内排序（核心算法，注释最多）
├── validator.py   检查问题，返回问题清单
├── lodging.py     住宿区域推荐、候选酒店排序
├── proposals.py   提案：移动/移出/改状态/锁定，带版本检查
├── state.py       版本号 + 历史快照 + 撤销
├── storage.py     读写 JSON 文件
├── geocode.py     地名 → 经纬度（OpenStreetMap）
└── cli.py         命令行
tests/             97 个测试（先看 test_scheduler.py，最容易读懂）
examples/          示例数据
DESIGN.md          设计原则、算法说明、已知局限、后续计划
```

---

## 五、已知局限（请务必了解）

- **交通时间只是估算**：用直线距离乘绕行系数再除以经验速度，不是真实路线。里程碑 3 才接入地图服务。
- **分天是启发式，不保证最优**：相同输入结果一致，但不一定是数学上最好的方案。好坏以“检查结果”为准，可以用提案手动调整。
- **闭馆只按“星期几”判断**，没有具体营业时间，也不知道法定节假日。
- **只支持整个行程住同一个酒店**。
- `date_mode` 为 `range` / `unknown` 时，不做闭馆日检查（因为不知道具体星期几）。
- 费用只含“门票 + 住宿”，不含餐饮和交通。
- 地理编码的结果有时不准（尤其是重名或中文别名），请人工核对。国内地图服务使用另一套坐标系（GCJ-02），以后接入时需要转换。
- 目前只在 Python 3.12 上运行过测试。

---

## 六、下一步

- **里程碑 2**：用 Streamlit 做一个能看地图、能手动调整的页面；数据改存 SQLite。
- **里程碑 3**：加聊天框，让大模型通过“工具调用”产出**提案**（不是直接改数据）；接入真实路线服务。

## 七、和 AI 编程助手配合的建议

- 一次只让它做一小步，并要求“给出能运行、能验证的例子”。
- 改代码前先跑 `python -m pytest -q`，改完再跑；红了就让它先修复。
- 想改规则，先用大白话写成测试，再让它实现。
- 把 `DESIGN.md` 发给它，让它遵守里面的设计原则。
- 用 git 保存每个能跑通的版本：`git init && git add . && git commit -m "第一个能跑的版本"`。

## MCP 服务（第 1 步）

`tripcore/mcp_server.py` 把 tripcore 包装成 17 个工具，供 nanobot 等 Agent 通过聊天调用：
`new_trip` `add_place` `update_place` `remove_place` `add_lodging` `lookup_coords` `refine_routes` `set_transport_prefs` `set_leg_mode` `compare_transport` `get_weather` `schedule_days` `check_plan`
`suggest_lodging` `propose_change` `apply_proposal` `undo` `show_trip`。

- 状态保存在 `~/.tripcore/trip.json`（环境变量 `TRIPCORE_FILE` 可改），待确认的提案在同目录 `proposals.json`。
- 所有修改走“提案 → 确认 → 套用”，`undo` 可撤销。
- 依赖：`pip install -r requirements.txt`（mcp 需 <2）。

nanobot 配置（写进 `tools.mcpServers`，把 python 路径换成 trip_env 里的，`cwd` 换成本项目目录）：

```json
{
  "tools": {
    "mcpServers": {
      "tripcore": {
        "command": "/Users/你的用户名/miniforge3/envs/trip_env/bin/python",
        "args": ["-m", "tripcore.mcp_server"],
        "cwd": "/Users/你的用户名/Desktop/tripcore",
        "env": { "TRIPCORE_CONTACT": "你的邮箱" }
      }
    }
  }
}
```

提案需要确认码：`propose_change` 返回 4 位 `confirm_code`，用户回复后才能 `apply_proposal`（这只是减速带，不是安全边界）。

## 高德地图（第 2 步）

- 设置环境变量 `AMAP_KEY`（nanobot 配置里写在 `tripcore` 的 `env` 中，不要写进代码、不要提交）。
- `lookup_coords`：有 key 时用高德搜索，返回候选（地址、评分、参考价 `cost_reference`、今日营业时间）；没有 key 或高德失败时退回 OpenStreetMap。
- `refine_routes`：把行程里的“估算”交通升级为高德真实路线时间并缓存（`Trip.route_overrides`）。
- 内部坐标统一为 WGS84，和高德交互时在 `tripcore/coords.py` 里与 GCJ-02 互转。
- `cost_reference` 是高德的“人均消费”参考值，不是实时房价，也不一定是门票。
- 目前所有高德代码只用假数据测试过，还没有用真实 key 联调。

景点新增 `opening_hours` / `hours_source`（营业时间及来源）和 `backups`（备选景点；预约没约上时 `check_plan` 会提示）。高德每次调用会记到 `~/.tripcore/amap_calls.log`（不含 key）。

出行方式：`set_transport_prefs`（步行上限、偏好地铁、最大换乘、是否打车）、`set_leg_mode`（单段指定方式）、`compare_transport`（高德比较步行/公交/驾车并按偏好给建议）。公交结果含换乘次数、步行距离、票价、线路、是否含地铁（字段按高德文档解析，待真实 key 联调确认）。

## 营业时间展示与天气

- `show_trip` 每个景点下显示营业时间、来源、预约与备选；有具体日期时按星期判断当天时段，可能闭馆会标 ⚠，无法判断标“待核实”。
- `get_weather`：高德天气预报，仅覆盖约未来 4 天；没有具体日期或日期超出范围时直接说明，不编造。
- 指定过出行方式的路段（`set_leg_mode`），`refine_routes` 严格按指定方式查询，不会因距离近改成步行。
