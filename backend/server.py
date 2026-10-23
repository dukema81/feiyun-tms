# -*- coding: utf-8 -*-
"""飞运 TMS 服务端：零依赖 HTTP API（端口 8026，前缀可配）"""
import os, re, json, time, hashlib, traceback, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http import cookies as http_cookies

import db as D
from db import q, q1, execute, next_seq, bump_sync, get_sync
import tms as K
import seed as S

PORT = int(os.environ.get("TMS_PORT", "8026"))
PREFIX = os.environ.get("TMS_PREFIX", "")
TOKEN_TTL = 7 * 86400
ADMIN_SECRET = os.environ.get("TMS_ADMIN_SECRET", "fyt-admin-secret")

def now_s():
    return time.strftime("%Y-%m-%d %H:%M:%S")

def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def jdump(o):
    return json.dumps(o, ensure_ascii=False, default=str)

class ApiError(Exception):
    def __init__(self, code, message):
        self.code = code; self.message = message

def page_args(qs):
    p = max(int(qs.get("page", ["1"])[0] or 1), 1)
    s = min(max(int(qs.get("size", ["20"])[0] or 20), 1), 200)
    return p, s, (p - 1) * s

def listwrap(sql, params, qs, extra=None):
    p, s, off = page_args(qs)
    total = q1("SELECT COUNT(*) AS c FROM (" + sql + ")", params)["c"]
    rows = q(sql + " LIMIT %d OFFSET %d" % (s, off), params)
    items = [dict(r) for r in rows]
    if extra:
        for it in items:
            extra(it)
    return {"items": items, "total": total, "page": p, "size": s}

# ---------- 认证 ----------

def auth_token(tok):
    if not tok:
        return None
    row = q1("SELECT t.*, u.username, u.name, u.role FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?", (tok,))
    if not row:
        return None
    if row["expires_at"] and row["expires_at"] < now_s():
        execute("DELETE FROM tokens WHERE token=?", (tok,))
        return None
    return row

def auth_key(key):
    if not key:
        return None
    row = q1("SELECT * FROM api_keys WHERE key_hash=? AND status=1", (sha(key),))
    if not row:
        return None
    execute("UPDATE api_keys SET last_used=? WHERE id=?", (now_s(), row["id"]))
    return {"username": "apikey:" + (row["prefix"] or "k"), "name": row["name"], "role": "apikey", "perms": (row["perms"] or "tms.read").split(",")}

def do_login(body):
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    u = q1("SELECT * FROM users WHERE username=? AND status=1", (username,))
    if not u or u["password"] != sha(password):
        D.execute("INSERT INTO logs(ts,user_id,action,detail) VALUES(?,NULL,'login_fail',?)", (now_s(), username))
        raise ApiError(401, "用户名或密码错误")
    tok = sha(username + str(time.time()) + os.urandom(8).hex())[:40]
    exp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + TOKEN_TTL))
    execute("INSERT INTO tokens(token, user_id, created_at, expires_at) VALUES(?,?,?,?)", (tok, u["id"], now_s(), exp))
    D.execute("INSERT INTO logs(ts,user_id,action,detail) VALUES(?,?,'login',?)", (now_s(), u["id"], username))
    perms = K.ROLE_PERMS.get(u["role"], K.ROLE_PERMS["reader"])
    return {"token": tok, "expires_at": exp, "user": {"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"]}, "perms": perms}

# ---------- 业务处理函数 ----------
# 每个函数签名 fn(ctx, m: match, qs, body) -> data dict

def ctx_user(ctx):
    return ctx["user"]

def h_login(ctx, m, qs, body):
    return do_login(body)

def h_logout(ctx, m, qs, body):
    execute("DELETE FROM tokens WHERE token=?", (ctx["token"],))
    return {"ok": True}

def h_me(ctx, m, qs, body):
    u = ctx["user"]
    perms = K.ROLE_PERMS.get(u["role"], K.ROLE_PERMS["reader"]) if u.get("role") != "apikey" else u["perms"]
    return {"user": {"id": u.get("id"), "username": u["username"], "name": u["name"], "role": u["role"]}, "perms": perms}

# users
def h_users(ctx, m, qs, body):
    return listwrap("SELECT id,username,name,role,status,created_at FROM users ORDER BY id", (), qs)

def h_users_create(ctx, m, qs, body):
    if not body.get("username") or not body.get("password"):
        raise ApiError(422, "username/password 必填")
    if q1("SELECT id FROM users WHERE username=?", (body["username"],)):
        raise ApiError(409, "用户名已存在")
    role = body.get("role", "reader")
    if role not in K.ROLE_PERMS:
        raise ApiError(422, "角色非法")
    c = execute("INSERT INTO users(username,password,name,role,phone) VALUES(?,?,?,?,?)",
                (body["username"], sha(body["password"]), body.get("name", body["username"]), role, body.get("phone")))
    return {"id": c.lastrowid}

