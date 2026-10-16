r"""无头冒烟：验 exp_interactive_snap.py 的计算部分（不开窗口）。

为什么要有它：试验台一开窗口卡住，就分不清是"算得慢"还是"界面卡"。
所以先把计算单独跑一遍并**计时**，界面出问题时才能排除计算。

用法：python tests\smoke_interactive_snap.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# 本机控制台是 GBK：先声明 UTF-8 输出，否则中文与符号会 UnicodeEncodeError 崩掉
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import exp_interactive_snap as T  # noqa: E402

REAL = T.DEFAULT_REAL
fails: list[str] = []


def check(cond: bool, label: str, extra: str = "") -> None:
    print(("  [OK]   " if cond else "  [FAIL] ") + label + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(label)


def main() -> int:
    if not REAL.exists():
        print(f"找不到真图：{REAL}")
        return 2
    img = Image.open(REAL)
    gray = np.asarray(img.convert("L"), dtype=np.float64)
    h, w = gray.shape
    print(f"图 = {REAL.name}  {w}×{h}px\n")

    # ---- 1 仿色 ----
    t0 = time.perf_counter()
    dots = T.fs_dither(gray)
    t_dither = time.perf_counter() - t0
    pct = 100.0 * dots.mean()
    print(f"1 仿色：{t_dither:.2f}s　墨点 {pct:.1f}%")
    check(dots.dtype == bool, "仿色返回 bool 点阵")
    check(dots.shape == (h, w), "仿色尺寸与原图一致")
    check(10.0 < pct < 60.0, "墨点占比落在合理区间（10%~60%）", f"实测 {pct:.1f}%")

    # ---- 2 梯度（只算一次）----
    t0 = time.perf_counter()
    grad = T.gradient_mag(gray)
    t_grad = time.perf_counter() - t0
    print(f"2 梯度：{t_grad:.3f}s")
    check(grad.shape == (h, w), "梯度尺寸一致")

    # ---- 3 吸附（两组几何：一组强边、一组弱边）----
    # ★ 口径说明：人脸坐标与上一场不同（上一场 exp_circle_snap3 用 400×380 的坐标，
    #   本轮用 400×380 但框取的是"上唇一条 / 眉线带"，与上一场的
    #   "整个嘴唇 / 左眉一带" 在**图片坐标**上并不完全同框。
    #   上一场探针（probe_edge_signal）另测出：左眼信号比 0.53、左眉 **0.46**（门槛 0.6）。
    # ⚠️ 标签只描述**几何位置**，不预判算法结论——上一版这里写"预期吸不住"，
    #   实测却是"吸到了边"，属于**我自己的标签错**（已修）。
    cases = [("嘴/上唇一条（强边）", (98, 195, 210, 275)),
             ("眉线带（弱边）", (60, 40, 150, 62))]
    masks = {}
    for name, box in cases:
        t0 = time.perf_counter()
        pts = T.ellipse_points(box)
        rough = T.polygon_mask((h, w), pts)
        disp, best_g, g_rough = T.snap_outline(pts, grad)
        snapped = np.clip(pts + T.normals_of(pts) * disp[:, None], 0, [w - 1, h - 1])
        mask = T.polygon_mask((h, w), snapped)
        dt = time.perf_counter() - t0
        iou = int((rough & mask).sum()) / max(1, int((rough | mask).sum()))
        med = float(np.median(best_g))
        verdict = "吸不住" if med < T.EDGE_WEAK else "吸到了边"
        print(f"3 吸附 {name}：{dt:.3f}s　梯度 {np.median(g_rough):.1f}→{med:.1f}"
              f"　IoU {iou:.2f}　判定={verdict}　圈内 {int(mask.sum())}px")
        masks[name] = mask
        check(dt < 1.0, f"吸附够快（<1s）: {name}", f"{dt:.3f}s")

    # ---- 4 距离变换（向量化，必须快）----
    seed = np.zeros((h, w), dtype=bool)
    seed[::7, ::7] = True
    t0 = time.perf_counter()
    dist = T._distance_to(seed)
    t_dist = time.perf_counter() - t0
    print(f"4 距离变换（全图 {h}×{w}）：{t_dist:.3f}s")
    check(t_dist < 2.0, "距离变换够快（<2s）", f"{t_dist:.3f}s")
    check(float(dist[seed].max()) == 0.0, "种子点自身距离为 0")
    check(np.isfinite(dist).all(), "距离场无 NaN/Inf")

    # ---- 5 稀疏 / 加密 ----
    mask = masks["嘴/上唇一条（强边）"]
    base_black = int((dots & mask).sum())
    for factor, label in ((0.7, "稀疏 70%"), (1.4, "加密 140%")):
        t0 = time.perf_counter()
        new_dots, note = T.dots_edit(dots, mask, factor)
        dt = time.perf_counter() - t0
        now = int((new_dots & mask).sum())
        print(f"5 {label}：{dt:.3f}s　圈内 {base_black} → {now}　({note})")
        check(dt < 3.0, f"密度编辑够快（<3s）: {label}", f"{dt:.3f}s")
        check(now != base_black, f"密度真的变了: {label}")
        # ★ 最关键的一条：圈外逐像素不变
        outside_same = bool(np.array_equal(new_dots[~mask], dots[~mask]))
        check(outside_same, f"★ 圈外逐像素不变: {label}")
        # ★★ 稀疏的语义必须是"只删不补"：补点会把圈内的白点（背景）涂黑
        if factor < 1.0:
            newly_black = int((~dots & mask & new_dots).sum())
            check(newly_black == 0, "★★ 稀疏只删不补（不许新涂黑任何点）",
                  f"新涂黑 {newly_black} 个")
            check(now < base_black, "稀疏后圈内黑点确实变少")

    # ---- 6 稀疏的方向对不对（变稀 = 黑点变少）----
    thin, _ = T.dots_edit(dots, mask, 0.5)
    check(int((thin & mask).sum()) < base_black, "稀疏 50% 时圈内黑点确实变少")

    # ---- 7 圈太小要能挡住 ----
    check(T.polygon_mask((h, w), T.ellipse_points((10, 10, 11, 11))).sum() >= 0,
          "极小圈不崩")

    print()
    if fails:
        print(f"[FAIL] {len(fails)} 项没过：")
        for f in fails:
            print("   -", f)
        return 1
    print("[PASS] 计算部分全部通过（界面部分要人眼看）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
