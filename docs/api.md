# 飞运 TMS API 接口契约 v1.0

Base URL（线上）：`http://42.193.158.63/tms/api/...`
Base URL（本地）：`http://127.0.0.1:8026/api/...`

## 0. 通用约定

- 统一响应包：`{"code": 200, "message": "ok", "data": {...}}`；code 与 HTTP 状态码一致
- 列表接口统一返回 `{"items": [...], "total": n, "page": p, "size": s}`
- 认证五通道（任选其一）：
  1. `Authorization: Bearer <token>`
  2. `X-Token: <token>`
  3. `Cookie: token=<token>`
  4. `?token=<token>`
  5. `X-Api-Key: <key>`（系统间对接推荐）
- 幂等：写接口可带 `Idempotency-Key` 头，重复请求返回首次结果
- 增量同步：`GET /api/sync?since=<version>&entities=waybills,trackings` 返回 `{"since": v, "current": c, "changes": {entity: {"items": [...], "version": v}}}`
- 错误码：400 参数错 / 401 未认证 / 403 无权限 / 404 不存在 / 409 冲突 / 422 业务校验失败 / 500 内部错误

## 1. 认证与账号

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| POST | /api/login | `{username, password}` → `{token, user, perms}` | 公开 |
| POST | /api/logout | 注销当前 token | 登录 |
| GET | /api/me | 当前用户信息与权限 | 登录 |
| GET | /api/users | 用户列表 | admin |
| POST | /api/users | 创建用户 | admin |
| PUT | /api/users/{id} | 修改（含重置密码/角色/禁用） | admin |
| GET | /api/api-keys | API Key 列表 | admin |
| POST | /api/api-keys | 生成 API Key（仅明文返回一次） | admin |
| DELETE | /api/api-keys/{id} | 吊销 | admin |

示例：
```bash
curl -X POST http://host/tms/api/login -d '{"username":"admin","password":"123456"}'
# {"code":200,"data":{"token":"...","perms":["*"]}}
curl http://host/tms/api/waybills -H "X-Api-Key: fyt_xxx"
```

## 2. 客户 customers

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/customers?keyword=&page=&size= | 列表（关键词搜编码/名称/联系人） |
| POST | /api/customers | 新建 `{code,name,contact,phone,address,settle_type,credit_limit}` |
| GET | /api/customers/{id} | 详情（含欠款、在途运单数） |
| PUT | /api/customers/{id} | 修改 |
| DELETE | /api/customers/{id} | 删除（有运单引用时 409） |
| GET | /api/customers/{id}/waybills | 该客户运单 |
| GET | /api/customers/{id}/balance | 欠款与信用额度使用率 |

## 3. 车辆 vehicles

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/vehicles?status=&keyword= | 列表 |
| POST | /api/vehicles | `{plate, vtype, cap_weight, cap_volume, next_maint, insurance_exp}` |
| GET/PUT/DELETE | /api/vehicles/{id} | 详情/修改/删除（在途 409） |
| GET | /api/vehicles/{id}/fuel | 该车油耗记录 |
| GET | /api/vehicles/{id}/stats | 运单数/总里程/平均装载率/百公里油耗 |

## 4. 司机 drivers

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/drivers?status=&keyword= | 列表 |
| POST | /api/drivers | `{name, phone, license_no, license_type, license_exp}` |
| GET/PUT/DELETE | /api/drivers/{id} | 详情/修改/删除（在途 409） |
| GET | /api/drivers/{id}/stats | 运单数/里程/准时率 |

## 5. 线路 routes

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/routes?keyword= | 列表 |
| POST | /api/routes | `{origin, dest, distance_km, hours, base_rate}` |
| GET/PUT/DELETE | /api/routes/{id} | 详情/修改/删除 |

