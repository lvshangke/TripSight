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

> **接入聊天 Agent（nanobot）**：见 [docs/SETUP.md](docs/SETUP.md)。仓库里的 `skills/` 是给 nanobot 用的说明书，`scripts/install_skills.py` 负责安装，`nanobot/config.example.json` 是配置样例（不含密钥）。

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

`tripcore/mcp_server.py` 把 tripcore 包装成 35 个工具，供 nanobot 等 Agent 通过聊天调用：
`new_trip` `add_place` `update_place` `remove_place` `add_lodging` `lookup_coords` `refine_routes` `set_transport_prefs` `set_leg_mode` `compare_transport` `fill_hours` `suggest_food` `find_food` `choose_food` `set_travelers` `export_map` `remove_food` `get_weather` `schedule_days` `check_plan`
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
- `fill_hours`：给没有营业时间的景点从高德补（名字相符且 1.5 km 内才采用，来源 amap，不覆盖已有数据）。
- 沿途美食：`suggest_food(day, after_place_id)` 用高德周边搜索（默认 800 m、餐饮类）返回候选，不改行程；用户选定后 `choose_food` 才写入 `Trip.meals`（不占景点容量、不参与排程，可撤销）。评分、人均是参考值。
- 营业时间按日期判断时支持季节条件（`3~10月`、`10月11日起`、`11月15日起周一闭馆`）；条件复杂就返回“待核实”。
- `find_food(店名)`：用户自己想吃的店。高德按店名搜索，并用代码算出离已排行程里哪一天、哪个景点最近，作为建议位置（超过 3 km 会警告）；`choose_food` 可指定 `day` / `after_place_id` 改位置。
- `Trip.meta.travelers`（人数，默认 1，`new_trip(travelers=…)` / `set_travelers`）：`show_trip` 按人数估算门票和已选餐厅，住宿按整间价不乘人数。

## 地图页（`export_map`）与 GPX（`export_gpx`）

`export_map` 生成 `~/.tripcore/map.html`（与 `trip.json` 同目录），浏览器直接打开：
- 左侧时间线：每天 9:00 从酒店出发 → 各景点（到达/离开时间、营业时间及来源、预约与备选）→ 回酒店，闭环；🍜 用餐点挂在对应景点后面；每段显示交通方式、时长、公交线路与换乘，并带“在高德打开”链接（`uri.amap.com/navigation`，手机可调起 App）。
- 右侧地图：一次显示一天；实线是高德返回的真实路线形状（`refine_routes` 缓存在 `Leg.path`），虚线是估算直线；靠得太近的标记会错开显示。
- 底图是高德通用瓦片（`webrd0{s}.is.autonavi.com`，仅供个人使用，不是官方 JS API），坐标由 WGS84 自动转成 GCJ-02。Leaflet 1.9.4（BSD-2，见 `tripcore/assets/LEAFLET-LICENSE`）内嵌在页面里，只有瓦片需要联网。
- 页面数据由代码生成，文字在浏览器端转义。

`export_gpx(day)` 把每天的闭环路线写成 `~/.tripcore/gpx/day-N.gpx`（WGS84；途经点 + 轨迹，估算段在注释里标明）。

## 高德专属地图（`create_amap_map`）

`create_amap_map(day, per_day)`：tripcore 用 `AMAP_KEY` 直接请求高德官方 MCP（`https://mcp.amap.com/mcp`，streamable HTTP，需要 `mcp>=1.8`）的 `maps_schema_personal_map`，返回高德 App 的唤起链接（`amapuri://…`，要在装了高德的手机上打开）。参数由 `personal_map_payload` 生成：`orgName`、`lineList[{title, pointInfoList[{name, lon, lat, poiId}]}]`，每天一条行程，酒店→景点（用餐点挂在景点后）→酒店；`poiId` 由代码按名称+距离（景点 1.5 km、酒店 1 km 内）在高德里匹配并存下来，匹配不上的点跳过并列出；坐标转成高德坐标系。整个过程不经过模型，请求记在 `amap_calls.log`（不含 key）。默认 `per_day=True`：每天一个链接（实测高德 App 的专属地图一次只显示 `lineList` 里的第一条行程）；`per_day=False` 才合成一张。
测试时可用环境变量 `AMAP_MCP_URL` 指向本地假服务。

