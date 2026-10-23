# -*- coding: utf-8 -*-
"""飞运 TMS 冒烟测试。用法: python smoke_api.py [--base http://127.0.0.1:8026]"""
import json, sys, urllib.request, ssl

BASE = "http://127.0.0.1:8026"
if "--base" in sys.argv:
    BASE = sys.argv[sys.argv.index("--base") + 1]
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=CTX))

TOKEN = None
passed = failed = 0
errors = []

def call(method, path, body=None, headers=None, raw=False):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    h = {"Content-Type": "application/json"}
    if TOKEN:
        h["Authorization"] = "Bearer " + TOKEN
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with OPENER.open(req, timeout=20) as r:
            b = r.read()
            if raw:
                return r.status, b, dict(r.headers)
            return r.status, json.loads(b.decode("utf-8"))
    except urllib.error.HTTPError as e:
        b = e.read()
        if raw:
            return e.code, b, dict(e.headers)
        try:
            return e.code, json.loads(b.decode("utf-8"))
        except Exception:
            return e.code, {"code": e.code, "message": b[:120].decode("utf-8", "ignore")}

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("PASS %s" % name)
    else:
        failed += 1
        errors.append(name + (" :: " + str(detail) if detail else ""))
        print("FAIL %s %s" % (name, detail))

