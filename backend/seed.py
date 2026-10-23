# -*- coding: utf-8 -*-
"""飞运 TMS 种子数据"""
import time, hashlib
from db import get_db, q1, execute, init_db, bump_sync

def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

USERS = [
    ("admin",    "系统管理员", "admin"),
    ("wangdc",   "王调度",   "dispatcher"),
    ("liyun",    "李运营",   "ops"),
    ("zhangcw",  "张财务",   "finance"),
    ("chenbd",   "陈车队长", "captain"),
    ("reader01", "查看账号", "reader"),
]

CUSTOMERS = [
    ("C001", "广州宏达电子", "陈经理", "13800001001", "广州市黄埔区科学城", "monthly", 500000),
    ("C002", "深圳华强物流", "林总",   "13800001002", "深圳市宝安区西乡", "monthly", 800000),
    ("C003", "东莞精密机械", "黄厂长", "13800001003", "东莞市长安镇", "monthly", 300000),
    ("C004", "佛山陶瓷集团", "周主管", "13800001004", "佛山市禅城区", "cash", 100000),
    ("C005", "中山家电制造", "吴经理", "13800001005", "中山市小榄镇", "monthly", 200000),
    ("C006", "珠海医药流通", "赵经理", "13800001006", "珠海市香洲区", "monthly", 400000),
]

VEHICLES = [
    ("粤A12345", "4.2m厢式", 2000, 18,  "idle", 185000, "2026-11-10", "2027-03-15"),
    ("粤A23456", "6.8m高栏", 8000, 45,  "idle", 320000, "2026-11-05", "2027-01-20"),
    ("粤B34567", "9.6m厢式", 15000, 60, "idle", 450000, "2026-10-28", "2026-11-25"),
    ("粤B45678", "13m半挂",  30000, 80, "in_transit", 620000, "2026-12-01", "2027-05-10"),
    ("粤C56789", "17.5m半挂",35000, 120, "idle", 780000, "2026-11-18", "2027-02-28"),
    ("粤C67890", "9.6m冷藏", 12000, 55, "maintenance", 290000, "2026-10-25", "2026-12-12"),
]

DRIVERS = [
    ("刘强国", "13900002001", "440101199001011234", "A2", "2027-06-30", "idle"),
    ("马志远", "13900002002", "440101199102022345", "A2", "2027-03-15", "in_transit"),
    ("孙为民", "13900002003", "440101199203033456", "B2", "2026-11-10", "idle"),
    ("何建业", "13900002004", "440101199304044567", "A2", "2026-11-20", "idle"),
    ("郑海涛", "13900002005", "440101199505055678", "B2", "2027-08-01", "rest"),
    ("冯天宇", "13900002006", "440101199606066789", "A2", "2027-01-31", "idle"),
]

ROUTES = [
    ("广州", "深圳", 140, 3.0, 90),
    ("广州", "长沙", 660, 9.0, 55),
    ("深圳", "武汉", 1050, 14.0, 48),
    ("东莞", "上海", 1450, 18.0, 45),
    ("佛山", "成都", 1650, 22.0, 42),
    ("中山", "南昌", 850, 12.0, 52),
]

def waybill_no(i):
    return "FY" + time.strftime("%Y%m%d") + "-%03d" % i

WAYBILLS = [  # (idx, cust, route, goods, w, v, mode, quote, status, km, signer)
    (1, 1, 1, "电子元器件", 3000, 15, "weight", 37800, "delivered", 142, "陈经理"),
    (2, 2, 3, "日用品",     12000, 50, "weight", 604800, "delivered", 1060, "林总"),
    (3, 3, 4, "精密机床",   18000, 65, "weight", 1174500, "delivered", 1465, "黄厂长"),
    (4, 4, 2, "陶瓷砖",     26000, 70, "weight", 943800, "in_transit", None, None),
    (5, 5, 6, "小家电",     9000, 40, "weight", 397800, "in_transit", None, None),
    (6, 6, 5, "药品",       6000, 35, "volume", 231000, "in_transit", None, None),
    (7, 1, 2, "服务器机柜", 5000, 25, "weight", 181500, "pending", None, None),
    (8, 2, 1, "显示屏",     4000, 20, "weight", 50400, "pending", None, None),
    (9, 3, 5, "机械配件",   15000, 55, "weight", 990000, "pending", None, None),
    (10, 5, 4, "家电配件",  7500, 32, "weight", 492750, "cancelled", None, None),
]

