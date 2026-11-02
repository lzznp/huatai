r"""A/B 对照探针：同一张灰度场，两种“点”的引擎。

A = 画台上机档（1bit BMP，Floyd–Steinberg 在像素格上抖动）—— 直接读现成产物，不重算
B = 泊松盘点集（等径圆点 + 最小间距 + 密度由灰度决定 + 背景纯白）—— 对齐参考作品那种点绘

口径：
  灰度场 = 该单的 PNG 预览（mode L，787x787），A 的点阵就是由这个场抖出来的
  darkness = (255 - gray) / 255；灰度 >= BG_CUT 的像素不撒点（背景纯白）
  B 的采样：候选点均匀撒 → 以 darkness 概率接受 → 最小间距 r_min 过滤
            （两者合起来 = “暗部只变密、但绝不相邻”，密度天然封顶）
  因 787px 画布上一个点只能是 1px 或 5px（粒度太粗），默认按 S 倍画布、
  物理不变的点径/间距撒点，再降回 787 —— 同一物理尺度下的真观感。
用法：python tests\exp_stipple_probe.py [png] [--rmin 2.6] [--rdot 0.95] [--gain 1.0] [--ss 4]
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".tmp-tests" / "stipple-export"
DEF_PNG = (ROOT / "projects" / "测试图片" / "order-20261017-201207" / "out"
           / "src_test_engrave_100mm_200dpi_v1.png")
DEF_BMP = DEF_PNG.with_suffix(".bmp")
BG_CUT = 244.0   # 背景纯白：灰度 >= 这个值就不撒点（参考作品的共同特征）


def _arg(name: str, default: float) -> float:
    if name in sys.argv:
        return float(sys.argv[sys.argv.index(name) + 1])
    return default


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def poisson_from_density(darkness: np.ndarray, r_min: float, gain: float,
                         seed: int = 0, n_cand: int | None = None,
                         subpixels: int = 1):
    """以 darkness 为接受概率、r_min 为最小间距抽一组点，返回 (xs, ys)。

    n_cand 默认按"目标点数 / 平均接受率"算：目标点数 = sum(darkness)/subpixels，
    即每个 787 像素的暗度折成 1 个点。候选撒太多会让最小间距过滤器成为主导，
    把亮暗差别压平（这是早期版本踩过的坑）。
    """
    h, w = darkness.shape
    rng = np.random.default_rng(seed)
    mean = max(1e-6, float(darkness.mean()))
    if n_cand is None:
        n_cand = int((float(darkness.sum()) / subpixels) / mean * 1.15)
    n_cand = min(max(n_cand, 50_000), 40_000_000)
    cx = rng.integers(0, w, n_cand)
    cy = rng.integers(0, h, n_cand)
    acc = rng.random(n_cand) < (darkness[cy, cx] * gain)
    cx, cy = cx[acc], cy[acc]

    cell = max(1, int(math.ceil(r_min)))
    r2 = r_min * r_min
    grid: dict[tuple[int, int], list[tuple[int, int]]] = {}
    rx: list[int] = []
    ry: list[int] = []
    for x, y in zip(cx.tolist(), cy.tolist()):
        gx, gy = x // cell, y // cell
        ok = True
        for dj in (-1, 0, 1):
            for di in (-1, 0, 1):
                for px, py in grid.get((gx + di, gy + dj), ()):
                    dx, dy = px - x, py - y
                    if dx * dx + dy * dy < r2:
                        ok = False
                        break
                if not ok:
                    break
            if not ok:
                break
        if ok:
            grid.setdefault((gx, gy), []).append((x, y))
            rx.append(x)
            ry.append(y)
    return np.array(rx, dtype=np.int32), np.array(ry, dtype=np.int32)


def render_dots(h: int, w: int, xs: np.ndarray, ys: np.ndarray, r_dot: float) -> np.ndarray:
    """把点画成图（黑点白底）。r_dot<=0.75 时按 1px 画。"""
    img = np.full((h, w), 255, dtype=np.uint8)
    if r_dot <= 0.75:
        img[ys, xs] = 0
        return img
    r = int(math.ceil(r_dot))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    disk = (xx * xx + yy * yy) <= r_dot * r_dot
    for x, y in zip(xs.tolist(), ys.tolist()):
        y0, y1 = max(0, y - r), min(h, y + r + 1)
        x0, x1 = max(0, x - r), min(w, x + r + 1)
        sub = disk[(y0 - (y - r)):(y1 - (y - r)), (x0 - (x - r)):(x1 - (x - r))]
        img[y0:y1, x0:x1][sub] = 0
    return img


def clump_stats(binary: np.ndarray) -> tuple[int, int]:
    """返回 (有黑邻居的黑点数, 2x2 全黑格数)。"""
    nb = np.zeros_like(binary)
    nb[1:, :] |= binary[:-1, :]
    nb[:-1, :] |= binary[1:, :]
    nb[:, 1:] |= binary[:, :-1]
    nb[:, :-1] |= binary[:, 1:]
    touch = int((nb & binary).sum())
    blocks = int((binary[:-1, :-1] & binary[1:, :-1] & binary[:-1, 1:] & binary[1:, 1:]).sum())
    return touch, blocks


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--") and not _is_number(a)]
    src_png = Path(args[0]) if args else DEF_PNG
    bmp = src_png.with_suffix(".bmp") if src_png.with_suffix(".bmp").exists() else DEF_BMP
    r_min = _arg("--rmin", 2.6)
    r_dot = _arg("--rdot", 0.95)
    S = int(_arg("--ss", 4))
    gain = _arg("--gain", 1.0)
    tag = time.strftime("%Y%m%d-%H%M%S")
    OUT.mkdir(parents=True, exist_ok=True)

    gray = np.asarray(Image.open(src_png).convert("L"), dtype=np.float64)
    h, w = gray.shape
    a = np.asarray(Image.open(bmp).convert("L")) < 128
    ta, ba = clump_stats(a)
    print(f"灰度场 {src_png.name}  {w}x{h}  平均灰度 {gray.mean():.1f}"
          f"  => 等效墨点 {100 * (1 - gray.mean() / 255):.2f}%")
    print(f"A 上机档 {bmp.name}: 墨点 {100 * a.mean():.2f}%  "
          f"有黑邻居的黑点 {100 * ta / a.sum():.1f}%  2x2 全黑格 {ba}")

    big = Image.fromarray(gray.astype(np.uint8)).resize((w * S, h * S), Image.LANCZOS)
    gray_big = np.asarray(big, dtype=np.float64)
    dark_big = (255.0 - gray_big) / 255.0
    dark_big[gray_big >= BG_CUT] = 0.0

    t0 = time.perf_counter()
    xs, ys = poisson_from_density(dark_big, r_min * S, gain, seed=7, subpixels=S * S)
    dt = time.perf_counter() - t0
    print(f"B 采样: {len(xs)} 个点  r_min={r_min}px(物理)  S={S}  用时 {dt:.1f}s")

    bimg_big = render_dots(h * S, w * S, xs, ys, r_dot * S)
    # 高分辨率原图（1:1 看才是"点绘"的样子）留一张裁图，用来证明"是尺寸/DPI 的问题"
    if "--big" in sys.argv:
        cb = (300 * S, 420 * S, 480 * S, 600 * S)
        Image.fromarray(bimg_big).crop(cb).save(OUT / f"stipple-{tag}-B在高分辨率下的1比1裁图.png")
        bb = bimg_big < 128
        for k, (y0, y1, x0, x1) in {"face": (300, 420, 300, 480), "hair_L": (620, 700, 200, 260),
                                    "bg_TL": (0, 120, 0, 120)}.items():
            print(f"  [S={S} 原图] {k}: {100 * bb[y0 * S:y1 * S, x0 * S:x1 * S].mean():5.1f}%")
    bimg = np.asarray(Image.fromarray(bimg_big).resize((w, h), Image.LANCZOS))
    xs = (xs / S).astype(np.int32)
    ys = (ys / S).astype(np.int32)
    b = bimg < 128
    area = float(h * w)
    print(f"B 点绘: {len(xs)} 点 = {len(xs) / area * 1e4:.1f} 点/万像素  覆盖率 {100 * b.mean():.2f}%"
          f"  最小间距 {r_min}px（> 2x半径 {2 * r_dot:.2f} => 不重叠）")
    print(f"   对比 A: {int(a.sum())} 点 = {a.sum() / area * 1e4:.1f} 点/万像素（1px 点）"
          f"  覆盖率 {100 * a.mean():.2f}%  有黑邻居 {100 * ta / a.sum():.1f}%  2x2 全黑 {ba}")

    for name, (y0, y1, x0, x1) in {"背景左上": (0, 120, 0, 120), "背景右上": (0, 120, w - 120, w)}.items():
        ca = int(a[y0:y1, x0:x1].sum())
        cb = int(((xs >= x0) & (xs < x1) & (ys >= y0) & (ys < y1)).sum())
        px = float((y1 - y0) * (x1 - x0))
        print(f"  {name}: A {ca} 点 ({ca / px * 1e4:.0f}/万px)  |  B {cb} 点 ({cb / px * 1e4:.0f}/万px)")

    A = np.stack([np.where(a, 0, 255)] * 3, -1).astype(np.uint8)
    B = np.stack([bimg] * 3, -1).astype(np.uint8)

    gap = 14
    canvas = Image.new("RGB", (w * 2 + gap, h), (255, 255, 255))
    canvas.paste(Image.fromarray(A), (0, 0))
    canvas.paste(Image.fromarray(B), (w + gap, 0))
    p1 = OUT / f"stipple-{tag}-对照.png"
    canvas.save(p1)

    crop = (180, 560, 340, 720)
    za = Image.fromarray(A).crop(crop).resize(((crop[2] - crop[0]) * 2, (crop[3] - crop[1]) * 2), Image.NEAREST)
    zb = Image.fromarray(B).crop(crop).resize(((crop[2] - crop[0]) * 2, (crop[3] - crop[1]) * 2), Image.NEAREST)
    zc = Image.new("RGB", (za.width * 2 + gap, za.height), (255, 255, 255))
    zc.paste(za, (0, 0))
    zc.paste(zb, (za.width + gap, 0))
    p2 = OUT / f"stipple-{tag}-放大2x-左A右B.png"
    zc.save(p2)

    p3 = OUT / f"stipple-{tag}-A.png"
    Image.fromarray(A).save(p3)
    p4 = OUT / f"stipple-{tag}-B.png"
    Image.fromarray(B).save(p4)

    p5 = OUT / f"stipple-{tag}-B.svg"
    with open(p5, "w", encoding="utf-8") as f:
        f.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
                f'viewBox="0 0 {w} {h}"><rect width="100%" height="100%" fill="#fff"/>\n')
        f.write('<g fill="#000">\n')
        for x, y in zip(xs.tolist(), ys.tolist()):
            f.write(f'<circle cx="{x}" cy="{y}" r="{r_dot}"/>\n')
        f.write("</g></svg>\n")

    for p in (p1, p2, p3, p4, p5):
        print("写出:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
