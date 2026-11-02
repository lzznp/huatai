r"""方案 C：纯像素点 + “点与点至少空一格”（8 邻接不粘连）+ 背景纯白。

这条约束是从"别人作品"里量出来的：5 张参考作品的点，最近邻距离恒为 2.0px，
即任意两个点都不相邻。用它在 787x787 的原画布上采样，输出仍是 1bit BMP 形态。

只读探针，不改画台。
用法：python tests\exp_dots_noadj.py [png] [--gain 1.0] [--bgcut 244] [--ink 0.10]
"""
from __future__ import annotations

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
OUT = ROOT / ".tmp-tests" / "dots-export"
DEF_PNG = (ROOT / "projects" / "测试图片" / "order-20261017-201207" / "out"
           / "src_test_engrave_100mm_200dpi_v1.png")


def _arg(name: str, default: float) -> float:
    if name in sys.argv:
        return float(sys.argv[sys.argv.index(name) + 1])
    return default


def sample_no_adjacent(darkness: np.ndarray, gain: float, seed: int = 3) -> np.ndarray:
    """按暗度概率撒 1px 点，但任何已落点的 8 邻接不再落点（⇒ 最近邻 >= 2px）。"""
    h, w = darkness.shape
    rng = np.random.default_rng(seed)
    flat = darkness.ravel()
    order = rng.permutation(flat.size)          # 随机顺序，避免扫描方向造成条纹
    prob = np.minimum(1.0, flat[order] * gain)
    keep = rng.random(flat.size) < prob

    dots = np.zeros((h, w), dtype=bool)
    n = 0
    for idx in order[keep].tolist():
        y, x = divmod(idx, w)
        if dots[y, x]:
            continue
        y0, y1 = max(0, y - 1), min(h, y + 2)
        x0, x1 = max(0, x - 1), min(w, x + 2)
        if dots[y0:y1, x0:x1].any():
            continue
        dots[y, x] = True
        n += 1
    return dots


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--") and not _is_num(a)]
    png = Path(args[0]) if args else DEF_PNG
    bmp = png.with_suffix(".bmp")
    gain = _arg("--gain", 1.0)
    bgcut = _arg("--bgcut", 244.0)
    target = _arg("--ink", 0.10)            # 目标墨量（参考作品区间 4~10%）
    tag = time.strftime("%Y%m%d-%H%M%S")
    OUT.mkdir(parents=True, exist_ok=True)

    gray = np.asarray(Image.open(png).convert("L"), dtype=np.float64)
    h, w = gray.shape
    dark = (255.0 - gray) / 255.0
    dark[gray >= bgcut] = 0.0

    # 用二分把 gain 调到目标墨量（墨量随 gain 单调，样本够大时很稳）
    lo, hi = 0.05, 8.0
    dots = None
    for _ in range(9):
        mid = 0.5 * (lo + hi)
        d = sample_no_adjacent(dark, mid)
        ink = d.mean()
        print(f"   gain={mid:.3f} -> 墨点 {100 * ink:.2f}%")
        dots = d
        if ink < target:
            lo = mid
        else:
            hi = mid
    ink = dots.mean()

    a = np.asarray(Image.open(bmp).convert("L")) < 128 if bmp.exists() else None
    print(f"\nC 结果: 墨点 {100 * ink:.2f}%   点数 {int(dots.sum())}"
          f" = {dots.sum() / (w * h) * 1e4:.1f} 点/万像素   纯白背景 {100 * (dots == 0).mean():.2f}%")
    # 邻接检查（应当为 0）
    nb = np.zeros_like(dots)
    nb[1:, :] |= dots[:-1, :]
    nb[:-1, :] |= dots[1:, :]
    nb[:, 1:] |= dots[:, :-1]
    nb[:, :-1] |= dots[:, 1:]
    nb[1:, 1:] |= dots[:-1, :-1]
    nb[:-1, :-1] |= dots[1:, 1:]
    nb[1:, :-1] |= dots[:-1, 1:]
    nb[:-1, 1:] |= dots[1:, :-1]
    print(f"   有 8 邻接邻居的点：{int((nb & dots).sum())} 个（应为 0）")
    if a is not None:
        na = np.zeros_like(a)
        na[1:, :] |= a[:-1, :]
        na[:-1, :] |= a[1:, :]
        na[:, 1:] |= a[:, :-1]
        na[:, :-1] |= a[:, 1:]
        print(f"   对比 A: 墨点 {100 * a.mean():.2f}%  有邻居的黑点 {100 * (na & a).sum() / a.sum():.1f}%")

    img = np.where(dots, 0, 255).astype(np.uint8)
    p1 = OUT / f"dots-{tag}-C.png"
    Image.fromarray(img).convert("1").save(OUT / f"dots-{tag}-C.bmp")
    Image.fromarray(img).save(p1)

    gap = 14
    A = np.stack([np.where(a, 0, 255)] * 3, -1).astype(np.uint8) if a is not None else None
    C = np.stack([img] * 3, -1).astype(np.uint8)
    if A is not None:
        cv = Image.new("RGB", (w * 2 + gap, h), (255, 255, 255))
        cv.paste(Image.fromarray(A), (0, 0))
        cv.paste(Image.fromarray(C), (w + gap, 0))
        p2 = OUT / f"dots-{tag}-左A右C.png"
        cv.save(p2)
        print("写出:", p2)
    print("写出:", p1)
    print("写出:", OUT / f"dots-{tag}-C.bmp")
    return 0


def _is_num(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
