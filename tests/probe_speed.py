r"""探针：**出一版要多久**（只读原图、写临时目录、不联网、不花钱）

为什么问这个：
用户说"现在的 ai 出图，总是一遍一遍的抽卡，感觉不舒服"。我打算建议的改法是
**一次给几组候选参数、并排出小图让他挑**（把"猜"变成"选"）。
但那个前提是"出一版够快"——如果一版要十几秒，四组候选就是四十多秒，人不会等。

口径：调**同一套**确定性管线 `kernel\image_lib\pipeline.render_grayscale`，
量 wall-clock 秒数（含 PNG + 1bit BMP 落盘）。**逐项分开报**：
  · 787px 档 = 界面默认 100mm@200dpi 的实际像素量（用户真实单就是这个规格）
  · 200px 档 = 若做"候选小图"大概会用到的规格
  · 只算管线，**不含**进程启动 / HTTP / 界面渲染
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kernel"))

from image_lib import pipeline as PL  # noqa: E402

TMP = ROOT / ".tmp-tests" / "probe-speed"
TMP.mkdir(parents=True, exist_ok=True)

SRC = Path(r"D:\画台\projects\美女玻璃画\order-20261012-165706\src_one.jpeg")


def one(label: str, mm: float, dpi: int, reps: int = 1) -> None:
    src = SRC if SRC.is_file() else None
    if src is None:
        print("（没找到真实图，跳过）")
        return
    ts = []
    rep = None
    for i in range(reps):
        t0 = time.perf_counter()
        rep = PL.render_grayscale(src, TMP / "out", knobs={"素描感强度": 0.7},
                                 physical_mm=mm, dpi=dpi, tag=f"{label}-{i}")
        ts.append(time.perf_counter() - t0)
    px = rep["pixels"]
    best = min(ts)
    print(f"{label:22s} {px[0]}×{px[1]}px @{dpi}dpi  最短 {best:.2f}s" +
          (f"  全部 {[round(t, 2) for t in ts]}" if reps > 1 else ""))


def main() -> int:
    print(f"源图 = {SRC.name}（真实用户数据，只读）")
    print(f"临时输出目录 = {TMP / 'out'}")
    print()
    print("—— 单版耗时（每档跑 2 次取最短）——")
    one("100mm@200dpi（默认档）", 100, 200, reps=2)
    one("100mm@300dpi", 100, 300, reps=2)
    one("小图档 25mm@200dpi", 25, 200, reps=2)
    print()
    print("—— 四组候选 = 4 次上面这一档 ——")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
