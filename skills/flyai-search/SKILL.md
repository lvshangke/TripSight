---
name: flyai-search
description: 用飞猪 flyai 命令行只读地查询机票、火车票、酒店价格（search-flight / search-train / search-hotel），结果只作参考价；用户问机票、车票、订票、酒店价格时使用。禁止预订、禁止安装程序。
---

# FlyAI 只读查询（机票 / 火车票 / 酒店价格）

本技能是对飞猪 flyai 命令行的**受限用法**。目的是给 tripcore 的行程提供“到达/离开的大交通”和“酒店价格参考”，价格和班次都只是查询当时的参考。

## 铁律

1. **只允许这三个命令**：`flyai search-flight`、`flyai search-train`、`flyai search-hotel`。不要用 `keyword-search`、`ai-search`、`search-poi`、`search-marriott-*`；景点、营业时间、路线一律用 tripcore 的工具。
2. **绝不预订、下单、支付**。结果里的 `jumpUrl` / `detailUrl` 只是给用户自己打开的链接，你不要访问它们，不要替用户点击。
3. **绝不安装、下载、升级任何程序**，不要执行 `npm`、`curl`、`wget` 去装 flyai。先运行 `flyai --help` 检查；找不到命令就告诉用户“需要你自己先安装 flyai 命令行（npm i -g @fly-ai/flyai-cli）”，然后停下。
4. **不要配置或索要 API key**（不要运行 `flyai config set`）。
5. 价格必须写明**查询日期**和**来源 flyai**，并告诉用户“价格是查询时的参考，下单前以平台为准”；不要说成最终价格，也不要自己估算。

## 命令参数（写命令前以这里为准，不要猜）

- 机票：`flyai search-flight --origin "上海" --destination "北京" --dep-date 2026-10-19 [--back-date 日期] [--journey-type 1(直达)|2(中转)] [--dep-hour-start N --dep-hour-end N] [--arr-hour-start N --arr-hour-end N] [--max-price 数字(元)] [--sort-type 3]`
  `--origin` 必填；日期格式 `YYYY-MM-DD`；`--sort-type`：1 价格高到低，2 推荐，3 价格低到高，4 耗时短到长，6 出发早到晚，8 直达优先。
- 火车票：`flyai search-train --origin "上海" --destination "杭州" --dep-date 2026-10-19 [同上筛选参数]`，`--seat-class-name` 支持逗号分隔（二等座、一等座等）。
- 酒店：`flyai search-hotel --dest-name "西安" [--poi-name "钟楼"] [--check-in-date 日期 --check-out-date 日期] [--hotel-stars "4,5"] [--sort price_asc|rate_desc|distance_asc] [--max-price 每晚上限]`，`--dest-name` 必填，只能是国家/省/市/区。
- 输出是单行 JSON：`data.itemList[]`；机票/火车有 `adultPrice`（带 ¥ 的字符串）、`journeys[].segments[]`（`depDateTime`、`arrDateTime`、`marketingTransportNo`、`depStationName`、`arrStationName`、`seatClassName`）、`jumpUrl`；酒店有 `name`、`price`（带 ¥）、`score`、`address`、`detailUrl`。`systemMessage` 如有，原样转告用户。

## 机票 / 火车票的流程

1. 先确认：出发城市、目的地、日期（行程日期没定就先问，不要猜）、人数、偏好（直达、时段、预算）。
2. 查询后展示 3~5 个方案的表格：航班号/车次、出发和到达时间、时长、直达或中转、价格（¥，查询日期）。如实写，不要美化。
3. 由用户选定后，用 `set_connection` 记录：
   - `which`：到达行程目的地用 `arrival`，离开用 `departure`；
   - 时间取自第一段的 `depDateTime` 和最后一段的 `arrDateTime`，逐字抄，不要换算；多段中转的方案，先把各段念给用户确认；
   - `number`、`from_name`、`to_name` 取自结果；`price_per_person` 取 `adultPrice` 的数字，`price_source` 填 `flyai`，`price_date` 填今天日期（可运行 `date +%Y-%m-%d`）；
   - `booked` 保持 False，只有用户亲口说已订好才填 True。
4. 记录后调用 `check_plan`：如果提示第一天或最后一天时间不够，把原因告诉用户，用 `propose_change` 提出调整方案，等用户确认。不要自己改行程。

## 酒店价格的流程

- FlyAI 的酒店**只用来取价格**。它返回的经纬度坐标系没有确认，**不要**用它的坐标；酒店的位置一律用 `lookup_coords` 查（高德）后再 `add_lodging`。
- `add_lodging` 的价格：每晚价，`price_min`/`price_max` 填同一个或区间，`price_source` 填 `flyai`，`price_date` 写查询日期。没有来源就不要填价格。
- 同一家酒店有多个来源的价格（如 RollingGo、用户手填）差距明显时，如实列出来让用户判断，不要自己取平均。
