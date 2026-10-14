r"""只查一件事：距离变换自检里那 18.33px 到底出在谁身上。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\画台\tests")))
import numpy as np  # noqa: E402

from exp_region_edit import distance_to_mask  # noqa: E402

small = np.zeros((30, 40), dtype=bool)
small[10:20, 15:28] = True

# 参考实现：到 **mask 像素** 的精确欧氏距离（用 mask 像素集合）
my, mx = np.where(small)
d_ref = np.full((30, 40), 0.0)
for y in range(30):
    for x in range(40):
        if not small[y, x]:
            d_ref[y, x] = np.min(np.hypot(my - y, mx - x))

# 脚本里那版错误参考：到 **紧邻边界像素** 的距离
by, bx = np.where(~small)
d_border = np.full((30, 40), 0.0)
for y in range(30):
    for x in range(40):
        if not small[y, x]:
            d_border[y, x] = np.min(np.hypot(by - y, bx - x))

d_mine = distance_to_mask(small)

print("我和【到 mask 像素】的差：最大", round(float(np.abs(d_mine[~small] - d_ref[~small]).max()), 3))
print("我和【到边界 pixel】的差：最大", round(float(np.abs(d_mine[~small] - d_border[~small]).max()), 3))
print("两个参考之间的差：最大", round(float(np.abs(d_ref[~small] - d_border[~small]).max()), 3))
print()
print("mask 内像素数 =", int(small.sum()), " 非 mask 像素数 =", int((~small).sum()))
print("mask 行范围", np.where(small.any(axis=1))[0].min(), "-", np.where(small.any(axis=1))[0].max(),
      "列范围", np.where(small.any(axis=0))[0].min(), "-", np.where(small.any(axis=0))[0].max())

# 挑几个点看具体数值
for (y, x) in [(0, 0), (5, 5), (10, 5), (12, 20), (25, 35), (29, 39)]:
    print(f"  ({y:2d},{x:2d}) 我={d_mine[y, x]:6.2f}  到mask={d_ref[y, x]:6.2f}  到边界={d_border[y, x]:6.2f}")
