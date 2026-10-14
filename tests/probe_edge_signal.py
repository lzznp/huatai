r"""探针：这张图的"特征 vs 周围"到底有多少**信号**可以拿来吸附？（离线、免费）

背景：实验 A（区域生长）大失败——嘴唇圈吸成了 8.4 倍面积。失败原因要归因清楚，
      否则会误判成"算法写得差"。这个探针只量**数据本身**：
        · 圈内像素 与 圈外一圈（环形带）的 灰度差 / 颜色差 有多少
        · 圈内自身的 离散度（稳健σ）有多少
        · 边界处（圈的轮廓上）梯度有多强
      口径仍是原图像素坐标。

怎么读：
  信号比 = (圈内均值 − 环带均值) / 圈内稳健σ
    ≥1.0   ⇒ 有得吸（特征和周围可分）
    0.3~1  ⇒ 很勉强，得靠"边缘/形状"这类更强的先验
    <0.3   ⇒ 分不开：任何"按亮度/颜色生长"的方法都会失控（不是算法的错）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

REAL = Path(r"D:\画台\projects\美女玻璃画\order-20261012-165706\src_one.jpeg")


def robust_sigma(v: np.ndarray) -> float:
    med = float(np.median(v))
    return max(1e-6, 1.4826 * float(np.median(np.abs(v - med))))


def ring_mask(shape, box, grow: int) -> np.ndarray:
    """椭圆外扩 grow 像素的环带。"""
    m_in = Image.new("L", (shape[1], shape[0]), 0)
    m_out = Image.new("L", (shape[1], shape[0]), 0)
    x0, y0, x1, y1 = box
    ImageDraw.Draw(m_in).ellipse([x0, y0, x1, y1], fill=255)
    ImageDraw.Draw(m_out).ellipse([x0 - grow, y0 - grow, x1 + grow, y1 + grow], fill=255)
    a = np.asarray(m_in) > 0
    b = np.asarray(m_out) > 0
    return a, (b & ~a)


def main() -> int:
    img = Image.open(REAL)
    W, H = img.size
    rgb = np.asarray(img.convert("RGB"), dtype=np.float64)
    gray = np.asarray(img.convert("L"), dtype=np.float64)
    gy, gx = np.gradient(gray)
    grad = np.hypot(gx, gy)
    print(f"图 = {REAL.name} {W}×{H}px（原图坐标）")

    cases = [
        ("左眼", (72, 55, 140, 105)),
        ("嘴唇", (98, 195, 210, 275)),
        ("上唇只圈一条", (110, 200, 200, 235)),
        ("左眉一带", (60, 40, 150, 62)),
    ]
    print(f"\n{'场景':14s} {'圈内σ':>7s} {'灰度差':>8s} {'信号比':>7s} {'颜色差(RGB距离)':>16s} {'颜色信号比':>10s} {'边界梯度(中位)':>13s}")
    for name, box in cases:
        inside, ring = ring_mask((H, W), box, 10)
        gi, gr = gray[inside], gray[ring]
        ci, cr = rgb[inside], rgb[ring]
        d_gray = float(gi.mean() - gr.mean())
        s_i = robust_sigma(gi)
        sig_gray = abs(d_gray) / s_i
        # 颜色差：两个分布的均值在 RGB 空间的距离（欧氏），以及圈内的颜色离散度
        d_col = float(np.linalg.norm(ci.mean(axis=0) - cr.mean(axis=0)))
        s_col = max(1e-6, robust_sigma(np.linalg.norm(ci - ci.mean(axis=0), axis=1)))
        sig_col = d_col / s_col
        g_edge = float(np.median(grad[inside]))
        print(f"{name:14s} {s_i:7.1f} {d_gray:8.1f} {sig_gray:7.2f} {d_col:16.1f} {sig_col:10.2f} {g_edge:13.1f}")
    print("\n参考：界面上人眼能分辨的灰度差大约 2~3；梯度 10 以上才算'看得见的边'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
