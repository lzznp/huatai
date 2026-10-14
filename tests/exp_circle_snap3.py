r"""实验 A3（第 2 档做法）：**磁性吸附——不改亮度，只把你的轮廓线挪到最近的边上**

为什么换做法（A1/A2 的实测结论）：
  "按相似度生长"（魔棒/区域生长）在这张图上**必失控**：
    · 圈左眼 4.4×、圈嘴唇 8.4×、上唇 3.5×，吸出来的形状爬到鼻子和脸颊上（图 3b 可见）；
    · 根因：特征内部自身的颜色离散度 ≥ 特征与周围的差（信号比 0.2~1.2），
      生长条件"像不像目标"永远成立 ⇒ 一路蔓延；加"遇到边停"也不够，因为**嘴边界的梯度只有 3~7**。
  ⇒ 换一条**几何**路线：用户那条粗轮廓**只在附近找边**，找不到就走原样。

做法（PS「磁性套索」的味道，全是确定性代码）：
  1. 把用户的粗轮廓（椭圆）离散成 N 个点，并算出每点的**法线方向**；
  2. 每点沿法线在 ±R 像素内搜：
       代价 = −梯度 + 距离惩罚×|位移|
     取代价最小处 ⇒ 有强边就被吸过去，没强边就基本不动；
  3. 对位移做**中值平滑**（防抖动出一个尖刺）；
  4. 用吸完的多边形填充出掩膜；报：面积比 / 外扩 / 位移量 / **有多少点几乎没动**（=诚实说明"没边可吸"）。

★ 这条方法的天然好处：**它不可能长到远离用户圈的地方**（R 就是硬上限）。

用法：  python tests\exp_circle_snap3.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

REAL = Path(r"D:\画台\projects\美女玻璃画\order-20261012-165706\src_one.jpeg")
OUT = ROOT / ".tmp-tests" / "exp-circle-snap3"
OUT.mkdir(parents=True, exist_ok=True)

N_POINTS = 96        # 轮廓离散成多少个点
SEARCH_R = 18        # 每点沿法线最多挪多少像素（硬上限，防跑远）
DIST_PENALTY = 1.2   # 距离惩罚：挪得越远越要"边更强"才值
SMOOTH_WIN = 7       # 位移的中值平滑窗口


def gradient(g: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(g)
    return np.hypot(gx, gy)


def ellipse_points(box, n: int) -> np.ndarray:
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([cx + rx * np.cos(t), cy + ry * np.sin(t)], axis=1)


def normals(pts: np.ndarray) -> np.ndarray:
    """相邻点切线的法线（单位向量）——直接由点序列算，够用。"""
    nxt = np.roll(pts, -1, axis=0)
    prv = np.roll(pts, 1, axis=0)
    tan = nxt - prv
    nrm = np.stack([-tan[:, 1], tan[:, 0]], axis=1)
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    return nrm / np.maximum(ln, 1e-6)


def sample(g: np.ndarray, x: float, y: float) -> float:
    H, W = g.shape
    xi = int(round(x))
    yi = int(round(y))
    if xi < 0 or yi < 0 or xi >= W or yi >= H:
        return 0.0
    return float(g[yi, xi])


def snap(pts: np.ndarray, nrm: np.ndarray, grad: np.ndarray, r: int, penalty: float):
    """返回每点的位移（带符号，沿法线方向为正）与每个位移处的梯度。"""
    offs = np.arange(-r, r + 1)
    disp = np.zeros(len(pts))
    best_g = np.zeros(len(pts))
    for i, (p, nv) in enumerate(zip(pts, nrm)):
        scores = []
        for d in offs:
            x, y = p[0] + nv[0] * d, p[1] + nv[1] * d
            scores.append(-sample(grad, x, y) + penalty * abs(d))
        k = int(np.argmin(scores))
        disp[i] = offs[k]
        best_g[i] = sample(grad, p[0] + nv[0] * offs[k], p[1] + nv[1] * offs[k])
    # 中值平滑位移，防止个别点飞出尖刺
    if SMOOTH_WIN > 1 and SMOOTH_WIN % 2 == 1:
        half = SMOOTH_WIN // 2
        padded = np.concatenate([disp[-half:], disp, disp[:half]])
        disp = np.array([np.median(padded[i:i + SMOOTH_WIN]) for i in range(len(disp))])
    return disp, best_g


def polygon_mask(shape, pts: np.ndarray) -> np.ndarray:
    m = Image.new("L", (shape[1], shape[0]), 0)
    ImageDraw.Draw(m).polygon([tuple(p) for p in pts], fill=255)
    return np.asarray(m) > 0


def main() -> int:
    img = Image.open(REAL)
    W, H = img.size
    gray = np.asarray(img.convert("L"), dtype=np.float64)
    grad = gradient(gray)
    gray_rgb = np.stack([gray, gray, gray], axis=-1).astype(np.uint8)
    print(f"图 = {REAL.name} {W}×{H}px")
    print(f"参数：轮廓 {N_POINTS} 点　法线搜索 ±{SEARCH_R}px　距离惩罚 {DIST_PENALTY}　中值平滑 {SMOOTH_WIN}")
    print(f"（对照：这张图嘴边界的渐变约 3~7，属于'弱边'）\n")

    cases = [
        ("只圈上唇一条", (110, 200, 200, 235)),
        ("整个嘴唇", (98, 195, 210, 275)),
        ("左眼", (72, 55, 140, 105)),
        ("左眉一带", (60, 40, 150, 62)),
    ]

    for i, (name, box) in enumerate(cases, start=1):
        pts = ellipse_points(box, N_POINTS)
        nrm = normals(pts)
        rough_mask = polygon_mask((H, W), pts)
        disp, best_g = snap(pts, nrm, grad, SEARCH_R, DIST_PENALTY)
        snapped = pts + nrm * disp[:, None]
        snapped = np.clip(snapped, 0, [W - 1, H - 1])
        new_mask = polygon_mask((H, W), snapped)

        a_rough, a_new = int(rough_mask.sum()), int(new_mask.sum())
        inter = int((rough_mask & new_mask).sum())
        iou = inter / max(1, (rough_mask | new_mask).sum())
        out_pct = int((new_mask & ~rough_mask).sum()) / max(1, a_new)
        moved = int((np.abs(disp) > 2).sum())
        # 吸到的边的强度：和圈上原始梯度比
        g_rough = np.array([sample(grad, p[0], p[1]) for p in pts])
        print(f"=== {i}. {name} ===")
        print(f"  位移：中位 {np.median(disp):+.1f}px　最大 {np.abs(disp).max():.1f}px　"
              f"动了(>2px)的点 {moved}/{N_POINTS}")
        print(f"  轮廓上的梯度：原圈 {np.median(g_rough):.1f} → 吸附后 {np.median(best_g):.1f}"
              f"（提高 {np.median(best_g) - np.median(g_rough):+.1f}）")
        print(f"  面积 {a_rough} → {a_new}px（{a_new / max(1, a_rough):.2f}×）　IoU {iou:.2f}　"
              f"吸到圈外 {out_pct * 100:.0f}%")
        verdict = ("边太弱 ⇒ 基本没动（应当如实说'这块吸不住'）" if np.median(best_g) < 6
                   else "吸到了较明显的边")
        print(f"  ★ 判定：{verdict}")

        vis = gray_rgb.astype(np.float64).copy()
        vis[new_mask] = vis[new_mask] * 0.55 + np.array([235, 45, 45]) * 0.45
        v = Image.fromarray(vis.astype(np.uint8))
        d = ImageDraw.Draw(v)
        d.line([tuple(p) for p in np.vstack([pts, pts[:1]])], fill=(255, 210, 0), width=2)      # 黄=你的粗圈
        d.line([tuple(p) for p in np.vstack([snapped, snapped[:1]])], fill=(60, 230, 120), width=2)  # 绿=吸附后
        v.save(OUT / f"{i}b-吸附结果-{name[:4]}.png")
        x0, y0, x1, y1 = box
        crop = (max(0, x0 - 50), max(0, y0 - 50), min(W, x1 + 50), min(H, y1 + 50))
        sub = vis[crop[1]:crop[3], crop[0]:crop[2]].astype(np.uint8)
        Image.fromarray(sub).resize(((crop[2] - crop[0]) * 3, (crop[3] - crop[1]) * 3),
                                    Image.NEAREST).save(OUT / f"{i}c-放大看形状-{name[:4]}.png")

    print(f"\n图都在：{OUT}")
    print("人眼判据：绿线（吸附后的轮廓）有没有贴到那个部位的真实边上；红=最终选区")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
