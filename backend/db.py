# -*- coding: utf-8 -*-
"""飞运 TMS 数据层：建表 + 连接管理（零依赖，SQLite WAL）"""
import os, sqlite3, threading

DB_PATH = os.environ.get("TMS_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "feiyun.db"))
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS depts(id INTEGER PRIMARY KEY, name TEXT UNIQUE, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT NOT NULL, name TEXT, role TEXT DEFAULT 'reader',
  dept_id INTEGER, phone TEXT, status INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY, user_id INTEGER, created_at TEXT, expires_at TEXT);
CREATE TABLE IF NOT EXISTS api_keys(
  id INTEGER PRIMARY KEY, name TEXT, key_hash TEXT UNIQUE, prefix TEXT, perms TEXT DEFAULT 'tms.*',
  created_at TEXT DEFAULT (datetime('now','localtime')), last_used TEXT, status INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS customers(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT NOT NULL, contact TEXT, phone TEXT, address TEXT,
  settle_type TEXT DEFAULT 'monthly', credit_limit REAL DEFAULT 0, status INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS vehicles(
  id INTEGER PRIMARY KEY, plate TEXT UNIQUE, vtype TEXT, cap_weight REAL DEFAULT 0, cap_volume REAL DEFAULT 0,
  status TEXT DEFAULT 'idle', odometer REAL DEFAULT 0, next_maint TEXT, insurance_exp TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS drivers(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT, license_no TEXT, license_type TEXT,
  license_exp TEXT, status TEXT DEFAULT 'idle', total_trips INTEGER DEFAULT 0, total_km REAL DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS routes(
  id INTEGER PRIMARY KEY, origin TEXT NOT NULL, dest TEXT NOT NULL, distance_km REAL, hours REAL,
  base_rate REAL DEFAULT 0, status INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS waybills(
  id INTEGER PRIMARY KEY, no TEXT UNIQUE, customer_id INTEGER NOT NULL, route_id INTEGER NOT NULL,
  goods TEXT, weight_kg REAL DEFAULT 0, volume_m3 REAL DEFAULT 0, price_mode TEXT DEFAULT 'weight',
  quote REAL DEFAULT 0, actual_km REAL, status TEXT DEFAULT 'pending', signer TEXT,
  delivered_at TEXT, remark TEXT, version INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS dispatches(
  id INTEGER PRIMARY KEY, waybill_id INTEGER UNIQUE, vehicle_id INTEGER NOT NULL, driver_id INTEGER NOT NULL,
  eta_ts TEXT, depart_at TEXT, arrive_at TEXT, status TEXT DEFAULT 'active',
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS trackings(
  id INTEGER PRIMARY KEY, waybill_id INTEGER, ts TEXT, lng REAL, lat REAL, location TEXT, event TEXT,
  version INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS settlements(
  id INTEGER PRIMARY KEY, waybill_id INTEGER UNIQUE, revenue REAL DEFAULT 0, fuel REAL DEFAULT 0,
  tolls REAL DEFAULT 0, other REAL DEFAULT 0, driver_pay REAL DEFAULT 0, profit REAL DEFAULT 0,
  status TEXT DEFAULT 'open', version INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS fuel(
  id INTEGER PRIMARY KEY, vehicle_id INTEGER NOT NULL, date TEXT, liters REAL, price REAL,
  amount REAL, odometer REAL, version INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS risks(
  id INTEGER PRIMARY KEY, rtype TEXT, ref_id INTEGER, title TEXT, detail TEXT, score INTEGER DEFAULT 0,
  status TEXT DEFAULT 'open', resolved_by TEXT, note TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS policies(id INTEGER PRIMARY KEY, title TEXT, content TEXT, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS notices(id INTEGER PRIMARY KEY, title TEXT, content TEXT, level TEXT DEFAULT 'info', created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY, ts TEXT, user_id INTEGER, action TEXT, detail TEXT, ip TEXT);
CREATE TABLE IF NOT EXISTS idem_keys(key TEXT PRIMARY KEY, user_id INTEGER, response TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS sync_state(entity TEXT PRIMARY KEY, version INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS tms_rules(id INTEGER PRIMARY KEY, name TEXT, value TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS seq(name TEXT PRIMARY KEY, val INTEGER DEFAULT 0);

CREATE INDEX IF NOT EXISTS idx_wb_status ON waybills(status);
CREATE INDEX IF NOT EXISTS idx_wb_customer ON waybills(customer_id);
CREATE INDEX IF NOT EXISTS idx_wb_created ON waybills(created_at);
CREATE INDEX IF NOT EXISTS idx_disp_wb ON dispatches(waybill_id);
CREATE INDEX IF NOT EXISTS idx_trk_wb_ts ON trackings(waybill_id, ts);
CREATE INDEX IF NOT EXISTS idx_settle_wb ON settlements(waybill_id);
CREATE INDEX IF NOT EXISTS idx_fuel_veh_date ON fuel(vehicle_id, date);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts);
"""

def get_db():
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        _local.conn = conn
    return conn

def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()

def q(sql, params=()):
    return get_db().execute(sql, params).fetchall()

def q1(sql, params=()):
    return get_db().execute(sql, params).fetchone()

def execute(sql, params=()):
    conn = get_db()
    import time as _t
    for attempt in range(30):
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < 29:
                try:
                    conn.rollback()
                except Exception:
                    pass
                _t.sleep(0.1)
                continue
            try:
                conn.rollback()
            except Exception:
                pass
            raise

def next_seq(name):
    row = q1("SELECT val FROM seq WHERE name=?", (name,))
    if row:
        execute("UPDATE seq SET val=val+1 WHERE name=?", (name,))
        return row["val"] + 1
    execute("INSERT INTO seq(name, val) VALUES(?, 1)", (name,))
    return 1

def bump_sync(entity, conn=None):
    c = conn or get_db()
    c.execute("INSERT INTO sync_state(entity, version) VALUES(?,1) ON CONFLICT(entity) DO UPDATE SET version=version+1", (entity,))
    c.commit()
    row = c.execute("SELECT version FROM sync_state WHERE entity=?", (entity,)).fetchone()
    return row["version"] if row else 0

def get_sync(entity):
    row = q1("SELECT version FROM sync_state WHERE entity=?", (entity,))
    return row["version"] if row else 0