def h_users_update(ctx, m, qs, body):
    uid = int(m.group(1))
    u = q1("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise ApiError(404, "用户不存在")
    sets, params = [], []
    for f in ("name", "role", "phone"):
        if f in body:
            if f == "role" and body[f] not in K.ROLE_PERMS:
                raise ApiError(422, "角色非法")
            sets.append(f + "=?"); params.append(body[f])
    if body.get("password"):
        sets.append("password=?"); params.append(sha(body["password"]))
    if "status" in body:
        sets.append("status=?"); params.append(1 if body["status"] else 0)
    if sets:
        params.append(uid)
        execute("UPDATE users SET " + ",".join(sets) + " WHERE id=?", params)
    return {"ok": True}

# api keys
def h_keys(ctx, m, qs, body):
    return listwrap("SELECT id,name,prefix,perms,status,last_used,created_at FROM api_keys ORDER BY id", (), qs)

def h_keys_create(ctx, m, qs, body):
    name = body.get("name") or "default"
    raw = "fyt_" + sha(name + str(time.time()) + os.urandom(8).hex())[:32]
    c = execute("INSERT INTO api_keys(name, key_hash, prefix, perms) VALUES(?,?,?,?)",
                (name, sha(raw), raw[:12], body.get("perms", "tms.*")))
    return {"id": c.lastrowid, "key": raw, "note": "仅此一次返回明文，请妥善保存"}

def h_keys_delete(ctx, m, qs, body):
    execute("DELETE FROM api_keys WHERE id=?", (int(m.group(1)),))
    return {"ok": True}

# customers
def h_cust_list(ctx, m, qs, body):
    kw = qs.get("keyword", [""])[0]
    cond, params = "", []
    if kw:
        cond = "WHERE code LIKE ? OR name LIKE ? OR contact LIKE ?"
        params = ["%" + kw + "%"] * 3
    def ex(it):
        it["overdue"] = 0
        return it
    return listwrap("SELECT * FROM customers " + cond + " ORDER BY id", params, qs, ex)

def h_cust_create(ctx, m, qs, body):
    if not body.get("code") or not body.get("name"):
        raise ApiError(422, "code/name 必填")
    if q1("SELECT id FROM customers WHERE code=?", (body["code"],)):
        raise ApiError(409, "客户编码已存在")
    c = execute("INSERT INTO customers(code,name,contact,phone,address,settle_type,credit_limit) VALUES(?,?,?,?,?,?,?)",
                (body["code"], body["name"], body.get("contact"), body.get("phone"), body.get("address"),
                 body.get("settle_type", "monthly"), body.get("credit_limit", 0)))
    return {"id": c.lastrowid}

def h_cust_get(ctx, m, qs, body):
    r = q1("SELECT * FROM customers WHERE id=?", (int(m.group(1)),))
    if not r:
        raise ApiError(404, "客户不存在")
    d = dict(r)
    d["waybill_count"] = q1("SELECT COUNT(*) c FROM waybills WHERE customer_id=?", (r["id"],))["c"]
    return d

def h_cust_update(ctx, m, qs, body):
    cid = int(m.group(1))
    if not q1("SELECT id FROM customers WHERE id=?", (cid,)):
        raise ApiError(404, "客户不存在")
    sets, params = [], []
    for f in ("name", "contact", "phone", "address", "settle_type", "credit_limit", "status"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(cid)
        execute("UPDATE customers SET " + ",".join(sets) + " WHERE id=?", params)
    return {"ok": True}

def h_cust_delete(ctx, m, qs, body):
    cid = int(m.group(1))
    if q1("SELECT id FROM waybills WHERE customer_id=? LIMIT 1", (cid,)):
        raise ApiError(409, "客户存在运单，禁止删除")
    execute("DELETE FROM customers WHERE id=?", (cid,))
    return {"ok": True}

def h_cust_waybills(ctx, m, qs, body):
    return listwrap("SELECT * FROM waybills WHERE customer_id=? ORDER BY id DESC", (int(m.group(1)),), qs)

def h_cust_balance(ctx, m, qs, body):
    cid = int(m.group(1))
    r = q1("SELECT credit_limit FROM customers WHERE id=?", (cid,))
    if not r:
        raise ApiError(404, "客户不存在")
    open_amt = q1("SELECT COALESCE(SUM(revenue),0) s FROM settlements st JOIN waybills w ON w.id=st.waybill_id WHERE w.customer_id=? AND st.status='open'", (cid,))["s"]
    used = open_amt / r["credit_limit"] if r["credit_limit"] else 0
    return {"credit_limit": r["credit_limit"], "open_revenue": open_amt, "usage_ratio": round(used, 3)}

# vehicles
def h_veh_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("status", [""])[0]:
        cond += " AND status=?"; params.append(qs["status"][0])
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND (plate LIKE ? OR vtype LIKE ?)"; params += ["%" + kw + "%"] * 2
    return listwrap("SELECT * FROM vehicles WHERE " + cond + " ORDER BY id", params, qs)

def h_veh_create(ctx, m, qs, body):
    errs = K.validate_vehicle(body)
    if errs:
        raise ApiError(422, "；".join(errs))
    if q1("SELECT id FROM vehicles WHERE plate=?", (body["plate"],)):
        raise ApiError(409, "车牌已存在")
    c = execute("INSERT INTO vehicles(plate,vtype,cap_weight,cap_volume,next_maint,insurance_exp,odometer) VALUES(?,?,?,?,?,?,?)",
                (body["plate"], body.get("vtype"), body.get("cap_weight", 0), body.get("cap_volume", 0),
                 body.get("next_maint"), body.get("insurance_exp"), body.get("odometer", 0)))
    return {"id": c.lastrowid}

def _veh_or_404(vid):
    r = q1("SELECT * FROM vehicles WHERE id=?", (vid,))
    if not r:
        raise ApiError(404, "车辆不存在")
    return r

def h_veh_get(ctx, m, qs, body):
    return dict(_veh_or_404(int(m.group(1))))

def h_veh_update(ctx, m, qs, body):
    vid = int(m.group(1)); _veh_or_404(vid)
    sets, params = [], []
    for f in ("vtype", "cap_weight", "cap_volume", "status", "next_maint", "insurance_exp", "odometer"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(vid)
        execute("UPDATE vehicles SET " + ",".join(sets) + " WHERE id=?", params)
    return {"ok": True}

def h_veh_delete(ctx, m, qs, body):
    vid = int(m.group(1))
    if q1("SELECT id FROM dispatches WHERE vehicle_id=? AND status='active' LIMIT 1", (vid,)):
        raise ApiError(409, "车辆在途，禁止删除")
    execute("DELETE FROM vehicles WHERE id=?", (vid,))
    return {"ok": True}

def h_veh_fuel(ctx, m, qs, body):
    return listwrap("SELECT * FROM fuel WHERE vehicle_id=? ORDER BY date DESC", (int(m.group(1)),), qs)

def h_veh_stats(ctx, m, qs, body):
    vid = int(m.group(1)); _veh_or_404(vid)
    trips = q1("SELECT COUNT(*) c FROM dispatches WHERE vehicle_id=? AND status='done'", (vid,))["c"]
    fuel_rows = q("SELECT date, liters, odometer FROM fuel WHERE vehicle_id=? AND odometer>0 ORDER BY date", (vid,))
    avg100 = None
    if len(fuel_rows) >= 2:
        lit = sum(r["liters"] for r in fuel_rows[1:])
        km = fuel_rows[-1]["odometer"] - fuel_rows[0]["odometer"]
        avg100 = K.hundred_km_fuel(lit, km)
    return {"trips": trips, "avg_fuel_per_100km": avg100}

# drivers
def h_drv_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("status", [""])[0]:
        cond += " AND status=?"; params.append(qs["status"][0])
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND (name LIKE ? OR phone LIKE ?)"; params += ["%" + kw + "%"] * 2
    return listwrap("SELECT * FROM drivers WHERE " + cond + " ORDER BY id", params, qs)

def h_drv_create(ctx, m, qs, body):
    errs = K.validate_driver(body)
    if errs:
        raise ApiError(422, "；".join(errs))
    c = execute("INSERT INTO drivers(name,phone,license_no,license_type,license_exp) VALUES(?,?,?,?,?)",
                (body["name"], body.get("phone"), body.get("license_no"), body.get("license_type"), body.get("license_exp")))
    return {"id": c.lastrowid}

def _drv_or_404(did):
    r = q1("SELECT * FROM drivers WHERE id=?", (did,))
    if not r:
        raise ApiError(404, "司机不存在")
    return r

def h_drv_get(ctx, m, qs, body):
    return dict(_drv_or_404(int(m.group(1))))

def h_drv_update(ctx, m, qs, body):
    did = int(m.group(1)); _drv_or_404(did)
    sets, params = [], []
    for f in ("name", "phone", "license_no", "license_type", "license_exp", "status"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(did)
        execute("UPDATE drivers SET " + ",".join(sets) + " WHERE id=?", params)
    return {"ok": True}

def h_drv_delete(ctx, m, qs, body):
    did = int(m.group(1))
    if q1("SELECT id FROM dispatches WHERE driver_id=? AND status='active' LIMIT 1", (did,)):
        raise ApiError(409, "司机在途，禁止删除")
    execute("DELETE FROM drivers WHERE id=?", (did,))
    return {"ok": True}

def h_drv_stats(ctx, m, qs, body):
    did = int(m.group(1)); _drv_or_404(did)
    trips = q1("SELECT COUNT(*) c FROM dispatches WHERE driver_id=? AND status='done'", (did,))["c"]
    ontime = q1("SELECT COUNT(*) c FROM dispatches d JOIN waybills w ON w.id=d.waybill_id WHERE d.driver_id=? AND d.status='done' AND w.delivered_at<=d.eta_ts", (did,))["c"]
    return {"trips": trips, "ontime": ontime, "ontime_rate": round(ontime / trips, 3) if trips else None}

# routes
def h_route_list(ctx, m, qs, body):
    kw = qs.get("keyword", [""])[0]
    cond, params = "1=1", []
    if kw:
        cond = "(origin LIKE ? OR dest LIKE ?)"; params = ["%" + kw + "%"] * 2
    return listwrap("SELECT * FROM routes WHERE " + cond + " ORDER BY id", params, qs)

def h_route_create(ctx, m, qs, body):
    if not body.get("origin") or not body.get("dest"):
        raise ApiError(422, "origin/dest 必填")
    c = execute("INSERT INTO routes(origin,dest,distance_km,hours,base_rate) VALUES(?,?,?,?,?)",
                (body["origin"], body["dest"], body.get("distance_km", 0), body.get("hours", 0), body.get("base_rate", 0)))
    return {"id": c.lastrowid}

def _route_or_404(rid):
    r = q1("SELECT * FROM routes WHERE id=?", (rid,))
    if not r:
        raise ApiError(404, "线路不存在")
    return r

def h_route_get(ctx, m, qs, body):
    return dict(_route_or_404(int(m.group(1))))

def h_route_update(ctx, m, qs, body):
    rid = int(m.group(1)); _route_or_404(rid)
    sets, params = [], []
    for f in ("origin", "dest", "distance_km", "hours", "base_rate", "status"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(rid)
        execute("UPDATE routes SET " + ",".join(sets) + " WHERE id=?", params)
    return {"ok": True}

def h_route_delete(ctx, m, qs, body):
    rid = int(m.group(1))
    if q1("SELECT id FROM waybills WHERE route_id=? LIMIT 1", (rid,)):
        raise ApiError(409, "线路已被运单引用，禁止删除")
    execute("DELETE FROM routes WHERE id=?", (rid,))
    return {"ok": True}

# waybills
def wb_detail(it):
    d = q1("SELECT d.*, v.plate, dr.name AS driver_name FROM dispatches d JOIN vehicles v ON v.id=d.vehicle_id JOIN drivers dr ON dr.id=d.driver_id WHERE d.waybill_id=? AND d.status='active'", (it["id"],))
    if d:
        it["dispatch"] = dict(d)
    it["customer_name"] = (q1("SELECT name FROM customers WHERE id=?", (it["customer_id"],)) or {"name": ""})["name"]
    r = q1("SELECT origin, dest, distance_km FROM routes WHERE id=?", (it["route_id"],))
    it["route"] = dict(r) if r else None
    return it

def h_wb_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("status", [""])[0]:
        cond += " AND status=?"; params.append(qs["status"][0])
    if qs.get("customer_id", [""])[0]:
        cond += " AND customer_id=?"; params.append(int(qs["customer_id"][0]))
    if qs.get("date_from", [""])[0]:
        cond += " AND created_at>=?"; params.append(qs["date_from"][0])
    if qs.get("date_to", [""])[0]:
        cond += " AND created_at<=?"; params.append(qs["date_to"][0] + " 23:59:59")
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND (no LIKE ? OR goods LIKE ?)"; params += ["%" + kw + "%"] * 2
    return listwrap("SELECT * FROM waybills WHERE " + cond + " ORDER BY id DESC", params, qs, wb_detail)

def h_wb_create(ctx, m, qs, body):
    errs = K.validate_waybill(body)
    if errs:
        raise ApiError(422, "；".join(errs))
    if not q1("SELECT id FROM customers WHERE id=?", (body["customer_id"],)):
        raise ApiError(404, "客户不存在")
    route = _route_or_404(int(body["route_id"]))
    no = body.get("no") or ("FY" + time.strftime("%Y%m%d") + "-%04d" % next_seq("waybill"))
    if q1("SELECT id FROM waybills WHERE no=?", (no,)):
        raise ApiError(409, "运单号已存在")
    c = execute("""INSERT INTO waybills(no,customer_id,route_id,goods,weight_kg,volume_m3,price_mode,quote) VALUES(?,?,?,?,?,?,?,?)""",
                (no, body["customer_id"], body["route_id"], body.get("goods"), body.get("weight_kg", 0),
                 body.get("volume_m3", 0), body.get("price_mode", "weight"), body.get("quote", 0)))
    wb_id = c.lastrowid
    conn = D.get_db(); conn.commit()
    conn.execute("UPDATE waybills SET version=? WHERE id=?", (get_sync("waybills") + 1, wb_id))
    bump_sync("waybills"); conn.commit()
    return {"id": wb_id, "no": no}

def h_wb_get(ctx, m, qs, body):
    r = q1("SELECT * FROM waybills WHERE id=?", (int(m.group(1)),))
    if not r:
        raise ApiError(404, "运单不存在")
    return wb_detail(dict(r))

def h_wb_update(ctx, m, qs, body):
    wid = int(m.group(1))
    r = q1("SELECT * FROM waybills WHERE id=?", (wid,))
    if not r:
        raise ApiError(404, "运单不存在")
    if r["status"] != "pending":
        raise ApiError(422, "仅待调度运单可修改")
    sets, params = [], []
    for f in ("goods", "weight_kg", "volume_m3", "price_mode", "quote", "remark", "route_id"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(wid)
        execute("UPDATE waybills SET " + ",".join(sets) + " WHERE id=?", params)
    return {"ok": True}

def h_wb_delete(ctx, m, qs, body):
    wid = int(m.group(1))
    r = q1("SELECT * FROM waybills WHERE id=?", (wid,))
    if not r:
        raise ApiError(404, "运单不存在")
    if r["status"] != "pending":
        raise ApiError(422, "仅待调度运单可删除")
    execute("DELETE FROM waybills WHERE id=?", (wid,))
    return {"ok": True}

def _wb_or_404(wid):
    r = q1("SELECT * FROM waybills WHERE id=?", (wid,))
    if not r:
        raise ApiError(404, "运单不存在")
    return r

def h_wb_dispatch(ctx, m, qs, body):
    wid = int(m.group(1))
    r = _wb_or_404(wid)
    if r["status"] != "pending":
        raise ApiError(422, "运单状态为 %s，不可调度" % r["status"])
    veh = _veh_or_404(int(body.get("vehicle_id", 0)))
    drv = _drv_or_404(int(body.get("driver_id", 0)))
    if veh["status"] not in ("idle",):
        raise ApiError(422, "车辆非空闲（%s）" % veh["status"])
    if drv["status"] not in ("idle",):
        raise ApiError(422, "司机非空闲（%s）" % drv["status"])
    route = _route_or_404(r["route_id"])
    import datetime
    eta = datetime.datetime.now() + datetime.timedelta(hours=K.eta_hours(route["distance_km"]))
    eta_s = eta.strftime("%Y-%m-%d %H:%M:%S")
    execute("INSERT INTO dispatches(waybill_id,vehicle_id,driver_id,eta_ts,depart_at) VALUES(?,?,?,?,?)",
            (wid, veh["id"], drv["id"], eta_s, now_s()))
    execute("UPDATE waybills SET status='in_transit' WHERE id=?", (wid,))
    execute("UPDATE vehicles SET status='in_transit' WHERE id=?", (veh["id"],))
    execute("UPDATE drivers SET status='in_transit' WHERE id=?", (drv["id"],))
    execute("INSERT INTO trackings(waybill_id,ts,lng,lat,location,event,version) VALUES(?,?,113.26,23.13,'发车地','发车',?)",
            (wid, now_s(), get_sync("trackings") + 1))
    bump_sync("waybills"); bump_sync("trackings")
    return {"ok": True, "eta": eta_s}

def h_wb_track(ctx, m, qs, body):
    wid = int(m.group(1)); _wb_or_404(wid)
    execute("INSERT INTO trackings(waybill_id,ts,lng,lat,location,event,version) VALUES(?,?,?,?,?,?,?)",
            (wid, body.get("ts") or now_s(), body.get("lng", 0), body.get("lat", 0),
             body.get("location"), body.get("event", "在途"), get_sync("trackings") + 1))
    bump_sync("trackings")
    return {"ok": True}

def h_wb_deliver(ctx, m, qs, body):
    wid = int(m.group(1))
    r = _wb_or_404(wid)
    if r["status"] != "in_transit":
        raise ApiError(422, "运单状态为 %s，不可签收" % r["status"])
    d = q1("SELECT * FROM dispatches WHERE waybill_id=? AND status='active'", (wid,))
    if not d:
        raise ApiError(422, "无有效调度记录")
    route = _route_or_404(r["route_id"])
    actual_km = body.get("actual_distance") or route["distance_km"]
    execute("""UPDATE waybills SET status='delivered', signer=?, delivered_at=?, actual_km=? WHERE id=?""",
            (body.get("signer") or "签收人", now_s(), actual_km, wid))
    execute("UPDATE dispatches SET arrive_at=?, status='done' WHERE id=?", (now_s(), d["id"]))
    execute("UPDATE vehicles SET status='idle' WHERE id=?", (d["vehicle_id"],))
    execute("UPDATE drivers SET status='idle', total_trips=total_trips+1, total_km=total_km+? WHERE id=?",
            (actual_km, d["driver_id"]))
    # 自动生成结算
    price = K.freight_price(r["price_mode"], r["weight_kg"], r["volume_m3"], actual_km, route["base_rate"])
    rev = K.money(r["quote"] or price)
    fu = K.fuel_cost(actual_km, 30, 7.9)
    sp = K.settlement_split(float(rev), float(fu), float(K.money(actual_km * route["base_rate"] * 0)), 0)
    execute("""INSERT INTO settlements(waybill_id,revenue,fuel,tolls,other,driver_pay,profit,version)
             VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(waybill_id) DO NOTHING""",
            (wid, sp["revenue"], sp["fuel"], 0, 0, sp["driver_pay"], sp["profit"], get_sync("settlements") + 1))
    bump_sync("waybills"); bump_sync("trackings"); bump_sync("settlements")
    return {"ok": True, "settlement_profit": sp["profit"]}

def h_wb_cancel(ctx, m, qs, body):
    wid = int(m.group(1))
    r = _wb_or_404(wid)
    if r["status"] == "cancelled":
        raise ApiError(422, "运单已取消")
    if r["status"] == "in_transit":
        d = q1("SELECT * FROM dispatches WHERE waybill_id=? AND status='active'", (wid,))
        if d:
            execute("UPDATE dispatches SET status='replaced' WHERE id=?", (d["id"],))
            execute("UPDATE vehicles SET status='idle' WHERE id=?", (d["vehicle_id"],))
            execute("UPDATE drivers SET status='idle' WHERE id=?", (d["driver_id"],))
    execute("UPDATE waybills SET status='cancelled' WHERE id=?", (wid,))
    bump_sync("waybills")
    return {"ok": True}

def h_wb_trackings(ctx, m, qs, body):
    return listwrap("SELECT * FROM trackings WHERE waybill_id=? ORDER BY ts", (int(m.group(1)),), qs)

def h_quote(ctx, m, qs, body):
    try:
        price = K.freight_price(body.get("price_mode", "weight"), body.get("weight_kg", 0),
                                body.get("volume_m3", 0), body.get("distance_km", 0), body.get("base_rate", 0))
    except ValueError as e:
        raise ApiError(422, str(e))
    return {"price": float(price), "eta_hours": K.eta_hours(body.get("distance_km", 0))}

# dispatches
def h_disp_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("status", [""])[0]:
        cond += " AND d.status=?"; params.append(qs["status"][0])
    return listwrap("""SELECT d.*, w.no AS waybill_no, w.status AS wb_status, v.plate, dr.name AS driver_name
                       FROM dispatches d JOIN waybills w ON w.id=d.waybill_id
                       JOIN vehicles v ON v.id=d.vehicle_id JOIN drivers dr ON dr.id=d.driver_id
                       WHERE """ + cond + " ORDER BY d.id DESC", params, qs)

def h_disp_create(ctx, m, qs, body):
    return h_wb_dispatch(ctx, m, qs, {"waybill_id": body.get("waybill_id"), **body})

def h_disp_get(ctx, m, qs, body):
    r = q1("SELECT * FROM dispatches WHERE id=?", (int(m.group(1)),))
    if not r:
        raise ApiError(404, "调度不存在")
    return dict(r)

def h_disp_revoke(ctx, m, qs, body):
    did = int(m.group(1))
    d = q1("SELECT * FROM dispatches WHERE id=? AND status='active'", (did,))
    if not d:
        raise ApiError(404, "有效调度不存在")
    execute("UPDATE dispatches SET status='replaced' WHERE id=?", (did,))
    execute("UPDATE waybills SET status='pending' WHERE id=?", (d["waybill_id"],))
    execute("UPDATE vehicles SET status='idle' WHERE id=?", (d["vehicle_id"],))
    execute("UPDATE drivers SET status='idle' WHERE id=?", (d["driver_id"],))
    bump_sync("waybills")
    return {"ok": True}

# trackings
def h_trk_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("waybill_no", [""])[0]:
        cond += " AND waybill_id=(SELECT id FROM waybills WHERE no=?)"; params.append(qs["waybill_no"][0])
    if qs.get("from", [""])[0]:
        cond += " AND ts>=?"; params.append(qs["from"][0])
    if qs.get("to", [""])[0]:
        cond += " AND ts<=?"; params.append(qs["to"][0])
    return listwrap("SELECT t.*, w.no AS waybill_no FROM trackings t JOIN waybills w ON w.id=t.waybill_id WHERE " + cond + " ORDER BY t.ts DESC", params, qs)

def h_trk_batch(ctx, m, qs, body):
    if not isinstance(body, list):
        raise ApiError(400, "body 须为数组")
    n = 0
    for rec in body:
        w = q1("SELECT id FROM waybills WHERE no=?", (rec.get("waybill_no"),))
        if not w:
            continue
        execute("INSERT INTO trackings(waybill_id,ts,lng,lat,location,event,version) VALUES(?,?,?,?,?,?,?)",
                (w["id"], rec.get("ts") or now_s(), rec.get("lng", 0), rec.get("lat", 0),
                 rec.get("location"), rec.get("event", "在途"), get_sync("trackings") + 1))
        n += 1
    bump_sync("trackings")
    return {"accepted": n}

# settlements
def settle_detail(it):
    wb = q1("SELECT no, goods FROM waybills WHERE id=?", (it["waybill_id"],))
    it["waybill_no"] = wb["no"] if wb else None
    return it

def h_settle_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("status", [""])[0]:
        cond += " AND status=?"; params.append(qs["status"][0])
    return listwrap("SELECT * FROM settlements WHERE " + cond + " ORDER BY id DESC", params, qs, settle_detail)

def h_settle_create(ctx, m, qs, body):
    wid = int(body.get("waybill_id", 0))
    _wb_or_404(wid)
    if q1("SELECT id FROM settlements WHERE waybill_id=?", (wid,)):
        raise ApiError(409, "该运单已有结算")
    sp = K.settlement_split(body.get("revenue", 0), body.get("fuel", 0), body.get("tolls", 0), body.get("other", 0))
    c = execute("INSERT INTO settlements(waybill_id,revenue,fuel,tolls,other,driver_pay,profit,version) VALUES(?,?,?,?,?,?,?,?)",
                (wid, sp["revenue"], sp["fuel"], body.get("tolls", 0), body.get("other", 0), sp["driver_pay"], sp["profit"], get_sync("settlements") + 1))
    bump_sync("settlements")
    return {"id": c.lastrowid, **sp}

def h_settle_get(ctx, m, qs, body):
    r = q1("SELECT * FROM settlements WHERE id=?", (int(m.group(1)),))
    if not r:
        raise ApiError(404, "结算不存在")
    return settle_detail(dict(r))

def h_settle_update(ctx, m, qs, body):
    sid = int(m.group(1))
    r = q1("SELECT * FROM settlements WHERE id=?", (sid,))
    if not r:
        raise ApiError(404, "结算不存在")
    if r["status"] != "open":
        raise ApiError(422, "仅待结结算可修改")
    rev = body.get("revenue", r["revenue"]); fu = body.get("fuel", r["fuel"])
    tol = body.get("tolls", r["tolls"]); ot = body.get("other", r["other"])
    sp = K.settlement_split(rev, fu, tol, ot)
    execute("UPDATE settlements SET revenue=?,fuel=?,tolls=?,other=?,driver_pay=?,profit=?,version=? WHERE id=?",
            (sp["revenue"], sp["fuel"], tol, ot, sp["driver_pay"], sp["profit"], get_sync("settlements") + 1, sid))
    bump_sync("settlements")
    return {"ok": True}

def h_settle_close(ctx, m, qs, body):
    sid = int(m.group(1))
    r = q1("SELECT * FROM settlements WHERE id=?", (sid,))
    if not r:
        raise ApiError(404, "结算不存在")
    if r["status"] != "open":
        raise ApiError(422, "结算已结清")
    execute("UPDATE settlements SET status='closed', version=? WHERE id=?", (get_sync("settlements") + 1, sid))
    bump_sync("settlements")
    return {"ok": True}

def h_settle_summary(ctx, m, qs, body):
    rec = q1("SELECT COALESCE(SUM(revenue),0) v FROM settlements WHERE status='open'")["v"]
    pay = q1("SELECT COALESCE(SUM(revenue-profit),0) v FROM settlements WHERE status='open'")["v"]
    profit = q1("SELECT COALESCE(SUM(profit),0) v FROM settlements")["v"]
    total = q1("SELECT COUNT(*) c FROM settlements")["c"]
    closed = q1("SELECT COUNT(*) c FROM settlements WHERE status='closed'")["c"]
    return {"open_receivable": rec, "open_payable": pay, "total_profit": profit,
            "closed_ratio": round(closed / total, 3) if total else 0}

def csv_export(rows, cols):
    import csv, io
    buf = io.StringIO()
    buf.write("\ufeff")
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] if c in r.keys() else "" for c in cols])
    return buf.getvalue()

def h_settle_export(ctx, m, qs, body):
    rows = q("SELECT s.*, w.no AS waybill_no FROM settlements s JOIN waybills w ON w.id=s.waybill_id ORDER BY s.id")
    return ("csv", csv_export(rows, ["id", "waybill_no", "revenue", "fuel", "tolls", "other", "driver_pay", "profit", "status", "created_at"]))

# fuel
def h_fuel_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("vehicle_id", [""])[0]:
        cond += " AND f.vehicle_id=?"; params.append(int(qs["vehicle_id"][0]))
    if qs.get("from", [""])[0]:
        cond += " AND f.date>=?"; params.append(qs["from"][0])
    if qs.get("to", [""])[0]:
        cond += " AND f.date<=?"; params.append(qs["to"][0])
    return listwrap("SELECT f.*, v.plate FROM fuel f JOIN vehicles v ON v.id=f.vehicle_id WHERE " + cond + " ORDER BY f.date DESC", params, qs)

def h_fuel_create(ctx, m, qs, body):
    _veh_or_404(int(body.get("vehicle_id", 0)))
    liters = body.get("liters", 0); price = body.get("price", 0)
    c = execute("INSERT INTO fuel(vehicle_id,date,liters,price,amount,odometer,version) VALUES(?,?,?,?,?,?,?)",
                (body["vehicle_id"], body.get("date") or time.strftime("%Y-%m-%d"), liters, price,
                 float(K.money(liters * price)), body.get("odometer", 0), get_sync("fuel") + 1))
    bump_sync("fuel")
    return {"id": c.lastrowid}

def h_fuel_update(ctx, m, qs, body):
    fid = int(m.group(1))
    if not q1("SELECT id FROM fuel WHERE id=?", (fid,)):
        raise ApiError(404, "记录不存在")
    sets, params = [], []
    for f in ("date", "liters", "price", "odometer"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if "liters" in body or "price" in body:
        r = q1("SELECT * FROM fuel WHERE id=?", (fid,))
        liters = body.get("liters", r["liters"]); price = body.get("price", r["price"])
        sets.append("amount=?"); params.append(float(K.money(liters * price)))
    if sets:
        params.append(fid)
        execute("UPDATE fuel SET " + ",".join(sets) + " WHERE id=?", params)
    return {"ok": True}

def h_fuel_delete(ctx, m, qs, body):
    execute("DELETE FROM fuel WHERE id=?", (int(m.group(1)),))
    return {"ok": True}

# risks
def h_risk_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("status", [""])[0]:
        cond += " AND status=?"; params.append(qs["status"][0])
    return listwrap("SELECT * FROM risks WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_risk_scan(ctx, m, qs, body):
    created = 0
    import datetime
    now = datetime.datetime.now()
    # 1) 逾期运单
    for w in q("SELECT w.*, d.eta_ts FROM waybills w JOIN dispatches d ON d.waybill_id=w.id AND d.status='active' WHERE w.status='in_transit'"):
        if w["eta_ts"] and w["eta_ts"] < now_s():
            overdue_h = (now - datetime.datetime.fromisoformat(w["eta_ts"])).total_seconds() / 3600
            exists = q1("SELECT id FROM risks WHERE rtype='waybill_overdue' AND ref_id=? AND status='open'", (w["id"],))
            if not exists:
                sc = K.waybill_risk(overdue_h, 0, 0)
                execute("INSERT INTO risks(rtype,ref_id,title,detail,score) VALUES('waybill_overdue',?,?,?,?)",
                        (w["id"], "运单 %s 逾期未达" % w["no"], "已逾期 %.1f 小时" % overdue_h, sc["score"]))
                created += 1
    # 2) 车辆维保/保险
    for v in q("SELECT * FROM vehicles WHERE status!='disabled'"):
        for f, tp, label in (("next_maint", "vehicle_maint", "维保"), ("insurance_exp", "vehicle_ins", "保险")):
            if v[f] and v[f] <= (now + datetime.timedelta(days=30)).strftime("%Y-%m-%d"):
                if not q1("SELECT id FROM risks WHERE rtype=? AND ref_id=? AND status='open'", (tp, v["id"])):
                    execute("INSERT INTO risks(rtype,ref_id,title,detail,score) VALUES(?,?,?,?,30)",
                            (tp, v["id"], "车辆 %s %s临期" % (v["plate"], label), "%s 到期日：%s" % (label, v[f])))
                    created += 1
    # 3) 司机驾照
    for d in q("SELECT * FROM drivers WHERE status!='resigned'"):
        if d["license_exp"] and d["license_exp"] <= (now + datetime.timedelta(days=30)).strftime("%Y-%m-%d"):
            if not q1("SELECT id FROM risks WHERE rtype='driver_license' AND ref_id=? AND status='open'", (d["id"],)):
                execute("INSERT INTO risks(rtype,ref_id,title,detail,score) VALUES('driver_license',?,?,?,30)",
                        (d["id"], "司机 %s 驾照临期" % d["name"], "驾照到期日：%s，请及时办理换证" % d["license_exp"]))
                created += 1
    # 4) 客户欠款
    for c in q("SELECT * FROM customers WHERE status=1 AND credit_limit>0"):
        open_amt = q1("SELECT COALESCE(SUM(revenue),0) s FROM settlements st JOIN waybills w ON w.id=st.waybill_id WHERE w.customer_id=? AND st.status='open'", (c["id"],))["s"]
        ratio = open_amt / c["credit_limit"]
        if ratio > 0.8 and not q1("SELECT id FROM risks WHERE rtype='client_credit' AND ref_id=? AND status='open'", (c["id"],)):
            execute("INSERT INTO risks(rtype,ref_id,title,detail,score) VALUES('client_credit',?,?,?,35)",
                    (c["id"], "客户 %s 欠款临限" % c["name"], "未结金额 %.2f / 额度 %.2f（%.0f%%），请尽快对账收款" % (open_amt, c["credit_limit"], ratio * 100)))
            created += 1
    return {"new_risks": created}

def h_risk_resolve(ctx, m, qs, body):
    rid = int(m.group(1))
    r = q1("SELECT * FROM risks WHERE id=?", (rid,))
    if not r:
        raise ApiError(404, "预警不存在")
    u = ctx["user"]
    execute("UPDATE risks SET status='resolved', resolved_by=?, note=? WHERE id=?",
            (u.get("name") or u.get("username"), body.get("note"), rid))
    return {"ok": True}

# dashboard / stats
def h_dashboard(ctx, m, qs, body):
    today = time.strftime("%Y-%m-%d")
    return {
        "today_waybills": q1("SELECT COUNT(*) c FROM waybills WHERE created_at LIKE ?", (today + "%",))["c"],
        "in_transit": q1("SELECT COUNT(*) c FROM waybills WHERE status='in_transit'")["c"],
        "pending": q1("SELECT COUNT(*) c FROM waybills WHERE status='pending'")["c"],
        "delivered": q1("SELECT COUNT(*) c FROM waybills WHERE status='delivered'")["c"],
        "month_profit": q1("SELECT COALESCE(SUM(profit),0) v FROM settlements WHERE created_at LIKE ?", (today[:7] + "%",))["v"],
        "open_risks": q1("SELECT COUNT(*) c FROM risks WHERE status='open'")["c"],
        "idle_vehicles": q1("SELECT COUNT(*) c FROM vehicles WHERE status='idle'")["c"],
        "idle_drivers": q1("SELECT COUNT(*) c FROM drivers WHERE status='idle'")["c"],
        "recent_waybills": [wb_detail(dict(r)) for r in q("SELECT * FROM waybills ORDER BY id DESC LIMIT 8")],
    }

def h_stats_waybills(ctx, m, qs, body):
    days = min(int(qs.get("days", ["30"])[0] or 30), 180)
    import datetime
    out = []
    for i in range(days - 1, -1, -1):
        d = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400 * i))
        cnt = q1("SELECT COUNT(*) c FROM waybills WHERE created_at LIKE ?", (d + "%",))["c"]
        out.append({"date": d, "count": cnt})
    return {"days": days, "items": out}

def h_stats_vehicles(ctx, m, qs, body):
    rows = q("""SELECT v.id, v.plate, v.vtype, COUNT(d.id) trips, COALESCE(SUM(d2.km),0) km
                FROM vehicles v LEFT JOIN dispatches d ON d.vehicle_id=v.id AND d.status='done'
                LEFT JOIN (SELECT id, vehicle_id, CAST((julianday(arrive_at)-julianday(depart_at))*24 AS REAL) km FROM dispatches) d2 ON d2.id=d.id
                GROUP BY v.id ORDER BY trips DESC""")
    return {"items": [dict(r) for r in rows]}

def h_stats_drivers(ctx, m, qs, body):
    rows = q("""SELECT dr.id, dr.name, COUNT(d.id) trips, dr.total_km
                FROM drivers dr LEFT JOIN dispatches d ON d.driver_id=dr.id AND d.status='done'
                GROUP BY dr.id ORDER BY trips DESC""")
    return {"items": [dict(r) for r in rows]}

def h_stats_clients(ctx, m, qs, body):
    rows = q("""SELECT c.id, c.name, COUNT(w.id) waybills, COALESCE(SUM(s.revenue),0) revenue
                FROM customers c LEFT JOIN waybills w ON w.customer_id=c.id
                LEFT JOIN settlements s ON s.waybill_id=w.id
                GROUP BY c.id ORDER BY waybills DESC LIMIT 10""")
    return {"items": [dict(r) for r in rows]}

# 平台域
def h_notices(ctx, m, qs, body):
    return listwrap("SELECT * FROM notices ORDER BY id DESC", (), qs)

def h_notices_create(ctx, m, qs, body):
    if not body.get("title"):
        raise ApiError(422, "title 必填")
    c = execute("INSERT INTO notices(title, content, level) VALUES(?,?,?)", (body["title"], body.get("content"), body.get("level", "info")))
    return {"id": c.lastrowid}

def h_notices_delete(ctx, m, qs, body):
    execute("DELETE FROM notices WHERE id=?", (int(m.group(1)),))
    return {"ok": True}

def h_policies(ctx, m, qs, body):
    return listwrap("SELECT * FROM policies ORDER BY id", (), qs)

def h_policies_create(ctx, m, qs, body):
    if not body.get("title"):
        raise ApiError(422, "title 必填")
    c = execute("INSERT INTO policies(title, content) VALUES(?,?)", (body["title"], body.get("content")))
    return {"id": c.lastrowid}

def h_logs(ctx, m, qs, body):
    return listwrap("SELECT * FROM logs ORDER BY id DESC", (), qs)

def h_sync(ctx, m, qs, body):
    since = int(qs.get("since", ["0"])[0] or 0)
    ents = (qs.get("entities", [""])[0] or "").split(",")
    tables = {"waybills": "waybills", "trackings": "trackings", "settlements": "settlements", "fuel": "fuel"}
    changes = {}
    for e, t in tables.items():
        if ents and e not in ents:
            continue
        cur_v = get_sync(e)
        if cur_v <= since:
            continue
        rows = q("SELECT * FROM %s WHERE version>? ORDER BY version LIMIT 500" % t, (since,))
        changes[e] = {"items": [dict(r) for r in rows], "version": cur_v}
    return {"since": since, "current": max([get_sync(e) for e in tables] or [0]), "changes": changes}

def h_export(ctx, m, qs, body):
    ent = m.group(1)
    if ent == "waybills":
        rows = q("SELECT w.*, c.name AS customer_name FROM waybills w LEFT JOIN customers c ON c.id=w.customer_id ORDER BY w.id")
        cols = ["no", "customer_name", "goods", "weight_kg", "volume_m3", "price_mode", "quote", "status", "created_at"]
    elif ent == "customers":
        rows = q("SELECT * FROM customers ORDER BY id")
        cols = ["code", "name", "contact", "phone", "settle_type", "credit_limit"]
    elif ent == "settlements":
        return h_settle_export(ctx, m, qs, body)
    elif ent == "fuel":
        rows = q("SELECT f.*, v.plate FROM fuel f LEFT JOIN vehicles v ON v.id=f.vehicle_id ORDER BY f.id")
        cols = ["plate", "date", "liters", "price", "amount", "odometer"]
    else:
        raise ApiError(404, "未知导出实体")
    return ("csv", csv_export(rows, cols))

# ---------- 路由表 (method, regex, handler, perm) ----------
ROUTES = [
    ("GET",  r"^/api/health$", lambda ctx, m, qs, body: {"ok": True, "service": "feiyun-tms", "ts": now_s()}, None),
    ("POST", r"^/api/login$", h_login, None),
    ("POST", r"^/api/logout$", h_logout, "auth"),
    ("GET",  r"^/api/me$", h_me, "auth"),
    ("GET",  r"^/api/users$", h_users, "admin"),
    ("POST", r"^/api/users$", h_users_create, "admin"),
    ("PUT",  r"^/api/users/(\d+)$", h_users_update, "admin"),
    ("GET",  r"^/api/api-keys$", h_keys, "admin"),
    ("POST", r"^/api/api-keys$", h_keys_create, "admin"),
    ("DELETE", r"^/api/api-keys/(\d+)$", h_keys_delete, "admin"),
    ("GET",  r"^/api/customers$", h_cust_list, "tms.customer.read"),
    ("POST", r"^/api/customers$", h_cust_create, "tms.customer.write"),
    ("GET",  r"^/api/customers/(\d+)$", h_cust_get, "tms.customer.read"),
    ("PUT",  r"^/api/customers/(\d+)$", h_cust_update, "tms.customer.write"),
    ("DELETE", r"^/api/customers/(\d+)$", h_cust_delete, "tms.customer.write"),
    ("GET",  r"^/api/customers/(\d+)/waybills$", h_cust_waybills, "tms.customer.read"),
    ("GET",  r"^/api/customers/(\d+)/balance$", h_cust_balance, "tms.customer.read"),
    ("GET",  r"^/api/vehicles$", h_veh_list, "tms.vehicle.read"),
    ("POST", r"^/api/vehicles$", h_veh_create, "tms.vehicle.write"),
    ("GET",  r"^/api/vehicles/(\d+)$", h_veh_get, "tms.vehicle.read"),
    ("PUT",  r"^/api/vehicles/(\d+)$", h_veh_update, "tms.vehicle.write"),
    ("DELETE", r"^/api/vehicles/(\d+)$", h_veh_delete, "tms.vehicle.write"),
    ("GET",  r"^/api/vehicles/(\d+)/fuel$", h_veh_fuel, "tms.fuel.read"),
    ("GET",  r"^/api/vehicles/(\d+)/stats$", h_veh_stats, "tms.vehicle.read"),
    ("GET",  r"^/api/drivers$", h_drv_list, "tms.driver.read"),
    ("POST", r"^/api/drivers$", h_drv_create, "tms.driver.write"),
    ("GET",  r"^/api/drivers/(\d+)$", h_drv_get, "tms.driver.read"),
    ("PUT",  r"^/api/drivers/(\d+)$", h_drv_update, "tms.driver.write"),
    ("DELETE", r"^/api/drivers/(\d+)$", h_drv_delete, "tms.driver.write"),
    ("GET",  r"^/api/drivers/(\d+)/stats$", h_drv_stats, "tms.driver.read"),
    ("GET",  r"^/api/routes$", h_route_list, "tms.route.read"),
    ("POST", r"^/api/routes$", h_route_create, "tms.route.write"),
    ("GET",  r"^/api/routes/(\d+)$", h_route_get, "tms.route.read"),
    ("PUT",  r"^/api/routes/(\d+)$", h_route_update, "tms.route.write"),
    ("DELETE", r"^/api/routes/(\d+)$", h_route_delete, "tms.route.write"),
    ("GET",  r"^/api/waybills$", h_wb_list, "tms.waybill.read"),
    ("POST", r"^/api/waybills$", h_wb_create, "tms.waybill.write"),
    ("POST", r"^/api/waybills/quote$", h_quote, "tms.waybill.read"),
    ("GET",  r"^/api/waybills/(\d+)$", h_wb_get, "tms.waybill.read"),
    ("PUT",  r"^/api/waybills/(\d+)$", h_wb_update, "tms.waybill.write"),
    ("DELETE", r"^/api/waybills/(\d+)$", h_wb_delete, "tms.waybill.write"),
    ("POST", r"^/api/waybills/(\d+)/dispatch$", h_wb_dispatch, "tms.dispatch.write"),
    ("POST", r"^/api/waybills/(\d+)/track$", h_wb_track, "tms.tracking.write"),
    ("POST", r"^/api/waybills/(\d+)/deliver$", h_wb_deliver, "tms.dispatch.write"),
    ("POST", r"^/api/waybills/(\d+)/cancel$", h_wb_cancel, "tms.dispatch.write"),
    ("GET",  r"^/api/waybills/(\d+)/trackings$", h_wb_trackings, "tms.tracking.read"),
    ("GET",  r"^/api/dispatches$", h_disp_list, "tms.dispatch.read"),
    ("POST", r"^/api/dispatches$", h_disp_create, "tms.dispatch.write"),
    ("GET",  r"^/api/dispatches/(\d+)$", h_disp_get, "tms.dispatch.read"),
    ("POST", r"^/api/dispatches/(\d+)/revoke$", h_disp_revoke, "tms.dispatch.write"),
    ("GET",  r"^/api/trackings$", h_trk_list, "tms.tracking.read"),
    ("POST", r"^/api/trackings$", h_trk_batch, "tms.tracking.write"),
    ("GET",  r"^/api/settlements$", h_settle_list, "tms.settlement.read"),
    ("POST", r"^/api/settlements$", h_settle_create, "tms.settlement.write"),
    ("GET",  r"^/api/settlements/summary$", h_settle_summary, "tms.settlement.read"),
    ("GET",  r"^/api/settlements/export$", h_settle_export, "tms.settlement.read"),
    ("GET",  r"^/api/settlements/(\d+)$", h_settle_get, "tms.settlement.read"),
    ("PUT",  r"^/api/settlements/(\d+)$", h_settle_update, "tms.settlement.write"),
    ("POST", r"^/api/settlements/(\d+)/close$", h_settle_close, "tms.settlement.write"),
    ("GET",  r"^/api/fuel$", h_fuel_list, "tms.fuel.read"),
    ("POST", r"^/api/fuel$", h_fuel_create, "tms.fuel.write"),
    ("PUT",  r"^/api/fuel/(\d+)$", h_fuel_update, "tms.fuel.write"),
    ("DELETE", r"^/api/fuel/(\d+)$", h_fuel_delete, "tms.fuel.write"),
    ("GET",  r"^/api/risks$", h_risk_list, "tms.risk.read"),
    ("POST", r"^/api/risks/scan$", h_risk_scan, "tms.risk.read"),
    ("PUT",  r"^/api/risks/(\d+)/resolve$", h_risk_resolve, "tms.risk.read"),
    ("GET",  r"^/api/dashboard$", h_dashboard, "tms.dashboard.read"),
    ("GET",  r"^/api/stats/waybills$", h_stats_waybills, "tms.dashboard.read"),
    ("GET",  r"^/api/stats/vehicles$", h_stats_vehicles, "tms.dashboard.read"),
    ("GET",  r"^/api/stats/drivers$", h_stats_drivers, "tms.dashboard.read"),
    ("GET",  r"^/api/stats/clients$", h_stats_clients, "tms.dashboard.read"),
    ("GET",  r"^/api/notices$", h_notices, "auth"),
    ("POST", r"^/api/notices$", h_notices_create, "tms.notice.write"),
    ("DELETE", r"^/api/notices/(\d+)$", h_notices_delete, "tms.notice.write"),
    ("GET",  r"^/api/policies$", h_policies, "auth"),
    ("POST", r"^/api/policies$", h_policies_create, "tms.policy.write"),
    ("GET",  r"^/api/logs$", h_logs, "admin"),
    ("GET",  r"^/api/sync$", h_sync, "auth"),
    ("GET",  r"^/api/export/([a-z]+)$", h_export, "auth"),
]

_COMPILED = [(mt, re.compile(rx), fn, perm) for mt, rx, fn, perm in ROUTES]

# ---------- HTTP Handler ----------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FeiYunTMS/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, data, ctype="application/json; charset=utf-8", extra=None):
        body = data if isinstance(data, bytes) else data.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Token, X-Api-Key, Idempotency-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, code, data, extra=None):
        self._send(code, jdump({"code": code, "message": "ok" if code < 400 else data if isinstance(data, str) else "error", "data": data if code < 400 or not isinstance(data, str) else None}), extra=extra)

    def _body(self):
        ln = int(self.headers.get("Content-Length") or 0)
        if ln <= 0:
            return {}
        raw = self.rfile.read(ln)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _token_from_req(self):
        h = self.headers
        auth = h.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        if h.get("X-Token"):
            return h["X-Token"].strip()
        ck = h.get("Cookie")
        if ck:
            try:
                c = http_cookies.SimpleCookie(ck)
                if "token" in c:
                    return c["token"].value
            except Exception:
                pass
        if h.get("X-Api-Key"):
            return "key:" + h["X-Api-Key"].strip()
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "token" in qs:
            return qs["token"][0]
        return None

    def _authenticate(self):
        tok = self._token_from_req()
        if not tok:
            return None, None
        if tok.startswith("key:"):
            u = auth_key(tok[4:])
            return ({"id": None, **u} if u else None), tok
        u = auth_token(tok)
        if u:
            perms = K.ROLE_PERMS.get(u["role"], K.ROLE_PERMS["reader"])
            return {"id": u["user_id"], "username": u["username"], "name": u["name"], "role": u["role"], "perms": perms}, tok
        return None, tok

    def _match_route(self, method, path):
        for mt, rx, fn, perm in _COMPILED:
            if mt != method:
                continue
            m = rx.match(path)
            if m:
                return fn, perm, m
        return None, None, None

    def _handle(self, method):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if PREFIX and path.startswith(PREFIX):
                path = path[len(PREFIX):] or "/"
            if method == "OPTIONS":
                return self._send(200, "{}")
            if not path.startswith("/api/"):
                # 静态文件
                return self._static(path)
            qs = urllib.parse.parse_qs(parsed.query)
            fn, perm, m = self._match_route(method, path)
            if not fn:
                return self._send_json(404, "接口不存在: %s" % path)
            user, tok = self._authenticate()
            ctx = {"user": user or {}, "token": (tok or "").replace("key:", "")}
            # 鉴权
            if perm is not None and not user:
                return self._send_json(401, "未认证")
            if perm == "admin":
                if not user or user.get("role") != "admin":
                    return self._send_json(403, "需要管理员权限")
            elif perm == "auth":
                if not user:
                    return self._send_json(401, "未认证")
            elif perm:
                perms = user.get("perms") if user else None
                if not user or not K.has_perm(perms or [], perm):
                    return self._send_json(403, "无权限: " + perm)
            body = self._body() if method in ("POST", "PUT", "DELETE") else {}
            # 幂等
            idem = self.headers.get("Idempotency-Key")
            if idem and method == "POST":
                row = q1("SELECT response FROM idem_keys WHERE key=?", (idem,))
                if row:
                    return self._send(200, row["response"])
            result = fn(ctx, m, qs, body)
            if isinstance(result, tuple) and result[0] == "csv":
                return self._send(200, result[1], ctype="text/csv; charset=utf-8",
                                  extra={"Content-Disposition": "attachment; filename=export.csv"})
            payload = jdump({"code": 200, "message": "ok", "data": result})
            if idem and method == "POST":
                execute("INSERT OR REPLACE INTO idem_keys(key, user_id, response, created_at) VALUES(?,?,?,?)",
                        (idem, user.get("id") if user else None, payload, now_s()))
            return self._send(200, payload)
        except ApiError as e:
            return self._send_json(e.code, e.message)
        except Exception as e:
            traceback.print_exc()
            return self._send_json(500, "内部错误: %s" % e)

    def _static(self, path):
        if path in ("/", "/index.html", ""):
            path = "/index.html"
        fp = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend"), path.lstrip("/"))
        fp = os.path.normpath(fp)
        if not fp.startswith(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))):
            return self._send(403, "forbidden", ctype="text/plain")
        if not os.path.isfile(fp):
            return self._send(404, "not found", ctype="text/plain")
        ctype = {"html": "text/html; charset=utf-8", "js": "application/javascript; charset=utf-8",
                 "css": "text/css; charset=utf-8", "svg": "image/svg+xml", "png": "image/png", "ico": "image/x-icon"}.get(fp.rsplit(".", 1)[-1], "application/octet-stream")
        with open(fp, "rb") as f:
            return self._send(200, f.read(), ctype=ctype)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_OPTIONS(self):
        self._handle("OPTIONS")

def main():
    D.init_db()
    S.seed_if_empty()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("FeiYun TMS listening on :%d prefix=%r db=%s" % (PORT, PREFIX, D.DB_PATH))
    srv.serve_forever()

if __name__ == "__main__":
    main()
