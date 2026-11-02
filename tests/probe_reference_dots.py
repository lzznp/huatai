r"""量“别人的作品”：把 1bit 点绘作品的点算出来（点数/点径/间距/背景）。

只读，不改任何东西。
口径：
  墨点      = 灰度 < 128 的像素数 / 总像素
  背景      = 灰度 == 255 的像素占比（“纯白背景”就是这个数接近 89~96%）
  连通块    = 8 邻接把黑像素分成块；一个块就是一个“点”（块>1px 说明点有直径或点粘连）
  最近邻    = 以块质心算两两最近距离（在像素上，越大表示点越稀）
用法：python tests\probe_reference_dots.py [目录或文件...]
"""
from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEF_DIR = Path(r"D:\玻璃画和剪纸画\别人作品")


def label_components(blk: np.ndarray):
    """8 邻接连通块标记（只遍历黑像素，黑像素少时很快）。返回 (标签图, 块列表[(ys,xs)])。"""
    h, w = blk.shape
    lab = np.zeros((h, w), dtype=np.int32)
    comps: list[tuple[np.ndarray, np.ndarray]] = []
    cur = 0
    ys_all, xs_all = np.nonzero(blk)
    for sy, sx in zip(ys_all.tolist(), xs_all.tolist()):
        if lab[sy, sx]:
            continue
        cur += 1
        q = deque([(sy, sx)])
        lab[sy, sx] = cur
        pts = []
        while q:
            y, x = q.popleft()
            pts.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and blk[ny, nx] and not lab[ny, nx]:
                        lab[ny, nx] = cur
                        q.append((ny, nx))
        arr = np.array(pts, dtype=np.int32)
        comps.append((arr[:, 0], arr[:, 1]))
    return lab, comps


def nn_distances(cent: np.ndarray, cell: float = 8.0) -> np.ndarray:
    """网格加速的最近邻距离（质心两两）。"""
    if len(cent) < 2:
        return np.zeros(0)
    grid: dict[tuple[int, int], list[int]] = {}
    for i, (y, x) in enumerate(cent):
        grid.setdefault((int(y // cell), int(x // cell)), []).append(i)
    out = np.empty(len(cent))
    for i, (y, x) in enumerate(cent):
        gy, gx = int(y // cell), int(x // cell)
        best = float("inf")
        r = 1
        while best == float("inf") and r <= 6:
            for dj in range(-r, r + 1):
                for di in range(-r, r + 1):
                    for j in grid.get((gy + dj, gx + di), ()):
                        if j == i:
                            continue
                        d = float(np.hypot(cent[j, 0] - y, cent[j, 1] - x))
                        if d < best:
                            best = d
            r += 1
        out[i] = best if best != float("inf") else np.nan
    return out


def report(path: Path) -> None:
    im = Image.open(path)
    a = np.asarray(im.convert("L"))
    h, w = a.shape
    blk = a < 128
    ink = 100.0 * blk.mean()
    white = 100.0 * (a == 255).mean()
    _, comps = label_components(blk)
    sizes = np.array([len(c[0]) for c in comps]) if comps else np.zeros(0, dtype=int)
    cent = np.array([[c[0].mean(), c[1].mean()] for c in comps]) if comps else np.zeros((0, 2))
    nn = nn_distances(cent) if len(cent) > 1 else np.zeros(0)

    print(f"\n== {path.name}  {w}x{h}  mode={im.mode}")
    print(f"   墨点 {ink:.2f}%   纯白背景 {white:.2f}%")
    print(f"   点的块数 {len(comps)}  = {len(comps) / (w * h) * 1e4:.1f} 点/万像素")
    if len(sizes):
        u, c = np.unique(sizes, return_counts=True)
        top = ", ".join(f"{int(x)}px×{int(n)}" for x, n in list(zip(u, c))[:6])
        print(f"   块大小分布：{top}{' …' if len(u) > 6 else ''}"
              f"   最大块 {sizes.max()}px  1px 块占 {100.0 * (sizes == 1).mean():.1f}%")
    if len(nn):
        print(f"   最近邻距离：中位 {np.nanmedian(nn):.1f}px  P10 {np.nanpercentile(nn, 10):.1f}px"
              f"  最小 {np.nanmin(nn):.1f}px")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    targets: list[Path] = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            targets += sorted(q for q in p.iterdir()
                              if q.suffix.lower() in {".png", ".bmp", ".jpg", ".jpeg"})
        elif p.is_file():
            targets.append(p)
    if not targets:
        targets = sorted(q for q in DEF_DIR.iterdir()
                         if q.suffix.lower() in {".png", ".bmp", ".jpg", ".jpeg"})
    for p in targets:
        try:
            report(p)
        except Exception as e:                      # noqa: BLE001
            print(f"\n!! {p.name}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