## 机场/车站接驳的时间感知

机场/车站 ↔ 酒店这两段会带上预计出发时间去问高德（含夜班车）。出发时间落在 23:00–05:30 时，按经验规则视为公共交通已停运，改按打车（驾车）计算，路线说明里会写明；这是经验规则，不是真实末班车时间。出发时间（精确到小时）变了，会自动重查。地图在到达日/离开日显示 ✈/🚄 标记和酒店标记，即使当天没有景点。

## 游记/攻略 → 候选景点（`submit_candidates` / `adopt_candidates`）

用户粘贴游记后，模型只负责读文字、列清单；代码核对：每个候选的原话 `quote` 必须逐字出现在原文里且包含地名，线索 `clues` 也必须是原文片段，对不上的拒收；候选按原文出现先后排序（顺路路线即游览顺序）并去重。候选存在 `~/.tripcore/candidates.json`，用户挑选后 `adopt_candidates` 才用地图查坐标：名字相符且无歧义、与已有景点相距 ≥ 300 米才加入，价格/时间只作“待核实线索”写进备注。餐饮类走 `find_food`。工具：`submit_candidates` `list_candidates` `drop_candidates` `adopt_candidates`。

## 路线型景点（`add_route_place`）与排程改动

- **路线型景点**：一个景点带有序途经点（如 citywalk 老菜场→…→永宁门）。排程里仍是一项，但进入它的路段终点是第一个途经点、离开它的路段起点是最后一个途经点；地图画出途经点和相邻点之间的步行路线（高德，没有 key 时是直线并标注），GPX 也包含这些点和路线。时长 = 步行时间 + 每站 15 分钟（估算，可 `update_place` 调整）。途经点位置只采用高德里名字相符且无歧义的结果。
- **排程尊重可用时间窗口**：到达日/离开日按窗口缩小容量，窗口不足 2 小时的那天不排景点（例如凌晨 6:30 的航班那天）。
- **提案里的“移动”自动锁定**：确认过的安排不会被之后的 `schedule_days` 打乱；要再移动，先在提案里加 `lock`（locked=false）解锁。

## 出行偏好会真正影响路线

`set_transport_prefs` 里的“最多换乘几次”“更愿意坐地铁”现在会传给公交路线查询：高德返回多个方案时，只选换乘不超限的；默认方案都超限时再查“少换乘”方案；仍然超限就选换乘最少的，并在路线说明里标 `⚠`；坐地铁的方案最多比最快方案慢 30% 时优先。改了这两项偏好会清掉旧的公交路线缓存，需要重新 `refine_routes`。

## 到达与离开（`set_connection` / `clear_connection`）

`Trip.arrival` / `Trip.departure`：到达、离开目的地的航班/火车（班次、出发和到达时间、每人参考价及来源日期、是否已订）。确定性规则：到达日可开始游玩 = 到达时间 + 出站时间（飞机 45 / 火车 15 分钟）+ 机场/车站→酒店（没选酒店则第一个景点）的路程时间；离开日最晚出发 = 起飞/发车时间 − 提前量（飞机 120 / 火车 40 分钟）− 酒店→机场/车站的路程时间；每天默认 9:00–21:00。`set_connection(..., terminal_name="咸阳国际机场")` 会用高德查出机场/车站位置，`refine_routes` 查真实路程（`show_trip`/地图标明“高德路线”或“距离估算”）；没填名称或查不到时，路程用经验值兜底（到达 飞机 45/火车 30，离开 飞机 60/火车 20 分钟）。第一天/最后一天的可玩时间据此缩短：`check_plan` 报 `CONNECTION_WINDOW_TOO_SMALL`（装不下）和 `CONNECTION_DATE_MISMATCH`（日期不在行程内）；`show_trip` 和地图时间线显示可玩时段，地图第一天从到达后的时间开始；大交通价格 × 人数计入“按 N 人估算”。排程算法本身不变，调整由提案走确认。

查询机票/火车票/酒店价格使用飞猪 `flyai` 命令行，技能 `flyai-search` 限制为只读（只用 `search-flight`/`search-train`/`search-hotel`，不预订，不安装，不配置 key，价格标来源和日期；酒店坐标一律由高德查，不用 FlyAI 的）。