SETTLEMENTS = [  # waybill_id, revenue, fuel, tolls, other, status
    (1, 37800, 2100, 450, 100, "closed"),
    (2, 604800, 15800, 2100, 500, "closed"),
    (3, 1174500, 20500, 2900, 800, "open"),
]

FUEL = [
    (1, "2026-10-20", 180, 7.85, 185200),
    (1, "2026-10-23", 165, 7.90, 185900),
    (2, "2026-10-21", 240, 7.85, 321000),
    (3, "2026-10-22", 310, 7.88, 451500),
    (4, "2026-10-23", 380, 7.88, 619800),
    (5, "2026-10-19", 330, 7.90, 779200),
]

POLICIES = [
    ("安全驾驶制度", "连续驾驶不得超过4小时，每日驾驶累计不超过10小时。"),
    ("运单签收规范", "签收须核对运单号与货品清单，异常货损当场拍照留证。"),
    ("结算对账制度", "月结客户每月5日前完成上月对账，超期暂停派单。"),
    ("油耗管控制度", "百公里油耗超基准15%的车辆须提交书面说明。"),
]

NOTICES = [
    ("四季度安全培训通知", "11月5日 9:00 全体司机参加安全培训，地点：总部三楼会议室。", "warn"),
    ("新增成都专线", "佛山-成都线路已开通，日发一班。", "info"),
    ("系统维护公告", "本周日凌晨2点系统升级，预计30分钟。", "info"),
    ("油价上调提醒", "柴油价格上调0.15元/升，请合理安排加油。", "warn"),
]

