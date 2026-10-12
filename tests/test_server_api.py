r"""画台 · 服务离线测试（不需网络，自隔离数据根）

用法：  python tests\test_server_api.py
数据根走环境变量 HUATAI_PROJECTS → D:\画台\.tmp-tests\projects，**绝不碰真实工程**。

判据（每条一行 [OK]）：
 1 健康检查给出数据根现状
 2 能力声明形状正确 + 工艺有"能做/不能做"两类
 3 ★ 能力声明与内核旋钮清单**不漂移**（旋钮数一致、状态无"未知"）
 4 工程列表（空 → 新建 → 出现）
 5 新建工程真的落盘（目录 + meta.json，显示名与目录名分开）
 6 目录名安全化（非法字符 / 超长 / 保留名）
 7 同名工程拒绝（409，不静默加后缀）
 8 坏请求一律报错不静默（空体 / 坏 JSON / 缺字段 / 缺参数 → 400）
 9 未知路由 404、不支持的方法 405
10 订单列表与单条订单（缺参数 400、查不到 404）
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = ROOT / ".tmp-tests" / "projects"
if TMP.exists():
    shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)
os.environ["HUATAI_PROJECTS"] = str(TMP)

from server import app as APP  # noqa: E402
from server import capabilities as CAP  # noqa: E402
from server import store as ST  # noqa: E402

PASS = 0
FAIL: list[str] = []


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"[OK] {msg}")


def eq(got, want, msg: str) -> None:
    if got == want:
        ok(msg)
    else:
        FAIL.append(f"{msg} —— 期望 {want!r}，实得 {got!r}")
        print(f"[FAIL] {msg} —— 期望 {want!r}，实得 {got!r}")


def call(method: str, path: str, payload=None):
    # URL 里有中文必须百分号编码（urllib 只吃 ASCII）
    if "?" in path:
        base, query = path.split("?", 1)
        path = base + "?" + urlencode(parse_qsl(query, keep_blank_values=True))
    url = f"http://127.0.0.1:{PORT}{path}"
    data = None
    headers = {}
    if payload is not None:
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"_raw": raw}


httpd = ThreadingHTTPServer(("127.0.0.1", 0), APP.Handler)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def main() -> int:
    print(f"数据根（隔离）= {TMP}")
    print(f"服务端口（临时）= {PORT}")

    # 1 健康
    code, body = call("GET", "/api/health")
    eq(code, 200, "1.1 健康检查 200")
    eq(body.get("数据根"), str(TMP), "1.2 健康检查报出隔离数据根")
    eq(body.get("ok"), True, "1.3 健康检查 ok=True")

    # 2 能力声明
    code, cap = call("GET", "/api/capabilities")
    eq(code, 200, "2.1 能力声明 200")
    crafts = {c["id"]: c for c in cap.get("工艺", [])}
    eq(crafts.get("glass", {}).get("能不能"), True, "2.2 玻璃画 = 能做")
    eq(crafts.get("model3d", {}).get("能不能"), False, "2.3 三维模型 = 不能做")
    eq(bool(crafts.get("model3d", {}).get("为什么不能")), True, "2.4 '不能做'必须带理由（不许只说不会）")
    eq(crafts.get("paper_cut", {}).get("能不能"), False, "2.5 剪纸·镂空切割 = 不能做（矢量内核未接）")
    eq(len(cap.get("本版不做", [])), 7, "2.6 '本版不做'清单非空")

    # 3 与内核不漂移
    import knobs as K  # noqa: E402
    kn = cap.get("旋钮", [])
    eq(len(kn), len(K.KNOBS), "3.1 旋钮数与内核 knobs.KNOBS 一致")
    eq([k["状态"] for k in kn].count("未知"), 0, "3.2 旋钮状态无'未知'（说明内核两侧清单没漂）")
    eq(len([k for k in kn if k["状态"] == "缺口"]), 3, "3.3 缺口旋钮 = 3 个（与内核一致）")

    # 4 工程列表（空）
    code, body = call("GET", "/api/projects")
    eq(code, 200, "4.1 工程列表 200")

    # 5 新建工程
    code, body = call("POST", "/api/projects", {"name": "测试工程"})
    eq(code, 201, "5.1 新建工程 201")
    pdir = ST.projects_root() / "测试工程"
    eq(pdir.is_dir(), True, "5.2 工程目录真的落盘")
    meta = json.loads((pdir / "meta.json").read_text(encoding="utf-8"))
    eq(meta.get("显示名"), "测试工程", "5.3 显示名存进 meta.json")
    eq(meta.get("工程目录名"), "测试工程", "5.4 目录名单独存一份（显示名≠目录名）")
    code, body = call("GET", "/api/projects")
    ids = [p["id"] for p in body["projects"]]
    eq("测试工程" in ids, True, "5.5 新建后出现在工程列表里")

    # 6 目录名安全化
    eq(ST.safe_dirname('a<b>c:d"e/f\\g|h?i*j'), "a_b_c_d_e_f_g_h_i_j", "6.1 非法字符被替换")
    eq(len(ST.safe_dirname("长" * 100)), 40, "6.2 超长目录名截到 40 字")
    eq(ST.safe_dirname("CON"), "_CON", "6.3 Windows 保留名被避开")
    eq(ST.safe_dirname("  名字带空格  "), "名字带空格", "6.4 首尾空格去掉")
    code, body = call("POST", "/api/projects", {"name": "带/斜杠 的工程"})
    eq(code, 201, "6.5 含非法字符的工程名可建（显示名照原样）")
    eq(body["project"]["显示名"], "带/斜杠 的工程", "6.6 显示名保留用户原话")
    eq(body["project"]["工程目录名"], "带_斜杠 的工程", "6.7 目录名被安全化（显示名≠目录名）")

    # 7 同名拒绝
    code, body = call("POST", "/api/projects", {"name": "测试工程"})
    eq(code, 409, "7.1 同名工程 409（不静默加后缀）")
    eq("error" in body, True, "7.2 409 带 error 字段")

    # 8 坏请求不静默
    code, body = call("POST", "/api/projects")
    eq(code, 400, "8.1 空请求体 400")
    code, body = call("POST", "/api/projects", b"{not json")
    eq(code, 400, "8.2 坏 JSON 400")
    code, body = call("POST", "/api/projects", {"nope": 1})
    eq(code, 400, "8.3 缺 name 字段 400")
    code, body = call("POST", "/api/projects", {"name": "   "})
    eq(code, 400, "8.4 空白工程名 400")
    code, body = call("POST", "/api/projects", {"name": "///"})
    eq(code, 400, "8.5 全是非法字符的工程名 400")

    # 9 路由与方法
    code, body = call("GET", "/api/nope")
    eq(code, 404, "9.1 未知路由 404")
    code, body = call("PUT", "/api/projects")
    eq(code, 405, "9.2 不支持的方法 405")

    # 10 订单
    code, body = call("GET", "/api/orders?project=测试工程")
    eq(code, 200, "10.1 订单列表 200")
    eq(body.get("orders"), [], "10.2 新工程订单为空")
    code, body = call("GET", "/api/order")
    eq(code, 400, "10.3 订单缺参数 400")
    code, body = call("GET", "/api/order?project=测试工程&id=不存在")
    eq(code, 404, "10.4 查不到的订单 404")

    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：")
        for f in FAIL:
            print("  -", f)
        return 1
    print(f"全部通过 [PASS] {PASS}/{PASS}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        httpd.shutdown()
