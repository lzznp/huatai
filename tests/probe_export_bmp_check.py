r"""探针：查 exp_smart_brush.py --selftest 里那条失败判据到底坏在哪。

背景：会话报告-20261016.md 说 7 项全绿，2026-10-16 重跑实测 1 项 FAIL：
  「★★导出：1bit 成品与内部点阵逐像素一致（没混进标记色）」

两种可能（必须分清，不许含糊）：
  A. 导出真的坏了（1bit BMP 与内部点阵不一致）—— 那是抓到一个真 bug；
  B. 判据自己写错了（例如 Image.open 读回 1bit BMP 后 convert("L") 的口径不对）。
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

dots = np.zeros((40, 60), dtype=bool)
dots[3:9, 5:20] = True
dots[20:25, 30:40] = True
print("内部点阵黑点数 =", int(dots.sum()), " 形状 =", dots.shape)

src = np.where(dots, 0, 255).astype(np.uint8)
print("喂给 PIL 的数组：唯一值 =", np.unique(src).tolist())

im = Image.fromarray(src).convert("1")
p = ROOT / ".tmp-tests" / "probe-export" / "probe.bmp"
p.parent.mkdir(parents=True, exist_ok=True)
im.save(p)

back = Image.open(p)
print("存盘/读回：mode =", back.mode, " size =", back.size)
b = np.asarray(back.convert("L")) < 128
print("读回后 convert(L)<128 的黑点数 =", int(b.sum()))
print("与内部点阵逐像素一致？", bool((b == dots).all()))
if b.shape != dots.shape:
    print("形状就不一样：", b.shape, "vs", dots.shape)
else:
    diff = int((b != dots).sum())
    print("不一样的点数 =", diff)
    if diff:
        ys, xs = np.nonzero(b != dots)
        print("前 10 个不一样的坐标(读回值/内部值) =",
              [(int(y), int(x), bool(b[y, x]), bool(dots[y, x])) for y, x in list(zip(ys, xs))[:10]])

print()
print("---- 换成 .point() 阈值化再存 ----")
im2 = Image.fromarray(src).point(lambda v: 255 if v > 127 else 0, mode="1")
p2 = p.with_name("probe2.bmp")
im2.save(p2)
b2 = np.asarray(Image.open(p2).convert("L")) < 128
print("逐像素一致？", bool((b2 == dots).all()), " 黑点数 =", int(b2.sum()))

print()
print("---- 用真上机档尺寸再验一次（787×748 全黑点阵，逼出非 8 倍数的行宽坑）----")
big = np.zeros((748, 787), dtype=bool)
big[::3, ::5] = True
im3 = Image.fromarray(np.where(big, 0, 255).astype(np.uint8)).convert("1")
p3 = p.with_name("probe3.bmp")
im3.save(p3)
b3 = np.asarray(Image.open(p3).convert("L")) < 128
print("逐像素一致？", bool((b3 == big).all()), " 黑点数 =", int(b3.sum()), "vs", int(big.sum()))
