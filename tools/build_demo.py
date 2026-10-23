# -*- coding: utf-8 -*-
"""飞运运输管理系统 · 离线 DEMO 构建器

从进程内实例抓取真实接口快照，内联前端资源，fetch 拦截读快照，
产出双击即开的单文件 HTML。
"""
import io
import json
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "demo")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOK = ""
SRV = None
BASE = ""


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def boot_inproc():
    global SRV, BASE
    import threading
    dbp = os.path.join(OUT, "_snap.db")
    for f in (dbp, dbp + "-wal", dbp + "-shm"):
        if os.path.exists(f):
            os.remove(f)
    os.environ["TMS_DB"] = dbp
    sys.path.insert(0, os.path.join(ROOT, "backend"))
    import db
    import seed as seedmod
    import server as srvmod

    srvmod.PORT = free_port()
    db.init_db()
    seedmod.seed_if_empty()
    SRV = srvmod.ThreadingHTTPServer(("127.0.0.1", srvmod.PORT), srvmod.Handler)
    threading.Thread(target=SRV.serve_forever, daemon=True).start()
    BASE = "http://127.0.0.1:%d" % srvmod.PORT
    print("in-proc server on", BASE)


def login(as_user="admin", pwd=None):
    global TOK
    pwd = pwd or ("123456")
    body = json.dumps({"username": as_user, "password": pwd}).encode()
    req = urllib.request.Request(BASE + "/api/login", data=body,
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=20) as r:
        TOK = json.loads(r.read().decode("utf-8"))["data"]["token"]
    print("login ->", BASE, "@", as_user)


def get(path):
    req = urllib.request.Request(BASE + path)
    req.add_header("Authorization", "Bearer " + TOK)
    try:
        with OPENER.open(req, timeout=60) as r:
            js = json.loads(r.read().decode("utf-8"))
            if isinstance(js, dict) and "data" in js:
                return js["data"]
            return js
    except Exception as e:                                    # noqa: BLE001
        print("  !! %-46s %s" % (path, e))
        return None


def collect():
    """按前端 12 个页面的真实调用顺序抓快照。"""
    paths = (
        ["/api/me", "/api/dashboard", "/api/notices", "/api/policies"]
        + ["/api/users", "/api/api-keys"]
        + ["/api/waybills", "/api/waybills?status=in_transit", "/api/waybills?status=pending",
           "/api/waybills?status=delivered", "/api/waybills/1", "/api/waybills/1/trackings"]
        + ["/api/dispatches", "/api/dispatches?status=active", "/api/dispatches/1"]
        + ["/api/trackings", "/api/trackings?waybill_no=FY20261023-004"]
        + ["/api/customers", "/api/customers/1", "/api/customers/1/waybills", "/api/customers/1/balance"]
        + ["/api/vehicles", "/api/vehicles?status=idle", "/api/vehicles/1", "/api/vehicles/1/fuel", "/api/vehicles/1/stats"]
        + ["/api/drivers", "/api/drivers/1", "/api/drivers/1/stats"]
        + ["/api/routes"]
        + ["/api/settlements", "/api/settlements?status=open", "/api/settlements?status=closed",
           "/api/settlements/1", "/api/settlements/summary"]
        + ["/api/fuel", "/api/fuel?vehicle_id=1"]
        + ["/api/risks", "/api/risks?status=open"]
        + ["/api/stats/waybills?days=30", "/api/stats/vehicles", "/api/stats/drivers", "/api/stats/clients"]
        + ["/api/logs", "/api/sync?since=0&entities=waybills"]
    )
    snap = {}
    for p in paths:
        snap[p] = get(p)
    return snap


