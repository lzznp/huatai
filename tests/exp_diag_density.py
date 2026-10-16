r"""诊断图：把"眉毛 vs 额头 vs 刘海"**画出来给人眼看**（决策 #29：谈坐标必须出图）。

为什么要这张图：
  探针 probe_dot_density.py 打出数字后发现一件反直觉的事——
  **眉线带的黑点密度（56.2%）比它上面的额头带（63.9%）和刘海带（63.2%）都低。**
  光看数字说不清"那到底是眉毛还是头发"，必须画出来人眼判。

输出 4 张图到 .tmp-tests\diag-density\ ：
  1-灰度+标注.png      灰度图上画出三条测量带与大圈（带文字标注、带坐标尺）
  2-密度热力图.png     局部黑点密度（绿=稀 / 红=密），同标注
  3-圈内稀疏对比.png   原图点阵 vs 稀疏后点阵（红=要删的点），3 倍放大
  4-整图点阵+圈.png    整图点阵 + 大圈（看整体疏密分布）

用法：python tests\exp_diag_density.py
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
from PIL import Image, ImageDraw  # noqa: E402

import exp_interactive_snap as T  # noqa: E402
from probe_dot_density import BANDS, R, local_density  # noqa: E402

OUT = ROOT / ".tmp-tests" / "diag-density"
ZOOM = 3
BIG_BOX = (55, 30, 200, 130)          # 故意圈大的那一圈


def colorize(dens: np.ndarray) -> np.ndarray:
    """密度 → 绿-黄-红。绿=稀（像皮肤），红=密（像头发/眉毛）。"""
    t = np.clip(dens, 0, 1)
    r = np.clip(2.0 * t, 0, 1)
    g = np.clip(2.0 * (1 - np.abs(t - 0.5) * 2), 0, 1)
    b = np.clip(2.0 * (1 - t), 0, 1)
    return (np.stack([r, g, b], axis=-1) * 255).astype(np.uint8)


def draw_marks(d: ImageDraw.ImageDraw, scale: float = 1.0, label: bool = True):
    """画坐标尺 + 三条测量带 + 那一个大圈。"""
    w, h = d.im.size
    # 坐标尺：每 50px 一条
    for x in range(0, w, 50):
        d.line([(x, 0), (x, 8)], fill=(255, 0, 255), width=1)
        if label:
            d.text((x + 2, 9), str(int(x / scale)), fill=(255, 0, 255))
    for y in range(0, h, 50):
        d.line([(0, y), (8, y)], fill=(255, 0, 255), width=1)
        if label:
            d.text((10, y + 10), str(int(y / scale)), fill=(255, 0, 255))

    # 三条测量带
    for name, x0, y0, x1, y1 in BANDS:
        box = [x0 * scale, y0 * scale, x1 * scale, y1 * scale]
        d.rectangle(box, outline=(255, 255, 0), width=2)
        if label:
            d.text((box[0] + 2, box[1] + 2), name, fill=(255, 255, 0))

    # 那一个大圈（椭圆轮廓）
    x0, y0, x1, y1 = BIG_BOX
    d.ellipse([x0 * scale, y0 * scale, x1 * scale, y1 * scale], outline=(0, 255, 255), width=2)
    if label:
        d.text((x0 * scale + 2, y1 * scale + 2), "用户圈的大圈", fill=(0, 255, 255))


def main() -> int:
    if not T.DEFAULT_REAL.exists():
        print(f"找不到真图：{T.DEFAULT_REAL}")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)

    src = Image.open(T.DEFAULT_REAL)
    gray = np.asarray(src.convert("L"), dtype=np.float64)
    h, w = gray.shape
    dots = T.fs_dither(gray)
    dens = local_density(dots, R)

    # ---------- 1 灰度 + 标注 ----------
    g1 = Image.fromarray(np.stack([gray] * 3, axis=-1).astype(np.uint8))
    draw_marks(ImageDraw.Draw(g1))
    g1.save(OUT / "1-灰度+标注.png")

    # ---------- 2 密度热力图 + 标注 ----------
    heat = Image.fromarray(colorize(dens))
    draw_marks(ImageDraw.Draw(heat))
    heat.save(OUT / "2-密度热力图.png")

    # ---------- 3 圈内稀疏对比（3 倍放大）----------
    pts = T.ellipse_points(BIG_BOX)
    mask = T.polygon_mask((h, w), pts)
    thin, note = T.dots_edit(dots, mask, 0.7)
    print(f"大圈 {BIG_BOX}：{note}")

    x0, y0, x1, y1 = 55, 25, 205, 100         # 取景框（含眉线带与额头带）
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)

    def dots_rgb(dd: np.ndarray, marked_delete: np.ndarray | None = None) -> Image.Image:
        vis = np.full((h, w, 3), 255, dtype=np.uint8)
        vis[dd] = np.array([40, 40, 40], dtype=np.uint8)
        if marked_delete is not None:
            vis[marked_delete] = np.array([230, 30, 30], dtype=np.uint8)   # 红=要删的
        return Image.fromarray(vis[y0:y1, x0:x1])

    deleted = dots & mask & ~thin
    a = dots_rgb(dots).resize(((x1 - x0) * ZOOM, (y1 - y0) * ZOOM), Image.NEAREST)
    b = dots_rgb(thin, deleted).resize(((x1 - x0) * ZOOM, (y1 - y0) * ZOOM), Image.NEAREST)
    cmp_img = Image.new("RGB", (a.width * 2 + 12, a.height + 26), (255, 255, 255))
    cmp_img.paste(a, (0, 26))
    cmp_img.paste(b, (a.width + 12, 26))
    dc = ImageDraw.Draw(cmp_img)
    dc.text((4, 6), f"原图点阵（{x0},{y0})-({x1},{y1}) {ZOOM}x", fill=(0, 0, 0))
    dc.text((a.width + 16, 6), "稀疏到 70% 之后（红=被删掉的点）", fill=(0, 0, 0))
    cmp_img.save(OUT / "3-圈内稀疏对比.png")

    # ---------- 4 整图点阵 + 大圈 ----------
    vis = np.stack([gray] * 3, axis=-1).astype(np.float64)
    vis[dots] = vis[dots] * 0.25 + np.array([190, 40, 40]) * 0.75
    g4 = Image.fromarray(vis.astype(np.uint8))
    d4 = ImageDraw.Draw(g4)
    d4.ellipse([BIG_BOX[0], BIG_BOX[1], BIG_BOX[2], BIG_BOX[3]], outline=(0, 255, 255), width=2)
    g4.save(OUT / "4-整图点阵+圈.png")

    # 图里再画一遍坐标，方便人眼对照
    print("\n=== 再看一眼数字（与图对照）===")
    for name, bx0, by0, bx1, by1 in BANDS:
        bx0, by0 = max(0, bx0), max(0, by0)
        bx1, by1 = min(w, bx1), min(h, by1)
        sub = dens[by0:by1, bx0:bx1].ravel()
        blk = 100.0 * dots[by0:by1, bx0:bx1].mean()
        print(f"  {name:14s} 带内黑点 {blk:5.1f}%   局部密度中位 {np.median(sub) * 100:5.1f}%")

    print(f"\n图都在：{OUT}")
    print("人眼判据：")
    print("  · 图1 里那三条黄框，**框住的到底是眉毛、额头还是头发**？")
    print("  · 图2 里红色区是否就对应黄框？如果额头比眉线更红 ⇒ 说明'暗的地方'不止眉毛。")
    print("  · 图3 左边那团点，稀疏 30% 之后（右）**还像不像眉毛**？")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
