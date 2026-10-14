r"""实验 A2（第 1 条的修正版）：**圈个大概 → 先自检信号 → 再吸附到边界**

A1（`exp_circle_snap.py`）失败的原因已经查清（见 `probe_edge_signal.py`）：
  · 圈太大 ⇒ 圈内混进多种东西 ⇒ 圈内离散度 σ 被抬高 ⇒ 容差大到把整张脸包住；
  · 关键指标是**信号比 = |圈内均值 − 环带均值| / 圈内σ**：
      左眼 0.38、整个嘴唇 0.22、左眉 0.29（都 < 0.3 ⇒ 分不开，必失控）
      但「只圈上唇一条」= 1.21（灰度）/ 2.27（颜色）⇒ **可分**

A2 相对 A1 改了三处（每处都对应上面的一条发现）：
  1. **先自检**：算信号比，不用用户可见的阈值糊弄——低于门槛就直接报"这块我分不开"，**不硬吸**；
  2. **种子不再是整个圈**：从"圈里最像目标的那部分"取（离圈外均值最远的 30%），
     避免用户圈大一点就把目标稀释掉；
  3. **容差不再用全圈的 σ**：改用**种子内部**的 σ（种子已经只剩目标 ⇒ σ 小得多）。

用法：  python tests\exp_circle_snap2.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

REAL = Path(r"D:\画台\projects\美女玻璃画\order-20261012-165706\src_one.jpeg")
OUT = ROOT / ".tmp-tests" / "exp-circle-snap2"
OUT.mkdir(parents=True, exist_ok=True)

RING_GROW = 10        # 环带宽度（用来估计"周围长什么样"）
CORE_FRAC = 0.30      # 圈内取最像目标的 30% 当种子
TOL_K = 1.5           # 容差 = 种子稳健σ × 这个系数
SIGNAL_MIN = 0.60     # 信号比低于它 ⇒ 判"分不开"，直接拒（口径见 probe_edge_signal.py）


def robust_sigma(v: np.ndarray) -> float:
    med = float(np.median(v))
    return max(1.0, 1.4826 * float(np.median(np.abs(v - med))))


def ellipses(shape, box, grow: int):
    x0, y0, x1, y1 = box
    m_in = Image.new("L", (shape[1], shape[0]), 0)
    m_out = Image.new("L", (shape[1], shape[0]), 0)
    ImageDraw.Draw(m_in).ellipse([x0, y0, x1, y1], fill=255)
    ImageDraw.Draw(m_out).ellipse([x0 - grow, y0 - grow, x1 + grow, y1 + grow], fill=255)
    a = np.asarray(m_in) > 0
    b = np.asarray(m_out) > 0
    return a, (b & ~a)


def grow_features(feat: np.ndarray, core: np.ndarray, tol: float) -> np.ndarray:
    """在**特征图**（灰度或颜色）上生长：允许进入 = 与种子中位数差在 tol 内。"""
    med = float(np.median(feat[core]))
    ok = np.abs(feat - med) <= tol
    cur = core & ok
    for _ in range(4000):
        nb = np.zeros_like(cur)
        nb[1:, :] |= cur[:-1, :]
        nb[:-1, :] |= cur[1:, :]
        nb[:, 1:] |= cur[:, :-1]
        nb[:, :-1] |= cur[:, 1:]
        nxt = cur | (nb & ok)
        if nxt.sum() == cur.sum():
            break
        cur = nxt
    return cur


def fill_holes(m: np.ndarray) -> np.ndarray:
    bg = ~m
    cur = np.zeros_like(bg)
    cur[0, :] |= bg[0, :]
    cur[-1, :] |= bg[-1, :]
    cur[:, 0] |= bg[:, 0]
    cur[:, -1] |= bg[:, -1]
    for _ in range(4000):
        nb = np.zeros_like(cur)
        nb[1:, :] |= cur[:-1, :]
        nb[:-1, :] |= cur[1:, :]
        nb[:, 1:] |= cur[:, :-1]
        nb[:, :-1] |= cur[:, 1:]
        nxt = cur | (nb & bg)
        if nxt.sum() == cur.sum():
            break
        cur = nxt
    return m | (~cur & ~m)


def main() -> int:
    img = Image.open(REAL)
    W, H = img.size
    rgb = np.asarray(img.convert("RGB"), dtype=np.float64)
    gray = np.asarray(img.convert("L"), dtype=np.float64)
    print(f"图 = {REAL.name} {W}×{H}px（原图坐标）")
    print(f"参数：环带 {RING_GROW}px　种子取圈内最像目标的 {CORE_FRAC:.0%}　容差 = 种子σ×{TOL_K}")
    print(f"信号门槛 = {SIGNAL_MIN}（低于它就判'分不开'，不硬吸）\n")

    cases = [
        ("左眼（A1 失败过）", (72, 55, 140, 105)),
        ("整个嘴唇（A1 失败过）", (98, 195, 210, 275)),
        ("只圈上唇一条（信号最好）", (110, 200, 200, 235)),
        ("左眉一带（细长）", (60, 40, 150, 62)),
        ("大半张脸（看它会不会贪心）", (120, 90, 300, 260)),
    ]

    gray_rgb = np.stack([gray, gray, gray], axis=-1).astype(np.uint8)
    rows = []
    for i, (name, box) in enumerate(cases, start=1):
        inside, ring = ellipses((H, W), box, RING_GROW)
        # ---- ① 自检：两种特征图各算一次信号比，取好的那个 ----
        cands = {}
        gi, gr = gray[inside], gray[ring]
        sig_g = abs(float(gi.mean() - gr.mean())) / robust_sigma(gi)
        cands["灰度"] = (sig_g, gray)
        ci, cr = rgb[inside], rgb[ring]
        d_col = float(np.linalg.norm(ci.mean(axis=0) - cr.mean(axis=0)))
        d_within = np.linalg.norm(ci - ci.mean(axis=0), axis=1)
        sig_c = d_col / robust_sigma(d_within)
        # 颜色特征图：到环带平均颜色的距离（一维，好生长）
        feat_col = np.linalg.norm(rgb - cr.mean(axis=0), axis=2)
        cands["颜色"] = (sig_c, feat_col)

        feat_name, (signal, feat) = max(cands.items(), key=lambda kv: kv[1][0])
        print(f"=== {i}. {name} ===")
        print(f"  信号比：灰度 {sig_g:.2f}　颜色 {sig_c:.2f} ⇒ 采用【{feat_name}】")
        if signal < SIGNAL_MIN:
            print(f"  ★ 判定：**分不开**（信号比 {signal:.2f} < {SIGNAL_MIN}）⇒ 不硬吸，"
                  f"应当回用户一句'这块和周围太接近，我圈不准，你圈小一点/更准一点'")
            rows.append((name, "分不开", None, None, None))
            v = Image.fromarray(gray_rgb.copy())
            ImageDraw.Draw(v).ellipse(list(box), outline=(255, 210, 0), width=3)
            v.save(OUT / f"{i}a-原图加粗圈-{name[:4]}.png")
            continue

        # ---- ② 种子 = 圈内最像目标的那部分 ----
        vals = feat[inside]
        med_in = float(np.median(vals))
        ring_med = float(np.median(feat[ring]))
        direction = 1.0 if med_in >= ring_med else -1.0     # 目标比周围亮还是暗
        dist = direction * (vals - ring_med)
        thr = np.quantile(dist, 1 - CORE_FRAC)
        core = np.zeros_like(inside)
        core[inside] = dist >= thr
        if core.sum() < 20:                                  # 兜底：目标太弱就给个最小核
            core = inside & (feat == feat[inside].max())
            if core.sum() < 20:
                core = inside

        # ---- ③ 容差用**种子**的 σ（比全圈小得多）----
        tol = TOL_K * robust_sigma(feat[core])
        grown = fill_holes(grow_features(feat, core, tol))

        a_core, a_grow = int(core.sum()), int(grown.sum())
        a_seed = int(inside.sum())
        a_out = int((grown & ~inside).sum())
        inter = int((grown & inside).sum())
        iou = inter / max(1, (grown | inside).sum())
        ratio = a_grow / max(1, a_seed)
        print(f"  种子 {a_core}px（容差 ±{tol:.1f}）⇒ 吸附后 {a_grow}px"
              f"（用户圈 {a_seed}px，面积比 {ratio:.2f}×，吸到圈外 {a_out / max(1, a_grow) * 100:.0f}%）"
              f"　IoU={iou:.2f}")
        rows.append((name, f"{feat_name}", ratio, iou, a_out / max(1, a_grow)))

        # ---- 出图给人眼判 ----
        v1 = Image.fromarray(gray_rgb.copy())
        ImageDraw.Draw(v1).ellipse(list(box), outline=(255, 210, 0), width=3)
        v1.save(OUT / f"{i}a-原图加粗圈-{name[:4]}.png")
        vis = gray_rgb.astype(np.float64).copy()
        vis[core] = vis[core] * 0.5 + np.array([40, 160, 255]) * 0.5      # 蓝=种子
        vis[grown & ~core] = vis[grown & ~core] * 0.45 + np.array([235, 45, 45]) * 0.55  # 红=长出来的
        v2 = Image.fromarray(vis.astype(np.uint8))
        ImageDraw.Draw(v2).ellipse(list(box), outline=(255, 210, 0), width=2)
        v2.save(OUT / f"{i}b-吸附结果-{name[:4]}.png")
        x0, y0, x1, y1 = box
        crop = (max(0, x0 - 50), max(0, y0 - 50), min(W, x1 + 50), min(H, y1 + 50))
        sub = vis[crop[1]:crop[3], crop[0]:crop[2]].astype(np.uint8)
        Image.fromarray(sub).resize(((crop[2] - crop[0]) * 3, (crop[3] - crop[1]) * 3),
                                    Image.NEAREST).save(OUT / f"{i}c-放大看形状-{name[:4]}.png")

    print("\n========== 汇总 ==========")
    for name, feat, ratio, iou, out_pct in rows:
        if ratio is None:
            print(f"  分不开  {name:26s}（信号不足 ⇒ 正确地拒绝了）")
        else:
            print(f"  {feat:4s}   {name:26s} 面积比 {ratio:5.2f}×  IoU {iou:.2f}  外扩 {out_pct * 100:4.0f}%")
    print(f"\n图都在：{OUT}\n人眼判据：b/c 里 蓝=种子、红=吸附出来的形状——像不像你要的那个部位")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
