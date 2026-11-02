r"""全自动跑一轮：不带任何用户输入，用 R1~R4 规则出图 + 自检。

关键对照：点绘引擎吃的是“仿色前的灰度场”。画台默认带 素描感强度=0.7（线稿风格），
线稿靠线条表达明暗 —— 打成点会不会碎掉？所以同时出两版：
  ① 素描感 0.7（与那一单相同）
  ② 素描感 0.0（照片式连续调）
其余完全一样：R1（点不相邻）、目标墨量 8%、背景纯白（自动 floodfill 推白）。

不动画台本体：只 import 内核，用 spy 截获它“仿色前的那张灰度”。
用法：python tests\exp_auto_fullrun.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / ".tmp-tests" / "auto-export"
SRC = ROOT / "projects" / "测试图片" / "order-20261017-201207" / "src_test.jpg"

from kernel.image_lib import pipeline as P            # noqa: E402

BG_CUT = 244.0
TARGET_INK = 0.08


def capture_gray(knobs: dict) -> np.ndarray:
    """跑一次内核，截获“仿色前最终灰度”。内核代码一行不改。"""
    cap: dict = {}
    orig = P._fs_dither

    def spy(g):
        cap["g"] = np.asarray(g, dtype=np.float64).copy()
        return orig(g)

    P._fs_dither = spy
    try:
        with tempfile.TemporaryDirectory() as td:
            P.render_grayscale(SRC, td, knobs=knobs, physical_mm=100.0, dpi=200, tag="spy")
    finally:
        P._fs_dither = orig
    return cap["g"]


def stretch_contrast(gray: np.ndarray, lo_p: float = 3.0, hi_p: float = 97.0) -> np.ndarray:
    """自动拉对比：只在“主体像素”（未推白的部分）上量分位，把 p3→0、p97→255。

    为什么必须这步：R1 的“点不相邻”把局部密度上限锁在 ~25%，若灰度原本挤在
    200~247 这一段，映射后整张都是 5~10% 的一片灰 —— 人脸结构就没了（实测过）。
    """
    sub = gray[gray < 254.0]
    if sub.size < 100:
        return gray
    lo = float(np.percentile(sub, lo_p))
    hi = float(np.percentile(sub, hi_p))
    if hi - lo < 1.0:
        return gray
    out = (gray - lo) / (hi - lo) * 255.0
    out = np.clip(out, 0.0, 255.0)
    out[gray >= 254.0] = 255.0        # 已经推白的背景不许回灰
    return out


def whiten_background(gray: np.ndarray, thresh: int | None = None) -> np.ndarray:
    """自动把“从画面四周连通的近白区域”推成纯白（R4 背景纯白）。

    阈值不写死：先量四条边框的灰度中位数（那就是背景亮度），再往下留 4 级余量。
    """
    from collections import deque

    h, w = gray.shape
    ring = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
    bg_level = float(np.median(ring))
    if thresh is None:
        thresh = int(bg_level) - 4
    light = gray >= thresh
    seen = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    for x in range(w):
        for y in (0, h - 1):
            if light[y, x] and not seen[y, x]:
                seen[y, x] = True
                q.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if light[y, x] and not seen[y, x]:
                seen[y, x] = True
                q.append((y, x))
    while q:
        y, x = q.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and light[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                q.append((ny, nx))
    out = gray.copy()
    out[seen] = 255.0
    return out


def sample_no_adjacent(darkness: np.ndarray, gain: float, seed: int = 3) -> np.ndarray:
    """按暗度概率撒 1px 点；任何已落点的 8 邻接不再落点 ⇒ 最近邻 >= 2px（R1）。"""
    h, w = darkness.shape
    rng = np.random.default_rng(seed)
    flat = darkness.ravel()
    order = rng.permutation(flat.size)
    keep = rng.random(flat.size) < np.minimum(1.0, flat[order] * gain)
    dots = np.zeros((h, w), dtype=bool)
    for idx in order[keep].tolist():
        y, x = divmod(idx, w)
        if dots[y, x]:
            continue
        y0, y1 = max(0, y - 1), min(h, y + 2)
        x0, x1 = max(0, x - 1), min(w, x + 2)
        if dots[y0:y1, x0:x1].any():
            continue
        dots[y, x] = True
    return dots


def auto_dots(gray: np.ndarray, target: float = TARGET_INK) -> np.ndarray:
    dark = (255.0 - gray) / 255.0
    dark[gray >= BG_CUT] = 0.0
    lo, hi = 0.02, 12.0
    dots = None
    for _ in range(10):
        mid = 0.5 * (lo + hi)
        d = sample_no_adjacent(dark, mid)
        if d.mean() < target:
            lo = mid
        else:
            hi = mid
        dots = d
    return dots


def checks(name: str, dots: np.ndarray) -> bool:
    h, w = dots.shape
    nb = np.zeros_like(dots)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            ys = slice(max(0, dy), h + min(0, dy))
            xs = slice(max(0, dx), w + min(0, dx))
            ys2 = slice(max(0, -dy), h + min(0, -dy))
            xs2 = slice(max(0, -dx), w + min(0, -dx))
            nb[ys, xs] |= dots[ys2, xs2]
    adj = int((nb & dots).sum())
    ink = 100 * dots.mean()
    bg = 100 * dots[0:120, 0:120].mean()
    N = 8
    bh, bw = h // N, w // N
    blocks = [100 * dots[j * bh:(j + 1) * bh, i * bw:(i + 1) * bw].mean()
              for j in range(N) for i in range(N)]
    ok = (adj == 0) and (4.0 <= ink <= 10.0) and (bg < 0.5)
    print(f"  [{name}] 墨点 {ink:.2f}%（R3 4~10%）| 相邻点 {adj}（R1=0）| 背景 {bg:.2f}%（R4<0.5）"
          f" | 分块密度 {min(blocks):.1f}~{max(blocks):.1f}%  => {'达标' if ok else '不达标'}")
    return ok


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tags = {"sketch07": {"素描感强度": 0.7}, "photo00": {"素描感强度": 0.0}}
    imgs: dict[str, np.ndarray] = {}
    for name, knobs in tags.items():
        t0 = time.perf_counter()
        gray = capture_gray(knobs)
        g = gray
        print(f"\n== {name}: {gray.shape[1]}x{gray.shape[0]}  均值 {g.mean():.1f}"
              f"  p5 {np.percentile(g, 5):.0f}  p50 {np.percentile(g, 50):.0f}"
              f"  p95 {np.percentile(g, 95):.0f}  取灰度 {time.perf_counter() - t0:.1f}s")
        gw = whiten_background(gray)
        ring = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
        sub = gw[gw < 254.0]
        print(f"   背景亮度(边框灰度中位) {float(np.median(ring)):.0f}"
              f"  推白后：均值 {gw.mean():.1f}  纯白像素 {100 * (gw >= 255).mean():.1f}%"
              f"  主体 p3~p97 = {np.percentile(sub, 3):.0f}~{np.percentile(sub, 97):.0f}")
        gw = stretch_contrast(gw)
        print(f"   拉对比后：主体 p3~p97 = {np.percentile(gw[gw < 254.0], 3):.0f}~"
              f"{np.percentile(gw[gw < 254.0], 97):.0f}")
        dots = auto_dots(gw)
        checks(name, dots)
        img = np.where(dots, 0, 255).astype(np.uint8)
        imgs[name] = img
        Image.fromarray(img).save(OUT / f"auto-{name}.png")
        Image.fromarray(img).convert("1").save(OUT / f"auto-{name}.bmp")
        print(f"   写出 auto-{name}.png / .bmp")

    names = list(imgs)
    h, w = imgs[names[0]].shape
    gap = 14
    cv = Image.new("RGB", (w * len(names) + gap * (len(names) - 1), h), (255, 255, 255))
    for i, n in enumerate(names):
        cv.paste(Image.fromarray(np.stack([imgs[n]] * 3, -1)), (i * (w + gap), 0))
    p = OUT / "auto-对照-左素描07-右照片00.png"
    cv.save(p)
    print("\n写出:", p, f"（左={names[0]}  右={names[1]}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
