# 飞运运输管理系统（TMS）建设方案

版本：v1.0　日期：2026-10-24　分类：企业管理系统

## 1. 项目概述

飞运运输管理系统（FeiYun TMS）面向中小物流/运输企业，覆盖**客户管理、车辆与司机资产、线路、运单全生命周期、调度、在途跟踪、财务结算、油耗、风险预警**九大业务域，并提供用户/角色/权限/令牌/API Key/公告/日志/幂等/增量同步等平台能力。

### 1.1 设计原则
- 零依赖：Python 标准库（http.server + sqlite3），无第三方包
- 纯函数内核：运价/ETA/油耗/结算/风险等计算与 IO 解耦，可独立单测
- 统一响应包：`{"code": 200, "message": "ok", "data": {...}}`
- Decimal 精确：金额一律 quantize 到分（ROUND_HALF_UP）
- 对外友好：五通道鉴权、幂等键、增量同步、CSV 导出、OpenAPI 风格 API 文档

### 1.2 技术栈
| 层 | 技术 |
|---|---|
| 后端 | Python 3.8+ 标准库，ThreadingHTTPServer |
| 数据库 | SQLite（WAL 模式） |
| 前端 | 原生 HTML/CSS/JS 单页应用（SPA），橙色主题 |
| 部署 | systemd + nginx 反向代理 /tms/ → 127.0.0.1:8026 |

## 2. 业务域设计

### 2.1 客户（customers）
托运人/收货人档案：编码、名称、联系人、电话、地址、结算方式（月结/现结）、信用额度、欠款。信用额度用于风险预警。

### 2.2 车辆（vehicles）
车牌、车型（4.2m/6.8m/9.6m/13m/17.5m）、载重(kg)、容积(m³)、状态（空闲/在途/维保/停用）、里程、下次维保日期、保险到期日。

### 2.3 司机（drivers）
姓名、手机、驾照号、驾照类型（A2/B2/C1）、驾照到期日、状态（空闲/在途/休假/离职）、累计运单数、累计里程。

### 2.4 线路（routes）
起点、终点、标准里程(km)、标准时长(小时)、基础运价（元/km）。

### 2.5 运单（waybills）—— 核心实体
状态机：**待调度(pending) → 运输中(in_transit) → 已签收(delivered)**，另有 **已取消(cancelled)**。
字段：运单号、客户、线路、货物名称/重量(kg)/体积(m³)、单价模式（按重/按方/按趟）、报价、实际里程、签收时间、签收人、备注。

### 2.6 调度（dispatch）
运单绑定车辆+司机，一次调度一条记录：调度时间、发车时间、预计到达(ETA)、实际到达。同一运单可改派（旧记录标 replaced）。

### 2.7 跟踪（tracking）
GPS 点位流：运单号、时间、经度、纬度、位置描述、事件（发车/到达服务区/异常/到达）。

### 2.8 结算（settlements）
应收（客户）、应付（司机）、毛利三段拆分：运费收入、油耗成本、过路费、其他成本；状态（待结/已结）。金额 Decimal 精确到分。

### 2.9 油耗（fuel）
车辆加油记录：日期、升数、单价、金额、当前里程表读数 → 计算百公里油耗。

### 2.10 风险预警（risks）
四类规则：
- 运单逾期未达（超 ETA 未签收）
- 车辆维保/保险到期（30 天内）
- 司机驾照到期（30 天内）
- 客户欠款超信用额度 80%

## 3. 计算内核（tms.py 纯函数）

| 函数 | 说明 |
|---|---|
| `freight_price(mode, weight_kg, volume_m3, distance_km, base_rate)` | 按重（元/吨km×0.001）、按方、按趟三种模式，Decimal 到分 |
| `eta_hours(distance_km, avg_speed=60, rest_every=4, rest_hours=0.5)` | 每 4 小时强制休息 0.5h |
| `fuel_cost(distance_km, per_100km_l, price_per_l)` | Decimal |
| `load_ratio(weight, cap_w, volume, cap_v)` | 装载率 = max(重载率, 方载率)，封顶 100% |
| `settlement_split(revenue, fuel, tolls, other)` | 应收/应付司机(60%)/毛利，Decimal |
| `overdue_check(eta_ts, delivered_ts)` | 逾期判定与逾期小时数 |
| `waybill_risk(overdue_h, load_ratio, client_overdue_ratio)` | 风险评分 0-100 分档：≥60险 ≥35警 >0提 0正常 |
| `hundred_km_fuel(liters, km)` | 百公里油耗，km<50 返回 None |
| `validate_waybill / validate_vehicle / validate_driver` | 实体校验 |
| `ROLE_PERMS / has_perm` | 六角色权限（admin/dispatcher/ops/finance/driver_captain/reader），通配与前缀规则 |

## 4. 数据库设计（21 表 + 索引）

customers, vehicles, drivers, routes, waybills, dispatches, trackings, settlements, fuel, risks, policies, notices, users, tokens, api_keys, logs, idem_keys, sync_state, tms_rules, sessions_meta, seq（编号序列）。

关键索引：waybills(status)、waybills(customer_id)、dispatches(waybill_id)、trackings(waybill_id, ts)、settlements(waybill_id)、fuel(vehicle_id, date)、logs(ts)。

## 5. 安全与集成能力

- 鉴权五通道：`Authorization: Bearer` / `X-Token` / `Cookie` / `?token=` / `X-Api-Key`（SHA-256 存储）
- 权限模型：`*` 超级、`tms.*` 前缀、写含读
- 幂等：`Idempotency-Key` 头，结果落 idem_keys 表，24h 复用
- 增量同步：`GET /api/sync?since=<version>&entities=waybills,trackings`
- 审计日志：登录、写操作全量落 logs
- CSV 导出：UTF-8 BOM，Excel 直开

## 6. 部署方案

- 服务：systemd 单元 `feiyun-tms`，`TMS_PORT=8026 TMS_DB=/opt/feiyun-tms/data/feiyun.db`
- nginx：`location /tms/ { proxy_pass http://127.0.0.1:8026/; }`（剥前缀，后端 PREFIX 留空）
- 前端 PREFIX 由 `location.pathname` 自动推导
- GitHub：`dukema81/feiyun-tms`

## 7. 质量门禁

1. pytest 单测（内核 + API）≥ 45 例全绿
2. Playwright UI 巡检（登录 + 全部页面）全绿
3. 冒烟测试（本地 + 线上）全绿
4. DEMO 单文件快照 ≥ 30 路径有数据
