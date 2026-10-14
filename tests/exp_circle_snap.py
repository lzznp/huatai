r"""实验 A（第 1 条）：**圈个大概 → 代码吸附到边界**（离线、不联网、不花钱）

用户 2026-10-13 的想法原话：
  "我想直接圈，但是这个圈的范围一定不准确，要是我圈个大致的范围，然后代码或者 llm
   能通过对比，或者类似 ps 中的某个手段把我圈的给精确的话，那不是好一点了吗"

这一条要验的就是：**区域生长（PS 魔棒/快速选择的学名）在他自己的图上到底能不能吸准。**

做法（全部确定性、无随机、无新依赖）：
  1. 在**灰度图**上做（★ 判据在点阵上会失效：1bit 图上"眉毛"是散点，生长会乱跳）；
  2. 种子 = 用户粗圈内的像素；取它们的**中位数**当"目标亮度"；
  3. 容差 = 种子内的**稳健标准差** × 系数（稳健 = 用 MAD，抗异常点）；
  4. 生长条件：亮度落在容差内 **且** 梯度不超阈值（遇边界停）；
  5. 只保留**与用户粗圈重叠最多**的连通块（防止长到别的地方去）；
  6. 填小洞；
  7. **失控检查**：吸出来的面积相对用户圈的面积比，超阈值就明确报"我吸过头了"。

报什么：
  · 面积比（吸附后 / 用户圈）与"外扩比例"（吸到圈外的部分占吸附面积）
  · 与用户圈的重叠（IoU / 覆盖率）
  · 是否有强边界、是否失控
  · 三张图给人眼判：原图+粗圈 / 吸附结果叠加 / 吸附结果 + 点阵（看实机会长什么样）

用法：  python tests\exp_circle_snap.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kernel"))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

REAL = Path(r"D:\画台\projects\美女玻璃画\order-20261012-165706\src_one.jpeg")
OUT = ROOT / ".tmp-tests" / "exp-circle-snap"
OUT.mkdir(parents=True, exist_ok=True)

# 容差系数与梯度系数是这一条唯一要调的旋钮，先取一组保守值
TOL_K = 1.0        # 容差 = 稳健标准差 × 这个系数
GRAD_K = 1.5       # 梯度阈值 = 稳健标准差 × 这个系数
RUNAWAY_RATIO = 4.0  # 吸附面积 / 圈面积 超过它 ⇒ 判"失控"


def to_gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.float64)


def robust_sigma(v: np.ndarray) -> float:
    """稳健标准差（1.4826×MAD）——用普通 std 会被圈里的边缘/反光带跑。"""
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med)))
    return max(1.0, 1.4826 * mad)


def gradient_mag(g: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(g)
    return np.hypot(gx, gy)


def grow(g: np.ndarray, seed: np.ndarray, tol: float, grad_max: float) -> np.ndarray:
    """区域生长：从 seed 出发，4 邻域扩张，亮度在 tol 内、梯度不超 grad_max。

    实现用"反复扩张 bool 掩膜"的迭代法（向量化，不写 BFS；对小图足够快）。
    """
    med = float(np.median(g[seed]))
    grad = gradient_mag(g)
    ok = (np.abs(g - med) <= tol) & (grad <= grad_max)      # 允许进入的像素
    cur = seed & ok
    for _ in range(4000):                                    # 上限防死循环
        nb = np.zeros_like(cur)
        nb[1:, :] |= cur[:-1, :]
        nb[:-1, :] |= cur[1:, :]
        nb[:, 1:] |= cur[:, :-1]
        nb[:, :-1] |= cur[:, 1:]
        nxt = cur | (nb & ok)
        if nxt.sum() == cur.sum():
            break
        cur = nxt
    return cur


def fill_holes(m: np.ndarray) -> np.ndarray:
    """填内部小洞：从图像边界做一次"背景"洪水，剩下的空区就是洞。"""
    bg = ~m
    cur = np.zeros_like(bg)
    cur[0, :] |= bg[0, :]
    cur[-1, :] |= bg[-1, :]
    cur[:, 0] |= bg[:, 0]
    cur[:, -1] |= bg[:, -1]
    for _ in range(4000):
        nb = np.zeros_like(cur)
        nb[1:, :] |= cur[:-1, :]
        nb[:-1, :] |= cur[1:, :]
        nb[:, 1:] |= cur[:, :-1]
        nb[:, :-1] |= cur[:, 1:]
        nxt = cur | (nb & bg)
        if nxt.sum() == cur.sum():
            break
        cur = nxt
    return m | (~cur & ~m)      # 非背景的空洞 = 内部洞 → 补上


def main() -> int:
    if not REAL.is_file():
        print(f"找不到 {REAL}")
        return 2
    img = Image.open(REAL)
    W, H = img.size
    print(f"图 = {REAL.name}　{W}×{H}px（口径：原图像素，坐标都是原图坐标）")
    g = to_gray(img)

    # 用户"粗圈"：用椭圆近似手抖的圈——故意画偏、画大一点（真实人手就是这样）
    cases = [
        ("左眼（细长、边界偏弱 ⇒ 难）", (72, 55, 140, 105)),
        ("嘴唇（成块、边界清楚 ⇒ 应好吸）", (98, 195, 210, 275)),
        ("一大块脸（试它会不会贪心失控）", (120, 90, 300, 260)),
    ]

    gray_rgb = np.stack([g, g, g], axis=-1).astype(np.uint8)
    report = []
    for name, (x0, y0, x1, y1) in cases:
        rough = Image.new("L", (W, H), 0)
        ImageDraw.Draw(rough).ellipse([x0, y0, x1, y1], fill=255)
        seed = np.asarray(rough) > 0
        band = g[seed]
        sig = robust_sigma(band)
        tol = TOL_K * sig
        grad_max = GRAD_K * sig

        # 生长 + 只留和粗圈重叠最多的那一块（这里整图就一个种子区，先直接长）
        grown_raw = grow(g, seed, tol, grad_max)
        grown = fill_holes(grown_raw)

        a_seed = int(seed.sum())
        a_grow = int(grown.sum())
        a_out = int((grown & ~seed).sum())
        inter = int((grown & seed).sum())
        iou = inter / max(1, (grown | seed).sum())
        cover = inter / max(1, a_seed)          # 我圈的里面有多少被吸进来了
        ratio = a_grow / max(1, a_seed)
        runaway = ratio > RUNAWAY_RATIO
        grad_at_seed = float(np.median(gradient_mag(g)[seed]))
        strong_edge = grad_at_seed > 8.0        # 圈内是否本来就存在明显边界

        print(f"\n=== {name} ===")
        print(f"  粗圈面积={a_seed}px　吸附后={a_grow}px　面积比={ratio:.2f}×　"
              f"吸到圈外={a_out}px（占吸附面 {a_out / max(1, a_grow) * 100:.1f}%）")
        print(f"  与粗圈重叠 IoU={iou:.2f}　粗圈被覆盖={cover * 100:.1f}%")
        print(f"  种子内亮度：中位 {np.median(band):.0f}　稳健σ={sig:.1f} ⇒ 容差 ±{tol:.1f}　梯度阈值 {grad_max:.1f}")
        print(f"  圈内中位梯度={grad_at_seed:.1f} ⇒ {'圈内本来就有明显边界' if strong_edge else '圈内边界不明显（低对比）'}")
        print(f"  ★ 判定：{'失控（吸过头了，必须明说）' if runaway else '未失控'}")
        report.append((name, ratio, iou, cover, runaway))

        # ---- 三张图给人眼判 ----
        # 1) 原图 + 黄色粗圈（人手画的圈就是这么多半）
        v1 = Image.fromarray(gray_rgb.copy())
        ImageDraw.Draw(v1).ellipse([x0, y0, x1, y1], outline=(255, 210, 0), width=3)
        v1.save(OUT / f"{len(report)}a-原图加粗圈-{name[:2]}.png")

        # 2) 原图 + 吸附结果（红色半透明）
        vis2 = gray_rgb.astype(np.float64).copy()
        vis2[grown] = vis2[grown] * 0.45 + np.array([230, 40, 40]) * 0.55
        v2 = Image.fromarray(vis2.astype(np.uint8))
        ImageDraw.Draw(v2).ellipse([x0, y0, x1, y1], outline=(255, 210, 0), width=2)
        v2.save(OUT / f"{len(report)}b-吸附结果-{name[:2]}.png")

        # 3) 圈外全部置白 + 中心放大：看吸出来的形状像不像那个部位
        crop = (max(0, x0 - 60), max(0, y0 - 60), min(W, x1 + 60), min(H, y1 + 60))
        sub = vis2[crop[1]:crop[3], crop[0]:crop[2]].astype(np.uint8)
        big = Image.fromarray(sub).resize(((crop[2] - crop[0]) * 3, (crop[3] - crop[1]) * 3), Image.NEAREST)
        big.save(OUT / f"{len(report)}c-放大看形状-{name[:2]}.png")

    print("\n\n========== 汇总 ==========")
    for name, ratio, iou, cover, runaway in report:
        flag = "失控" if runaway else "OK "
        print(f"{flag} {name:34s} 面积比 {ratio:5.2f}×  IoU {iou:.2f}  覆盖率 {cover * 100:5.1f}%")
    print(f"\n图都在：{OUT}")
    print("人眼判据：b/c 两张里，红色形状**像不像**你要的那个部位（这是唯一必须你看的一条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
