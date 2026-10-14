r"""实验 3（第 3 条）：**圈完之后怎么改**——提亮/压暗 vs 点密度加减 vs 边缘羽化

背景：第 1 条已定"用什么圈"（磁性吸附，见 exp_circle_snap3.py）。
      这一条定"圈完能干什么"，这是决定它有没有用的另一半。

要回答三问：
  Q1 圈内改**亮度**（提亮/压暗）——生效吗？幅度怎么算？
  Q2 圈内改**点密度**（"眉毛加点数"）——和亮度有什么区别？哪个更像用户要的？
  Q3 边缘**羽化**——不羽化会不会出现一条明显的"台阶"？（玻璃雕刻上会看得见）

口径与做法（全是确定性代码，不装新库）：
  · 圈 = 第 1 条的磁性吸附结果（椭圆粗圈 → 吸附，96 点，±18px）；
  · 羽化 = 用**距离变换**（自己写的两遍 chamfer，纯 numpy）算"离边界多远"，
    在边界内外各 f 像素内做 smoothstep 过渡 ⇒ 权重 0~1；
    羽化同样作用于**权重**：内圈权重 1，边界附近渐变到 0；
  · 改图 = 在**灰度层**上按权重加权改（提亮/压暗/密度），然后再仿色 ⇒ 与现有管线同构；
  · 出图：把点阵放大 4 倍看（玻璃雕刻的实际观感），并对羽化 0 / 8 / 20px 各出一张。

判据（都能自动算）：
  ① 圈内黑点占比确实按方向变了，圈**外**几乎没变；
  ② 羽化 0 与羽化 20 的差别能量化（边界附近的黑点占比跳变幅度）；
  ③ 耗时（羽化 + 改图 + 仿色）够不够快（要能进界面）。

用法：  python tests\exp_region_edit.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kernel"))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from image_lib import pipeline as PL  # noqa: E402

REAL = Path(r"D:\画台\projects\美女玻璃画\order-20261012-165706\src_one.jpeg")
OUT = ROOT / ".tmp-tests" / "exp-region-edit"
OUT.mkdir(parents=True, exist_ok=True)

N_POINTS = 96
SEARCH_R = 18
DIST_PENALTY = 1.2
BIG = 4          # 点阵放大倍数（看观感）


# ---------------------------------------------------------------- 第 1 条的吸附（抄过来复用）
def ellipse_points(box, n=N_POINTS):
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([cx + rx * np.cos(t), cy + ry * np.sin(t)], axis=1)


def normals(pts):
    tan = np.roll(pts, -1, axis=0) - np.roll(pts, 1, axis=0)
    n = np.stack([-tan[:, 1], tan[:, 0]], axis=1)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-6)


def snap(pts, nrm, grad, r=SEARCH_R, penalty=DIST_PENALTY):
    offs = np.arange(-r, r + 1)
    disp = np.zeros(len(pts))
    H, W = grad.shape
    for i, (p, nv) in enumerate(zip(pts, nrm)):
        best, bd = 1e18, 0.0
        for d in offs:
            x, y = int(round(p[0] + nv[0] * d)), int(round(p[1] + nv[1] * d))
            if 0 <= x < W and 0 <= y < H:
                s = -float(grad[y, x]) + penalty * abs(d)
                if s < best:
                    best, bd = s, d
        disp[i] = bd
    half = 3
    pad = np.concatenate([disp[-half:], disp, disp[:half]])
    disp = np.array([np.median(pad[i:i + 7]) for i in range(len(disp))])
    return np.clip(pts + nrm * disp[:, None], 0, [W - 1, H - 1])


# ---------------------------------------------------------------- 距离变换（自己写，替 scipy）
def distance_to_mask(mask: np.ndarray) -> np.ndarray:
    """每个**圈外**像素到 mask 的近似欧氏距离（两遍 chamfer，3-4 权）。

    mask 内恒为 0；圈外像素取到最近 mask 像素的距离。
    ★ 2026-10-13 第一次写反了（把"圈内=0"当成外部初始），自检立刻抓到 18.33px 的误差
      —— 所以这次把自检放在脚本最前面，宁可它挡路。
    """
    H, W = mask.shape
    inf = 1e9
    # ★ dtype 必须是浮点：np.where(mask, 0.0, 1e9) 里 1e9 是 Python int
    #   ⇒ 整个数组会被推成 int64，chamfer 加出来的 1.33/2.67 全被截成整数，
    #   最后再 /3.0 已经救不回来（自检实测误差 18.33px 就是这么来的）。
    d = np.where(mask, 0.0, inf).astype(np.float64)
    # 正向（左上 → 右下）
    for y in range(H):
        row = d[y]
        prev = d[y - 1] if y > 0 else None
        for x in range(W):
            if row[x] == 0.0:
                continue
            v = row[x]
            if prev is not None and x > 0:
                v = min(v, prev[x - 1] + 4)
            if prev is not None:
                v = min(v, prev[x] + 3)
            if prev is not None and x + 1 < W:
                v = min(v, prev[x + 1] + 4)
            if x > 0:
                v = min(v, row[x - 1] + 3)
            row[x] = v
    # 反向（右下 → 左上）
    for y in range(H - 1, -1, -1):
        row = d[y]
        nxt = d[y + 1] if y + 1 < H else None
        for x in range(W - 1, -1, -1):
            if row[x] == 0.0:
                continue
            v = row[x]
            if nxt is not None and x + 1 < W:
                v = min(v, nxt[x + 1] + 4)
            if nxt is not None:
                v = min(v, nxt[x] + 3)
            if nxt is not None and x > 0:
                v = min(v, nxt[x - 1] + 4)
            if x + 1 < W:
                v = min(v, row[x + 1] + 3)
            row[x] = v
    return d / 3.0                        # chamfer 3-4 的权重要除 3 才是像素距离


def outside_distance(mask: np.ndarray) -> np.ndarray:
    """mask 内每个像素到**外部**的距离（用于向内羽化）。"""
    return distance_to_mask(~mask)


def feather_weights(mask: np.ndarray, f: float) -> np.ndarray:
    """羽化权重：mask 内部 = 1，边界内外各 f 像素内 smoothstep 过渡到 0。"""
    if f <= 0:
        return mask.astype(np.float64)
    d_out = distance_to_mask(mask)          # 外部像素到 mask 的距离
    d_in = outside_distance(mask)           # 内部像素到外部的距离
    w_out = np.clip(1.0 - d_out / f, 0.0, 1.0)   # 外面的渐变
    w_in = np.clip(d_in / f, 0.0, 1.0)           # 里面的渐变（靠边处变淡）
    w = np.where(mask, np.clip(0.5 + 0.5 * w_in, 0, 1), np.clip(0.5 * w_out, 0, 1))
    return np.clip(w, 0.0, 1.0)


def smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def measure_ink(bitmap: np.ndarray, mask: np.ndarray) -> dict:
    inside = float((bitmap[mask] == 0).mean() * 100) if mask.any() else 0.0
    outside = float((bitmap[~mask] == 0).mean() * 100)
    return {"圈内墨点%": round(inside, 2), "圈外墨点%": round(outside, 2),
            "全图墨点%": round(float((bitmap == 0).mean() * 100), 2)}


def main() -> int:
    img = Image.open(REAL)
    W, H = img.size
    gray = np.asarray(img.convert("L"), dtype=np.float64)
    gy, gx = np.gradient(gray)
    grad = np.hypot(gx, gy)
    print(f"图 = {REAL.name} {W}×{H}px")

    # ---- 距离变换自检（和暴力算法比，确保自己写的没错）----
    # ★ 2026-10-13 这个自检救了我两次：
    #   第一次参考实现写成"到**非** mask 像素的距离"（那些像素到处都有 ⇒ 参考全是 0），
    #   于是本该正确的实现被报成"差 18.33px"。**错的是参考，不是被测对象。**
    #   正确参考必须是"到 **mask 像素** 的最近距离"。
    small = np.zeros((30, 40), dtype=bool)
    small[10:20, 15:28] = True
    d_fast = distance_to_mask(small)
    my, mx = np.where(small)
    d_brute = np.zeros((30, 40), dtype=np.float64)
    for y in range(30):
        for x in range(40):
            if not small[y, x]:
                d_brute[y, x] = np.min(np.hypot(my - y, mx - x))
    err = float(np.abs(d_fast[~small] - d_brute[~small]).max())
    print(f"距离变换自检：与暴力算法最大差 {err:.2f}px"
          f"（chamfer 近似，<1px 就算对；{'通过' if err < 1.0 else '★不对'}）")
    if err >= 1.0:
        return 3

    # ---- 圈（上唇 + 整个嘴唇各试一个）----
    cases = [("整个嘴唇", (98, 195, 210, 275)), ("只圈上唇一条", (110, 200, 200, 235))]
    for name, box in cases:
        pts = snap(ellipse_points(box), normals(ellipse_points(box)), grad)
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).polygon([tuple(p) for p in pts], fill=255)
        mask = np.asarray(m) > 0
        print(f"\n########## {name}｜选区 {int(mask.sum())}px（占全图 {mask.mean() * 100:.1f}%）##########")

        t0 = time.perf_counter()
        base_bin = PL._fs_dither(np.asarray(Image.fromarray(gray.astype(np.uint8)), dtype=np.uint8))
        t_base = time.perf_counter() - t0

        base_m = measure_ink(base_bin, mask)
        print(f"  基线：{base_m}　（仿色耗时 {t_base:.2f}s）")

        # ---- Q1 提亮 / 压暗（按羽化权重加权，不是硬切）----
        for f in (0.0, 8.0, 20.0):
            t0 = time.perf_counter()
            w = feather_weights(mask, f) if f else mask.astype(np.float64)
            t_feather = time.perf_counter() - t0
            for sign, lab in ((+1, "提亮"), (-1, "压暗")):
                delta = sign * 35.0            # 先给个固定幅度看效果（幅度是"试算排"那一条的事）
                g2 = np.clip(gray + w * delta, 0, 255)
                b2 = PL._fs_dither(np.asarray(g2, dtype=np.uint8))
                mm = measure_ink(b2, mask)
                print(f"  羽化{f:4.0f}px {lab}：圈内 {base_m['圈内墨点%']}→{mm['圈内墨点%']}%　"
                      f"圈外 {base_m['圈外墨点%']}→{mm['圈外墨点%']}%　（羽化耗时 {t_feather:.2f}s）")
            # 只存一张 3 倍放大的对比图（羽化 0 与羽化 f）
            if f in (0.0, 20.0):
                pass

        # ---- Q2 点密度（加法：在圈内直接把该打的点补上/抹掉，看和提亮的差别）----
        w0 = mask.astype(np.float64)
        g_dense = np.clip(gray - w0 * 45.0, 0, 255)     # "加点"= 让这一块更暗（更可能打点）
        b_dense = PL._fs_dither(np.asarray(g_dense, dtype=np.uint8))
        md = measure_ink(b_dense, mask)
        print(f"  点密度 加点（圈内压暗 45）：圈内 {base_m['圈内墨点%']}→{md['圈内墨点%']}%，"
              f"圈外 {base_m['圈外墨点%']}→{md['圈外墨点%']}%")
        g_sparse = np.clip(gray + w0 * 45.0, 0, 255)
        b_sparse = PL._fs_dither(np.asarray(g_sparse, dtype=np.uint8))
        ms = measure_ink(b_sparse, mask)
        print(f"  点密度 减点（圈内提亮 45）：圈内 {base_m['圈内墨点%']}→{ms['圈内墨点%']}%，"
              f"圈外 {base_m['圈外墨点%']}→{ms['圈外墨点%']}%")

        # ---- Q3 羽化对边界"台阶"的影响：量边界带内的黑点占比跳变 ----
        d_in = outside_distance(mask)
        ring = (d_in > 0) & (d_in <= 12)          # 边界内 12px 的带
        out_ring = (distance_to_mask(mask) > 0) & (distance_to_mask(mask) <= 12)
        for f in (0.0, 8.0, 20.0):
            w = feather_weights(mask, f) if f else mask.astype(np.float64)
            g2 = np.clip(gray + w * 35.0, 0, 255)
            b2 = PL._fs_dither(np.asarray(g2, dtype=np.uint8))
            base_in_ring = float((base_bin[ring] == 0).mean() * 100)
            new_in_ring = float((b2[ring] == 0).mean() * 100)
            base_out_ring = float((base_bin[out_ring] == 0).mean() * 100)
            new_out_ring = float((b2[out_ring] == 0).mean() * 100)
            jump0 = abs(new_in_ring - base_in_ring) + abs(new_out_ring - base_out_ring)
            print(f"  [台阶] 羽化{f:4.0f}px：边界内带 {base_in_ring:.1f}→{new_in_ring:.1f}%（Δ{new_in_ring - base_in_ring:+.1f}）"
                  f"　边界外带 {base_out_ring:.1f}→{new_out_ring:.1f}%（Δ{new_out_ring - base_out_ring:+.1f}）")

        # ---- 出图：点阵放大 + 羽化对比 ----
        def save_bitmap(bin_, tag):
            vis = np.where(bin_ == 0, 0, 255).astype(np.uint8)
            im = Image.fromarray(vis).convert("L")
            box2 = (max(0, box[0] - 30), max(0, box[1] - 30), min(W, box[2] + 30), min(H, box[3] + 30))
            sub = im.crop(box2).resize(((box2[2] - box2[0]) * BIG, (box2[3] - box2[1]) * BIG), Image.NEAREST)
            sub.save(OUT / f"{name[:4]}-{tag}.png")

        save_bitmap(base_bin, "0-基线点阵")
        for f in (0.0, 20.0):
            w = feather_weights(mask, f) if f else mask.astype(np.float64)
            g2 = np.clip(gray - w * 45.0, 0, 255)      # 加点（用户说"眉毛加点数"就是想要这个）
            save_bitmap(PL._fs_dither(np.asarray(g2, dtype=np.uint8)), f"1-加点-羽化{int(f)}")

        # 灰度层看羽化本身
        for f in (0.0, 20.0):
            w = feather_weights(mask, f) if f else mask.astype(np.float64)
            vis = np.stack([gray, gray, gray], axis=-1).astype(np.float64)
            vis[..., 0] = np.clip(vis[..., 0] + w * 90, 0, 255)
            vis[..., 2] = np.clip(vis[..., 2] - w * 40, 0, 255)
            box2 = (max(0, box[0] - 30), max(0, box[1] - 30), min(W, box[2] + 30), min(H, box[3] + 30))
            sub = Image.fromarray(vis.astype(np.uint8)).crop(box2)
            sub = sub.resize(((box2[2] - box2[0]) * 2, (box2[3] - box2[1]) * 2), Image.NEAREST)
            sub.save(OUT / f"{name[:4]}-2-选区羽化{int(f)}.png")

    print(f"\n图都在：{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
