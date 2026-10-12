r"""只读探针：逐个旋钮验它到底动不动（不动 = "假装生效"，是硬伤）。

用法：  python tests\probe_knobs.py
不联网、不花钱；产物写进隔离目录。**只报事实，不下结论。**
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kernel"))

TMP = ROOT / ".tmp-tests" / "probe-knobs"
if TMP.exists():
    shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)

from PIL import Image, ImageDraw  # noqa: E402

from image_lib import pipeline as PL  # noqa: E402


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def make_images() -> dict[str, Path]:
    out = {}
    # 1) 平滑渐变（低高频）
    im = Image.new("L", (120, 160))
    px = im.load()
    for y in range(160):
        for x in range(120):
            px[x, y] = int((x / 119) * 200 + (y / 159) * 55) % 256
    p1 = TMP / "smooth.png"
    im.save(p1)
    out["平滑渐变"] = p1

    # 2) 有细节的图（棋盘 + 细线 + 灰阶），接近"人像头发/皱纹"那类高频
    im2 = Image.new("L", (200, 200), 170)
    d = ImageDraw.Draw(im2)
    for i in range(0, 200, 8):
        d.line([(i, 0), (i, 200)], fill=40, width=1)
    for i in range(0, 200, 10):
        d.line([(0, i), (200, i)], fill=220, width=1)
    d.ellipse([40, 40, 160, 160], outline=20, width=3)
    d.ellipse([80, 80, 100, 100], fill=10)
    p2 = TMP / "detail.png"
    im2.save(p2)
    out["有细节"] = p2
    return out


def main() -> int:
    imgs = make_images()
    knobs = [k.name for k in __import__("knobs").KNOBS]
    print("旋钮（全部）：", knobs)
    print("已实现：", PL.IMPLEMENTED_KNOBS)
    print("缺口  ：", PL.CAPABILITY_GAPS)
    print()

    for tag, src in imgs.items():
        base = PL.render_grayscale(src, TMP / f"out_{tag}", knobs={}, physical_mm=60, dpi=150, tag="base")
        base_sha = sha(Path(base["output"]))
        print(f"===== {tag}（{src.name}）  基线 sha={base_sha}  指标={base['metrics']}")
        for name in knobs:
            for val in (1.0, -1.0) if name in ("整体明暗", "明暗反差") else (0.9,):
                rep = PL.render_grayscale(src, TMP / f"out_{tag}", knobs={name: val},
                                          physical_mm=60, dpi=150, tag=f"k_{name}_{val}")
                s = sha(Path(rep["output"]))
                moved = "变了" if s != base_sha else "★ 没变"
                print(f"  {name}={val:<5} sha={s} ink {base['metrics']['ink_pct']}→{rep['metrics']['ink_pct']}%  "
                      f"mean {base['metrics']['mean']}→{rep['metrics']['mean']}  {moved}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
