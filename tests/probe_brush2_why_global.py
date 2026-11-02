r"""探针：「只对包围框重仿色」为什么**不可能**与全图重仿一致（可重跑，1 分钟出结论）。

════════════════════════════════════════════════════════════════════
为什么留这份探针（2026-10-17，参谋长在实现取向 B 时绕了一大圈，全是因为这条）：
  "在灰度层减淡 → **只对选区重仿色**" —— 直觉上，只要给框留一点余量、把框外的灰度钉回基线，
  框内结果就该与全图重仿一致。**错。** 误差扩散（Floyd–Steinberg）的误差 = 灰度 − 决策，
  它既取决于**框外已走过的像素的灰度**，也取决于那些像素的**决策**；而"框外决策"又取决于
  更早的像素……于是：
    · 留 2px：差 2178 点；
    · 留 4 行 / 20px 带 / 只留上带：差 1939~4100 点；
    · 拿"当前点阵"当种子：**它反而会把框内也钉死**，一行都改不了（实测"删除 0"）。
  ⇒ 结论：**要么整图重仿，要么接受"与全图重仿不一致"**。本项目的取向 B 选了前者
    （松手时全图重仿一次，实测 0.73s；换取"已写区 = 全图重仿 + 只删不补"**按定义成立**）。
  实测差异随场景在 **1500~4100 点**之间浮动（"已写区"只有两千多点，也就是一半以上对不上）；
  精确数不必记，记结论：**它不可能为 0**。

本探针把上面四句变成可复现的数字，防止后来人（或以后的自己）再绕一圈。
════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import numpy as np  # noqa: E402
import exp_smart_brush2 as B  # noqa: E402
from exp_interactive_snap import fs_dither  # noqa: E402
from exp_interactive_snap2 import DEF_SRC, DEF_BMP  # noqa: E402

app = B.BrushCore(DEF_SRC, DEF_BMP, verbose=True)
# 一笔：在密区（头发）斜扫
app.stroke_begin(radius=20, strength=60)
for i in range(-2, 3):
    app.stamp(640 + i * 6, 330 + i * 6)
s = app.cur
app.apply_gray(s)                       # 只落灰度（点阵不动，与实现一致）

full = fs_dither(app.gray)              # 全图重仿（"标准答案"）
blk = s["all_blk"]
ys, xs = np.nonzero(blk)
y0t, y1t = int(ys.min()), int(ys.max()) + 1
x0t, x1t = int(xs.min()), int(xs.max()) + 1
gate = app.gate_hard()
wrote = blk & s["dict"] & gate
print(f"\n改动框 y[{y0t},{y1t}) x[{x0t},{x1t})；已写区 {int(wrote.sum())} 像素\n")

delta = app.gray - app.gray0


def local(margin_y: int, margin_x: int, seed_mode: str) -> np.ndarray:
    """只在框附近重仿：框 + 余量；框外灰度钉回基线；引子按 seed_mode 处理。"""
    y0 = max(0, y0t - margin_y); x0 = max(0, x0t - margin_x)
    y1, x1 = y1t, x1t
    g = app.gray0[y0:y1, x0:x1].copy()
    loc = delta[y0:y1, x0:x1] != 0
    g[loc] = app.gray[y0:y1, x0:x1][loc]
    seed = np.zeros(g.shape, dtype=bool)
    if seed_mode == "top-band":                       # 只喂上带（整宽）
        ny = y0t - y0
        if ny:
            seed[:ny, :] = app.dots[y0:y0t, x0:x1]
    elif seed_mode == "all-current":                  # 整块喂当前点阵（= 全钉死）
        seed[:] = app.dots[y0:y1, x0:x1]
    elif seed_mode == "margin":                       # 框外一圈喂当前点阵（最讲究的做法）
        ny, nx = y0t - y0, x0t - x0
        if ny:
            seed[:ny, :] = app.dots[y0:y0t, x0:x1]
        if nx:
            seed[ny:, :nx] = app.dots[y0t:y1, x0:x0t]
    d = fs_dither(g, seed=seed)
    out = full.copy()
    m = np.zeros((app.h, app.w), dtype=bool)
    m[y0:y1, x0:x1] = True
    out[m] = d.ravel()
    return out


print("【1】几乎不留余量（2px）——直觉做法")
out = local(2, 2, "none")
print(f"    已写区与全图重仿不一致：{int((out[wrote] != full[wrote]).sum())} / {int(wrote.sum())}")

print("【2】留一点余量（4 行 / 20px 带）——上一层直觉")
for my, mx in ((4, 4), (20, 20)):
    out = local(my, mx, "margin")
    print(f"    余量 {my:>2}px + 框外喂当前点阵：不一致 "
          f"{int((out[wrote] != full[wrote]).sum())} / {int(wrote.sum())}")

print("【3】把引子（上带）的**决策**也喂进去 —— 再上一层直觉")
out = local(4, 8, "top-band")
print(f"    上带当引子：不一致 {int((out[wrote] != full[wrote]).sum())} / {int(wrote.sum())}")

print("【4】整块都喂当前点阵 —— 最省事但会钉死")
out = local(4, 8, "all-current")
print(f"    整块钉死：不一致 {int((out[wrote] != full[wrote]).sum())} / {int(wrote.sum())}"
      f"　★注意：这一项的'没改'后果是**框内一点都没变**（等于没刷）")

print("\n【5】按定义来（本项目的做法）：全图重仿 + 只删不补")
cand = app.dots_base & ~full
print(f"    已写区与候选不一致：{int((cand[wrote] != cand[wrote]).sum())}（同一条式子的同一侧，恒为 0）")
print("    ⇒ 所以本项目改成『松手时全图重仿一次』，代价 0.73s/笔（本机）。")
print("\n【结论】局部重仿不是'留多少余量'的问题，是**原理上做不到**：")
print("        FS 的误差同时依赖框外像素的灰度与决策，而决策又依赖更早的像素。")
print("        要么整图重仿，要么接受不一致 —— 没有第三种。")
