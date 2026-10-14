r"""实验 5b：**以"眼睛"为锚，在它上方找眉毛**（最后一个不用模型的尝试）

为什么换做法（5a 的结论）：
  · 在"上半脸"里找细长暗块，找到的是**眼睛**（眼睛比眉毛暗得多），眉毛一个都没进榜；
  · 所以单纯"全局找细长暗块"不行 ⇒ 换成**借用解剖先验**：
    眉毛几乎总在眼睛**上方 10~30px**、横向宽度约等于眼睛宽、方向基本水平。
  · 这一步的输入是"眼睛在哪"。眼睛很好找（5a 已经稳定找到左右眼），
    也可以由用户点一下（点眼睛或点眉毛都行）。

判据：找到的"眉"块与眼睛的相对位置是否合理（在上方、宽度相当），
      以及它**比周围皮肤暗多少**（暗度不够就是没信号，必须如实说）。
用法：  python tests\exp_brow_detect2.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".tmp-tests" / "exp-brow"
OUT.mkdir(parents=True, exist_ok=True)

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

REAL = Path(r"D:\画台\projects\美女玻璃画\order-20261012-165706\src_one.jpeg")

# 5a 实测出来的两只眼睛（原图坐标，来自检测器）
EYES = {"左眼": (80, 65, 111, 80), "右眼": (215, 62, 241, 77)}
UP_MIN, UP_MAX = 8, 34        # 眉在眼上方这个范围内找


def ridge_y(g: np.ndarray, x0: int, x1: int, y_from: int, y_to: int) -> tuple[int, float]:
    """在 [y_from, y_to) 里找"横向最暗的一行"：返回 (行号, 该行相对周围皮肤的暗度)。"""
    sub = g[y_from:y_to, x0:x1]
    rows = sub.mean(axis=1)
    k = int(np.argmin(rows))
    # 暗度 = 上方皮肤带（眉上方 10~25px）的均值 − 该行均值
    skin_y0 = max(0, y_from - 25)
    skin_y1 = max(1, y_from - 8)
    skin = g[skin_y0:skin_y1, x0:x1].mean() if skin_y1 > skin_y0 else g[y_to:y_to + 10, x0:x1].mean()
    return y_from + k, float(skin - rows[k])


def main() -> int:
    im = Image.open(REAL).convert("L")
    W, H = im.size
    g = np.asarray(im, dtype=np.float64)
    # 轻度平滑，压掉单像素噪点（不影响眉毛这种成条的暗区）
    gs = np.asarray(Image.fromarray(g.astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0)),
                    dtype=np.float64)
    print(f"图 {W}×{H}｜锚=眼睛（5a 实测框）｜在眼上方 {UP_MIN}~{UP_MAX}px 找最暗横条\n")

    vis = Image.open(REAL).convert("RGB")
    d = ImageDraw.Draw(vis)
    report = []
    for name, (ex0, ey0, ex1, ey1) in EYES.items():
        # 横向稍微放宽一点（眉毛通常比眼睛略宽或相当）
        pad = int((ex1 - ex0) * 0.25)
        x0, x1 = max(0, ex0 - pad), min(W, ex1 + pad)
        # 眼睛上沿往上找
        y_to = max(1, ey0 - UP_MIN)
        y_from = max(0, ey0 - UP_MAX)
        row, dark = ridge_y(gs, x0, x1, y_from, y_to)
        # 沿这一行做"暗于阈值"的横向连段（取最长的一段）
        thr = gs[row, x0:x1].mean() + 2.0
        run, best = 0, (x0, x0)
        for i, v in enumerate(gs[row, x0:x1]):
            if v <= thr:
                run += 1
                if run > best[1] - best[0]:
                    best = (x0 + i - run + 1, x0 + i + 1)
            else:
                run = 0
        bx0, bx1 = best
        # 厚度：以该行为中心，向上向下各扩到"仍然暗于皮肤+3"为止
        skin = float(np.median(gs[max(0, y_from - 20):max(1, y_from - 6), x0:x1])) if y_from > 26 else float(np.median(gs[row + 8:row + 18, x0:x1]))
        yy0, yy1 = row, row
        while yy0 > 0 and gs[yy0 - 1, bx0:bx1].mean() <= skin - 2.5:
            yy0 -= 1
        while yy1 < H - 1 and gs[yy1 + 1, bx0:bx1].mean() <= skin - 2.5:
            yy1 += 1
        report.append((name, bx0, yy0, bx1, yy1 + 1, dark, skin))
        print(f"{name}：眉毛候选 x {bx0}~{bx1}（宽 {bx1 - bx0}）  y {yy0}~{yy1 + 1}（厚 {yy1 + 1 - yy0}）")
        print(f"        最暗行 y={row}　相对上方皮肤的暗度 = {dark:.1f} 灰阶"
              f"（参考：人眼能分辨约 2~3；小于 3 基本等于「看不出来」）")
        print(f"        眼角位置 x {ex0}~{ex1} y {ey0}~{ey1}　⇒ 眉在眼上方 {ey0 - yy1 - 1}~{ey0 - yy0}px")
        d.rectangle([ex0, ey0, ex1, ey1], outline=(60, 200, 255), width=1)      # 青=眼睛
        d.rectangle([bx0, yy0, bx1, yy1 + 1], outline=(255, 60, 60), width=2)   # 红=眉毛候选
        d.text((bx0, max(0, yy0 - 11)), f"{name}眉? {dark:.1f}", fill=(255, 220, 60))

    vis.save(OUT / "brow-anchored.png")
    crop = vis.crop((0, 20, W, 120)).resize((W * 3, 300), Image.LANCZOS)
    crop.save(OUT / "brow-anchored-放大3倍.png")
    print(f"\n图：{OUT / 'brow-anchored.png'}（青=眼睛锚，红=眉毛候选）")
    print("★ 人眼判据：红框有没有正好压在眉毛上；brow-anchored-放大3倍.png 更清楚")
    print("★ 数字判据：暗度 <3 灰阶 ⇒ 这个眉毛在照片里没有可用信号，任何算法都锁不住它")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
