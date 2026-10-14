r"""实验 4（视觉分类可行性）：把同一个人像做成四张"视觉模型看到的图"，供逐张试读

用户 2026-10-13 问：
  "我们要先试试，视觉模型能否分类，打标签？分类可以按五官或者明暗度？
   能否我们直接在对话中测试，我上传图片，这个做好的bmp？"

这一条要回答的是：**喂给视觉模型的那张图，长什么样、能读出什么**。
所以要先把候选"喂料形态"一次做齐（同一张真图、同一次出图）：

  A 彩色原图           —— 信息最多；但我们的产物里没有它（灰度管线）
  B 灰度预览 PNG       —— 现在的预览就是它（787px）
  C 1bit 点阵 BMP      —— 上机档；**放大后**才是人眼能辨的形状
  D 标尺参考图         —— 在 B 上叠 20% 网格 + 刻度 + 百分位坐标（用来对坐标，不是给人看的成品）
  E 明暗分区图         —— 按亮度分成 4 档上色（"按明暗度"分类的样子）

口径：全部来自 `kernel\image_lib\pipeline.render_grayscale`（同一套确定性管线，100mm@200dpi）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kernel"))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from image_lib import pipeline as PL  # noqa: E402

REAL = Path(r"D:\画台\projects\美女玻璃画\order-20261012-165706\src_one.jpeg")
OUT = ROOT / ".tmp-tests" / "exp-vision"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    if not REAL.is_file():
        print(f"找不到 {REAL}")
        return 2
    rep = PL.render_grayscale(REAL, OUT, knobs={"素描感强度": 0.7}, physical_mm=100.0, dpi=200, tag="vis")
    png, bmp = Path(rep["output"]), Path(rep["bmp"])
    W, H = rep["pixels"]
    print(f"出图：{png.name} / {bmp.name}  {W}×{H}px  墨点 {rep['metrics']['ink_pct']}%")

    # A 彩色原图（只读，复制一份到临时区，方便一起看）
    a = OUT / "A-彩色原图.png"
    Image.open(REAL).convert("RGB").resize((W, H), Image.LANCZOS).save(a)

    # B 灰度预览（就是产物本身，另存个清楚的名字）
    b = OUT / "B-灰度预览.png"
    Image.open(png).convert("L").save(b)

    # C 点阵：1bit BMP 原样 + 放大 3 倍（点阵必须放大才看得清形状）
    c1 = OUT / "C1-点阵原尺寸.png"
    Image.open(bmp).convert("L").save(c1)
    im_bin = Image.open(bmp).convert("L")
    c2 = OUT / "C2-点阵放大3倍.png"
    im_bin.resize((W * 3, H * 3), Image.NEAREST).save(c2)

    # D 标尺参考图：20% 网格 + 刻度（坐标对齐用）
    d = Image.open(png).convert("RGB")
    dr = ImageDraw.Draw(d)
    for i in range(1, 5):
        x = int(W * i / 5)
        y = int(H * i / 5)
        dr.line([(x, 0), (x, H)], fill=(255, 80, 80), width=2)
        dr.line([(0, y), (W, y)], fill=(255, 80, 80), width=2)
        dr.text((x + 3, 3), f"{i*20}%", fill=(255, 200, 0))
        dr.text((3, y + 3), f"{i*20}%", fill=(255, 200, 0))
    d.save(OUT / "D-标尺参考图.png")

    # E 明暗分区图：按亮度 4 档上色（这就是"按明暗度分类"的样子）
    g = np.asarray(Image.open(png).convert("L"), dtype=np.float64)
    q = np.quantile(g, [0.25, 0.5, 0.75])
    e = np.zeros((H, W, 3), dtype=np.uint8)
    e[g <= q[0]] = (20, 40, 160)        # 最暗 → 蓝
    e[(g > q[0]) & (g <= q[1])] = (40, 170, 90)     # 偏暗 → 绿
    e[(g > q[1]) & (g <= q[2])] = (240, 200, 60)    # 偏亮 → 黄
    e[g > q[2]] = (235, 90, 70)         # 最亮 → 红
    Image.fromarray(e).save(OUT / "E-明暗四档.png")
    print(f"明暗四档的分位阈值 = {[round(float(x), 1) for x in q]}")

    for p in sorted(OUT.iterdir()):
        if p.is_file():
            print(f"  {p.name}  {p.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
