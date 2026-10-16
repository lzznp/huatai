r"""诊断图 2：**先把框画对，再量密度**（上一版框错了：框住的是刘海/额头，不是眉毛）

上一版（exp_diag_density.py）的教训（决策 #29 再次生效）：
  1-灰度+标注.png 人眼一看就知道——那三条黄框落在**刘海和额头**上；
  左眉被刘海盖住，右眉露在外面（约 x 190~255 / y 55~75），
  而三个框都停在 y≤62 ⇒ **量到的是头发的密度，不是眉毛的**。

这一版做两件事：
  ① **左右眉毛分别框**（按图1看到的位置），并**同图带上"刘海/额头"对照带**；
  ② 除了"局部黑点密度"，再量**灰度均值**——用户当年是在**灰度图**上用 PS 减淡工具的，
     所以"灰度层能不能分开眉毛和皮肤"和"点阵层能不能分开"是**两个不同的问题**，都量。

口径：图 = src_one.jpeg（400×380）；点阵 = Floyd–Steinberg（阈值 127.5，与内核同口径）。
★ 坐标必须画出来给人眼复核（决策 #29）——本文件同时输出标注图。

用法：python tests\exp_diag_density2.py
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
from probe_dot_density import R, local_density  # noqa: E402

OUT = ROOT / ".tmp-tests" / "diag-density"
ZOOM = 4
# 小圈：只圈右眉（那一带露在外面）
RIGHT_BROW_BOX = (185, 45, 265, 85)

# ★ 新的一组框：按图1看到的实际位置重新框；每类各给"眉毛 / 对照"两组
NEW_BANDS = [
    # 眉毛（露出来的那条）
    ("右眉", 190, 55, 255, 78),
    # 对照：右眉正上方（额头，应先亮）
    ("右眉上额头", 190, 30, 255, 52),
    # 对照：刘海（应最暗）
    ("左上刘海", 55, 30, 150, 62),
    ("右上刘海", 265, 0, 400, 60),
    # 对照：脸颊皮肤（应最亮）
    ("左脸颊皮肤", 60, 120, 140, 180),
]


def stats(a: np.ndarray) -> str:
    if a.size == 0:
        return "（空）"
    return (f"中位 {np.median(a):5.1f}  均值 {a.mean():5.1f}  标准差 {a.std():5.1f}"
            f"  P25 {np.percentile(a, 25):5.1f}  P75 {np.percentile(a, 75):5.1f}")


def main() -> int:
    if not T.DEFAULT_REAL.exists():
        print(f"找不到真图：{T.DEFAULT_REAL}")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)

    gray = np.asarray(Image.open(T.DEFAULT_REAL).convert("L"), dtype=np.float64)
    h, w = gray.shape
    dots = T.fs_dither(gray)
    dens = local_density(dots, R)

    # ---------- 标注图（新框）----------
    g1 = Image.fromarray(np.stack([gray] * 3, axis=-1).astype(np.uint8))
    d1 = ImageDraw.Draw(g1)
    for x in range(0, w, 50):
        d1.line([(x, 0), (x, 6)], fill=(255, 0, 255))
        d1.text((x + 1, 7), str(x), fill=(255, 0, 255))
    for y in range(0, h, 50):
        d1.line([(0, y), (6, y)], fill=(255, 0, 255))
        d1.text((7, y + 1), str(y), fill=(255, 0, 255))
    for name, x0, y0, x1, y1 in NEW_BANDS:
        color = (0, 255, 0) if name in ("右眉",) else (255, 255, 0)
        d1.rectangle([x0, y0, x1, y1], outline=color, width=2)
        d1.text((x0 + 2, y0 + 2), name, fill=color)
    d1.ellipse([RIGHT_BROW_BOX[0], RIGHT_BROW_BOX[1], RIGHT_BROW_BOX[2], RIGHT_BROW_BOX[3]],
               outline=(0, 255, 255), width=1)
    g1.save(OUT / "5-灰度+新框.png")

    # ---------- 两层指标：灰度 与 点阵密度 ----------
    print(f"图 = {T.DEFAULT_REAL.name}  {w}×{h}px　全图墨点 {100 * dots.mean():.1f}%")
    print(f"局部密度窗 {2 * R + 1}×{2 * R + 1}　（灰度 0=黑 255=白）\n")
    print("=" * 100)
    print("★ 两层分开量：『灰度均值』和『局部黑点密度』是两件事")
    print("=" * 100)
    print(f"  {'带子':14s} {'像素数':>7s} | {'灰度均值':>8s} {'灰度中位':>8s} | "
          f"{'点阵黑点':>8s} {'密度中位':>8s}")
    print("  " + "-" * 92)
    rows = []
    for name, x0, y0, x1, y1 in NEW_BANDS:
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        gsub = gray[y0:y1, x0:x1].ravel()
        dsub = dens[y0:y1, x0:x1].ravel()
        dsub = dsub[np.isfinite(dsub)]
        blk = 100.0 * dots[y0:y1, x0:x1].mean()
        rows.append((name, gsub.mean(), np.median(gsub), blk, np.median(dsub) * 100))
        print(f"  {name:14s} {gsub.size:7d} | {gsub.mean():8.1f} {np.median(gsub):8.1f} | "
              f"{blk:7.1f}% {np.median(dsub) * 100:7.1f}%")

    # ---------- 关键判别：眉毛 vs 皮肤 分得开吗 ----------
    print()
    print("=" * 100)
    print("★ 判别：『右眉』能不能和『右眉上额头』『脸颊皮肤』分开？")
    print("=" * 100)
    by = {r[0]: r for r in rows}
    brow = by.get("右眉")
    skin = by.get("左脸颊皮肤")
    fore = by.get("右眉上额头")
    if brow and skin and fore:
        g_gap_skin = skin[1] - brow[1]
        g_gap_fore = fore[1] - brow[1]
        d_gap_skin = brow[3] - skin[3]
        d_gap_fore = brow[3] - fore[3]
        print(f"  灰度层：眉 {brow[1]:.1f}  vs  额头 {fore[1]:.1f}（差 {g_gap_fore:+.1f}）"
              f"  vs  脸颊 {skin[1]:.1f}（差 {g_gap_skin:+.1f}）")
        print(f"         （灰度越小越暗；差为正 = 眉毛更暗）")
        print(f"  点阵层：眉 {brow[3]:.1f}%  vs  额头 {fore[3]:.1f}%（差 {d_gap_fore:+.1f}）"
              f"  vs  脸颊 {skin[3]:.1f}%（差 {d_gap_skin:+.1f}）")
        print()
        if d_gap_skin > 10 and d_gap_fore > 0:
            print("  ⇒ 点阵层：眉毛**比皮肤密**，且**比额头也密** ⇒ 密度可以拿来分。")
        elif d_gap_skin > 10:
            print("  ⇒ 点阵层：眉毛比皮肤密，但**跟额头分不开** ⇒ 只能分『眉+额头』和『皮肤』。")
        else:
            print("  ⇒ 点阵层：连皮肤都分不太开 ⇒ 密度不能单独拿来分。")

    # ---------- 视觉证明：稀疏后眉毛像不像 ----------
    pts = T.ellipse_points(RIGHT_BROW_BOX)
    mask = T.polygon_mask((h, w), pts)
    thin, note = T.dots_edit(dots, mask, 0.7)
    print(f"\n只圈右眉 {RIGHT_BROW_BOX}：{note}")

    x0, y0, x1, y1 = 175, 25, 275, 100
    def strip(dd, marked=None):
        vis = np.full((h, w, 3), 255, dtype=np.uint8)
        vis[dd] = np.array([40, 40, 40], dtype=np.uint8)
        if marked is not None:
            vis[marked] = np.array([230, 30, 30], dtype=np.uint8)
        return Image.fromarray(vis[y0:y1, x0:x1]).resize(
            ((x1 - x0) * ZOOM, (y1 - y0) * ZOOM), Image.NEAREST)

    deleted = dots & mask & ~thin
    a = strip(dots)
    b = strip(thin, deleted)
    cmp_img = Image.new("RGB", (a.width * 2 + 12, a.height + 26), (255, 255, 255))
    cmp_img.paste(a, (0, 26)); cmp_img.paste(b, (a.width + 12, 26))
    dc = ImageDraw.Draw(cmp_img)
    dc.text((4, 6), f"原图点阵（右眉）{ZOOM}x", fill=(0, 0, 0))
    dc.text((a.width + 16, 6), "只圈右眉、稀疏到 70%（红=删掉的点）", fill=(0, 0, 0))
    cmp_img.save(OUT / "6-右眉稀疏对比.png")

    print(f"\n图都在：{OUT}")
    print("人眼判据：")
    print("  · 图5：绿框（右眉）**框住了眉毛没有**？")
    print("  · 图6：稀疏 30% 之后（右）**还像不像眉毛**？会不会变成断断续续的虚点？")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