## 6. 运单 waybills（核心）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/waybills?status=&customer_id=&date_from=&date_to=&page= | 列表 |
| POST | /api/waybills | 新建（状态 pending）`{no?, customer_id, route_id, goods, weight_kg, volume_m3, price_mode, quote}` |
| GET | /api/waybills/{id} | 详情（含调度/跟踪/结算） |
| PUT | /api/waybills/{id} | 修改（仅 pending 可改核心字段） |
| DELETE | /api/waybills/{id} | 删除（仅 pending） |
| POST | /api/waybills/{id}/dispatch | 调度 `{vehicle_id, driver_id}` → 状态 in_transit，生成 ETA |
| POST | /api/waybills/{id}/track | 追加跟踪点 `{lng, lat, location, event}` |
| POST | /api/waybills/{id}/deliver | 签收 `{signer, actual_distance?}` → delivered，自动生成结算 |
| POST | /api/waybills/{id}/cancel | 取消（in_transit 需先撤销调度） |
| GET | /api/waybills/{id}/trackings | 跟踪点位流 |
| POST | /api/waybills/quote | 运价试算（不落库）`{price_mode, weight_kg, volume_m3, distance_km, base_rate}` |

**状态机约束**：
- pending → in_transit（dispatch）；in_transit → delivered（deliver）或 pending（撤销调度）；pending/delivered → cancelled
- 非法迁移返回 422

## 7. 调度 dispatches

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/dispatches?status= | 列表 |
| POST | /api/dispatches | 直接创建 `{waybill_id, vehicle_id, driver_id}` |
| POST | /api/dispatches/{id}/revoke | 撤销调度（运单回 pending） |
| GET | /api/dispatches/{id} | 详情 |

## 8. 跟踪 trackings

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/trackings?waybill_no=&from=&to= | 全局跟踪流 |
| POST | /api/trackings | 批量上报（供车载终端）`[{waybill_no, ts, lng, lat, location, event}]` |

## 9. 结算 settlements

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/settlements?status=&type= | 列表（type=receivable/payable） |
| POST | /api/settlements | 手工创建 `{waybill_id, revenue, fuel, tolls, other}` |
| GET | /api/settlements/{id} | 详情（含毛利拆分） |
| PUT | /api/settlements/{id} | 修改（仅待结） |
| POST | /api/settlements/{id}/close | 结清 |
| GET | /api/settlements/summary | 汇总：应收/应付/毛利/结清率 |
| GET | /api/settlements/export | CSV 导出 |

## 10. 油耗 fuel

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/fuel?vehicle_id=&from=&to= | 列表 |
| POST | /api/fuel | `{vehicle_id, date, liters, price, odometer}` |
| PUT/DELETE | /api/fuel/{id} | 修改/删除 |

## 11. 风险预警 risks

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/risks | 预警列表 |
| POST | /api/risks/scan | 触发扫描（逾期运单/维保/驾照/欠款），返回新增数 |
| PUT | /api/risks/{id}/resolve | 处理 `{note}` |

## 12. 看板与统计

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/dashboard | 今日运单/在途/待调度/本月毛利/预警数/装载率 |
| GET | /api/stats/waybills?days=30 | 按日运单量与毛利趋势 |
| GET | /api/stats/vehicles | 车辆利用率排行 |
| GET | /api/stats/drivers | 司机绩效排行 |
| GET | /api/stats/clients | 客户业务量 TOP |

## 13. 平台域

notices（公告 CRUD）、policies（制度 CRUD）、logs（审计查询，admin）、idem_keys（运维查询）、
`GET /api/sync?since=&entities=`（增量同步）、`GET /api/export/{entity}`（CSV 导出：waybills/customers/settlements/fuel）。

## 14. 对接示例（外部系统 → 飞运）

```bash
# 1) 外部 OA 用 API Key 建运单（幂等）
curl -X POST http://host/tms/api/waybills \
  -H "X-Api-Key: fyt_ab12..." -H "Idempotency-Key: OA-2026-0001" \
  -H "Content-Type: application/json" \
  -d '{"customer_id":1,"route_id":2,"goods":"设备","weight_kg":8000,"volume_m3":30,"price_mode":"weight","quote":450000}'

# 2) 车载终端批量上报 GPS
curl -X POST http://host/tms/api/trackings \
  -H "X-Api-Key: fyt_ab12..." \
  -d '[{"waybill_no":"FY20261024-001","ts":"2026-10-24T10:00:00","lng":113.26,"lat":23.13,"event":" departure"}]'

# 3) 财务系统每小时增量拉取结算
curl "http://host/tms/api/sync?since=1024&entities=settlements" -H "X-Api-Key: fyt_ab12..."
```
