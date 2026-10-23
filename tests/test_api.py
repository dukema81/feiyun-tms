# -*- coding: utf-8 -*-
"""飞运 TMS API 集成测试"""
import json
from conftest import jreq, req


def test_login_ok():
    code, r = jreq("POST", "/api/login", {"username": "admin", "password": "123456"})
    assert code == 200 and r["data"]["token"]
    assert r["data"]["perms"] == ["*"]


def test_login_fail():
    code, r = jreq("POST", "/api/login", {"username": "admin", "password": "x"})
    assert code == 401


def test_me(H):
    code, r = jreq("GET", "/api/me", headers=H)
    assert code == 200 and r["data"]["user"]["role"] == "admin"


def test_unauth():
    code, r = jreq("GET", "/api/dashboard")
    assert code == 401


def test_x_token_channel(admin_token):
    code, r = jreq("GET", "/api/dashboard", headers={"X-Token": admin_token})
    assert code == 200


def test_query_token_channel(admin_token):
    code, r = jreq("GET", "/api/dashboard?token=" + admin_token)
    assert code == 200


def test_customers_crud(H):
    code, r = jreq("POST", "/api/customers", {"code": "UT1", "name": "单测客户", "credit_limit": 50000}, H)
    assert code == 200
    cid = r["data"]["id"]
    code, r = jreq("POST", "/api/customers", {"code": "UT1", "name": "重复"}, H)
    assert code == 409
    code, r = jreq("GET", "/api/customers/%d" % cid, headers=H)
    assert code == 200 and r["data"]["name"] == "单测客户"
    code, r = jreq("PUT", "/api/customers/%d" % cid, {"contact": "李四"}, H)
    assert code == 200
    code, r = jreq("DELETE", "/api/customers/%d" % cid, headers=H)
    assert code == 200
    code, r = jreq("GET", "/api/customers/%d" % cid, headers=H)
    assert code == 404


def test_customer_with_waybill_no_delete(H):
    code, r = jreq("DELETE", "/api/customers/1", headers=H)
    assert code == 409


def test_vehicle_validation(H):
    code, r = jreq("POST", "/api/vehicles", {"plate": ""}, H)
    assert code == 422
    code, r = jreq("POST", "/api/vehicles", {"plate": "测T99999", "cap_weight": -5}, H)
    assert code == 422


def test_driver_validation(H):
    code, r = jreq("POST", "/api/drivers", {"name": "", "license_type": "A2"}, H)
    assert code == 422


def test_waybill_flow(H):
    # 建运单
    code, r = jreq("POST", "/api/waybills",
                   {"customer_id": 2, "route_id": 2, "goods": "单测货", "weight_kg": 8000,
                    "volume_m3": 30, "price_mode": "weight", "quote": 480000}, H)
    assert code == 200, r
    wid = r["data"]["id"]
    # pending 不可签收
    code, r = jreq("POST", "/api/waybills/%d/deliver" % wid, {"signer": "x"}, H)
    assert code == 422
    # 建测试车辆与司机
    code, r = jreq("POST", "/api/vehicles", {"plate": "测T88888", "vtype": "测试", "cap_weight": 20000, "cap_volume": 60}, H)
    vid = r["data"]["id"]
    code, r = jreq("POST", "/api/drivers", {"name": "单测司机", "license_type": "A2"}, H)
    did = r["data"]["id"]
    # 调度
    code, r = jreq("POST", "/api/waybills/%d/dispatch" % wid, {"vehicle_id": vid, "driver_id": did}, H)
    assert code == 200 and r["data"]["eta"]
    # 重复调度
    code, r = jreq("POST", "/api/vehicles", {"plate": "测T77777", "cap_weight": 10000}, H)
    vid2 = r["data"]["id"]
    code, r = jreq("POST", "/api/waybills/%d/dispatch" % wid, {"vehicle_id": vid2, "driver_id": did}, H)
    assert code == 422
    # 占用车辆再调度应 422
    code, r = jreq("POST", "/api/waybills",
                   {"customer_id": 2, "route_id": 2, "goods": "单测货2", "weight_kg": 1000}, H)
    wid2 = r["data"]["id"]
    code, r = jreq("POST", "/api/waybills/%d/dispatch" % wid2, {"vehicle_id": vid, "driver_id": did}, H)
    assert code == 422
    # 跟踪
    code, r = jreq("POST", "/api/waybills/%d/track" % wid, {"lng": 113.5, "lat": 23.0, "location": "测试点"}, H)
    assert code == 200
    code, r = jreq("GET", "/api/waybills/%d/trackings" % wid, headers=H)
    assert r["data"]["total"] >= 2
    # 签收 → 自动结算
    code, r = jreq("POST", "/api/waybills/%d/deliver" % wid, {"signer": "单测签收"}, H)
    assert code == 200 and "settlement_profit" in r["data"]
    code, r = jreq("GET", "/api/waybills/%d" % wid, headers=H)
    assert r["data"]["status"] == "delivered" and r["data"]["signer"] == "单测签收"
    # 结算存在
    code, r = jreq("GET", "/api/settlements", headers=H)
    assert wid in [i["waybill_id"] for i in r["data"]["items"]]
    # 取消
    code, r = jreq("POST", "/api/waybills/%d/cancel" % wid, headers=H)
    assert code == 200
    # 清理
    jreq("DELETE", "/api/waybills/%d" % wid2, headers=H)