def seed_if_empty():
    init_db()
    if q1("SELECT id FROM users LIMIT 1"):
        return False
    conn = get_db()
    cur = conn.cursor()
    for username, name, role in USERS:
        cur.execute("INSERT INTO users(username, password, name, role) VALUES(?,?,?,?)",
                    (username, sha("123456"), name, role))
    for code, name, contact, phone, addr, st, limit in CUSTOMERS:
        cur.execute("INSERT INTO customers(code,name,contact,phone,address,settle_type,credit_limit) VALUES(?,?,?,?,?,?,?)",
                    (code, name, contact, phone, addr, st, limit))
    for plate, vtype, cw, cv, st, odo, maint, ins in VEHICLES:
        cur.execute("INSERT INTO vehicles(plate,vtype,cap_weight,cap_volume,status,odometer,next_maint,insurance_exp) VALUES(?,?,?,?,?,?,?,?)",
                    (plate, vtype, cw, cv, st, odo, maint, ins))
    for name, phone, lno, ltype, lexp, st in DRIVERS:
        cur.execute("INSERT INTO drivers(name,phone,license_no,license_type,license_exp,status) VALUES(?,?,?,?,?,?)",
                    (name, phone, lno, ltype, lexp, st))
    for origin, dest, km, hrs, rate in ROUTES:
        cur.execute("INSERT INTO routes(origin,dest,distance_km,hours,base_rate) VALUES(?,?,?,?,?)",
                    (origin, dest, km, hrs, rate))
    # 运单
    drows = {r["id"]: dict(r) for r in cur.execute("SELECT * FROM dispatches").fetchall()}
    for idx, cust, route, goods, w, v, mode, quote, status, km, signer in WAYBILLS:
        no = waybill_no(idx)
        r = cur.execute("SELECT * FROM routes WHERE id=?", (route,)).fetchone()
        cur.execute("""INSERT INTO waybills(no,customer_id,route_id,goods,weight_kg,volume_m3,price_mode,quote,
                       actual_km,status,signer,delivered_at,version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                    (no, cust, route, goods, w, v, mode, quote, km, status, signer,
                     time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 86400 * (idx % 5))) if status == "delivered" else None))
        wb_id = cur.lastrowid
        if status == "in_transit":
            veh = (4 if idx == 4 else 1, 2 if idx == 4 else 3, 6 if idx == 6 else None)
        if status == "in_transit":
            vid, did = (4, 2) if idx == 4 else ((1, 3) if idx == 5 else (5, 6))
            import datetime
            eta = (datetime.datetime.now() + datetime.timedelta(hours=float(r["hours"])))
            cur.execute("INSERT INTO dispatches(waybill_id,vehicle_id,driver_id,eta_ts,depart_at,status) VALUES(?,?,?,?,?,'active')",
                        (wb_id, vid, did, eta.strftime("%Y-%m-%d %H:%M:%S"),
                         time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 3600 * (idx * 3)))))
            cur.execute("UPDATE vehicles SET status='in_transit' WHERE id=?", (vid,))
            cur.execute("UPDATE drivers SET status='in_transit' WHERE id=?", (did,))
        if status == "delivered":
            import datetime
            dep = datetime.datetime.now() - datetime.timedelta(days=idx)
            arr = dep + datetime.timedelta(hours=float(r["hours"]))
            cur.execute("INSERT INTO dispatches(waybill_id,vehicle_id,driver_id,eta_ts,depart_at,arrive_at,status) VALUES(?,?,?,?,?,?,'done')",
                        (wb_id, idx % 6 + 1, (idx % 6) + 1, arr.strftime("%Y-%m-%d %H:%M:%S"),
                         dep.strftime("%Y-%m-%d %H:%M:%S"), arr.strftime("%Y-%m-%d %H:%M:%S")))
            for j in range(3):
                cur.execute("INSERT INTO trackings(waybill_id,ts,lng,lat,location,event,version) VALUES(?,?,?,?,?,?,1)",
                            (wb_id, (dep + datetime.timedelta(hours=j * 2)).strftime("%Y-%m-%d %H:%M:%S"),
                             113.2 + j * 0.4, 23.1 + j * 0.3, "途经点%d" % (j + 1),
                             "发车" if j == 0 else ("到达" if j == 2 else "在途")))
        if status == "in_transit":
            import datetime
            dep = datetime.datetime.now() - datetime.timedelta(hours=idx * 3)
            for j in range(2):
                cur.execute("INSERT INTO trackings(waybill_id,ts,lng,lat,location,event,version) VALUES(?,?,?,?,?,?,1)",
                            (wb_id, (dep + datetime.timedelta(hours=j)).strftime("%Y-%m-%d %H:%M:%S"),
                             113.0 + j * 0.5, 22.8 + j * 0.4, "在途%d" % (j + 1), "发车" if j == 0 else "在途"))
    # 结算
    for wb, rev, fu, tol, ot, st in SETTLEMENTS:
        from tms import settlement_split
        sp = settlement_split(rev, fu, tol, ot)
        cur.execute("INSERT INTO settlements(waybill_id,revenue,fuel,tolls,other,driver_pay,profit,status,version) VALUES(?,?,?,?,?,?,?,?,1)",
                    (wb, sp["revenue"], sp["fuel"], sp["tolls"], sp["other"], sp["driver_pay"], sp["profit"], st))
    for vid, date, liters, price, odo in FUEL:
        cur.execute("INSERT INTO fuel(vehicle_id,date,liters,price,amount,odometer,version) VALUES(?,?,?,?,?,?,1)",
                    (vid, date, liters, price, round(liters * price, 2), odo))
    for title, content in POLICIES:
        cur.execute("INSERT INTO policies(title, content) VALUES(?,?)", (title, content))
    for title, content, level in NOTICES:
        cur.execute("INSERT INTO notices(title, content, level) VALUES(?,?,?)", (title, content, level))
    cur.execute("INSERT INTO tms_rules(name, value) VALUES('overdue_hours_threshold','2')")
    conn.commit()
    for e in ("waybills", "trackings", "settlements", "fuel"):
        bump_sync(e)
    return True

if __name__ == "__main__":
    print("seeded:", seed_if_empty())
