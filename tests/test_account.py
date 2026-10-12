r"""画台 · 账层离线测试（工程 / 订单 / 对话流水）

用法：  python tests\test_account.py
数据根走 HUATAI_PROJECTS → D:\画台\.tmp-tests\account-projects，**绝不碰真实工程**。

判据（重点都在"盘上"，不在回执上）：
 1 投料：原图副本落盘、与原件**逐字节一致**、原件**没被改**
 2 源文件不是图片 → 400，且**明说读不了**（凭据来自 capabilities）
 3 工程不存在 / 源文件不存在 → 404（不偷偷新建、不静默）
 4 session.json 落盘 ⇒ 内核的订单列表能看见这张单
 5 out\ 目录建好（产物将来落这里）
 6 对话流水：★ **只追加**（旧行一字不动）、顺序正确、kind 必须合法
 7 流水三分：材料 / 用户 / 小助手 三类都落得住，读回来是分开的
 8 bad kind → 400（不许把"机器结论"当"人说的话"混进去）
 9 一单全貌：归档 + 流水 + 产物清单
10 同一工程连投两张图 → 两张不同的单
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = ROOT / ".tmp-tests" / "account-projects"
if TMP.exists():
    shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)
os.environ["HUATAI_PROJECTS"] = str(TMP)

from PIL import Image  # noqa: E402

from server import dispatch as D  # noqa: E402
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


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    print(f"数据根（隔离）= {TMP}")

    # 准备两张真图 + 一个假"资料"
    src_dir = ROOT / ".tmp-tests" / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    img1 = src_dir / "touxiang.png"
    img2 = src_dir / "test.jpg"
    Image.new("L", (24, 24), 200).save(img1)
    Image.new("L", (24, 24), 90).save(img2)
    fake = src_dir / "说明.pdf"
    fake.write_bytes(b"%PDF-1.4 not really")

    img1_sha_before = sha(img1)

    # 建工程
    code, body = D.handle("projects.create", {"name": "玻璃画测试"})
    eq(code, 201, "0.1 建工程 201")

    # 1 投料
    code, body = D.handle("orders.create", {"project": "玻璃画测试", "src": str(img1)})
    eq(code, 201, "1.1 投料建单 201")
    oid = body.get("order_id")
    eq(bool(oid), True, "1.2 拿到单号")
    d = ST.order_path("玻璃画测试", oid)
    copy_path = Path(body["src"])
    eq(copy_path.is_file(), True, "1.3 ★ 原图副本真的落盘：" + copy_path.name)
    eq(sha(copy_path), img1_sha_before, "1.4 ★ 副本与原件逐字节一致")
    eq(sha(img1), img1_sha_before, "1.5 ★ 原件没被改动（只进不改）")
    eq((d / "out").is_dir(), True, "1.6 out\\ 目录建好（产物将来落这里）")
    eq(copy_path.parent == d, True, "1.7 副本落在这一单的目录里（不是别处）")

    # 4 session.json
    eq((d / "session.json").is_file(), True, "4.1 session.json 落盘")
    lst = D.handle("orders.list", {"project": "玻璃画测试"})[1]["orders"]
    eq([o["order_id"] for o in lst], [oid], "4.2 内核的订单列表能看见这张单")
    eq(lst[0]["src_name"], "touxiang.png", "4.3 订单里记着原文件名")

    # 2 不是图片
    code, body = D.handle("orders.create", {"project": "玻璃画测试", "src": str(fake)})
    eq(code, 400, "2.1 非图片 → 400")
    eq("读不了" in (body.get("detail") or ""), True, "2.2 ★ 明说读不了（不是静默失败）")

    # 3 不存在
    code, body = D.handle("orders.create", {"project": "没有这个工程", "src": str(img1)})
    eq(code, 404, "3.1 工程不存在 → 404（不偷偷新建）")
    code, body = D.handle("orders.create", {"project": "玻璃画测试", "src": str(src_dir / "没有.png")})
    eq(code, 404, "3.2 源文件不存在 → 404")

    # 6/7 流水：只追加 + 三分
    before = ST.transcript_path("玻璃画测试", oid).read_text(encoding="utf-8")
    code, _ = D.handle("transcript.append", {
        "project": "玻璃画测试", "order": oid,
        "entry": {"kind": "user", "text": "把这个做成玻璃画"},
    })
    eq(code, 201, "6.1 追加用户话 201")
    code, _ = D.handle("transcript.append", {
        "project": "玻璃画测试", "order": oid,
        "entry": {"kind": "assistant", "text": "我猜你是想做玻璃画，是吗？"},
    })
    eq(code, 201, "6.2 追加小助手话 201")

    after = ST.transcript_path("玻璃画测试", oid).read_text(encoding="utf-8")
    eq(after.startswith(before), True, "6.3 ★ 只追加：旧内容一字不动（新内容是旧内容的延长）")

    tr = D.handle("transcript.read", {"project": "玻璃画测试", "order": oid})[1]
    kinds = [e["kind"] for e in tr["entries"]]
    eq(kinds, ["material", "user", "assistant"], "7.1 ★ 三分：材料 / 用户 / 小助手 各归各的行")
    eq(tr["entries"][1]["text"], "把这个做成玻璃画", "7.2 用户原话原样存住")
    eq(tr["坏行"], 0, "7.3 没有坏行")

    # 8 bad kind
    code, body = D.handle("transcript.append", {
        "project": "玻璃画测试", "order": oid,
        "entry": {"kind": "随便", "text": "x"},
    })
    eq(code, 400, "8.1 非法 kind → 400（不许混类）")
    eq(bool(body.get("error")), True, "8.2 带 error 文字")

    # 9 一单全貌
    code, detail = D.handle("order.detail", {"project": "玻璃画测试", "id": oid})
    eq(code, 200, "9.1 order.detail 200")
    eq(detail["订单"]["order_id"], oid, "9.2 全貌里有整单归档")
    eq(len(detail["流水"]), 3, "9.3 全貌里有 3 行流水")
    eq(detail["产物"], [], "9.4 还没出图，产物清单为空")

    # 10 同工程第二张图 → 第二张单
    code, body2 = D.handle("orders.create", {"project": "玻璃画测试", "src": str(img2)})
    eq(code, 201, "10.1 同工程投第二张图 201")
    eq(body2["order_id"] != oid, True, "10.2 ★ 是两张不同的单（不覆盖）")
    lst2 = D.handle("orders.list", {"project": "玻璃画测试"})[1]["orders"]
    eq(len(lst2), 2, "10.3 工程里现在有两张单")

    # 11 缺参数
    eq(D.handle("orders.create", {"project": "玻璃画测试"})[0], 400, "11.1 缺 src → 400")
    eq(D.handle("transcript.append", {"project": "玻璃画测试"})[0], 400, "11.2 缺 order → 400")
    eq(D.handle("order.detail", {"project": "玻璃画测试"})[0], 400, "11.3 缺 id → 400")

    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：")
        for f in FAIL:
            print("  -", f)
        return 1
    print(f"全部通过 [PASS] {PASS}/{PASS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
