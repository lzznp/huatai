r"""减淡同步试验台 v3 · 左：灰度图（刷这个）｜右：玻璃画效果（同步跟着变）

════════════════════════════════════════════════════════════════════
这一版只回答一个问题（用户 2026-10-17 原话精神）：
  > "原来手工是：PS 里在灰度图上减淡 → 扩散仿色 → 存位图 → 回来再看 →
  >  再改灰度 → 再存位图…… 很不方便。
  >  我想试试**减淡工具处理的同步显示**——刷灰度，旁边的玻璃画效果同步变。
  >  如果同步效果达不到满意，那就放弃这个想法，**越界就不用考虑了**。"

所以本台子的取舍与 v2 完全不同：
  · 只做减淡（不加深、不管“只删不补”、不管闸门）；
  · 越界（改动泄到笔刷外）先不管 —— 用户明确说：同步效果不满意就别谈越界；
  · 唯一要验的是同步：刷灰度时，右边的点阵能不能几毫秒内跟着变、看起来“就是它”。

★ 为什么能做到“同步”（v2 做不到的原因）
  v2 每笔要对全图重仿色（0.73s）才能保证“圈外不动”——那是为了守越界付出的代价。
  本版既然不管越界，就只对笔刷动过的那一小块重仿色（实测 10~30ms），
  于是拖动中就能实时更新。这是拿“越界”换来的速度，两边不能同时要。
  ⇒ 右图边界上可能有一条薄接缝，这是本版故意留下的，不是 bug。

★ 灰度从哪来（关键）
  右图点阵是**真上机档**；左图灰度是**从点阵反推**出来的标定灰度
  （calibrate_gray_from_bitmap，实测零改动能复现成品 23.9% vs 真品 24.0%）。
  ⇒ 一打开：右图 = 真上机档，左图 = 能生成它的灰度，两边天然一致；
     这样“刷左图 → 右图跟着变”才可信。

用法：
    python tests\\exp_smart_brush3.py --selftest     # 无头自检（含同步耗时实测）
    python tests\\exp_smart_brush3.py                # 开窗（左灰度 / 右玻璃画）
    python tests\\exp_smart_brush3.py <原图> <上机档.bmp>
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from exp_interactive_snap import fs_dither  # noqa: E402
from exp_interactive_snap2 import (  # noqa: E402
    DEF_SRC, DEF_BMP, RENDER_LONG, dots_panel, calibrate_gray_from_bitmap,
)
from exp_smart_brush import DEF_BRUSH, MIN_BRUSH, MAX_BRUSH  # noqa: E402

# ---- 参数 ----
DEF_STRENGTH = 2.0       # 每个印子把“到白的距离”吃掉多少 %（PS 减淡工具就是这个模型）
MIN_STRENGTH, MAX_STRENGTH = 0.3, 8.0
MAX_GRAY = 245.0         # 不刷到纯白（留一点余地，免得整块消失）
PAD = 10                 # 重仿时在笔刷框外多算几像素（让误差先跑开一点，接缝轻一些）


def _falloff(radius: int):
    """笔刷圆内的相对偏移 + 软衰减权重（中心 1，边缘 0，余弦过渡）。"""
    r = int(radius)
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    d2 = (yy * yy + xx * xx).astype(np.float64)
    inside = d2 <= r * r
    t = np.clip(1.0 - d2 / float(max(1, r * r)), 0.0, 1.0)
    w = 0.5 - 0.5 * np.cos(np.pi * t)        # 余弦羽化：中心平、边缘软
    return yy[inside], xx[inside], w[inside]


class DodgeSync:
    """左灰度 / 右点阵的同步核心（无 tkinter，判据可无头跑）。"""

    def __init__(self, src_path: Path, bmp_path: Path | None, *, verbose: bool = True):
        src = Image.open(src_path).convert("L")
        k = RENDER_LONG / max(src.size)
        self.gray_src = np.asarray(
            src.resize((round(src.width * k), round(src.height * k)), Image.LANCZOS),
            dtype=np.float64)
        if bmp_path and Path(bmp_path).exists():
            b = Image.open(bmp_path).convert("L")
            if b.size != self.gray_src.shape[::-1]:
                b = b.resize(self.gray_src.shape[::-1], Image.NEAREST)
            self.dots0 = np.asarray(b) < 128
            self.src_note = f"真上机档 {Path(bmp_path).name}"
            self.gray0, self.cal = _calibrate_cached(self.gray_src, self.dots0,
                                                     Path(src_path), Path(bmp_path))
        else:
            self.gray0 = self.gray_src.copy()
            self.dots0 = fs_dither(self.gray0)
            self.cal = None
            self.src_note = "自仿色（没找到上机档）"
        self.h, self.w = self.gray0.shape

        # ★ 另一种灰度来源：**原图灰度**（清楚），把它的整体亮度挪一挪，使仿色出来的
        #   墨点占比与真上机档相同（≈24%）。⚠️ 图案**不会**与真上机档逐像素相同
        #   （同一张图、同一密度、不同抖动纹理），所以它只适合"看手感/看清楚"。
        self.gray_photo = None
        if self.cal is not None:
            self.gray_photo = _photo_gray_for_ink(self.gray_src, float(self.dots0.mean()),
                                                  Path(src_path), Path(bmp_path))
        self.gray_source = "density"        # density = 与真上机档一致（偏糊）；photo = 原图（清楚）

        self.gray = self.gray0.copy()
        self.dots = self.dots0.copy()
        self.brush = DEF_BRUSH
        self.strength = DEF_STRENGTH
        self.strokes = []
        self.cur = None
        self.last_ms = 0.0          # 最近一次“减淡+重仿”的耗时（同步感的实测数）
        self._gray_density = self.gray0.copy()   # “密度反推”这一份（切回来要用）
        self._dots_real = self.dots0.copy()
        if verbose:
            print(f"素材 = {self.src_note}  {self.w}×{self.h}  墨点 {100 * self.dots.mean():.2f}%")
            if self.cal:
                print(f"灰度反推：原图直接仿色 {self.cal['ink_raw'] * 100:.1f}% → "
                      f"标定后 {self.cal['ink_after'] * 100:.1f}%")

    # ---------------------------------------------------------------- 灰度来源切换
    def set_gray_source(self, which: str):
        """切换左图灰度来源（会**清空所有笔画**，因为基线换了）。"""
        if which == "photo" and self.gray_photo is None:
            return False
        self.gray_source = which
        self.strokes.clear()
        self.cur = None
        if which == "photo":
            self.gray0 = self.gray_photo.copy()
            self.dots0 = fs_dither(self.gray0)
        else:
            self.gray0 = self._gray_density.copy()
            self.dots0 = self._dots_real.copy()
        self.gray = self.gray0.copy()
        self.dots = self.dots0.copy()
        return True

    # ---------------------------------------------------------------- 一笔
    def stroke_begin(self):
        self.cur = {"bytes": None, "boxes": [], "stamps": 0}

    def dodge(self, cx: float, cy: float):
        """在灰度上减淡一印，并只对笔刷那块重仿色；返回被更新的框 (x0,y0,x1,y1)。"""
        s = self.cur
        if s is None:
            return None
        r = int(self.brush)
        yy, xx, wgt = _falloff(r)
        iy, ix = yy + int(round(cy)), xx + int(round(cx))
        ok = (iy >= 0) & (iy < self.h) & (ix >= 0) & (ix < self.w)
        if not ok.any():
            return None
        iy, ix, wgt = iy[ok], ix[ok], wgt[ok]
        s["stamps"] += 1
        if s["bytes"] is None:                    # 撤销快照（第一次真改时）
            s["bytes"] = (self.gray.copy(), self.dots.copy())

        # ① 灰度减淡：朝 MAX_GRAY 走，越靠近越慢（PS 减淡的模型，天然不会过冲）
        #   ⚠️ 天花板要逐像素取 max(MAX_GRAY, 基线灰度)：标定灰度里有**本来就比 245 亮**的像素
        #      （稀疏处 255·(1−密度) 可以到 250），写死 245 会把它们**压暗**（踩过）。
        g = self.gray[iy, ix]
        cap = np.maximum(self.gray0[iy, ix], MAX_GRAY)
        self.gray[iy, ix] = np.minimum(
            cap, g + (cap - g) * (self.strength / 100.0) * wgt)

        # ② 只对“这一印的框”重仿色（多算 PAD 让误差先跑开，接缝轻一点）
        x0 = max(0, int(ix.min()) - PAD); x1 = min(self.w, int(ix.max()) + PAD + 1)
        y0 = max(0, int(iy.min()) - PAD); y1 = min(self.h, int(iy.max()) + PAD + 1)
        t0 = time.perf_counter()
        d = fs_dither(self.gray[y0:y1, x0:x1])
        self.dots[y0:y1, x0:x1] = d
        self.last_ms = (time.perf_counter() - t0) * 1000.0
        s["boxes"].append((x0, y0, x1, y1))
        return (x0, y0, x1, y1)

    def stroke_end(self):
        s = self.cur
        self.cur = None
        if s is None:
            return {}
        if s["bytes"] is not None:
            self.strokes.append(s)
        return {"stamps": s["stamps"], "ink": float(self.dots.mean()), "ms": self.last_ms}

    def undo(self):
        if not self.strokes:
            return False
        s = self.strokes.pop()
        self.gray, self.dots = s["bytes"][0].copy(), s["bytes"][1].copy()
        return True

    def reset(self):
        self.strokes.clear()
        self.cur = None
        self.gray = self.gray0.copy()
        self.dots = self.dots0.copy()

    # ---------------------------------------------------------------- 读数
    def region_ink(self, x0: int, y0: int, x1: int, y1: int) -> float:
        return float(self.dots[y0:y1, x0:x1].mean())


def _calibrate_cached(gray_src, dots0, src_path: Path, bmp_path: Path):
    """带缓存的灰度反推（开窗要等 9 秒太久；算法一字不改）。"""
    import hashlib
    fp = "-".join(str(x) for x in (src_path.stat().st_size, int(src_path.stat().st_mtime),
                                   bmp_path.stat().st_size, int(bmp_path.stat().st_mtime),
                                   gray_src.shape[0], gray_src.shape[1]))
    cache = (ROOT / ".tmp-tests" / "brush2-cache" /
             f"calibrate-{hashlib.md5(fp.encode()).hexdigest()[:12]}.npz")
    if cache.exists():
        try:
            z = np.load(cache)
            g = z["gray"].astype(np.float64)
            if g.shape == gray_src.shape:
                return g, {k: float(z[k]) for k in ("offset", "ink_want", "ink_after",
                                                    "ink_raw", "gray_raw_mean", "gray_cal_mean")}
        except Exception:                      # noqa: BLE001
            pass
    g, info = calibrate_gray_from_bitmap(gray_src, dots0)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, gray=g.astype(np.float32), **info)
    except Exception:                          # noqa: BLE001
        pass
    return g, info


def _photo_gray_for_ink(photo_gray: np.ndarray, want_ink: float,
                        src_path: Path, bmp_path: Path) -> np.ndarray:
    """把**原图灰度**整体挪亮度，使仿色出来的墨点占比 ≈ 真上机档（≈24%）。

    用途：给"想看清楚、想按原图的手感刷"的用户第二种灰度来源。
    ⚠️ 它**不会**逐像素复现真上机档（同密度、不同抖动纹理），所以只适合看手感。
    做法：先按均值估一个偏置，再实测一次仿色、按差值修正一次（约 2 次全图仿色，有缓存）。
    """
    import hashlib
    fp = "-".join(str(x) for x in ("photo", src_path.stat().st_size,
                                   int(src_path.stat().st_mtime), bmp_path.stat().st_size,
                                   int(bmp_path.stat().st_mtime), photo_gray.shape[0],
                                   photo_gray.shape[1], round(want_ink, 5)))
    cache = (ROOT / ".tmp-tests" / "brush2-cache" /
             f"photogray-{hashlib.md5(fp.encode()).hexdigest()[:12]}.npz")
    if cache.exists():
        try:
            z = np.load(cache)
            g = z["gray"].astype(np.float64)
            if g.shape == photo_gray.shape:
                return g
        except Exception:                      # noqa: BLE001
            pass
    off = 255.0 * want_ink - float(photo_gray.mean())   # 先给一个解析估计（≈直线关系）
    # ★ 再用**二分**校准（2026-10-17 踩过：解析式 + 一次线性修正会过冲 ——
    #   因为 ink 被 clip 到 [0,1] 后就**不再线性**了，实测冲出 100% 全黑）。
    lo, hi = -255.0, 255.0
    best = None
    for _ in range(8):
        g_try = np.clip(photo_gray + off, 0, 255)
        ink = float(fs_dither(g_try).mean())
        if best is None or abs(ink - want_ink) < best[0]:
            best = (abs(ink - want_ink), off, ink)
        # 方向：偏置越大 ⇒ 灰度越亮 ⇒ 墨点越**少**（单调递减）
        if ink > want_ink:
            lo = off            # 墨点太多 ⇒ 偏置要更大
        else:
            hi = off            # 墨点太少 ⇒ 偏置要更小
        off = (lo + hi) / 2.0
    off = best[1]
    g = np.clip(photo_gray + off, 0, 255)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, gray=g.astype(np.float32))
    except Exception:                          # noqa: BLE001
        pass
    return g


# ================================================================ 导出
def export(app: DodgeSync, tag_prefix: str = "sync"):
    import json
    from datetime import datetime
    out = ROOT / ".tmp-tests" / "brush3-export"
    out.mkdir(parents=True, exist_ok=True)
    tag = f"{tag_prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    meta = {
        "导出时间": datetime.now().isoformat(timespec="seconds"),
        "口径": "减淡同步：左灰度 / 右点阵；只对笔刷块重仿色（不管越界）",
        "点阵来源": app.src_note,
        "尺寸": [app.w, app.h],
        "笔刷_px": app.brush,
        "力度_每印吃掉到白距离的百分比": app.strength,
        "笔数": len(app.strokes),
        "全图墨点": {"基线": round(100 * app.dots0.mean(), 3),
                    "现在": round(100 * app.dots.mean(), 3)},
        "最近一次重仿耗时_ms": round(app.last_ms, 2),
        "灰度": {"基线均值": round(float(app.gray0.mean()), 2),
                 "现在均值": round(float(app.gray.mean()), 2)},
    }
    (out / f"{tag}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    files = [str(out / f"{tag}.json")]
    Image.fromarray(np.stack([app.gray] * 3, -1).astype(np.uint8)).save(
        out / f"{tag}-灰度.png")
    files.append(str(out / f"{tag}-灰度.png"))
    Image.fromarray(np.where(app.dots, 0, 255).astype(np.uint8)).convert("1").save(
        out / f"{tag}-成品1bit.bmp")
    files.append(str(out / f"{tag}-成品1bit.bmp"))
    Image.fromarray(dots_panel(app.dots, None, app.h, app.w)).save(
        out / f"{tag}-成品点位.png")
    files.append(str(out / f"{tag}-成品点位.png"))
    left = Image.fromarray(np.stack([app.gray] * 3, -1).astype(np.uint8))
    right = Image.fromarray(dots_panel(app.dots, None, app.h, app.w))
    cv = Image.new("RGB", (left.width * 2 + 12, left.height + 26), (255, 255, 255))
    cv.paste(left, (0, 26)); cv.paste(right, (left.width + 12, 26))
    dr = ImageDraw.Draw(cv)
    dr.text((4, 7), "left: gray (paint on this)", fill=(0, 0, 0))
    dr.text((left.width + 16, 7), "right: engrave dots (live)", fill=(0, 0, 0))
    cv.save(out / f"{tag}-两联.png"); files.append(str(out / f"{tag}-两联.png"))
    return files


# ================================================================ 无头自检
def selftest() -> int:
    fails = []

    def check(c, label, extra=""):
        print(("  [OK]   " if c else "  [FAIL] ") + label + (f"  {extra}" if extra else ""))
        if not c:
            fails.append(label)

    t_init = time.perf_counter()
    app = DodgeSync(DEF_SRC, DEF_BMP)
    init_s = time.perf_counter() - t_init

    print("\n①一打开：右图 = 真上机档，左图是能生成它的灰度（两边天然一致）")
    diff = int((app.dots != app.dots0).sum())
    print(f"   初始点阵与真上机档逐像素差 {diff}；墨点 {100 * app.dots.mean():.2f}%"
          f"（真品 24.05%）；准备耗时 {init_s:.1f}s")
    check(diff == 0, "★零改动时右图 = 真上机档（逐像素一致）")

    print("\n②★★同步：一印的“减淡+重仿色”要多久（这是本台的唯一目的）")
    app.reset()
    app.stroke_begin()
    times = []
    for i in range(30):
        t0 = time.perf_counter()
        app.dodge(400 + (i % 10) * 6, 300 + (i // 10) * 6)
        times.append((time.perf_counter() - t0) * 1000)
    app.stroke_end()
    times = np.array(times[1:])            # 去掉第一次（含快照）
    print(f"   单印中位 {np.median(times):.1f}ms　P90 {np.percentile(times, 90):.1f}ms　"
          f"最大 {times.max():.1f}ms　⇒ 约 {1000 / max(1e-6, np.median(times)):.0f} 帧/秒")
    check(np.median(times) < 60, "★★单印同步耗时 <60ms（手感上算“跟手”）",
          f"{np.median(times):.1f}ms")
    check(np.percentile(times, 90) < 120, "★P90 <120ms（偶发慢也不会卡）",
          f"{np.percentile(times, 90):.1f}ms")

    print("\n③减淡确实让点阵变稀（右图真的跟着变了，不是只改了灰度）")
    app.reset()
    y0, y1, x0, x1 = 280, 340, 380, 460
    before = app.region_ink(x0, y0, x1, y1)
    g_before = float(app.gray[y0:y1, x0:x1].mean())
    app.stroke_begin()
    for i in range(12):
        app.dodge(400 + i * 4, 300 + i * 2)
    app.stroke_end()
    after = app.region_ink(x0, y0, x1, y1)
    g_after = float(app.gray[y0:y1, x0:x1].mean())
    print(f"   该块墨点 {100 * before:.1f}% → {100 * after:.1f}%（灰度均值 "
          f"{g_before:.1f} → {g_after:.1f}）")
    check(after < before, "★减淡后该块**点阵变稀**（右图跟着变）")
    check(g_after > g_before, "★灰度确实被调亮了")

    print("\n④反复刷：朝白走但不到纯白（不过冲）")
    app.reset()
    app.stroke_begin()
    for k in range(40):
        for i in range(6):
            app.dodge(400 + i * 6, 300)
    app.stroke_end()
    gmax = float(app.gray.max())
    cap_max = float(np.maximum(app.gray0, MAX_GRAY).max())
    ink = float(app.dots.mean())
    print(f"   刷 240 印后：灰度最大 {gmax:.0f}（逐像素上限 {cap_max:.0f}），"
          f"全图墨点 {100 * ink:.2f}%")
    check(gmax <= cap_max + 0.5, "★灰度有硬上限，不会刷到纯白", f"{gmax:.0f} ≤ {cap_max:.0f}")
    check(bool((app.gray >= app.gray0 - 1e-6).all()), "★减淡只会变亮，不会把任何像素压暗")
    check(ink > 0, "★墨点没有被刷成 0")

    print("\n⑤撤销 / 还原")
    app.reset()
    app.stroke_begin()
    for i in range(10):
        app.dodge(400 + i * 5, 300)
    app.stroke_end()
    changed = int((app.dots != app.dots0).sum())
    ok = app.undo()
    back = bool((app.dots == app.dots0).all()) and bool((app.gray == app.gray0).all())
    print(f"   撤销前改动 {changed} 点；撤销后与初始一致 = {back}")
    check(ok and changed > 0 and back, "★撤销一笔精确回到初始（灰度+点阵都回）")

    print("\n⑥导出这条路要通（参谋长的眼睛只能读文件）")
    app.reset()
    app.stroke_begin()
    for i in range(12):
        app.dodge(400 + i * 4, 300 + i * 2)
    app.stroke_end()
    try:
        files = export(app, tag_prefix="selftest")
        print("   导出：", ", ".join(Path(f).name for f in files))
        bmp = [f for f in files if f.endswith("-成品1bit.bmp")][0]
        got = np.asarray(Image.open(bmp).convert("L")) < 128
        check(bool((got == app.dots).all()), "★导出的 1bit 与内部点阵逐像素一致")
    except Exception as e:                     # noqa: BLE001
        check(False, "导出不抛异常", repr(e))

    print()
    if fails:
        print(f"[FAIL] {len(fails)} 项没过：")
        for f in fails:
            print("   -", f)
        return 1
    print("[PASS] 减淡同步试验台全部通过")
    print("       ★ 真正要你判的是：开窗刷的时候，右边看起来是不是“就是它”（只有眼睛能定）")
    return 0


# ================================================================ 开窗
def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    import tkinter as tk
    from tkinter import ttk
    from PIL import ImageTk

    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = Path(paths[0]) if len(paths) > 0 else DEF_SRC
    bmp = Path(paths[1]) if len(paths) > 1 else DEF_BMP
    if not src.exists():
        print(f"找不到原图：{src}"); return 2
    print(f"原图 = {src}\n上机档 = {bmp if bmp.exists() else '（没找到，将自仿色）'}")
    app = DodgeSync(src, bmp if bmp.exists() else None)

    root = tk.Tk()
    root.title(f"减淡同步 · 左灰度（刷这个）｜右玻璃画（同步）   {src.name}")
    wrap = ttk.Frame(root, padding=6); wrap.pack(fill="both", expand=True)

    scale = 0.85                      # 两张图并排，默认缩到 85% 才放得下
    gap = 14
    view_w = int(app.w * scale); view_h = int(app.h * scale)

    canv = tk.Canvas(wrap, width=view_w * 2 + gap, height=view_h,
                     highlightthickness=1, highlightbackground="#999", cursor="none")
    canv.grid(row=0, column=0, sticky="nw")
    side = ttk.Frame(wrap, padding=(10, 0)); side.grid(row=0, column=1, sticky="nw")

    ttk.Label(side, text="① 笔刷（只在左边灰度图上刷）", font=("", 10, "bold")).pack(anchor="w")
    var_brush = tk.IntVar(value=app.brush)
    lbl_brush = ttk.Label(side, text=f"{app.brush}px")
    tk.Scale(side, from_=MIN_BRUSH, to=MAX_BRUSH, variable=var_brush,
             orient="horizontal", length=230).pack(anchor="w")
    lbl_brush.pack(anchor="w")
    lbl_zoom = ttk.Label(side, text=f"缩放 {scale:.2f}×（滚轮　右键拖=平移）", foreground="#666")
    lbl_zoom.pack(anchor="w")

    ttk.Label(side, text="② 力度：每印把『到白的距离』吃掉多少 %").pack(anchor="w", pady=(8, 0))
    var_str = tk.DoubleVar(value=app.strength)
    lbl_str = ttk.Label(side, text=f"{app.strength:.1f}%")
    tk.Scale(side, from_=MIN_STRENGTH, to=MAX_STRENGTH, resolution=0.1,
             variable=var_str, orient="horizontal", length=230).pack(anchor="w")
    lbl_str.pack(anchor="w")
    ttk.Label(side, text="（越刷越淡、靠近白越慢；上限 245 不会刷成纯白）",
              foreground="#666").pack(anchor="w")

    ttk.Separator(side).pack(fill="x", pady=8)
    ttk.Label(side, text="③ ★ 左图灰度用哪一份", font=("", 10, "bold")).pack(anchor="w")
    var_src = tk.StringVar(value="density")
    ttk.Radiobutton(side, text="密度反推（与真上机档一致，偏糊）", value="density",
                    variable=var_src).pack(anchor="w")
    ttk.Radiobutton(side, text="原图（清楚；右图纹理与真上机档不同）", value="photo",
                    variable=var_src).pack(anchor="w")
    ttk.Label(side, text="切换会清空已刷的笔画", foreground="#666").pack(anchor="w")

    ttk.Separator(side).pack(fill="x", pady=8)
    ttk.Label(side, text="④ 同步读数", font=("", 10, "bold")).pack(anchor="w")
    lbl_sync = ttk.Label(side, text="—", foreground="#036")
    lbl_sync.pack(anchor="w")

    ttk.Separator(side).pack(fill="x", pady=8)
    btn_undo = ttk.Button(side, text="撤销上一笔（Ctrl+Z）")
    btn_undo.pack(anchor="w")
    btn_reset = ttk.Button(side, text="全部还原")
    btn_reset.pack(anchor="w", pady=(3, 0))
    btn_export = ttk.Button(side, text="★ 导出（灰度 + 1bit + 两联图）")
    btn_export.pack(anchor="w", pady=(6, 0))
    ttk.Separator(side).pack(fill="x", pady=8)
    txt = tk.Text(side, width=46, height=16, wrap="word", relief="flat", background="#f7f7f7")
    txt.pack(anchor="w"); txt.configure(state="disabled")

    def say(t):
        txt.configure(state="normal"); txt.delete("1.0", "end"); txt.insert("1.0", t)
        txt.configure(state="disabled")

    def to_image(e):
        return canv.canvasx(e.x) / scale, canv.canvasy(e.y) / scale

    def build():
        """把两张图拼成一张（左灰度 / 右点阵），一次 PhotoImage。"""
        left = np.stack([app.gray] * 3, -1).astype(np.uint8)
        right = dots_panel(app.dots, None, app.h, app.w)
        comp = np.full((app.h, app.w * 2 + gap, 3), 255, dtype=np.uint8)
        comp[:, :app.w] = left
        comp[:, app.w + gap:] = right
        img = Image.fromarray(comp)
        if abs(scale - 1.0) > 1e-6:
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.NEAREST)
        return img

    def render(cursor=None):
        img = build()
        if cursor is not None:
            d = ImageDraw.Draw(img)
            cx, cy = cursor
            rp = app.brush * scale
            d.ellipse([cx - rp, cy - rp, cx + rp, cy + rp], outline=(0, 150, 255), width=2)
        canv._photo = ImageTk.PhotoImage(img)
        canv.delete("all")
        canv.create_image(0, 0, anchor="nw", image=canv._photo)
        canv.configure(scrollregion=(0, 0, img.width, img.height))

    def readout(ms=None):
        lbl_brush.configure(text=f"{int(var_brush.get())}px")
        lbl_str.configure(text=f"{float(var_str.get()):.1f}%")
        a = 100 * app.dots.mean()
        b = 100 * app.dots0.mean()
        extra = f"　重仿 {ms:.1f}ms" if ms is not None else ""
        lbl_sync.configure(text=f"全图墨点 {b:.2f}% → {a:.2f}%{extra}")

    # ★ 帧合并（2026-10-17 实测逼出来的）：减淡+重仿只要 7ms，但**重画整张两联图要 30ms**；
    #   鼠标拖动每秒会产生上百个事件 ⇒ 若每个事件都 render，就会排队、越拖越滞后。
    #   改成"最多 25ms 画一次、只画最后一帧"，拖动就不会堆积。
    pend = {"job": None, "cursor": None}

    def flush():
        if pend["job"] is not None:
            try:
                root.after_cancel(pend["job"])
            except Exception:                  # noqa: BLE001
                pass
            pend["job"] = None
        render(pend["cursor"])
        readout(app.last_ms)

    def schedule(cursor, ms=25):
        pend["cursor"] = cursor
        if pend["job"] is None:
            pend["job"] = root.after(ms, flush)

    def on_press(e):
        x, y = to_image(e)
        if x >= app.w:                    # 点在右图上：不处理
            return
        app.brush = int(var_brush.get())
        app.strength = float(var_str.get())
        app.stroke_begin()
        app.dodge(x, y)
        pend["cursor"] = (e.x, e.y)
        flush()                           # 第一印立刻显示

    def on_drag(e):
        x, y = to_image(e)
        if x >= app.w or app.cur is None:
            return
        app.dodge(x, y)
        schedule((e.x, e.y))              # 拖动中：合并帧，不排队

    def on_release(_e):
        st = app.stroke_end()
        flush()
        readout(st.get("ms"))
        if st:
            say(f"这一笔：{st['stamps']} 个印子，全图墨点 {100 * app.dots0.mean():.2f}% → "
                f"{100 * st['ink']:.2f}%\n"
                f"同步一次重仿 {st['ms']:.1f}ms（这就是“跟不跟手”的关键数）\n\n"
                f"★ 看右图：应该整体变淡、纹理还在；边界那条薄接缝是本版故意不管越界造成的。")

    def on_move(e):
        x, _y = to_image(e)
        schedule((e.x, e.y) if x < app.w else None, ms=60)

    def on_wheel(e):
        nonlocal scale
        new = max(0.4, min(2.0, scale * (1.15 if e.delta > 0 else 1 / 1.15)))
        if abs(new - scale) < 1e-4:
            return
        ix, iy = to_image(e)
        scale = new
        render()
        W, H = (app.w * 2 + gap) * scale, app.h * scale
        canv.xview_moveto(max(0.0, min(1.0, (ix * scale - e.x) / max(1.0, W))))
        canv.yview_moveto(max(0.0, min(1.0, (iy * scale - e.y) / max(1.0, H))))
        lbl_zoom.configure(text=f"缩放 {scale:.2f}×（滚轮　右键拖=平移）")

    def undo(_=None):
        if app.undo():
            flush(); readout(); say(f"已撤销一笔。全图墨点 {100 * app.dots.mean():.2f}%")
        else:
            say("没有可撤销的一笔了。")

    def reset(_=None):
        app.reset(); flush(); readout(); say("已全部还原到真上机档。")

    def do_export():
        if not app.strokes:
            say("先刷一笔再导出。"); return
        files = export(app, tag_prefix="sync")
        say("已导出：\n" + "\n".join("  " + Path(f).name for f in files))

    btn_undo.configure(command=undo)
    btn_reset.configure(command=reset)
    btn_export.configure(command=do_export)
    canv.bind("<ButtonPress-1>", on_press)
    canv.bind("<B1-Motion>", on_drag)
    canv.bind("<ButtonRelease-1>", on_release)
    canv.bind("<Motion>", on_move)
    canv.bind("<MouseWheel>", on_wheel)
    canv.bind("<ButtonPress-3>", lambda e: canv.scan_mark(e.x, e.y))
    canv.bind("<B3-Motion>", lambda e: canv.scan_dragto(e.x, e.y, gain=1))
    root.bind("<Control-z>", undo)

    var_brush.trace_add("write", lambda *_: readout())
    var_str.trace_add("write", lambda *_: readout())

    def on_src_change(*_):
        ok = app.set_gray_source(var_src.get())
        flush(); readout()
        if not ok:
            var_src.set("density")
            say("这一版没有原图灰度可切（缺上机档）。")
        else:
            say(f"已切换左图灰度：{'原图（清楚）' if app.gray_source == 'photo' else '密度反推（与真上机档一致）'}。\n"
                f"笔画已清空；右图基线墨点 {100 * app.dots0.mean():.2f}%。")

    var_src.trace_add("write", on_src_change)

    render(); readout()
    say(f"素材：{app.src_note}　{app.w}×{app.h}　全图墨点 {100 * app.dots.mean():.2f}%\n\n"
        f"左图是灰度图（刷这个），右图是玻璃画效果（同步跟着变）。\n"
        f"在左图上按住左键拖 = 减淡；右图立刻跟着变。\n\n"
        f"★ 本版只做减淡、不管越界（右图边界可能有一条薄接缝，是故意的）。\n"
        f"★ 要判的只有一件事：刷的时候，右边是不是“看起来就是它”。")
    print("窗口已开：左=灰度（刷这个），右=玻璃画（同步）。")
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
