r"""画台 · 出图离线判据（第 4c 步，不联网、不花钱）

用法：  python tests\test_render_offline.py
数据根走 HUATAI_PROJECTS → D:\画台\.tmp-tests\render-projects，**绝不碰真实工程**。

判据：
 1 产物真的落盘：PNG 预览 + 1bit BMP 上机档（判据落在**盘上**，不在回执上）
 2 指标齐（暗部/亮部/墨点/均值）+ 9 格分区
 3 ★ **独立回读**：从 BMP 反算的黑点占比，与管线自报**对得上**（破"同源自证"）
 4 ★ **逐字节可复现**：同参数再出一版，PNG 与 BMP 的 sha256 完全一致
 5 ★ **旋钮累积**：第二版只改一个旋钮 ⇒ 上一版调过的旋钮**不被归零**
 6 非法旋钮 ⇒ 400（整轮拒，不许静默按默认出图）
 7 版本号递增（v1 → v2），历史真的追加
 8 ★ 出图**不许冲掉订单原有字段**（src_name / src_path 还在）
 9 账里留了一条 action 行，带"本次改的 / 生效的 / 回读"
10 界面能取到图（order.image 给出 data URL + sha256）
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = ROOT / ".tmp-tests" / "render-projects"
if TMP.exists():
    shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)
os.environ["HUATAI_PROJECTS"] = str(TMP)

from PIL import Image  # noqa: E402

from server import dispatch as D  # noqa: E402
from server import render as R  # noqa: E402
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


def main() -> int:
    print(f"数据根（隔离）= {TMP}")

    # 造一张**有高频细节**的图（细线+棋盘+边缘）：
    # 平滑渐变会让 USM（细节保留度）完全不起作用，从而得出"这个旋钮坏了"的假结论
    # —— 见 tests\test_knobs_effect.py 的说明。
    img = ROOT / ".tmp-tests" / "lian.png"
    im = Image.new("L", (240, 240), 175)
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    for i in range(0, 240, 6):
        d.line([(i, 0), (i, 240)], fill=50, width=1)
    for i in range(0, 240, 9):
        d.line([(0, i), (240, i)], fill=220, width=1)
    d.ellipse([50, 50, 190, 190], outline=18, width=4)
    d.ellipse([95, 95, 120, 120], fill=10)
    im.save(img)

    D.handle("projects.create", {"name": "出图测试"})
    code, body = D.handle("orders.create", {"project": "出图测试", "src": str(img)})
    oid = body["order_id"]
    ok(f"0.1 备好一单：{oid}")

    # ---- 第 1 版：给两个旋钮 ----
    code, r1 = D.handle("render.run", {
        "project": "出图测试", "order": oid,
        "knobs": {"素描感强度": 0.6, "整体明暗": 0.2},
    })
    eq(code, 201, "1.1 出图 201")
    png1, bmp1 = Path(r1["产物"]["png"]), Path(r1["产物"]["bmp"])
    eq(png1.is_file(), True, "1.2 ★ PNG 预览真的落盘")
    eq(bmp1.is_file(), True, "1.3 ★ 1bit BMP 上机档真的落盘")
    eq(png1.parent.name, "out", "1.4 产物落在这一单的 out\\ 里")
    eq(r1["版本"], "v1", "1.5 第一版是 v1")

    m = r1["指标"]
    eq(all(k in m for k in ("mean", "dark_pct", "light_pct", "ink_pct")), True, "2.1 指标齐（均值/暗部/亮部/墨点）")
    eq(len(r1["分区"]), 9, "2.2 9 格分区齐")
    eq(len(r1["像素"]), 2, "2.3 有像素尺寸")

    rb = r1["回读"]
    eq(rb["对得上"], True, "3.1 ★ 独立回读与管线自报对得上")
    eq(abs(rb["bmp里的黑点占比"] - rb["管线自报的黑点占比"]) <= R.INK_TOLERANCE_PCT, True,
       f"3.2 BMP 反算 {rb['bmp里的黑点占比']}% vs 自报 {rb['管线自报的黑点占比']}%（差 {rb['差']}）")
    eq(rb["模式"], "1", "3.3 回读确认上机档是 1bit 图")
    eq(rb["字节"] > 0, True, "3.4 BMP 真有内容")

    # ---- 第 2 版：同参数 ⇒ 应当逐字节一致 ----
    code, r2 = D.handle("render.run", {
        "project": "出图测试", "order": oid,
        "knobs": {"素描感强度": 0.6, "整体明暗": 0.2},
    })
    eq(code, 201, "4.1 同参数再出一版 201")
    eq(r2["版本"], "v2", "4.2 版本号递增到 v2")
    eq(r2["回读"]["sha256"], r1["回读"]["sha256"], "4.3 ★ 同参数的 BMP 逐字节一致（可复现）")
    eq(Path(r2["产物"]["png"]).read_bytes() == png1.read_bytes(), True, "4.4 ★ 同参数的 PNG 也逐字节一致")

    # ---- 第 3 版：只改一个旋钮 ⇒ 上一个旋钮不许被归零 ----
    code, r3 = D.handle("render.run", {
        "project": "出图测试", "order": oid, "knobs": {"细节保留度": 0.4},
    })
    eq(code, 201, "5.1 只改一个旋钮 201")
    eff = r3["旋钮生效"]
    eq(eff.get("素描感强度"), 0.6, "5.2 ★ 上一版的「素描感强度 0.6」还在（累积，没被归零）")
    eq(eff.get("整体明暗"), 0.2, "5.3 ★ 上一版的「整体明暗 0.2」也还在")
    eq(eff.get("细节保留度"), 0.4, "5.4 这一版改的那个旋钮生效了")
    line = [e for e in ST.read_transcript("出图测试", oid)["entries"] if e["kind"] == "action"][-1]
    eq(line["data"]["参数"]["本次改的"], {"细节保留度": 0.4}, "5.5 账里记着'本次改了什么'（意图）")
    eq(line["data"]["参数"]["生效的"].get("素描感强度"), 0.6, "5.6 账里也记着'这一版真正生效的全量'（状态）")

    # ---- 5.7+ ★ 缺口旋钮：写了不生效，但**必须喊出来**（不许假装生效）----
    code, r3b = D.handle("render.run", {
        "project": "出图测试", "order": oid, "knobs": {"背景纯净度": 0.3},
    })
    eq(code, 201, "5.7 写缺口旋钮本身不报错（名字是合法的）")
    eq(r3b["本次写了但没生效的旋钮"], ["背景纯净度"], "5.8 ★ 返回值里明确列出'写了没生效'的旋钮")
    eq(r3b["旋钮生效"].get("背景纯净度"), None, "5.9 它确实没进'生效'里（因为没实现）")
    line_b = [e for e in ST.read_transcript("出图测试", oid)["entries"] if e["kind"] == "action"][-1]
    eq("没实现" in line_b["text"] or "不生效" in line_b["text"], True, "5.10 ★ 账里也写明了（不静默）")

    # ---- 非法旋钮 ----
    code, b = D.handle("render.run", {"project": "出图测试", "order": oid, "knobs": {"不存在的旋钮": 1}})
    eq(code, 400, "6.1 ★ 未知旋钮 ⇒ 400（不许静默按默认出一版）")
    eq("旋钮" in (b.get("detail") or ""), True, "6.2 拒绝理由说得明白")
    code, b = D.handle("render.run", {"project": "出图测试", "order": oid, "knobs": {"整体明暗": 9}})
    eq(code, 400, "6.3 超范围 ⇒ 400")

    # ---- 历史与原有字段 ----
    data = ST.get_order("出图测试", oid)
    eq(data["n_ver"], 4, "7.1 session.json 里 n_ver = 4（出了四版）")
    eq(len(data["history"]), 4, "7.2 history 追加了 4 条（不是覆盖）")
    eq(data["history"][0]["ver"], 1, "7.3 第一条是 v1")
    eq(data["src_name"] == "lian.png", True, "8.1 ★ 出图没冲掉 src_name")
    eq(Path(data["src_path"]).is_file(), True, "8.2 ★ 出图没冲掉 src_path，原图还在")

    # ---- 账 ----
    entries = ST.read_transcript("出图测试", oid)["entries"]
    kinds = [e["kind"] for e in entries]
    eq(kinds.count("action"), 4, "9.1 每出一版都留了一条 action 行")
    last_action = [e for e in entries if e["kind"] == "action"][-1]
    eq("回读" in last_action["data"], True, "9.2 ★ 账里带着独立回读（BMP 反算）")

    # ---- 界面取图 ----
    code, im1 = D.handle("order.image", {"project": "出图测试", "order": oid, "which": "png"})
    eq(code, 200, "10.1 order.image 200")
    eq(im1["data_url"].startswith("data:image/png;base64,"), True, "10.2 给出可直接显示的 data URL")
    eq(im1["sha256"] == last_action["data"]["产物"]["png_sha256"], True,
       "10.3 ★ 界面拿到的图与账里记的是同一张（sha256 对得上）")
    eq(im1["版本"], 4, "10.4 默认给最新那一版")
    code, im1v = D.handle("order.image", {"project": "出图测试", "order": oid, "which": "png", "ver": 1})
    eq(im1v["sha256"] != im1["sha256"], True, "10.5 能按版本号取指定的那一版（且确实不是同一张）")
    eq(im1v["版本"], 1, "10.6 取回来的版本号也对")

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
