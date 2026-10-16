r"""无头冒烟：验 exp_interactive_snap2.py（灰度减淡→仿色）的计算部分。

★ 本冒烟专门盯住 v1 犯过的那个错：
  **必须真的加载上机档 BMP**（787×748、墨点 24.0%），而不是拿原图自仿色（那会得到 57.9%）。

用法：python tests\smoke_interactive_snap2.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import exp_interactive_snap2 as T2  # noqa: E402
from exp_interactive_snap import fs_dither, gradient_mag, ellipse_points, polygon_mask, snap_outline, normals_of  # noqa: E402

fails: list[str] = []


def check(cond: bool, label: str, extra: str = "") -> None:
    print(("  [OK]   " if cond else "  [FAIL] ") + label + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(label)


def main() -> int:
    src, bmp = T2.DEF_SRC, T2.DEF_BMP
    if not src.exists():
        print(f"找不到原图：{src}"); return 2

    # ---- 1 上机档真的加载了（v1 的错就出在这儿）----
    print(f"原图   = {src.name}  {Image.open(src).size}")
    if bmp.exists():
        b = Image.open(bmp)
        print(f"上机档 = {bmp.name}  {b.size}  mode={b.mode}")
        check(b.size == (787, 748), "上机档尺寸是 787×748", str(b.size))
    else:
        check(False, "上机档存在", str(bmp))

    # ---- 2 复刻 TestBed2 的加载逻辑 ----
    s = Image.open(src).convert("L")
    sc = T2.RENDER_LONG / max(s.size)
    small = s.resize((round(s.width * sc), round(s.height * sc)), Image.LANCZOS)
    gray = np.asarray(small, dtype=np.float64)
    h, w = gray.shape
    print(f"\n渲染到 {w}×{h}")
    check(0.9 < w / h < 1.3, "宽高比正常（没被拉变形）", f"{w/h:.3f}")

    dots_real = np.asarray(Image.open(bmp).convert("L").resize((w, h), Image.NEAREST)) < 128
    ink_real = 100.0 * dots_real.mean()
    print(f"真上机档墨点 = {ink_real:.1f}%（真品 v2 实测 24.0%）")
    check(abs(ink_real - 24.0) < 2.0, "加载后的墨点与真品一致（±2 个点）", f"{ink_real:.1f}%")

    dots_self = fs_dither(gray)
    ink_self = 100.0 * dots_self.mean()
    print(f"（对照）自仿色墨点 = {ink_self:.1f}%")
    check(abs(ink_self - ink_real) > 5.0,
          "★ 自仿色与真上机档**明显不同**（证实 v1 的错）",
          f"自仿 {ink_self:.1f}% vs 真品 {ink_real:.1f}%")

    # ---- 2b ★ 灰度重标定：零改动要能复现成品 ----
    gray_cal, cal = T2.calibrate_gray_from_bitmap(gray, dots_real)
    ink_cal = 100.0 * fs_dither(gray_cal).mean()
    print(f"\n★ 灰度重标定（从点阵反推）：原图直接仿色 {cal['ink_raw'] * 100:.1f}% → "
          f"重标定后 {ink_cal:.1f}%（真上机档 {cal['ink_want'] * 100:.1f}%）")
    check(abs(ink_cal - ink_real) < 3.0,
          "★ 重标定后零改动能复现成品墨点（±3 个点）",
          f"{ink_cal:.1f}% vs {ink_real:.1f}%")
    check(abs(cal["ink_raw"] - ink_real) > 10.0,
          "★ 未重标定时确实差很多（证明这一步不是多余的）",
          f"{cal['ink_raw'] * 100:.1f}% vs {ink_real:.1f}%")

    # ---- 3 基线用真上机档：圈选 + 吸附（梯度用**重标定后**的灰度）----
    grad = gradient_mag(gray_cal)
    box = (185, 45, 265, 85)      # 右眉（图5 人眼核过）
    t0 = time.perf_counter()
    pts = ellipse_points(box)
    rough = polygon_mask((h, w), pts)
    disp, best_g, g_rough = snap_outline(pts, grad)
    snapped = np.clip(pts + normals_of(pts) * disp[:, None], 0, [w - 1, h - 1])
    mask = polygon_mask((h, w), snapped)
    dt = time.perf_counter() - t0
    print(f"\n吸附（右眉）：{dt:.3f}s  梯度 {np.median(g_rough):.1f}→{np.median(best_g):.1f}"
          f"  圈内 {int(mask.sum())}px")
    check(dt < 1.0, "吸附够快（<1s）", f"{dt:.3f}s")

    # ---- 4 ★ 灰度减淡 → 仿色：圈外到底动没动？（这才是真问题）----
    # ★ 基线必须与试验台一致 = **重标定后**的灰度（gray_cal）与**真上机档**（dots_real）。
    #   第一次写这段时错拿"自仿色"当圈外基准，必然报 FAIL —— 那是测试写错（已修）。
    # ★★ 改成真基线后暴露了**真问题**：Floyd–Steinberg 是**全局**误差扩散，
    #   在选区内改灰度，误差会顺扫描方向往圈外泄。所以要**量出泄多远**，
    #   并验证 `_redither_inplace` 的"贴回"能不能把它清干净。
    soft = T2.TestBed2._feather(mask, max(1.0, min(box[2] - box[0], box[3] - box[1]) * 0.02))

    def spread_dist(changed: np.ndarray) -> int:
        """被改动的点里，离选区最近的有多远（像素，切比雪夫距离到选区包围框）。"""
        ys, xs = np.nonzero(changed)
        if ys.size == 0:
            return 0
        my, mx = np.nonzero(mask)
        y0, y1, x0, x1 = my.min(), my.max(), mx.min(), mx.max()
        dy = np.maximum(np.maximum(y0 - ys, ys - y1), 0)
        dx = np.maximum(np.maximum(x0 - xs, xs - x1), 0)
        return int(np.maximum(dy, dx).max())

    for delta in (-40, +40):
        g2 = np.clip(gray_cal + float(delta) * soft, 0, 255)
        # ★ 与试验台同一条路：重新仿色，但选区外的点阵贴回基线
        d2 = T2.TestBed2._redither_inplace(g2, dots_real, soft, mask)
        changed_gray = int((g2[~mask] != gray_cal[~mask]).sum())
        changed_dots = int((d2[~mask] != dots_real[~mask]).sum())
        same_gray = changed_gray == 0
        inb = int((dots_real & mask).sum()); ina = int((d2 & mask).sum())
        # 先量"不做贴回"时泄多远，作为对照（证明这一步不是多余的）
        d_raw = fs_dither(g2)
        raw_out = int((d_raw[~mask] != dots_real[~mask]).sum())
        far_raw = spread_dist((d_raw != dots_real) & (~mask))
        print(f"  灰度 {delta:+d}：圈内黑点 {inb} → {ina}"
              f"（{100.0 * ina / max(1, inb):.0f}%）　全图墨点 {100.0 * d2.mean():.1f}%")
        print(f"          圈外（贴回后）：灰度变 {changed_gray} 点，点阵变 {changed_dots} 点")
        print(f"          圈外（不贴回）：点阵会变 {raw_out} 点，最远泄出 {far_raw}px  ← 这就是那笔外溢账")
        check(same_gray, f"★ 圈外灰度逐像素不变（Δ={delta:+d}）", f"变了 {changed_gray}")
        check(changed_dots == 0, f"★★ 圈外点阵逐像素不变（Δ={delta:+d}）",
              f"变了 {changed_dots}")
        if delta < 0:
            # ★ 口径：PIL 灰度 0=黑 255=白。Δ<0 是把灰度往下压 = **加深** = 黑点变多。
            check(ina > inb, f"加深（Δ={delta:+d}）⇒ 圈内黑点变多", f"{inb}→{ina}")
        else:
            # Δ>0 是把灰度往上抬 = **减淡（变白）** = 黑点变少。
            check(ina < inb, f"减淡（Δ={delta:+d}）⇒ 圈内黑点变少", f"{inb}→{ina}")

    # ---- 5 羽化要平滑（不能是硬台阶）----
    check(0.0 <= soft.min() and soft.max() <= 1.0, "软掩膜值域在 0~1")
    check(soft[mask].mean() > 0.8, "选区内部权重接近 1", f"{soft[mask].mean():.2f}")
    edge_band = (soft > 0.05) & (soft < 0.95)
    check(int(edge_band.sum()) > 0, "存在羽化过渡带（不是硬边）",
          f"{int(edge_band.sum())}px")

    print()
    if fails:
        print(f"[FAIL] {len(fails)} 项没过：")
        for f in fails:
            print("   -", f)
        return 1
    print("[PASS] v2 计算部分全部通过（界面手感要人眼看）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
