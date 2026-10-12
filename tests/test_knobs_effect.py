r"""画台 · 旋钮是否**真的动**（离线，不联网、不花钱）

用途：把"能力清单是诚实的"这句话变成**可自动验的判据**。
- 每个标「已实现」的旋钮 ⇒ 在合适输入下**必须改变产物**（sha256 变）
- 每个标「缺口」的旋钮   ⇒ **必须不改变产物**（sha256 完全相同）——否则清单在骗人

★ 输入要用**有高频细节**的图：USM（细节保留度）对平滑渐变本来就不起作用，
  拿平滑图去测会得出"这个旋钮坏了"的**假结论**（本文件建立当天就先踩了这个坑）。

用法：  python tests\test_knobs_effect.py
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kernel"))

TMP = ROOT / ".tmp-tests" / "knob-effect"
if TMP.exists():
    shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)

from PIL import Image, ImageDraw  # noqa: E402

import knobs as K  # noqa: E402
from image_lib import pipeline as PL  # noqa: E402

PASS = 0
FAIL: list[str] = []


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"[OK] {msg}")


def bad(msg: str, detail: str) -> None:
    FAIL.append(f"{msg} —— {detail}")
    print(f"[FAIL] {msg} —— {detail}")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def detail_image() -> Path:
    """有高频细节的图（细线 + 棋盘 + 边缘），尽量像"头发/皱纹"那一类。"""
    im = Image.new("L", (240, 240), 170)
    d = ImageDraw.Draw(im)
    for i in range(0, 240, 6):
        d.line([(i, 0), (i, 240)], fill=45, width=1)
    for i in range(0, 240, 9):
        d.line([(0, i), (240, i)], fill=225, width=1)
    d.ellipse([50, 50, 190, 190], outline=15, width=4)
    d.ellipse([95, 95, 120, 120], fill=8)
    d.rectangle([150, 30, 210, 70], fill=200, outline=30, width=2)
    p = TMP / "detail.png"
    im.save(p)
    return p


def main() -> int:
    src = detail_image()
    print(f"输入图 = {src.name}（有高频细节）")
    print(f"已实现 = {PL.IMPLEMENTED_KNOBS}")
    print(f"缺口   = {PL.CAPABILITY_GAPS}")
    print()

    base = PL.render_grayscale(src, TMP / "out", knobs={}, physical_mm=80, dpi=200, tag="base")
    base_sha = sha(Path(base["output"]))

    # 已实现的旋钮：必须真的动
    for name in PL.IMPLEMENTED_KNOBS:
        knob = K.KNOB_MAP[name]
        val = knob.hi if knob.hi > 0 else -1.0
        rep = PL.render_grayscale(src, TMP / "out", knobs={name: val},
                                  physical_mm=80, dpi=200, tag="k")
        s = sha(Path(rep["output"]))
        if s == base_sha:
            bad(f"已实现旋钮「{name}」应当改变产物", f"sha 没变（{s}）——那就是'假装生效'")
        else:
            ok(f"已实现旋钮「{name}」真的动了（sha {base_sha}→{s}）")

    # 缺口的旋钮：必须一动不动（否则能力清单在骗人）
    for name in PL.CAPABILITY_GAPS:
        rep = PL.render_grayscale(src, TMP / "out", knobs={name: 0.9},
                                  physical_mm=80, dpi=200, tag="g")
        s = sha(Path(rep["output"]))
        if s != base_sha:
            bad(f"缺口旋钮「{name}」应当**不**改变产物", f"sha 却变了（{base_sha}→{s}）——清单与实现对不上")
        else:
            ok(f"缺口旋钮「{name}」确实没接线（sha 未变）—— 清单是诚实的")

    # 清单本身不许两边漂
    if set(PL.IMPLEMENTED_KNOBS) | set(PL.CAPABILITY_GAPS) != {k.name for k in K.KNOBS}:
        bad("已实现 + 缺口 应当恰好等于全部旋钮", "两边清单漂了")
    else:
        ok(f"已实现({len(PL.IMPLEMENTED_KNOBS)}) + 缺口({len(PL.CAPABILITY_GAPS)}) = 全部旋钮({len(K.KNOBS)})，没漂")

    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：")
        for f in FAIL:
            print("  -", f)
        return 1
    print(f"全部通过 [PASS] {PASS}/{PASS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
