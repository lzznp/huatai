r"""画台 · 版本对比与九宫格标签（离线判据，不联网、不花钱）

用途：把"两次出图都能看见、方便对比"和"格号与账对得上"变成**可自动验的判据**。
对应 `待完善.md` 的 A（多版对比）与用户 2026-10-13 要的"九宫格标签"。

判据：
  1 同一单能按版本号取到**不同**的两版，且回执版本号正确
  2 ★ 界面拿到的 sha256 与账里记的**逐字节一致**（图和账是同一张）
  3 ★ 每版都在账里留下自己的 `png_sha256` 与 9 格指标（**逐版**，不是只有最新那版）
  4 9 格数据自洽：9 格、4 个键齐、**面积权重**回算 ≈ 整图墨点
  5 界面上画的格号 = 账里的分区口径（行优先 0=左上）
  6 ★ **旧版账兼容**：加这两项之前出的版本（`history` 里没有 zones/png_sha256）读起来不许炸
  7 要点卡里带上 9 格数字网格（小助手核对"哪一格更暗"的凭据）

用法：  python tests\test_version_compare.py
数据根：HUATAI_PROJECTS → D:\画台\.tmp-tests\compare-projects（**不碰真实工程**）
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = ROOT / ".tmp-tests" / "compare-projects"
if TMP.exists():
    shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)
os.environ["HUATAI_PROJECTS"] = str(TMP)

from PIL import Image, ImageDraw  # noqa: E402

from server import dispatch as D  # noqa: E402
from server import intent as INTENT  # noqa: E402
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


def near(a: float, b: float, tol: float, msg: str) -> None:
    if abs(a - b) <= tol:
        ok(f"{msg}（{a} vs {b}，容差 {tol}）")
    else:
        FAIL.append(f"{msg} —— {a} vs {b}，超容差 {tol}")
        print(f"[FAIL] {msg} —— {a} vs {b}，超容差 {tol}")


def main() -> int:
    print(f"数据根（隔离）= {TMP}")

    img = ROOT / ".tmp-tests" / "compare.png"
    im = Image.new("L", (240, 240), 170)
    d = ImageDraw.Draw(im)
    for i in range(0, 240, 6):
        d.line([(i, 0), (i, 240)], fill=45, width=1)
    d.ellipse([50, 50, 190, 190], outline=15, width=4)
    im.save(img)

    D.handle("projects.create", {"name": "对比测试"})
    code, body = D.handle("orders.create", {"project": "对比测试", "src": str(img)})
    oid = body["order_id"]
    ok(f"0.1 备好一单：{oid}")

    code, r1 = D.handle("render.run", {"project": "对比测试", "order": oid, "knobs": {"素描感强度": 0.6}})
    eq(code, 201, "0.2 出 v1")
    code, r2 = D.handle("render.run", {"project": "对比测试", "order": oid, "knobs": {"整体明暗": 0.3}})
    eq(code, 201, "0.3 出 v2（只改一个旋钮 ⇒ 累积语义）")

    # ---- 1 两版都能取到、而且不是同一张 ----
    code, im2 = D.handle("order.image", {"project": "对比测试", "order": oid, "which": "png"})
    code1, im1 = D.handle("order.image", {"project": "对比测试", "order": oid, "which": "png", "ver": 1})
    eq(code, 200, "1.1 不给版本 ⇒ 200（取最新）")
    eq(im2["版本"], 2, "1.2 不给版本取回来的是 v2")
    eq(code1, 200, "1.3 指定 ver=1 ⇒ 200")
    eq(im1["版本"], 1, "1.4 取回来的版本号是 1")
    eq(im1["sha256"] != im2["sha256"], True, "1.5 ★ 两版是**不同**的图（不是同一张反复显示）")
    eq(Path(im1["路径"]).name != Path(im2["路径"]).name, True, "1.6 落盘的是两个不同文件")

    # ---- 2 图和账对得上 ----
    data = ST.get_order("对比测试", oid)
    hist = data["history"]
    eq(len(hist), 2, "2.1 账里 history 有两版")
    eq(im1["sha256"], hist[0]["png_sha256"], "2.2 ★ v1：界面拿到的 sha256 = 账里记的 png_sha256")
    eq(im2["sha256"], hist[1]["png_sha256"], "2.3 ★ v2：同上")
    eq(im1["sha256"] == hist[0]["png_sha256"] and hist[0]["png_sha256"] != hist[1]["png_sha256"],
       True, "2.4 ★ 逐版各记各的（不是全指向最新那一版）")

    # ---- 3 每版都有 9 格 ----
    for i, h in enumerate(hist, start=1):
        eq(isinstance(h.get("zones"), list) and len(h["zones"]) == 9, True, f"3.{i} v{i} 在账里留了 9 格指标")
        eq(all(k in h["zones"][0] for k in ("mean", "dark_pct", "light_pct", "ink_pct")), True,
           f"3.{i}b v{i} 的每格带齐 4 个键")

    # ---- 4 9 格自洽（面积加权 ≈ 整图）----
    zones = hist[1]["zones"]
    rep = data.get("last_report") or {}
    pixels = rep.get("pixels") or [0, 0]
    w, h_ = int(pixels[0]), int(pixels[1])
    xs = [(c * w // 3, (c + 1) * w // 3) for c in range(3)]
    ys = [(r * h_ // 3, (r + 1) * h_ // 3) for r in range(3)]
    areas, weighted = [], 0.0
    for r in range(3):
        for c in range(3):
            ys0, ys1 = ys[r]
            xs0, xs1 = xs[c]
            a = (ys1 - ys0) * (xs1 - xs0)
            areas.append(a)
            weighted += a * zones[r * 3 + c]["ink_pct"]
    eq(max(areas) - min(areas) <= max(w, h_), True, "4.1 9 格面积基本相等（差 ≤ 一边长）")
    global_ink = float((rep.get("metrics") or {}).get("ink_pct") or 0)
    near(weighted / sum(areas), global_ink, 0.2, "4.2 ★ 9 格墨点按面积加权 ≈ 整图墨点（口径一致）")
    eq(all(0.0 <= z["ink_pct"] <= 100.0 for z in zones), True, "4.3 每格墨点都在 0~100 之间")

    # ---- 5 要点卡里的格号与分区口径一致 ----
    txt = INTENT.format_zone_grid(zones)
    eq(txt.count("墨点"), 9, "5.1 9 格都渲染进了要点卡")
    eq(all(f"{i}:墨点" in txt for i in range(9)), True, "5.2 格号 0~8 齐（行优先 0=左上）")
    eq(f"4:墨点{zones[4]['ink_pct']}%" in txt, True, "5.3 正中格（4）的值与账里一致")

    brief = INTENT.render_prev_brief({"n_ver": 2, "last_report": rep})
    eq("9 格实测" in brief, True, "5.4 ★ 要点卡里带上了 9 格（小助手核对'哪一格更暗'的凭据）")

    # ---- 6 旧版账兼容（加这两项之前出的版本）----
    old = {
        "n_ver": 1,
        "last_report": {"metrics": {"dark_pct": 2.0, "light_pct": 60.0, "ink_pct": 18.0}, "knobs_applied": {}},
    }
    try:
        t = INTENT.render_prev_brief(old)
        eq("9 格" in t and "没有 9 格" in t, True, "6.1 ★ 旧账（没有 zones）不许炸，且如实说明'没有数据'")
    except Exception as e:  # noqa: BLE001
        eq(False, True, f"6.1 ★ 旧账不许炸 —— 实得 {type(e).__name__}: {e}")
    eq(INTENT.format_zone_grid(None).startswith("（这一单还没有"), True, "6.2 zones=None 时给的是说明而不是异常")
    eq(INTENT.format_zone_grid([{"ink_pct": 1}]).startswith("（这一单还没有"), True, "6.3 格数不足 9 时同样按'没数据'处理")

    # ---- 7 版本列表（界面版本条的数据来源）----
    code, det = D.handle("order.detail", {"project": "对比测试", "id": oid})
    eq(code, 200, "7.1 order.detail 200")
    hv = det["订单"]["history"]
    eq([x["ver"] for x in hv], [1, 2], "7.2 版本条能按顺序拿到 v1/v2")
    eq(all(Path(x["img"]).is_file() for x in hv), True, "7.3 ★ 每一版的图都还在盘上（对比时不会缺图）")
    eq(all(x.get("png_sha256") for x in hv), True, "7.4 每一版都带 sha256（界面可逐版核对）")

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
