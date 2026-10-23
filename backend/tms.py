# -*- coding: utf-8 -*-
"""飞运 TMS 计算内核（纯函数，无 IO / 无 DB）"""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

CENT = Decimal("0.01")

ROLE_PERMS = {
    "admin": ["*"],
    "dispatcher": ["tms.dispatch.*", "tms.waybill.*", "tms.customer.read", "tms.vehicle.read",
                   "tms.driver.read", "tms.route.*", "tms.tracking.*", "tms.risk.read", "tms.dashboard.read"],
    "ops": ["tms.waybill.*", "tms.tracking.*", "tms.customer.read", "tms.route.read",
            "tms.vehicle.read", "tms.driver.read", "tms.risk.read", "tms.dashboard.read"],
    "finance": ["tms.settlement.*", "tms.waybill.read", "tms.customer.*", "tms.fuel.*",
                "tms.risk.read", "tms.dashboard.read"],
    "captain": ["tms.waybill.read", "tms.dispatch.read", "tms.dispatch.update", "tms.tracking.*",
                "tms.vehicle.read", "tms.driver.read", "tms.dashboard.read"],
    "reader": ["tms.dashboard.read", "tms.waybill.read", "tms.customer.read", "tms.vehicle.read",
               "tms.driver.read", "tms.route.read", "tms.settlement.read", "tms.risk.read"],
}

def has_perm(perms, need):
    if not perms:
        return False
    if "*" in perms:
        return True
    for p in perms:
        if p == need:
            return True
        if p.endswith(".*") and need.startswith(p[:-1]):
            return True
        if p.endswith(".write") and need == p[:-6] + ".read":
            return True
    return False