DEMO_JS = r"""
/* ============ 离线演示运行时：拦截 fetch 改读快照 ============ */
var SNAP = __SNAP__;
var DEMO_USERS = __USERS__;
var DEMO_ME = (function () {
  var q = (location.search || '') + '&' + (location.hash || '');
  var m = q.match(/[?&#]as=([\w\-]+)/);
  var who = m ? decodeURIComponent(m[1]) : '';
  if (who && DEMO_USERS[who]) return DEMO_USERS[who];
  try {
    var saved = sessionStorage.getItem('demo_as');
    if (saved && DEMO_USERS[saved]) return DEMO_USERS[saved];
  } catch (e) { /* ignore */ }
  return __ME__;
})();

function normPath(p) {
  p = String(p || '').replace(PREFIX, '');
  if (p.charAt(0) !== '/') p = '/' + p;
  return p;
}
function lookup(p) {
  p = normPath(p);
  if (p === '/api/me') return DEMO_ME;
  if (SNAP[p] !== undefined && SNAP[p] !== null) return SNAP[p];
  var bare = p.split('?')[0];
  if (SNAP[bare] !== undefined && SNAP[bare] !== null) return SNAP[bare];
  var fb = [
    [/^\/api\/waybills\?/, '/api/waybills'],
    [/^\/api\/dispatches\?/, '/api/dispatches'],
    [/^\/api\/trackings\?/, '/api/trackings'],
    [/^\/api\/customers\?/, '/api/customers'],
    [/^\/api\/vehicles\?/, '/api/vehicles'],
    [/^\/api\/drivers\?/, '/api/drivers'],
    [/^\/api\/routes\?/, '/api/routes'],
    [/^\/api\/settlements\?/, '/api/settlements'],
    [/^\/api\/fuel\?/, '/api/fuel'],
    [/^\/api\/risks\?/, '/api/risks'],
    [/^\/api\/notices\?/, '/api/notices'],
    [/^\/api\/policies\?/, '/api/policies']
  ];
  for (var i = 0; i < fb.length; i++) {
    if (fb[i][0].test(p)) return SNAP[fb[i][1]] || {};
  }
  var m = p.match(/^\/api\/waybills\/(\d+)$/);
  if (m) {
    var hit = ((SNAP['/api/waybills'] || {}).items || []).filter(function (x) { return x.id == m[1]; })[0];
    if (hit) return Object.assign({}, hit);
  }
  m = p.match(/^\/api\/customers\/(\d+)$/);
  if (m) {
    var c = ((SNAP['/api/customers'] || {}).items || []).filter(function (x) { return x.id == m[1]; })[0];
    if (c) return Object.assign({}, c, {waybill_count: 2});
  }
  m = p.match(/^\/api\/vehicles\/(\d+)$/);
  if (m) {
    var v = ((SNAP['/api/vehicles'] || {}).items || []).filter(function (x) { return x.id == m[1]; })[0];
    if (v) return Object.assign({}, v);
  }
  m = p.match(/^\/api\/drivers\/(\d+)$/);
  if (m) {
    var d = ((SNAP['/api/drivers'] || {}).items || []).filter(function (x) { return x.id == m[1]; })[0];
    if (d) return Object.assign({}, d);
  }
  m = p.match(/^\/api\/settlements\/(\d+)$/);
  if (m) {
    var s = ((SNAP['/api/settlements'] || {}).items || []).filter(function (x) { return x.id == m[1]; })[0];
    if (s) return Object.assign({}, s, {waybill_no: 'FY-DEMO'});
  }
  return null;
}


window.fetch = function (url, opt) {
  var method = (opt && opt.method) || 'GET';
  var path = String(url).replace(location.origin, '');
  var status = 200, body;
  if (method !== 'GET') {
    body = {code: 200, message: '\u6f14\u793a\u73af\u5883\u53ea\u8bfb\uff0c\u5199\u64cd\u4f5c\u672a\u6267\u884c',
            data: {}};
  } else {
    var data = lookup(path);
    if (data === null || data === undefined) {
      body = {code: 200, message: 'ok', data: []};
    } else {
      body = {code: 200, message: 'ok', data: data};
    }
  }
  return Promise.resolve({
    status: status, ok: true,
    json: function () { return Promise.resolve(body); },
    text: function () { return Promise.resolve(JSON.stringify(body)); }
  });
};
window.CSV = function () { return Promise.reject(new Error('\u6f14\u793a\u73af\u5883\u4e0d\u652f\u6301\u5bfc\u51fa')); };

try {
  localStorage.setItem('tms_token', 'demo');
  localStorage.setItem('tms_user', JSON.stringify(DEMO_ME));
} catch (e) { /* ignore */ }

window.demoAs = function (who) {
  var m = DEMO_USERS[who];
  if (!m) return;
  try {
    localStorage.setItem('tms_user', JSON.stringify(m));
    localStorage.setItem('tms_token', 'demo');
    sessionStorage.setItem('demo_as', who);
  } catch (e) { /* ignore */ }
  location.hash = '#/dash';
  location.reload();
};

document.addEventListener('DOMContentLoaded', function () {
  var bar = document.createElement('div');
  bar.className = 'demo-bar';
  var opts = Object.keys(DEMO_USERS).map(function (k) {
    return '<option value="' + k + '"' + (k === DEMO_ME.username ? ' selected' : '') + '>'
      + DEMO_USERS[k].name + '\uff08' + DEMO_USERS[k].roleLabel + '\uff09</option>';
  }).join('');
  bar.innerHTML = '<b>\u79bb\u7ebf\u6f14\u793a</b> \u6570\u636e\u53d6\u81ea\u98de\u80b2\u6f14\u793a\u5b9e\u4f8b\u7684\u771f\u5b9e\u5feb\u7167\uff0c\u53ea\u8bfb\u6d4f\u89c8\uff0c\u5199\u64cd\u4f5c\u4e0d\u4f1a\u771f\u6b63\u6267\u884c\u3002'
    + '<span class="who">\u5f53\u524d\u89c6\u89d2 <select onchange="demoAs(this.value)">' + opts + '</select></span>';
  document.body.insertBefore(bar, document.body.firstChild);
});
"""