def main():
    global TOKEN
    import time as _t
    SUF = str(_t.time())[-6:]
    # 1 登录
    st, r = call("POST", "/api/login", {"username": "admin", "password": "123456"})
    check("登录", st == 200 and r["data"]["token"], r)
    TOKEN = r["data"]["token"]
    st, r = call("POST", "/api/login", {"username": "admin", "password": "wrong"})
    check("错误密码401", st == 401)
    st, r = call("GET", "/api/me")
    check("当前用户", st == 200 and r["data"]["user"]["role"] == "admin")
    _tok = TOKEN; TOKEN = None
    st, r = call("GET", "/api/dashboard")
    check("无token 401", st == 401, st)
    TOKEN = _tok
    # 2 平台域
    for p in ("/api/users", "/api/notices", "/api/policies"):
        st, r = call("GET", p)
        check("列表 %s" % p, st == 200 and isinstance(r["data"]["items"], list))
    st, r = call("GET", "/api/users", headers={"X-Token": TOKEN})
    check("X-Token 通道", st == 200)
    # 3 业务列表
    for p in ("/api/customers", "/api/vehicles", "/api/drivers", "/api/routes",
              "/api/waybills", "/api/dispatches", "/api/trackings", "/api/settlements",
              "/api/fuel", "/api/risks", "/api/dashboard", "/api/stats/waybills?days=7",
              "/api/stats/vehicles", "/api/stats/drivers", "/api/stats/clients"):
        st, r = call("GET", p)
        check("列表 %s" % p, st == 200 and "items" in r["data"] or st == 200, r.get("message"))
    st, r = call("GET", "/api/customers/1/balance")
    check("客户余额", st == 200 and "usage_ratio" in r["data"])
    st, r = call("GET", "/api/settlements/summary")
    check("结算汇总", st == 200 and "open_receivable" in r["data"])
    # 4 CRUD
    st, r = call("POST", "/api/customers", {"code": "TST" + SUF, "name": "冒烟客户", "credit_limit": 10000})
    check("新建客户", st == 200 and r["data"]["id"], r)
    cid = r["data"]["id"]
    st, r = call("POST", "/api/customers", {"code": "TST" + SUF, "name": "重复"})
    check("重复客户409", st == 409)
    st, r = call("PUT", "/api/customers/%d" % cid, {"contact": "测试"})
    check("修改客户", st == 200)
    st, r = call("DELETE", "/api/customers/%d" % cid)
    check("删除客户", st == 200)
    st, r = call("POST", "/api/vehicles", {"plate": "测T" + SUF, "vtype": "4.2m", "cap_weight": 2000, "cap_volume": 18})
    check("新建车辆", st == 200)
    vid = r["data"]["id"]
    st, r = call("POST", "/api/vehicles", {"plate": ""})
    check("车辆校验422", st == 422)
    st, r = call("POST", "/api/drivers", {"name": "冒烟司机", "license_type": "B2"})
    check("新建司机", st == 200)
    did = r["data"]["id"]
    st, r = call("POST", "/api/drivers", {"name": "坏司机", "license_type": "XX"})
    check("司机校验422", st == 422)
    st, r = call("POST", "/api/routes", {"origin": "冒烟A", "dest": "冒烟B", "distance_km": 200, "hours": 4, "base_rate": 60})
    check("新建线路", st == 200)
    rid = r["data"]["id"]
    # 5 运价试算
    st, r = call("POST", "/api/waybills/quote", {"price_mode": "weight", "weight_kg": 10000, "distance_km": 200, "base_rate": 60})
    check("运价试算", st == 200 and abs(r["data"]["price"] - 120000) < 0.01, r)
    st, r = call("POST", "/api/waybills/quote", {"price_mode": "bad", "distance_km": 10})
    check("非法模式422", st == 422)
    # 6 运单状态机
    st, r = call("POST", "/api/waybills", {"customer_id": cid if False else 1, "route_id": rid, "goods": "冒烟货", "weight_kg": 4000, "volume_m3": 15, "price_mode": "weight", "quote": 48000})
    check("新建运单", st == 200, r)
    wid = r["data"]["id"]
    st, r = call("POST", "/api/waybills", {"route_id": rid})
    check("运单校验422", st == 422)
    st, r = call("POST", "/api/waybills/%d/deliver" % wid, {"signer": "x"})
    check("pending不可签收422", st == 422)
    st, r = call("POST", "/api/waybills/%d/dispatch" % wid, {"vehicle_id": vid, "driver_id": did})
    check("调度", st == 200 and r["data"]["eta"], r)
    st, r = call("POST", "/api/waybills/%d/dispatch" % wid, {"vehicle_id": vid, "driver_id": did})
    check("重复调度422", st == 422)
    st, r = call("POST", "/api/waybills/%d/track" % wid, {"lng": 114.0, "lat": 23.5, "location": "冒烟点", "event": "在途"})
    check("追加跟踪", st == 200)
    st, r = call("GET", "/api/waybills/%d/trackings" % wid)
    check("跟踪流", st == 200 and r["data"]["total"] >= 2)
    st, r = call("POST", "/api/waybills/%d/deliver" % wid, {"signer": "冒烟签收"})
    check("签收", st == 200 and "settlement_profit" in r["data"], r)
    st, r = call("GET", "/api/waybills/%d" % wid)
    check("运单详情", st == 200 and r["data"]["status"] == "delivered")
    st, r = call("GET", "/api/settlements")
    wb_nos = [i["waybill_id"] for i in r["data"]["items"]]
    check("自动结算生成", (wid) in wb_nos, wb_nos)
    st, r = call("POST", "/api/waybills/%d/cancel" % wid)
    check("delivered可取消", st == 200)
    # 7 幂等
    st, r = call("POST", "/api/routes", {"origin": "幂等A", "dest": "幂等B", "distance_km": 100}, headers={"Idempotency-Key": "smoke-idem-1"})
    rid2 = r["data"]["id"]
    st, r = call("POST", "/api/routes", {"origin": "幂等A", "dest": "幂等B", "distance_km": 100}, headers={"Idempotency-Key": "smoke-idem-1"})
    check("幂等键复用", st == 200 and r["data"]["id"] == rid2, r)
    # 8 油耗
    st, r = call("POST", "/api/fuel", {"vehicle_id": vid, "liters": 100, "price": 7.9, "odometer": 1000})
    check("新建油耗", st == 200 and r["data"].get("id"), r)
    fid = r["data"]["id"] if isinstance(r["data"], dict) and "id" in r["data"] else None
    st, r = call("GET", "/api/vehicles/%d/stats" % vid)
    check("车辆统计", st == 200)
    st, r = call("GET", "/api/drivers/%d/stats" % did)
    check("司机统计", st == 200)
    # 9 风险
    st, r = call("POST", "/api/risks/scan")
    check("风险扫描", st == 200 and "new_risks" in r["data"])
    st, r = call("GET", "/api/risks")
    check("风险列表", st == 200 and r["data"]["total"] >= 1)
    if r["data"]["items"]:
        st, r2 = call("PUT", "/api/risks/%d/resolve" % r["data"]["items"][0]["id"], {"note": "冒烟处理"})
        check("处理预警", st == 200)
    # 10 同步/导出
    st, r = call("GET", "/api/sync?since=0&entities=waybills,settlements")
    check("增量同步", st == 200 and "waybills" in r["data"]["changes"])
    st, body, hdrs = call("GET", "/api/export/waybills", raw=True)
    check("CSV导出", st == 200 and b"no,customer_name" in body[:60], body[:60])
    # 11 权限
    st, r = call("POST", "/api/login", {"username": "reader01", "password": "123456"})
    check("reader登录", st == 200, r)
    rtok = r["data"]["token"]
    st, r = call("GET", "/api/waybills", headers={"Authorization": "Bearer " + rtok})
    check("reader可读运单", st == 200)
    st, r = call("POST", "/api/waybills", {"customer_id": 1, "route_id": rid}, headers={"Authorization": "Bearer " + rtok})
    check("reader不可写403", st == 403)
    st, r = call("GET", "/api/users", headers={"Authorization": "Bearer " + rtok})
    check("reader不可见用户403", st == 403)
    # 12 API Key（创建用管理员令牌，使用时为纯 Key 通道）
    _tok = TOKEN
    st, r = call("POST", "/api/api-keys", {"name": "smoke-" + SUF})
    check("生成APIKey", st == 200 and r["data"]["key"].startswith("fyt_"))
    key = r["data"]["key"]; kid = r["data"]["id"]
    st, r = call("GET", "/api/waybills", headers={"X-Api-Key": key})
    check("APIKey读通道", st == 200)
    st, r = call("POST", "/api/api-keys", {"name": "smoke-ro-" + SUF, "perms": "tms.waybill.read"})
    check("生成受限APIKey", st == 200 and r["data"]["key"].startswith("fyt_"))
    rokey = r["data"]["key"]
    TOKEN = None
    st, r = call("POST", "/api/waybills", {"customer_id": 1, "route_id": rid}, headers={"X-Api-Key": rokey})
    check("APIKey默认只读403", st == 403, st)
    st, r = call("GET", "/api/api-keys", headers={"Authorization": "Bearer " + _tok})
    check("APIKey列表", st == 200)
    st, r2 = call("DELETE", "/api/api-keys/%d" % kid, headers={"Authorization": "Bearer " + _tok})
    check("吊销APIKey", st == 200)
    st, r = call("GET", "/api/waybills", headers={"X-Api-Key": key})
    check("吊销后401/403", st in (401, 403), st)
    TOKEN = _tok

    print("\n==== 冒烟结果: %d 通过 / %d 失败 ====" % (passed, failed))
    for e in errors:
        print("  FAIL:", e)
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