def to_dec(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("invalid decimal: %r" % (v,))

def money(v):
    return to_dec(v).quantize(CENT, rounding=ROUND_HALF_UP)

PRICE_MODES = {"weight", "volume", "trip"}

def freight_price(mode, weight_kg, volume_m3, distance_km, base_rate):
    """运价计算。weight: 元/吨km*吨*km; volume: 元/m3km*m3*km; trip: 元/km*km"""
    if mode not in PRICE_MODES:
        raise ValueError("bad price_mode")
    km = to_dec(distance_km)
    if km < 0:
        raise ValueError("distance negative")
    rate = to_dec(base_rate)
    if mode == "weight":
        tons = to_dec(weight_kg) / Decimal(1000)
        return money(tons * km * rate)
    if mode == "volume":
        return money(to_dec(volume_m3) * km * rate)
    return money(km * rate)

def eta_hours(distance_km, avg_speed=60, rest_every=4, rest_hours=0.5):
    """ETA 小时数：每连续驾驶 rest_every 小时强制休息 rest_hours"""
    d = to_dec(distance_km)
    if d < 0:
        raise ValueError("distance negative")
    if to_dec(avg_speed) <= 0:
        raise ValueError("speed must be positive")
    drive = d / to_dec(avg_speed)
    if drive <= 0:
        return 0.0
    stops = int((float(drive) - 1e-9) // float(rest_every)) if rest_every > 0 else 0
    return round(float(drive + to_dec(rest_hours) * stops), 2)

def fuel_cost(distance_km, per_100km_l, price_per_l):
    return money(to_dec(distance_km) / Decimal(100) * to_dec(per_100km_l) * to_dec(price_per_l))

def load_ratio(weight, cap_weight, volume, cap_volume):
    """装载率 = max(重载率, 方载率)，封顶 100%，返回百分数"""
    ratios = []
    if cap_weight and to_dec(cap_weight) > 0:
        ratios.append(to_dec(weight) / to_dec(cap_weight))
    if cap_volume and to_dec(cap_volume) > 0:
        ratios.append(to_dec(volume) / to_dec(cap_volume))
    if not ratios:
        return 0.0
    r = max(ratios)
    return round(min(float(r), 1.0) * 100, 1)

DRIVER_SHARE = Decimal("0.6")

def settlement_split(revenue, fuel, tolls, other):
    """结算拆分：司机应付 = (收入-油耗-路桥) * 60% 不足为0；毛利 = 收入-全部成本-司机应付"""
    rev = money(revenue); fu = money(fuel); tol = money(tolls); ot = money(other)
    direct = fu + tol + ot
    pay = money((rev - direct) * DRIVER_SHARE) if rev > direct else Decimal("0.00")
    profit = money(rev - direct - pay)
    return {"revenue": float(rev), "fuel": float(fu), "tolls": float(tol),
            "other": float(ot), "driver_pay": float(pay), "profit": float(profit)}

def overdue_check(eta_ts, delivered_ts, now_ts):
    """逾期判定。返回 (bool 逾期, float 逾期小时)"""
    if not eta_ts or delivered_ts:
        return (False, 0.0)
    import datetime
    def parse(s):
        s = str(s).replace("T", " ")
        return datetime.datetime.fromisoformat(s[:19])
    try:
        eta = parse(eta_ts); now = parse(now_ts)
    except ValueError:
        return (False, 0.0)
    diff = (now - eta).total_seconds() / 3600
    if diff > 0:
        return (True, round(diff, 1))
    return (False, 0.0)

def hundred_km_fuel(liters, km):
    km_d = to_dec(km)
    if km_d < 50:
        return None
    return round(float(to_dec(liters) / km_d * 100), 2)

def waybill_risk(overdue_hours, load_ratio_pct, client_overdue_ratio):
    """风险评分：逾期 5 分/小时封顶 40；装载率>95 加 15；客户逾期占比>0.8 加 25"""
    score = 0
    oh = to_dec(overdue_hours)
    if oh > 0:
        score += min(int(oh * 5), 40)
    if to_dec(load_ratio_pct) > 95:
        score += 15
    if to_dec(client_overdue_ratio) > Decimal("0.8"):
        score += 25
    score = min(score, 100)
    if score >= 60:
        grade = "险"
    elif score >= 35:
        grade = "警"
    elif score > 0:
        grade = "提"
    else:
        grade = "正常"
    return {"score": score, "grade": grade}

WB_STATUS = {"pending", "in_transit", "delivered", "cancelled"}

def wb_can_transition(cur, nxt):
    trans = {
        "pending": {"in_transit", "cancelled"},
        "in_transit": {"delivered", "pending", "cancelled"},
        "delivered": {"cancelled"},
        "cancelled": set(),
    }
    return nxt in trans.get(cur, set())

def validate_waybill(d, require_all=True):
    errs = []
    if require_all or "customer_id" in d:
        if not d.get("customer_id"):
            errs.append("customer_id 必填")
    if require_all or "route_id" in d:
        if not d.get("route_id"):
            errs.append("route_id 必填")
    w = d.get("weight_kg") or 0
    v = d.get("volume_m3") or 0
    try:
        if to_dec(w) < 0: errs.append("重量不能为负")
        if to_dec(v) < 0: errs.append("体积不能为负")
        if d.get("quote") is not None and to_dec(d["quote"]) < 0: errs.append("报价不能为负")
    except ValueError:
        errs.append("数值字段非法")
    if d.get("price_mode") and d["price_mode"] not in PRICE_MODES:
        errs.append("price_mode 须为 weight/volume/trip")
    return errs

def validate_vehicle(d):
    errs = []
    if not d.get("plate"):
        errs.append("车牌必填")
    for f in ("cap_weight", "cap_volume"):
        if d.get(f) is not None:
            try:
                if to_dec(d[f]) < 0: errs.append(f + " 不能为负")
            except ValueError:
                errs.append(f + " 非法")
    if d.get("status") and d["status"] not in {"idle", "in_transit", "maintenance", "disabled"}:
        errs.append("车辆状态非法")
    return errs

def validate_driver(d):
    errs = []
    if not d.get("name"):
        errs.append("姓名必填")
    if d.get("license_type") and d["license_type"] not in {"A1", "A2", "B1", "B2", "C1"}:
        errs.append("驾照类型非法")
    if d.get("status") and d["status"] not in {"idle", "in_transit", "rest", "resigned"}:
        errs.append("司机状态非法")
    return errs
