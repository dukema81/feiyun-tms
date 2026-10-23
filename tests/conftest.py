# -*- coding: utf-8 -*-
"""飞运 TMS 测试夹具：临时库 + 进程内服务（session 级）。"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

_tmp = tempfile.mkdtemp(prefix="feiyun_test_")
os.environ["TMS_DB"] = os.path.join(_tmp, "test.db")
os.environ["TMS_PORT"] = "0"

import db            # noqa: E402
import seed as seedmod  # noqa: E402
import server        # noqa: E402

_base = [""]


@pytest.fixture(scope="session", autouse=True)
def svc():
    db.init_db()
    seedmod.seed_if_empty()
    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    _base[0] = "http://127.0.0.1:%d" % srv.server_address[1]
    yield {"base": _base[0]}
    srv.shutdown()


def req(method, path, body=None, headers=None):
    path = urllib.parse.quote(path, safe="/?=&%")
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(_base[0] + path, data=data, method=method,
                               headers={"Content-Type": "application/json",
                                        **(headers or {})})
    try:
        resp = urllib.request.urlopen(r, timeout=15)
        return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def jreq(method, path, body=None, headers=None):
    code, data = req(method, path, body, headers)
    try:
        return code, json.loads(data.decode("utf-8"))
    except Exception:
        return code, {"raw": data[:200].decode("utf-8", "ignore")}


@pytest.fixture(scope="session")
def admin_token(svc):
    code, data = jreq("POST", "/api/login", {"username": "admin", "password": "123456"})
    assert code == 200, data
    return data["data"]["token"]


@pytest.fixture(scope="session")
def H(admin_token):
    return {"Authorization": "Bearer " + admin_token}
