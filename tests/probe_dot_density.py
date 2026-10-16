r"""探针：圈里有"眉毛 + 背景"两部分时，**点阵能不能把它们分开**？

用户在 2026-10-16 问的原话精神：
  "假如我选定了一个轮廓，这个里面一定有很大比例是眉毛的那部分，还有部分是背景部分，
   按位图来说，背景部分就是白的吧" ⇒ **助手凭什么知道我要改的是眉毛，不是旁边皮肤？**

本探针只量一件事（不下结论、不改代码）：
  在**点阵**层，"眉毛那一带"的黑点密度，与旁边"皮肤/额头"的黑点密度，**是不是分得开**。

为什么要量这个：上一场已知**灰度层**上眉毛信号很弱（信号比 0.46，门槛 0.6）。
但点阵是灰度→疏密之后的产物，**局部分布**可能比灰度差更好分。这是两件事，必须分开量。

口径：
  · 图 = src_one.jpeg（400×380），与上一场探针同一张
  · 点阵 = Floyd–Steinberg 仿色，阈值 127.5（与 kernel\image_lib\pipeline.py 同口径）
  · "局部密度" = 以该点为中心 (2r+1)² 窗内黑点占比
  · 带子坐标来自上一场 exp_circle_snap3.py 的同一组框（便于对照），但**只写几何位置、不预判结论**

用法：python tests\probe_dot_density.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# 控制台是 GBK：先声明 UTF-8 输出
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
R = 6          # 局部密度窗口半径 ⇒ 13×13 窗

# 几何带（只写位置，不预判）——取自上一场同一组坐标，便于与 exp_circle_snap3 对照
BANDS = [
    ("口腔/上唇一条", 98, 195, 210, 275),
    ("眉线带", 60, 40, 150, 62),
    ("眉上额头带", 60, 20, 150, 40),
    ("左上刘海带", 60, 0, 150, 18),
]


def local_density(dots: np.ndarray, r: int = R) -> np.ndarray:
    """局部黑点占比（积分图，一次算全图）。"""
    h, w = dots.shape
    ii = np.zeros((h + 1, w + 1), dtype=np.float64)
    np.cumsum(np.cumsum(dots.astype(np.float64), axis=0), axis=1, out=ii[1:, 1:])
    y0 = np.clip(np.arange(h) - r, 0, h)
    y1 = np.clip(np.arange(h) + r + 1, 0, h)
    x0 = np.clip(np.arange(w) - r, 0, w)
    x1 = np.clip(np.arange(w) + r + 1, 0, w)
    S = ii[np.ix_(y1, x1)] - ii[np.ix_(y0, x1)] - ii[np.ix_(y1, x0)] + ii[np.ix_(y0, x0)]
    N = np.outer(y1 - y0, x1 - x0).astype(np.float64)
    return S / np.maximum(N, 1.0)


def stats(a: np.ndarray) -> str:
    if a.size == 0:
        return "（空）"
    return (f"n={a.size:6d}  中位 {np.median(a) * 100:5.1f}%  "
            f"均值 {a.mean() * 100:5.1f}%  标准差 {a.std() * 100:5.1f}  "
            f"P25 {np.percentile(a, 25) * 100:5.1f}%  P75 {np.percentile(a, 75) * 100:5.1f}%")


def main() -> int:
    if not REAL.exists():
        print(f"找不到真图：{REAL}")
        return 2
    gray = np.asarray(Image.open(REAL).convert("L"), dtype=np.float64)
    h, w = gray.shape
    dots = T.fs_dither(gray)
    dens = local_density(dots, R)

    print(f"图 = {REAL.name}  {w}×{h}px")
    print(f"点阵 = Floyd–Steinberg（阈值 127.5，与内核同口径）  全图墨点 {100 * dots.mean():.1f}%")
    print(f"局部密度窗 = {2 * R + 1}×{2 * R + 1}\n")

    print("=" * 96)
    print("一、各几何带的『局部黑点密度』（只看黑点，不看灰度）")
    print("=" * 96)
    for name, x0, y0, x1, y1 in BANDS:
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        sub = dens[y0:y1, x0:x1].ravel()
        print(f"  {name:14s} ({x0},{y0})-({x1},{y1})  {stats(sub)}")

    print()
    print("=" * 96)
    print("二、★ 模拟用户『圈大了』：一个把眉毛和周围一起圈进来的大椭圆")
    print("=" * 96)
    # 故意圈大：把 眉线带 + 额头 + 一点脸颊 都圈进来
    box = (55, 30, 200, 130)
    pts = T.ellipse_points(box)
    mask = T.polygon_mask((h, w), pts)
    inside = dens[mask]
    outside = dens[~mask]
    print(f"  圈 = {box}（故意圈大）  圈内 {int(mask.sum())}px")
    print(f"  圈内局部密度：{stats(inside)}")
    print(f"  圈外局部密度：{stats(outside)}")

    # 以圈内密度分位数为界，把圈内点阵分成"密"和"稀"两层
    print()
    print("  —— 把『圈内』按局部密度自动分层（看眉毛落在哪一层）——")
    for q in (50, 70, 85):
        thr = float(np.percentile(inside, q))
        hi = mask & (dens >= thr)
        lo = mask & (dens < thr)
        hi_black = int((dots & hi).sum())
        lo_black = int((dots & lo).sum())
        hi_pct = 100.0 * (dots & hi).sum() / max(1, int(hi.sum()))
        lo_pct = 100.0 * (dots & lo).sum() / max(1, int(lo.sum()))
        print(f"    分位 {q}% 阈值 {thr * 100:5.1f}%  →  密层 {int(hi.sum()):6d}px "
              f"黑点 {hi_pct:5.1f}%（{hi_black:5d} 个） | 稀层 {int(lo.sum()):6d}px "
              f"黑点 {lo_pct:5.1f}%（{lo_black:5d} 个）")

    print()
    print("=" * 96)
    print("三、『只改黑点』到底会不会误伤背景？（思辨的核心）")
    print("=" * 96)
    base_black = int((dots & mask).sum())
    print(f"  圈内像素 {int(mask.sum())}，其中**黑点 {base_black}**"
          f"（{100.0 * base_black / max(1, int(mask.sum())):.1f}%），白点 {int(mask.sum()) - base_black}")
    print(f"  ⇒ 如果只对『圈内黑点』做稀疏，那么圈内的**白点（背景）一个都不会被动**。")
    # 验一下：稀疏 70% 之后，圈内白点是否一个没变
    thin, _ = T.dots_edit(dots, mask, 0.7)
    became_black = int((~dots & mask & thin).sum())
    became_white = int((dots & mask & ~thin).sum())
    print(f"  实测（稀疏 70%，只删不补）：变黑的点 {became_black} 个，变白的点 {became_white} 个")
    print(f"  ⇒ 变黑的点 {became_black} = 0 说明**只删不补**：背景只会更空，绝不会被涂黑。")

    print()
    print("=" * 96)
    print("四、结论只写给眼睛：把上面这些带子画出来（下一步做图给人看）")
    print("=" * 96)
    print("  ★ 口径提醒（决策 #29）：以上都是数字，**要下判断必须画出来给人眼复核**。")
    print("  本探针只给数；要不要据此改做法，等图出来再说。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
