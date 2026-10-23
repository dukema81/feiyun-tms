# -*- coding: utf-8 -*-
"""飞运运输管理系统 · 文档与DEMO批量上传知识库（分类 33 企业管理系统）"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = r"C:/Users/maxl/WorkBuddy/Claw/feiyun-tms"
BASE = "http://42.193.158.63"
CAT = 33
PASSWORD = "YCSpyVwt@J2UByom3#n6gb"
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOKEN = None
REPLACE = "--replace" in sys.argv

DOCS = [
    ("docs/feiyun_design_v1.docx", "飞运运输管理系统建设方案",
     "「飞运运输管理系统（TMS）」完整建设方案 V1.0：中小物流企业运输管理痛点与建设目标、"
     "业务域设计（客户/车辆/司机/线路/运单状态机 待调度→运输中→已签收/调度/在途跟踪/"
     "结算/油耗/四类风险预警）、计算内核口径（运价三模式 Decimal 精确到分、ETA 强制休息、"
     "油耗成本、装载率、结算拆分司机应付60%、风险评分0~100分档）、"
     "总体架构与零依赖技术选型（Python 标准库 http.server + SQLite WAL）、"
     "21 表数据模型、6 角色权限矩阵、12 页面功能清单、对外集成方案、部署方案。",
     "飞运,TMS,运输管理,建设方案,物流"),
    ("docs/feiyun_api_v1.docx", "飞运运输管理系统 REST 接口契约",
     "78 端点分组契约：统一响应包 {code,message,data} 与 HTTP 状态一致、鉴权五通道"
     "（Bearer / X-Token / Cookie / ?token= / X-Api-Key，SHA-256 存储）、"
     "Idempotency-Key 幂等、增量同步协议（版本号 + 实体过滤）、列表统一 {items,total,page,size}、"
     "客户/车辆/司机/线路/运单/调度/跟踪/结算/油耗/风险/看板统计/平台域 全量接口表、"
     "运单状态机约束、校验规则与错误码表、外部系统对接三示例（建单幂等/GPS 批量上报/结算增量拉取）。",
     "飞运,TMS,API,接口契约,REST,幂等,增量同步,物流对接"),
    ("docs/feiyun_test_v1.docx", "飞运运输管理系统测试报告",
     "三道质量门禁全部通过：pytest 47 条（内核 24 例：运价三模式/ETA/油耗/装载率/结算拆分/"
     "逾期/风险评分/状态机/校验/权限通配/Decimal HALF_UP；API 集成 23 例：认证五通道/RBAC/"
     "运单全生命周期/调度冲突/签收自动结算/结算结清/油耗/风险扫描/增量同步/幂等/CSV 导出/"
     "API Key 生命周期）；UI 巡检 Playwright 登录+12 页面 0 控制台异常；冒烟 67 项全通过。"
     "测试中发现并修复多项缺陷（INSERT 列数错配、未提交事务导致 SQLite 写锁、"
     "无认证响应码语义、风险扫描绑定数、冒烟脚本幂等化）。",
     "飞运,TMS,测试报告,pytest,Playwright,质量门禁"),
    ("docs/feiyun_manual_v1.docx", "飞运运输管理系统使用手册",
     "面向全部 6 角色的操作手册：系统定位与账号表（admin/123456 等）、12 页面逐页说明"
     "（工作台 KPI、运单管理与新建调度签收取消、调度中心、在途跟踪轨迹、客户信用额度、"
     "车辆维保保险、司机驾照、线路运价、财务结算应收应付毛利与结清、油耗登记、"
     "风险预警四类扫描、系统管理用户密钥公告日志）、开一张运单五步上手、金额分口径说明、"
     "系统对接指引、部署运维、FAQ 四条。",
     "飞运,TMS,使用手册,操作指南,运输管理"),
    ("demo/飞运运输管理系统Demo.html", "飞运运输管理系统离线演示（DEMO）",
     "单文件离线演示：双击即可用浏览器打开，无需服务与网络。"
     "数据取自演示实例真实快照：6 用户 / 6 客户 / 6 车辆 / 6 司机 / 6 线路 / 10 运单 /"
     " 调度与 GPS 轨迹 / 结算单 / 加油记录。"
     "12 个页签覆盖工作台、运单管理、调度中心、在途跟踪、客户管理、车辆管理、司机管理、"
     "线路管理、财务结算、油耗管理、风险预警、系统管理。"
     "支持顶部切换 4 个真实视角（管理员 / 调度 / 财务 / 只读）。只读快照，写操作不会真正执行。",
     "飞运,TMS,DEMO,离线演示,运输管理"),
]


def req(path, method="GET", data=None, token=None):
    r = urllib.request.Request(BASE + path, method=method)
    if data is not None:
        r.data = json.dumps(data).encode("utf-8")
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with OP.open(r, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                     # noqa: BLE001
            return e.code, {}


def curl_upload(path, title, desc, tags):
    full = os.path.join(ROOT, path)
    mime = "text/html" if full.endswith(".html") else \
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    cmd = ["curl", "-s", "--noproxy", "*",
           "-H", "Authorization: Bearer " + TOKEN,
           "-F", "file=@%s;type=%s" % (full, mime),
           "-F", "title=" + title,
           "-F", "description=" + desc,
           "-F", "categoryId=%d" % CAT,
           "-F", "tags=" + tags,
           BASE + "/api/documents/upload"]
    out = subprocess.run(cmd, capture_output=True, timeout=300)
    try:
        return json.loads(out.stdout.decode("utf-8", "ignore"))
    except Exception:                                         # noqa: BLE001
        return {"code": -1, "raw": out.stdout.decode("utf-8", "ignore")[:400],
                "err": out.stderr.decode("utf-8", "ignore")[:200]}


def existing(cat=CAT):
    st, j = req("/api/documents?categoryId=%d&pageNum=1&pageSize=200" % cat, token=TOKEN)
    data = j.get("data") or {}
    if isinstance(data, list):
        return data
    return data.get("records") or data.get("list") or []


def delete_doc(doc_id):
    return req("/api/documents/%s" % doc_id, "DELETE", token=TOKEN)


def main():
    global TOKEN
    st, j = req("/api/auth/login", "POST", {"username": "admin", "password": PASSWORD})
    assert j.get("code") == 200, j
    TOKEN = j["data"]["token"]
    print("login ok")

    if REPLACE:
        want = {t for _, t, _, _ in DOCS}
        for r in existing():
            if r.get("title") in want:
                st, j = delete_doc(r.get("id"))
                print("删除旧文档 %s id=%s -> %s" % (r.get("title"), r.get("id"), st))
                time.sleep(0.4)

    results = []
    for path, title, desc, tags in DOCS:
        j = curl_upload(path, title, desc, tags)
        code = j.get("code")
        doc_id = (j.get("data") or {}).get("id") if isinstance(j.get("data"), dict) else j.get("data")
        size = os.path.getsize(os.path.join(ROOT, path))
        print("%-32s code=%s id=%s %.1fKB" % (os.path.basename(path), code, doc_id, size / 1024.0))
        if code != 200:
            print("   !!", str(j)[:300])
        results.append((path, title, code, doc_id))
        time.sleep(1.2)

    ok = [r for r in results if r[2] == 200]
    print("\n上传成功 %d / %d" % (len(ok), len(results)))
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    with open(os.path.join(ROOT, "reports", "kb_upload_result.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": r[0], "title": r[1], "code": r[2], "id": r[3]} for r in results],
                  f, ensure_ascii=False, indent=2)
    return results


if __name__ == "__main__":
    main()