DEMO_CSS = r"""
.demo-bar{position:fixed;left:0;right:0;top:0;z-index:99;background:#fff8e6;color:#7a5b12;
  border-bottom:1px solid #f0d9a8;font-size:12.5px;padding:7px 16px;text-align:center;
  box-shadow:0 1px 4px rgba(0,0,0,.06)}
.demo-bar b{color:#b8791b}
.demo-bar .who{margin-left:12px;padding-left:12px;border-left:1px solid #f0d9a8}
.demo-bar select{font-size:12.5px;padding:2px 6px;border:1px solid #e0c98f;border-radius:4px;
  background:#fff;color:#7a5b12}
body{padding-top:34px}
"""


def build():
    if not BASE:
        boot_inproc()
    login("admin")
    snap = collect()
    me = get("/api/me") or {}
    me["perms"] = ["*"]

    # 多视角：admin + 教务主任 + 财务 + 只读
    viewers = {"admin": me}
    for who in ("wangdc", "zhangcw", "reader01"):
        login(who)
        m = get("/api/me") or {}
        if m.get("username"):
            viewers[who] = m
    login("admin")

    filled = sum(1 for v in snap.values() if v not in (None, [], {}))
    print("snapshot paths: %d / %d 有数据" % (filled, len(snap)))

    fx = os.path.join(ROOT, "frontend")
    css = io.open(os.path.join(fx, "style.css"), encoding="utf-8").read()
    app = io.open(os.path.join(fx, "app.js"), encoding="utf-8").read()
    pages = io.open(os.path.join(fx, "pages.js"), encoding="utf-8").read()
    tpl = io.open(os.path.join(ROOT, "tools", "demo_template.html"), encoding="utf-8").read()

    data = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
    me_json = json.dumps(me, ensure_ascii=False, separators=(",", ":"))
    users_json = json.dumps(viewers, ensure_ascii=False, separators=(",", ":"))
    runtime = (DEMO_JS.replace("__SNAP__", data)
               .replace("__USERS__", users_json)
               .replace("__ME__", me_json))

    html = (tpl
            .replace("__STYLE__", css + "\n" + DEMO_CSS)
            .replace("__APP_JS__", app)
            .replace("__PAGES_JS__", pages)
            .replace("__RUNTIME_JS__", runtime))

    os.makedirs(OUT, exist_ok=True)
    name = "飞运运输管理系统Demo.html"
    out_html = os.path.join(OUT, name)
    io.open(out_html, "w", encoding="utf-8").write(html)
    print("html: %.1f KB -> %s" % (len(html.encode("utf-8")) / 1024.0, out_html))
    return out_html


if __name__ == "__main__":
    build()
