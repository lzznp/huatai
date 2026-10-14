r"""探针：**局部调整会不会外溢？**（只读排查，不写真实工程，不联网）

为什么要问这一条：
参考代码里那份和 GPT 的对话（2026-10-12）第 24 节提了一条硬提醒——
「Jarvis、Floyd–Steinberg 这类误差扩散算法，局部明暗变化**可能影响后续区域的点阵**。
  最终输出必须只替换选区内的点阵，选区外逐像素保留原来的结果。」

我们的现状：九宫格 `local_ops` 作用在**仿色之前**，然后整幅图跑一次 Floyd–Steinberg。
⇒ 按算法读，**调整一格的明暗，误差会顺着扫描行扩散到格子外面**，后面的点阵跟着变。
   这条以前**没验过**。本探针量它的**幅度**，作为像素级 diff（版本对比的增强项）的依据。

口径（写清楚，免得数字被误读）：
- 输入：一张固定种子的随机噪声图（有高频细节，按坑 22），**同一张图**跑两遍
- 基线：`local_ops=[]`
- 处理：`local_ops=[{zone:0, op:"brighten", amount:0.8}]`（左上一格提亮）
- 两个 1bit 结果**逐像素比**：
    改变的点数 = 两图不同的像素数（0/255 互换都算变）
    格子外的改变 = 改变像素里不属于左上那 1/9 的比例
- 另外单独看：两版的**灰度**在格子外是否被改过（这一项应该是 0，用来对账）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNEL = ROOT / "kernel"
sys.path.insert(0, str(KERNEL))

import numpy as np  # noqa: E402

from image_lib import pipeline as PL  # noqa: E402

TMP = ROOT / ".tmp-tests" / "probe-local-bleed"
TMP.mkdir(parents=True, exist_ok=True)

W = H = 300          # 小一点：纯 Python 的 FS 仿色是逐像素循环，慢了不值当
ZONE = 0             # 左上
AMOUNT = 0.8
KEY_GRAY = 0.0       # 旋钮全默认 ⇒ 两版**只差 local_ops**这一项


def zone_ids_for(zone: int) -> np.ndarray:
    """造一张和像素一一对应的格子编号图（3×3，行优先 0=左上）。"""
    ys = np.arange(H) * 3 // H
    xs = np.arange(W) * 3 // W
    return ys[:, None] * 3 + xs[None, :]


def measure(label: str, src: Path) -> None:
    """对一张图量一次：灰度是否外溢、仿色后点阵变了多少、其中多少在目标格之外。"""
    from PIL import Image

    gray = Image.open(src).convert("L")
    w, h = gray.size
    arr0 = np.asarray(gray, dtype=np.uint8)
    ys = np.arange(h) * 3 // h
    xs = np.arange(w) * 3 // w
    zmap = ys[:, None] * 3 + xs[None, :]
    inside = zmap == ZONE

    ops = PL._prepare_local_ops([{"zone": ZONE, "op": "brighten", "amount": AMOUNT}])
    arr1 = PL._apply_local_ops(arr0, ops)

    gray_changed = np.abs(arr1.astype(int) - arr0.astype(int)) > 0
    g_out = int(gray_changed[~inside].sum())

    b0 = PL._fs_dither(arr0)
    b1 = PL._fs_dither(arr1)
    diff = b0 != b1
    n_diff = int(diff.sum())
    n_out = int(diff[~inside].sum())
    total = w * h
    ink0 = float((b0 == 0).mean() * 100)
    ink1 = float((b1 == 0).mean() * 100)

    print(f"\n=== {label} ===  {w}×{h}px  源={src.name}")
    print(f"  灰度外溢（格子外被改像素） = {g_out}   ← 应该是 0")
    print(f"  点阵改变 = {n_diff} 点（占全图 {n_diff / total * 100:.2f}%）")
    print(f"  其中落在目标格之外 = {n_out} 点（占全部改变点的 {n_out / max(n_diff, 1) * 100:.1f}%）")
    print(f"  全局墨点占比 {ink0:.2f}% → {ink1:.2f}%（差 {ink1 - ink0:+.2f} 个百分点）")


def main() -> int:
    from PIL import Image

    rng = np.random.default_rng(11)
    rnd = TMP / "probe-noise.png"
    Image.fromarray((rng.random((H, W)) * 255).astype("uint8"), mode="L").save(rnd)

    print(f"口径：局部 op=zone{ZONE}（左上）brighten {AMOUNT}；旋钮全默认 ⇒ 两版**只差 local_ops**")
    print("      目标格 = 全图面积的 1/9 左右（左边一条 3 格中的左上那格）")
    measure("A 随机噪声图（高频细节）", rnd)

    # B 用户真实图：**只读**原图（src_* 只进不改），在临时目录里量
    real = Path(r"D:\画台\projects\美女玻璃画\order-20261012-165706\src_one.jpeg")
    if real.is_file():
        measure("B 你的真实图（美女玻璃画 src_one.jpeg，原图只读）", real)
        # C 同一张图缩到和界面默认档一样大的像素（100mm@200dpi 那张实测是 787 长边）
        big = TMP / "probe-real-787.png"
        im = Image.open(real).convert("L")
        s = 787 / max(im.size)
        im.resize((max(1, round(im.size[0] * s)), max(1, round(im.size[1] * s))), Image.LANCZOS).save(big)
        measure("C 同一张图、缩到 787 像素档（对齐界面默认 100mm@200dpi）", big)
    else:
        print(f"\n[B] 跳过：没找到 {real}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
