r"""实验 5：**不用视觉模型，能不能把"眉毛"这类细长特征锁出来？**

用户 2026-10-13/14 的诉求（原话精神）：范围是正题，力度是小事；
"比如我说眉毛太密集了，能不能把两个眉毛都处理一下"。

不用模型的话，能用的信号只有：
  · 眉毛 = **细长的暗结构**（比周围皮肤暗、横向长、纵向薄）；
  · 所以在**上半脸这一带**找"局部比周围暗、且横向连成条"的连通块，
    按"横向长度 / 纵向厚度 / 平均暗度"排序 ⇒ 候选就是眉毛/眼睛/嘴。
  · 用户只需**点一下**（点在选择带上）⇒ 就近吸附到某个候选块；
    "两个眉毛"就是**点两下**（两个块并成一个选区）。

这一条要量的是：**检测器找出来的块，跟真实眉毛对不对得上**。
判据（可自动算，但最终要人眼确认）：
  ① 候选块的形状特征（长宽比、厚度、暗度）是否像眉毛；
  ② **同一张图换不同参数，命中的是不是同一个块**（稳定性）——不稳定就没法用；
  ③ 用户"点一下眉毛中间" ⇒ 吸附到正确候选的**命中率**（本脚本按像素位置算）。

用法：  python tests\exp_brow_detect.py
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

# 搜索带：上半脸（眉毛只可能在这儿；这一条是"范围先验"，用户可以改）
BAND_Y = (0.04, 0.26)
# 局部背景窗口（用来算"比周围暗多少"）
BG = 15


def ridge_score(g: np.ndarray) -> np.ndarray:
    """"比周围暗多少"：局部均值 − 像素值（正值=比周围暗）。"""
    bg = np.asarray(Image.fromarray(g.astype(np.uint8)).filter(
        ImageFilter.BoxBlur(BG)), dtype=np.float64)
    return bg - g


def components(mask: np.ndarray, min_px: int = 12) -> list[dict]:
    """4 邻域连通块（纯 numpy BFS，不依赖 scipy）。"""
    H, W = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    for y in range(H):
        for x in range(W):
            if not mask[y, x] or seen[y, x]:
                continue
            stack = [(y, x)]
            seen[y, x] = True
            pix = []
            while stack:
                cy, cx = stack.pop()
                pix.append((cy, cx))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if len(pix) >= min_px:
                ys = [p[0] for p in pix]
                xs = [p[1] for p in pix]
                out.append({"px": len(pix), "y0": min(ys), "y1": max(ys),
                            "x0": min(xs), "x1": max(xs)})
    return out


def main() -> int:
    im = Image.open(REAL).convert("L")
    W, H = im.size
    g = np.asarray(im, dtype=np.float64)
    y0, y1 = int(BAND_Y[0] * H), int(BAND_Y[1] * H)
    band = g[y0:y1, :]
    print(f"图 {W}×{H}｜搜索带 y {y0}~{y1}（上半脸）｜局部背景窗口 {BG}px")
    sc = ridge_score(band)
    print(f"带内 ridge 分数：中位 {np.median(sc):.1f}　90 分位 {np.quantile(sc, 0.9):.1f}　max {sc.max():.1f}")

    # 用"分数分位数"当阈值，扫几个值看稳定性
    results = {}
    for q in (0.90, 0.94, 0.96, 0.98):
        thr = float(np.quantile(sc, q))
        mask = sc >= thr
        comps = components(mask, min_px=12)
        # 形状打分：横向长、纵向薄、够暗
        cands = []
        for c in comps:
            w = c["x1"] - c["x0"] + 1
            h = c["y1"] - c["y0"] + 1
            cands.append({**c, "w": w, "h": h, "ratio": round(w / max(1, h), 1)})
        cands.sort(key=lambda c: -c["px"])
        results[q] = cands
        print(f"\n阈值 q={q}（score≥{thr:.1f}）⇒ 连通块 {len(comps)} 个；最大的 6 个：")
        for c in cands[:6]:
            print(f"   像素{c['px']:4d}  x {c['x0']:3d}~{c['x1']:3d}  y {c['y0']:3d}~{c['y1']:3d}"
                  f"（原图 y {c['y0'] + y0}~{c['y1'] + y0}）  宽{c['w']:3d} 厚{c['h']:2d}  长厚比{c['ratio']:5.1f}")

    # ---- 存图：每个阈值一张（把候选框画回原图）----
    colors = [(255, 60, 60), (60, 200, 255), (255, 220, 60), (120, 255, 120), (255, 120, 255), (200, 200, 200)]
    for q, cands in results.items():
        vis = Image.open(REAL).convert("RGB")
        d = ImageDraw.Draw(vis)
        for i, c in enumerate(cands[:6]):
            col = colors[i % len(colors)]
            box = [c["x0"], c["y0"] + y0, c["x1"], c["y1"] + y0]
            d.rectangle(box, outline=col, width=2)
            d.text((box[0] + 2, box[1] + 1), f"#{i} {c['ratio']:.0f}", fill=col)
        vis.save(OUT / f"detect-q{int(q * 100)}.png")

    # ---- 人眼确认用：把上半脸放大 3 倍 + 候选框 ----
    q = 0.96
    vis = Image.open(REAL).convert("RGB")
    d = ImageDraw.Draw(vis)
    for i, c in enumerate(results[q][:6]):
        col = colors[i % len(colors)]
        d.rectangle([c["x0"], c["y0"] + y0, c["x1"], c["y1"] + y0], outline=col, width=1)
    crop = vis.crop((0, 0, W, int(H * 0.30)))
    crop.resize((crop.size[0] * 3, crop.size[1] * 3), Image.LANCZOS).save(OUT / "detect-放大3倍-看像不像眉毛.png")

    print(f"\n图都存到 {OUT}")
    print("★ 人眼判据：detect-放大3倍-看像不像眉毛.png 里，有没有哪个框正好盖住眉毛")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
