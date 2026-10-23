# -*- coding: utf-8 -*-
"""飞运 TMS 内核单测"""
import pytest
import tms
from tms import (freight_price, eta_hours, fuel_cost, load_ratio, settlement_split,
                 overdue_check, hundred_km_fuel, waybill_risk, wb_can_transition,
                 validate_waybill, validate_vehicle, validate_driver, has_perm)


def test_freight_weight():
    assert freight_price("weight", 10000, 0, 200, 60) == 120000.0

def test_freight_volume():
    assert freight_price("volume", 0, 50, 100, 60) == 300000.0

def test_freight_trip():
    assert freight_price("trip", 0, 0, 150, 8000) == 1200000.0

def test_freight_half_up():
    # 0.125 -> 0.13 (ROUND_HALF_UP)
    assert freight_price("trip", 0, 0, 1, 12.5) == 12.5
    assert freight_price("trip", 0, 0, 0.015, 100) == 1.5

def test_freight_bad_mode():
    with pytest.raises(ValueError):
        freight_price("bad", 1, 1, 1, 1)

def test_freight_negative_distance():
    with pytest.raises(ValueError):
        freight_price("trip", 0, 0, -5, 100)

def test_eta_basic():
    assert eta_hours(120, 60) == 2.0

def test_eta_rest():
    # 8 小时连续驾驶 → 中途休息一次 0.5h
    assert eta_hours(480, 60) == 8.5

def test_eta_zero():
    assert eta_hours(0, 60) == 0.0

def test_eta_bad_speed():
    with pytest.raises(ValueError):
        eta_hours(100, 0)

def test_fuel_cost():
    assert fuel_cost(200, 30, 7.9) == 474.0

def test_load_ratio_weight():
    assert load_ratio(15000, 20000, 0, 0) == 75.0

def test_load_ratio_max():
    assert load_ratio(50000, 20000, 200, 50) == 100.0

def test_load_ratio_volume():
    assert load_ratio(0, 0, 40, 50) == 80.0

def test_settlement_split():
    sp = settlement_split(100000, 10000, 5000, 5000)
    assert sp["revenue"] == 100000.0
    assert sp["driver_pay"] == 48000.0     # (100000-20000)*0.6
    assert sp["profit"] == 32000.0

def test_settlement_split_loss():
    sp = settlement_split(10000, 15000, 0, 0)
    assert sp["driver_pay"] == 0.0
    assert sp["profit"] == -5000.0

def test_overdue():
    assert overdue_check("2026-10-24 10:00:00", None, "2026-10-24 12:30:00") == (True, 2.5)
    assert overdue_check("2026-10-24 10:00:00", "2026-10-24 09:00:00", "2026-10-24 12:00:00") == (False, 0.0)
    assert overdue_check(None, None, "2026-10-24 12:00:00") == (False, 0.0)

def test_hundred_km_fuel():
    assert hundred_km_fuel(30, 200) == 15.0
    assert hundred_km_fuel(30, 40) is None

def test_risk_grades():
    assert waybill_risk(0, 0, 0) == {"score": 0, "grade": "正常"}
    assert waybill_risk(2, 0, 0)["grade"] == "提"      # 10
    assert waybill_risk(8, 100, 0.9)["score"] == 80    # 40+15+25
    assert waybill_risk(20, 0, 0) == {"score": 40, "grade": "警"}

def test_wb_transitions():
    assert wb_can_transition("pending", "in_transit")
    assert wb_can_transition("in_transit", "delivered")
    assert wb_can_transition("in_transit", "pending")
    assert not wb_can_transition("pending", "delivered")
    assert not wb_can_transition("cancelled", "pending")

def test_validate_waybill():
    assert validate_waybill({"customer_id": 1, "route_id": 2}) == []
    assert "customer_id 必填" in validate_waybill({"route_id": 2})
    assert "price_mode 须为 weight/volume/trip" in validate_waybill(
        {"customer_id": 1, "route_id": 2, "price_mode": "x"})

def test_validate_vehicle():
    assert validate_vehicle({"plate": "粤A11111"}) == []
    assert "车牌必填" in validate_vehicle({})
    assert "车辆状态非法" in validate_vehicle({"plate": "x", "status": "fly"})

def test_validate_driver():
    assert validate_driver({"name": "张三"}) == []
    assert "姓名必填" in validate_driver({})
    assert "驾照类型非法" in validate_driver({"name": "x", "license_type": "ZZ"})

def test_perm_wildcard():
    assert has_perm(["*"], "anything")
    assert has_perm(["tms.waybill.*"], "tms.waybill.read")
    assert has_perm(["tms.waybill.write"], "tms.waybill.read")
    assert not has_perm(["tms.waybill.read"], "tms.waybill.write")
    assert not has_perm([], "tms.dashboard.read")

def test_money_decimal():
    from decimal import Decimal
    from tms import money
    assert money("100.005") == Decimal("100.01")  # HALF_UP