def test_waybill_validation(H):
    code, r = jreq("POST", "/api/waybills", {"route_id": 1}, H)
    assert code == 422
    code, r = jreq("POST", "/api/waybills", {"customer_id": 999, "route_id": 1}, H)
    assert code == 404


def test_quote(H):
    code, r = jreq("POST", "/api/waybills/quote",
                   {"price_mode": "weight", "weight_kg": 20000, "distance_km": 300, "base_rate": 50}, H)
    assert code == 200 and r["data"]["price"] == 300000.0


def test_settlement_close(H):
    code, r = jreq("GET", "/api/settlements?status=open", headers=H)
    assert code == 200
    item = r["data"]["items"][0]
    code, r = jreq("POST", "/api/settlements/%d/close" % item["id"], {}, H)
    assert code == 200
    code, r = jreq("POST", "/api/settlements/%d/close" % item["id"], {}, H)
    assert code == 422
    code, r = jreq("PUT", "/api/settlements/%d" % item["id"], {"revenue": 1}, H)
    assert code == 422  # 已结不可改


def test_settlement_summary(H):
    code, r = jreq("GET", "/api/settlements/summary", headers=H)
    assert code == 200 and "open_receivable" in r["data"] and "closed_ratio" in r["data"]


def test_fuel(H):
    code, r = jreq("POST", "/api/fuel", {"vehicle_id": 1, "liters": 120, "price": 8.0, "odometer": 186000}, H)
    assert code == 200
    code, r = jreq("GET", "/api/vehicles/1/fuel", headers=H)
    assert r["data"]["total"] >= 1


def test_risk_scan(H):
    code, r = jreq("POST", "/api/risks/scan", {}, H)
    assert code == 200 and "new_risks" in r["data"]
    code, r = jreq("GET", "/api/risks", headers=H)
    assert code == 200 and r["data"]["total"] >= 1
    first = r["data"]["items"][0]
    if first["status"] == "open":
        code, r = jreq("PUT", "/api/risks/%d/resolve" % first["id"], {"note": "ok"}, H)
        assert code == 200


def test_sync(H):
    code, r = jreq("GET", "/api/sync?since=0&entities=waybills,settlements", headers=H)
    assert code == 200 and "waybills" in r["data"]["changes"]
    cur = r["data"]["current"]
    code, r = jreq("GET", "/api/sync?since=%d" % cur, headers=H)
    assert code == 200 and r["data"]["changes"] == {}


def test_idempotency(H):
    h = dict(H, **{"Idempotency-Key": "pytest-idem-1"})
    code1, r1 = jreq("POST", "/api/routes", {"origin": "幂等甲", "dest": "幂等乙", "distance_km": 10}, h)
    code2, r2 = jreq("POST", "/api/routes", {"origin": "幂等甲", "dest": "幂等乙", "distance_km": 10}, h)
    assert code1 == code2 == 200 and r1["data"]["id"] == r2["data"]["id"]


def test_csv_export(admin_token):
    code, data = req("GET", "/api/export/waybills", headers={"Authorization": "Bearer " + admin_token})
    assert code == 200 and "no,customer_name" in data.decode("utf-8")


def test_reader_permissions():
    code, r = jreq("POST", "/api/login", {"username": "reader01", "password": "123456"})
    tok = r["data"]["token"]
    RH = {"Authorization": "Bearer " + tok}
    assert jreq("GET", "/api/waybills", headers=RH)[0] == 200
    assert jreq("POST", "/api/waybills", {"customer_id": 1, "route_id": 1}, RH)[0] == 403
    assert jreq("GET", "/api/users", headers=RH)[0] == 403
    assert jreq("GET", "/api/logs", headers=RH)[0] == 403


def test_api_key(admin_token):
    h = {"Authorization": "Bearer " + admin_token}
    code, r = jreq("POST", "/api/api-keys", {"name": "pytest-k"}, h)
    assert code == 200 and r["data"]["key"].startswith("fyt_")
    key = r["data"]["key"]
    KH = {"X-Api-Key": key}
    assert jreq("GET", "/api/waybills", headers=KH)[0] == 200
    assert jreq("GET", "/api/customers", headers=KH)[0] == 200
    # 吊销
    code, lst = jreq("GET", "/api/api-keys", headers=h)
    kid = [i["id"] for i in lst["data"]["items"] if i["name"] == "pytest-k"][0]
    assert jreq("DELETE", "/api/api-keys/%d" % kid, None, h)[0] == 200
    code, r = jreq("GET", "/api/waybills", headers=KH)
    assert code in (401, 403)
