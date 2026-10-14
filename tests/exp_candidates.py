r"""实验 2（第 2 条）：**试算排**——一次给 4 组参数出小图，用户挑一个

要回答的问题（全部可自动量，不用人眼）：
  Q1 4 组候选**到底有没有差别**？（差别太小 = 4 张长一样 = 这个功能是摆设）
  Q2 小图能不能**代表**大图？（小图按同一套参数出，比例、观感是否一致 ⇒ 用"墨点占比"对齐口径）
  Q3 一排 4 张**要多久**？（v1 的速度前提：60px 约 0.12s）
  Q4 小图必须**不落账**：不写 out\、不进 history、不出上机档 —— 这一条是这套能不能用的分水岭

做法：
  · 基准参数 = 现在真机会给的 `素描感强度 0.7`（用户真实单就是这档）；
  · 候选 = 基准 ±0.1 与 ±0.25（共 4 档），**同一张图、同一尺寸**，只差这一个旋钮；
  · 小图走**同一套**确定性管线（PL.render_grayscale），但输出到临时目录 `cand\`，
    并且**只读它的指标、不把它当版本**（这就是"不算账的试算"）；
  · 拼一张对比条：基准 | A | B | C | D，各自标上墨点占比 ⇒ 给人眼判 + 给数字判。

用法：  python tests\exp_candidates.py
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kernel"))

from PIL import Image, ImageDraw  # noqa: E402

from image_lib import pipeline as PL  # noqa: E402

REAL = Path(r"D:\画台\projects\美女玻璃画\order-20261012-165706\src_one.jpeg")
OUT = ROOT / ".tmp-tests" / "exp-candidates"
if OUT.exists():
    shutil.rmtree(OUT, ignore_errors=True)
CAND = OUT / "cand"          # ★ 候选的临时落点（不是 projects\...\out\）
CAND.mkdir(parents=True)

THUMB_MM = 40.0              # 小图物理尺寸（mm）——够看清疏密，又不费时
THUMB_DPI = 160              # 小图 dpi ⇒ 40mm@160dpi ≈ 252px
KEY = "素描感强度"
BASE = 0.7
CANDIDATES = [("A", BASE - 0.25), ("B", BASE - 0.10), ("C", BASE + 0.10), ("D", BASE + 0.25)]


def main() -> int:
    if not REAL.is_file():
        print(f"找不到 {REAL}")
        return 2
    print(f"图 = {REAL.name}")
    print(f"基准 = {KEY} {BASE}　候选 = " + "　".join(f"{k}={v:.2f}" for k, v in CANDIDATES))
    print(f"小图规格 = 长边 {THUMB_MM:g}mm @{THUMB_DPI}dpi　⇒ 候选临时目录 {CAND}")
    print("（★ 候选只落在这个临时目录，**不进** projects\\...\\out\\、不进 history、不出上机档）\n")

    shots = []
    t0 = time.perf_counter()
    base = PL.render_grayscale(REAL, CAND, knobs={KEY: BASE},
                               physical_mm=THUMB_MM, dpi=THUMB_DPI, tag="base")
    t_base = time.perf_counter() - t0
    shots.append(("基准", BASE, base, t_base))
    print(f"基准：{base['pixels'][0]}×{base['pixels'][1]}px　墨点 {base['metrics']['ink_pct']}%　"
          f"耗时 {t_base * 1000:.0f}ms")

    for tag, val in CANDIDATES:
        t0 = time.perf_counter()
        r = PL.render_grayscale(REAL, CAND, knobs={KEY: val},
                                physical_mm=THUMB_MM, dpi=THUMB_DPI, tag=f"cand{tag}")
        dt = time.perf_counter() - t0
        shots.append((tag, val, r, dt))
        d = r["metrics"]["ink_pct"] - base["metrics"]["ink_pct"]
        print(f"候选 {tag}（{KEY}={val:.2f}）：墨点 {r['metrics']['ink_pct']}%（相对基准 {d:+.1f} 个点）"
              f"　暗部 {r['metrics']['dark_pct']}%　耗时 {dt * 1000:.0f}ms")

    inks = [s[2]["metrics"]["ink_pct"] for s in shots[1:]]
    spread = max(inks) - min(inks)
    total_ms = sum(s[3] for s in shots) * 1000
    print(f"\n★ Q1 候选之间的差距 = 墨点 {min(inks)}% ~ {max(inks)}%（跨幅 {spread:.1f} 个百分点）"
          f" ⇒ {'看得出差别，可用' if spread >= 4 else '★差别太小，等于白给'}")
    print(f"★ Q3 一排 4 张 + 基准共 5 张，合计 {total_ms:.0f}ms（单张均值 {total_ms / len(shots):.0f}ms）")

    # ---- 拼对比条：基准 | A | B | C | D（灰度预览）----
    ims = [Image.open(s[2]["output"]).convert("L") for s in shots]
    w, h = ims[0].size
    pad, lab = 8, 26
    sheet = Image.new("L", (len(ims) * (w + pad) + pad, h + lab + pad * 2), 255)
    d = ImageDraw.Draw(sheet)
    for i, (im, s) in enumerate(zip(ims, shots)):
        x = pad + i * (w + pad)
        sheet.paste(im, (x, lab))
        tag, val = s[0], s[1]
        cap = f"{tag}  {KEY}={val:.2f}  ink{s[2]['metrics']['ink_pct']}%"
        d.text((x, 6), cap.encode("ascii", "replace").decode(), fill=0)
    sheet_path = OUT / "对比条-五张-灰度.png"
    sheet.save(sheet_path)
    print(f"\n对比条（灰度）已存：{sheet_path}")

    # ---- 点阵对比条：用户真正判断的是"打出来的点"----
    bins = [Image.open(s[2]["bmp"]).convert("L") for s in shots]
    bw, bh = bins[0].size
    Z = 3
    sheet2 = Image.new("L", (len(bins) * (bw + pad) + pad, bh + lab + pad * 2), 255)
    d2 = ImageDraw.Draw(sheet2)
    for i, (im, s) in enumerate(zip(bins, shots)):
        x = pad + i * (bw + pad)
        sheet2.paste(im.resize((bw, bh), Image.NEAREST), (x, lab))
        cap = f"{s[0]}  {s[1]:.2f}  ink{s[2]['metrics']['ink_pct']}%"
        d2.text((x, 6), cap.encode("ascii", "replace").decode(), fill=0)
    p2 = OUT / "对比条-五张-点阵.png"
    sheet2.save(p2)
    print(f"对比条（点阵 1:1）已存：{p2}")

    # 再放大 3 倍只看中间那一块（疏密差最明显的地方）
    cw, ch = bw // 3, bh // 3
    sheet3 = Image.new("L", (len(bins) * (cw * Z + pad) + pad, ch * Z + lab + pad * 2), 255)
    d3 = ImageDraw.Draw(sheet3)
    for i, (im, s) in enumerate(zip(bins, shots)):
        crop = im.crop((bw // 2 - cw // 2, bh // 2 - ch // 2,
                        bw // 2 + cw // 2, bh // 2 + ch // 2)).resize((cw * Z, ch * Z), Image.NEAREST)
        x = pad + i * (cw * Z + pad)
        sheet3.paste(crop, (x, lab))
        cap = f"{s[0]}  {s[1]:.2f}  ink{s[2]['metrics']['ink_pct']}%"
        d3.text((x, 6), cap.encode("ascii", "replace").decode(), fill=0)
    p3 = OUT / "对比条-五张-点阵放大3倍.png"
    sheet3.save(p3)
    print(f"对比条（点阵中心放大 {Z}×）已存：{p3}")

    # ---- Q2：小图能不能代表大图（同参数，小图 vs 全尺寸，比"墨点占比"这个口径）----
    full = PL.render_grayscale(REAL, CAND, knobs={KEY: BASE}, physical_mm=100.0, dpi=200, tag="full")
    print(f"\n★ Q2 同参数下：小图（{base['pixels'][0]}×{base['pixels'][1]}px）墨点 {base['metrics']['ink_pct']}%"
          f"　大图（{full['pixels'][0]}×{full['pixels'][1]}px）墨点 {full['metrics']['ink_pct']}%"
          f"　差 {abs(base['metrics']['ink_pct'] - full['metrics']['ink_pct']):.1f} 个点")
    print("   （差得越小 ⇒ 用小图判断「该选哪个」越可靠；差得大 ⇒ 小图会骗人）")

    # ---- Q4：候选有没有污染账 ----
    print(f"\n★ Q4 候选落点里的文件（应当只在 {CAND}，且 projects 那边一点没动）：")
    for p in sorted(CAND.iterdir()):
        print(f"    {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
