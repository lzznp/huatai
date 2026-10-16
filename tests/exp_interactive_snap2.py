r"""交互试验台 v2：**圈选 + 磁性吸附 + 灰度减淡 → 仿色成上机档**（用完即扔）

═══════════════════════════════════════════════════════════════════
v1 的错（用户 2026-10-16 当场指出，已改）：
  · v1 拿**原图 400×380 自己仿色** ⇒ 墨点 **57.9%**，
    而真实上机档是 **787×748、24.6%** ⇒ **我在一个根本不是成品的点阵上做实验**，
    密度差了 2.4 倍（这就是"感觉不舒服"的根源）。
  · v1 把点阵画成**暗红** ⇒ 不像成品，刺眼。

v2 按用户要求改：
  ① **默认加载真上机档**（out\..._v2.bmp，787×748，24.6%），也能切原图；
  ② **默认黑点画在白纸上**（= 成品原貌）；只有"被删掉的点"用**淡红圈**标出；
  ③ ★ **在灰度层上做减淡/加深**（用户当年用 PS 减淡工具的做法，信号最强），
     **再仿色**成点阵 —— 所以"改灰度"和"看成品"是同一个动作的两面；
  ④ **羽化**：灰度改动带羽化，避免误差扩散把硬切痕带出去（对应决策 #25 的外溢问题）。

为什么要走灰度而不是直接删点（2026-10-16 新量的实锤，tests\exp_diag_density2.py）：
    区域之间在**灰度**上差 65.2，到**点阵**上只剩 26.0
    ⇒ 点阵是"有天花板的梯子"，越稀的地方越拧不动。**要局部调明暗，回灰度层做。**
═══════════════════════════════════════════════════════════════════

用法：
    python tests\exp_interactive_snap2.py                 # 默认用真实上机档 + 原图
    python tests\exp_interactive_snap2.py <原图> <上机档.bmp>
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
import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402
from PIL import Image, ImageDraw, ImageTk  # noqa: E402

from exp_interactive_snap import (  # noqa: E402  复用已验证的算法，别抄第二份
    N_POINTS, SEARCH_R, DIST_PENALTY, EDGE_WEAK, DITHER_WHITE_AT,
    fs_dither, gradient_mag, ellipse_points, normals_of, snap_outline, polygon_mask,
)

# ---- 默认素材：真实工程里的原图 + 真实上机档 ----
ORDER = Path(r"D:\画台\projects\美女玻璃画\order-20261012-165706")
DEF_SRC = ORDER / "src_one.jpeg"
DEF_BMP = ORDER / "out" / "src_one_engrave_100mm_200dpi_v2.bmp"

RENDER_LONG = 787        # 上机档长边（照真品；v2 实测 787×748）
VIEW_SCALE = 1.0
MIN_VIEW, MAX_VIEW = 0.35, 2.5
FEATHER = 0.02           # 羽化半径 = 选区短边 × 这个比例（先给 2%，可调）


# ---------------------------------------------------------------- 显示

def dots_panel(dots: np.ndarray, removed: np.ndarray | None, h: int, w: int) -> np.ndarray:
    """成品的原貌：黑点画在白纸上。被删掉的点用淡红圈标出（不铺满，省眼）。"""
    vis = np.full((h, w, 3), 255, dtype=np.uint8)
    vis[dots] = np.array([25, 25, 25], dtype=np.uint8)
    if removed is not None and removed.any():
        ys, xs = np.nonzero(removed)
        vis[ys, xs] = np.array([255, 200, 200], dtype=np.uint8)   # 淡红：这里被删了
    return vis


def colorize_density(dens: np.ndarray) -> np.ndarray:
    """密度 → 绿(稀)-黄-红(密)。"""
    t = np.clip(dens, 0, 1)
    r = np.clip(2.0 * t, 0, 1)
    g = np.clip(2.0 * (1 - np.abs(t - 0.5) * 2), 0, 1)
    b = np.clip(2.0 * (1 - t), 0, 1)
    return (np.stack([r, g, b], axis=-1) * 255).astype(np.uint8)


def local_density_masked(dots: np.ndarray, mask: np.ndarray, r: int) -> np.ndarray:
    """局部黑点密度，只在 mask 内有意义（作归一化，避免边缘被稀释）。

    ★ 坑（已踩）：积分图必须在前面**补 1 行 1 列 0**，否则 `ii[y1,x1]` 会越界
      （`y1` 最大值等于 h，而 cumsume 出来的数组只有 h 行）。
    """
    h, w = dots.shape
    y0 = np.clip(np.arange(h) - r, 0, h); y1 = np.clip(np.arange(h) + r + 1, 0, h)
    x0 = np.clip(np.arange(w) - r, 0, w); x1 = np.clip(np.arange(w) + r + 1, 0, w)

    def integral(a: np.ndarray) -> np.ndarray:
        ii = np.zeros((h + 1, w + 1), dtype=np.float64)
        np.cumsum(np.cumsum(a.astype(np.float64), axis=0), axis=1, out=ii[1:, 1:])
        return ii

    def box(ii):
        return (ii[np.ix_(y1, x1)] - ii[np.ix_(y0, x1)]
                - ii[np.ix_(y1, x0)] + ii[np.ix_(y0, x0)])

    S = box(integral(dots))
    M = box(integral(mask))
    return S / np.maximum(M, 1.0)


def box_blur(a: np.ndarray, r: int) -> np.ndarray:
    """盒式模糊（3 趟 ≈ 高斯），用于把点阵降采样成"目标密度图"。"""
    out = a.astype(np.float64)
    for _ in range(3):
        c = np.cumsum(np.pad(out, ((0, 0), (r + 1, r)), mode="edge"), axis=1)
        out = (c[:, 2 * r + 1:] - c[:, :-(2 * r + 1)]) / (2 * r + 1)
        c = np.cumsum(np.pad(out, ((r + 1, r), (0, 0)), mode="edge"), axis=0)
        out = (c[2 * r + 1:, :] - c[:-(2 * r + 1), :]) / (2 * r + 1)
    return out


def calibrate_gray_from_bitmap(gray_raw: np.ndarray, bitmap: np.ndarray,
                              window: int = 9, iters: int = 10) -> tuple[np.ndarray, dict]:
    """★ 从真上机档**反推**灰度，让「零改动就能复现成品」。

    为什么必须做（2026-10-16 实测踩到）：
      · 产品管线缩放时会压对比度，所以"原图 → 放大 787px"的灰度**不是**出点阵用的那份；
      · 后果：拿它当基点，同一块区域 真上机档 16.5% 黑点，重新仿色却是 56.2%
        ⇒ 滑块一拖整块就跳，用户一眼就看出不对。

    做法（两步，缺一不可）：
      ① **保地形**：把点阵盒式模糊成"目标密度图"，用它当灰度的形状
         （密度高 → 灰度暗）。这样"哪里密哪里稀"与成品一致；
      ② **对齐总量**：再找一个全局灰度偏置 `b`，二分搜索使
         `fs_dither(gray_cal + b)` 的墨点占比等于真上机档的墨点占比。
         （只靠①会偏，因为仿色阈值与模糊窗不是同一个尺度。）
    返回 (重标定灰度, 诊断信息)。
    """
    target = box_blur(bitmap.astype(np.float64), window)      # 0~1，1=最密
    gray_cal = 255.0 * (1.0 - target)                         # 密度高 → 灰度暗

    want = float(bitmap.mean())                               # 目标墨点占比
    lo, hi = -100.0, 100.0
    best = None
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        g = np.clip(gray_cal + mid, 0, 255)
        ink = float(fs_dither(g).mean())
        if best is None or abs(ink - want) < best[0]:
            best = (abs(ink - want), mid, ink)
        # 灰度加偏置 = 整体变暗/变亮：加正值 → 更暗 → 黑点更多
        if ink < want:
            lo = mid
        else:
            hi = mid
    _, b, ink_after = best
    gray_out = np.clip(gray_cal + b, 0, 255)
    info = {"offset": b, "ink_want": want, "ink_after": ink_after,
            "ink_raw": float(fs_dither(gray_raw).mean()),
            "gray_raw_mean": float(gray_raw.mean()),
            "gray_cal_mean": float(gray_out.mean())}
    return gray_out, info


# ---------------------------------------------------------------- 主程序

class TestBed2:
    def __init__(self, root: tk.Tk, src_path: Path, bmp_path: Path | None):
        self.root = root
        self.src_path = src_path
        self.bmp_path = bmp_path

        # ① 原图灰度
        src = Image.open(src_path).convert("L")
        scale = RENDER_LONG / max(src.size)
        self.src_small = src.resize((max(1, round(src.width * scale)),
                                     max(1, round(src.height * scale))), Image.LANCZOS)
        self.gray_small = np.asarray(self.src_small, dtype=np.float64)

        # ② 真上机档（若有）——它才是"成品原貌"
        self.bmp_dots = None
        if bmp_path and bmp_path.exists():
            b = Image.open(bmp_path).convert("L")
            if b.size != self.src_small.size:
                b = b.resize(self.src_small.size, Image.NEAREST)
            self.bmp_dots = np.asarray(b) < 128          # 1bit: 0=黑=雕

        # ③ 基线点阵 = 真上机档（优先），没有就用内核同口径仿色自己生成
        if self.bmp_dots is not None:
            self.dots_base = self.bmp_dots.copy()
            self.dots_src_note = f"真上机档 {bmp_path.name}"
            # ★ 关键：灰度**从点阵反推**，否则零改动就复现不出成品（见函数注释）
            self.gray_base, self.cal = calibrate_gray_from_bitmap(self.gray_small, self.bmp_dots)
        else:
            self.dots_base = fs_dither(self.gray_small)
            self.dots_src_note = "自仿色（没找到上机档）"
            self.gray_base = self.gray_small.copy()
            self.cal = None

        self.gray_base = self.gray_small.copy()
        self.gray = self.gray_base.copy()
        self.dots = self.dots_base.copy()

        self.h, self.w = self.gray.shape
        self.grad = gradient_mag(self.gray_base)         # 只在基线上算一次

        self.scale = VIEW_SCALE
        self.drag_from = self.drag_to = None
        self.last = None
        self.show = tk.StringVar(value="bitmap")         # bitmap | gray | density
        self.hide_removed = tk.BooleanVar(value=False)
        self._photo = None

        self._build_ui()
        self.redraw()
        self.say(self._welcome())

    def _welcome(self) -> str:
        tot = 100.0 * self.dots.mean()
        cal = ""
        if self.cal:
            cal = (f"\n  灰度重标定：原图直接仿色会得 {self.cal['ink_raw'] * 100:.1f}% 墨点，"
                   f"而真上机档是 {self.cal['ink_want'] * 100:.1f}%\n"
                   f"    ⇒ 已从点阵反推灰度（偏置 {self.cal['offset']:+.1f}），"
                   f"重标定后 {self.cal['ink_after'] * 100:.1f}%（差 "
                   f"{abs(self.cal['ink_after'] - self.cal['ink_want']) * 100:.1f} 个点）")
        return (f"素材\n"
                f"  原图   {self.src_path.name}  ({Image.open(self.src_path).size[0]}"
                f"×{Image.open(self.src_path).size[1]})\n"
                f"  点阵   {self.dots_src_note}\n"
                f"  渲染到 {self.w}×{self.h}（照真上机档）\n"
                f"  全图墨点 {tot:.1f}%（真品 v2 实测 24.0%）{cal}\n\n"
                f"用法：左键拖一个圈 → 松手吸附\n"
                f"然后拖右边『灰度减淡』滑块看成品变化（正数=减淡/变稀）")

    # ---------------- 界面 ----------------
    def _build_ui(self):
        self.root.title(f"试验台v2 · 灰度减淡→仿色→上机档   {self.src_path.name}")
        wrap = ttk.Frame(self.root, padding=6); wrap.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(wrap, width=int(self.w * self.scale),
                                height=int(self.h * self.scale),
                                highlightthickness=1, highlightbackground="#999",
                                cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="nw")
        for ev, fn in (("<ButtonPress-1>", self.on_press),
                       ("<B1-Motion>", self.on_motion),
                       ("<ButtonRelease-1>", self.on_release)):
            self.canvas.bind(ev, fn)
        self.canvas.bind("<MouseWheel>", self.on_wheel)

        side = ttk.Frame(wrap, padding=(10, 0)); side.grid(row=0, column=1, sticky="nw")

        # 显示模式
        ttk.Label(side, text="① 看什么", font=("", 9, "bold")).pack(anchor="w")
        for val, txt in (("bitmap", "成品点阵（黑点=白纸，像上机档）"),
                         ("gray", "灰度图（你当年动的地方）"),
                         ("density", "密度热力图（绿稀/红密）")):
            ttk.Radiobutton(side, text=txt, value=val, variable=self.show,
                            command=self.redraw).pack(anchor="w")
        ttk.Checkbutton(side, text="隐藏『被删掉的点』的淡红标记",
                        variable=self.hide_removed,
                        command=self.redraw).pack(anchor="w")

        # 吸附
        ttk.Separator(side).pack(fill="x", pady=8)
        ttk.Label(side, text="② 吸附", font=("", 9, "bold")).pack(anchor="w")
        ttk.Label(side, text="搜索半径（硬上限）").pack(anchor="w")
        self.var_r = tk.IntVar(value=SEARCH_R)
        ttk.Scale(side, from_=4, to=40, variable=self.var_r,
                  orient="horizontal", length=220).pack(anchor="w")
        ttk.Label(side, text="距离惩罚（越大越不爱挪）").pack(anchor="w")
        self.var_pen = tk.DoubleVar(value=DIST_PENALTY)
        ttk.Scale(side, from_=0.2, to=4.0, variable=self.var_pen,
                  orient="horizontal", length=220).pack(anchor="w")

        # 效果：灰度减淡
        ttk.Separator(side).pack(fill="x", pady=8)
        ttk.Label(side, text="③ ★ 效果：圈内灰度（你当年的减淡工具）",
                  font=("", 9, "bold")).pack(anchor="w")
        ttk.Label(side, text="★ 正数 = 减淡（变白、点变稀）／ 负数 = 加深",
                  foreground="#666").pack(anchor="w")
        self.var_bright = tk.IntVar(value=0)
        self.lbl_bright = ttk.Label(side, text="0")
        ttk.Scale(side, from_=-80, to=80, variable=self.var_bright,
                  orient="horizontal", length=220,
                  command=lambda _=None: self.on_bright_move()).pack(anchor="w")
        self.lbl_bright.pack(anchor="w")
        ttk.Label(side, text="羽化半径（占选区短边 %）").pack(anchor="w", pady=(4, 0))
        self.var_feather = tk.IntVar(value=int(FEATHER * 100))
        ttk.Scale(side, from_=0, to=20, variable=self.var_feather,
                  orient="horizontal", length=220,
                  command=lambda _=None: self.on_bright_move()).pack(anchor="w")

        ttk.Button(side, text="把这一版固定成新基线",
                   command=self.on_apply).pack(anchor="w", pady=(6, 0))
        ttk.Button(side, text="撤销全部改动",
                   command=self.on_reset).pack(anchor="w", pady=(3, 0))
        # ★ 导出：参谋长的眼睛就靠这个（他看不到屏幕，只能读文件）
        ttk.Separator(side).pack(fill="x", pady=6)
        ttk.Button(side, text="★ 导出这一版（给参谋长看）",
                   command=self.on_export).pack(anchor="w")
        ttk.Label(side, text="导出到 .tmp-tests\\snap2-export\\：\n"
                             "  原图点位+参数（JSON）、成品点位（PNG+BMP）、\n"
                             "  对比图（原 vs 改，带放大）",
                  foreground="#666", justify="left").pack(anchor="w")

        # 状态
        ttk.Separator(side).pack(fill="x", pady=8)
        self.txt = tk.Text(side, width=42, height=15, wrap="word",
                           relief="flat", background="#f7f7f7")
        self.txt.pack(anchor="w")
        self.txt.configure(state="disabled")
        ttk.Label(side, text="滚轮缩放　黄=你圈的　绿=吸完的　淡红=被删掉的点",
                  foreground="#555").pack(anchor="w", pady=(6, 0))

    # ---------------- 坐标 ----------------
    def to_canvas(self, x, y):
        return x * self.scale, y * self.scale

    def to_image(self, cx, cy):
        return cx / self.scale, cy / self.scale

    # ---------------- 鼠标 ----------------
    def on_press(self, e):
        self.drag_from = self.to_image(e.x, e.y); self.drag_to = self.drag_from

    def on_motion(self, e):
        if self.drag_from is None:
            return
        self.drag_to = self.to_image(e.x, e.y)
        self.redraw(preview_drag=True)

    def on_release(self, e):
        if self.drag_from is None:
            return
        self.drag_to = self.to_image(e.x, e.y)
        a, b = self.drag_from, self.drag_to
        self.drag_from = self.drag_to = None
        x0, x1 = sorted((a[0], b[0])); y0, y1 = sorted((a[1], b[1]))
        if (x1 - x0) < 6 or (y1 - y0) < 6:
            self.say("圈太小（不足 6px），当误点忽略了。")
            self.redraw(); return
        self.do_snap((x0, y0, x1, y1))

    def on_wheel(self, e):
        f = 1.12 if e.delta > 0 else 1 / 1.12
        new = max(MIN_VIEW, min(MAX_VIEW, self.scale * f))
        if abs(new - self.scale) < 1e-3:
            return
        self.scale = new
        self.canvas.configure(width=int(self.w * self.scale), height=int(self.h * self.scale))
        self.redraw()

    # ---------------- 吸附 ----------------
    def do_snap(self, box_px):
        x0, y0, x1, y1 = box_px
        pts = ellipse_points((x0, y0, x1, y1))
        rough = polygon_mask((self.h, self.w), pts)
        disp, best_g, g_rough = snap_outline(pts, self.grad, int(self.var_r.get()),
                                            float(self.var_pen.get()))
        snapped = np.clip(pts + normals_of(pts) * disp[:, None], 0, [self.w - 1, self.h - 1])
        mask = polygon_mask((self.h, self.w), snapped)

        # 羽化：按选区短边比例
        short = min(x1 - x0, y1 - y0)
        fpx = max(0.0, short * float(self.var_feather.get()) / 100.0)
        self.soft = self._feather(mask, fpx) if fpx > 0.5 else mask.astype(np.float64)

        med_best = float(np.median(best_g)); med_rough = float(np.median(g_rough))
        moved = int((np.abs(disp) > 2).sum())
        iou = int((rough & mask).sum()) / max(1, int((rough | mask).sum()))
        self.last = {"box": box_px, "pts": pts, "snapped": snapped,
                     "mask": mask, "soft": self.soft, "fpx": fpx,
                     "med_best": med_best, "med_rough": med_rough,
                     "moved": moved, "iou": iou, "area": int(mask.sum())}

        # 圈内密度分层（告诉用户"我要动的是哪一层"）
        dens = local_density_masked(self.dots, mask, 8)
        d_in = dens[mask]
        d_out = dens[~mask]
        self.last["dens_in_med"] = float(np.median(d_in)) if d_in.size else 0.0
        self.last["dens_out_med"] = float(np.median(d_out)) if d_out.size else 0.0
        self.last["dens_p25"] = float(np.percentile(d_in, 25)) if d_in.size else 0.0
        self.last["dens_p75"] = float(np.percentile(d_in, 75)) if d_in.size else 0.0

        weak = med_best < EDGE_WEAK
        L = [f"【你圈的】{x1 - x0:.0f}×{y1 - y0:.0f}px　面积 {int(rough.sum())}px",
             f"【吸完的】面积 {self.last['area']}px"
             f"（{self.last['area'] / max(1, int(rough.sum())):.2f}×）　"
             f"动了 {moved}/{N_POINTS} 点　IoU {iou:.2f}",
             f"轮廓梯度：{med_rough:.1f} → {med_best:.1f}"
             + ("　★ 边太弱（它没有硬吸）" if weak else "　（吸到了边）"),
             f"羽化 {fpx:.1f}px",
             "",
             f"圈内黑点密度：中位 {self.last['dens_in_med'] * 100:.1f}%"
             f"（P25 {self.last['dens_p25'] * 100:.1f}% ~ P75 {self.last['dens_p75'] * 100:.1f}%）",
             f"圈外黑点密度：中位 {self.last['dens_out_med'] * 100:.1f}%"]
        if weak:
            L += ["", "★ 这块吸不住（边太弱）。建议：",
                  "  · 圈小一点、只圈要改的那一条",
                  "  · 贴着边明显的地方再圈",
                  "  · 或把『搜索半径』拉到 4，就用你圈的形状"]
        if self.last["dens_in_med"] < self.last["dens_out_med"]:
            L += ["", "⚠️ 圈内比圈外还稀 —— 你要改的东西可能没圈进来，换个地方圈。"]
        self.say("\n".join(L))
        self.redraw()

    @staticmethod
    def _feather(mask: np.ndarray, radius: float) -> np.ndarray:
        """布尔掩膜 → 0~1 软掩膜（3 趟盒式模糊 ≈ 高斯），**选区外强制为 0**。

        ★ 坑（已踩）：盒式模糊用 edge padding 时，会把选区内的值"抄"到选区外面去，
          于是"圈外灰度逐像素不变"这条判据会失败（实测漏了 768 点）。
          修法：糊完再 `* mask`，把外面钉死为 0。
        """
        r = int(max(1, round(radius)))
        a = mask.astype(np.float64)
        for _ in range(3):
            c = np.cumsum(np.pad(a, ((0, 0), (r + 1, r)), mode="edge"), axis=1)
            a = (c[:, 2 * r + 1:] - c[:, :-(2 * r + 1)]) / (2 * r + 1)
            c = np.cumsum(np.pad(a, ((r + 1, r), (0, 0)), mode="edge"), axis=0)
            a = (c[2 * r + 1:, :] - c[:-(2 * r + 1), :]) / (2 * r + 1)
        return np.clip(a, 0, 1) * mask          # ★ 选区外钉死为 0

    @staticmethod
    def _redither_inplace(gray: np.ndarray, dots_base: np.ndarray, soft: np.ndarray,
                          hard: np.ndarray) -> np.ndarray:
        """改灰度后重新仿色，但**保留选区外的原始点阵**（否则全局重分配会动整张图）。

        ★ 为什么必须做这一步（实测）：
          Floyd–Steinberg 是全局误差扩散 ⇒ 只在选区内改灰度，圈外也会有
          **27 万个点**跟着变、并顺扫描方向泄出 **662px**。
          这里把选区外的点阵贴回基线 ⇒ 圈外**逐像素不变**，代价是选区边界上
          会有一点统计差异（两侧都是同一张图的抖动纹理，肉眼看不出来）。
        """
        d = fs_dither(gray)
        out = dots_base.copy()
        out[hard] = d[hard]              # 只取选区内的新结果
        return out

    # ---------------- 效果：灰度减淡 → 仿色 ----------------
    def on_bright_move(self):
        d = int(self.var_bright.get())
        self.lbl_bright.configure(text=f"{d:+d}")
        self.apply_bright(d)

    def apply_bright(self, delta: int):
        """★ 在灰度层做减淡/加深（带羽化），再仿色成点阵。

        这是用户当年在 PS 里的做法；差别只是"改完立刻看见成品点阵"。
        """
        if not self.last:
            self.say("先圈一块，再调灰度。")
            return
        soft = self.last["soft"]
        hard = self.last["mask"]
        # 灰度 = 基线 + Δ × 软掩膜（只在选区内，羽化过渡，选区外钉死）
        self.gray = np.clip(self.gray_base + float(delta) * soft, 0, 255)
        # ★ 重新仿色，但选区外的点阵贴回基线（否则全局重分配会动整张图）
        self.dots = self._redither_inplace(self.gray, self.dots_base, soft, hard)

        outside_same_gray = bool(np.array_equal(self.gray[~hard], self.gray_base[~hard]))
        outside_same_dots = bool(np.array_equal(self.dots[~hard], self.dots_base[~hard]))

        in_before = int((self.dots_base & hard).sum())
        in_after = int((self.dots & hard).sum())
        tot = 100.0 * self.dots.mean()
        self.say(f"灰度 {delta:+d}（羽化 {self.last['fpx']:.1f}px）\n"
                 f"  圈内黑点 {in_before} → {in_after}"
                 f"（{100.0 * in_after / max(1, in_before):.0f}%）\n"
                 f"  全图墨点 {100.0 * self.dots_base.mean():.1f}% → {tot:.1f}%\n"
                 f"  圈外灰度逐像素不变：{'是' if outside_same_gray else '★ 否'}\n"
                 f"  圈外点阵逐像素不变：{'是' if outside_same_dots else '★ 否'}")
        self.redraw()

    def on_apply(self):
        self.gray_base = self.gray.copy()
        self.dots_base = self.dots.copy()
        self.grad = gradient_mag(self.gray_base)
        self.var_bright.set(0); self.lbl_bright.configure(text="+0")
        self.say(f"已固定为新基线。全图墨点 {100.0 * self.dots.mean():.1f}%")

    def on_reset(self):
        self.gray = self.gray_base.copy()
        self.dots = self.dots_base.copy()
        self.var_bright.set(0); self.lbl_bright.configure(text="+0")
        self.say("已撤销全部改动。")

    # ---------------- ★ 导出（参谋长的眼睛）----------------
    def on_export(self):
        """把"用户选了什么、改了什么、结果什么样"全部落盘，供参谋长读。

        为什么需要：参谋长**看不到屏幕**，只能读文件。而用户在界面上做的
        任何操作（圈的坐标、滑块的数值）对参谋长都是不可见的。
        所以把关键状态全部导成文件 —— 这样"人机协作"靠文件而不是靠眼睛。
        """
        if not self.last:
            self.say("先圈一块再导出（导出的是「你圈的那一块」的结果）。")
            return
        import json
        from datetime import datetime

        out = ROOT / ".tmp-tests" / "snap2-export"
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%H%M%S")
        tag = f"sel{stamp}"

        box = self.last["box"]
        mask = self.last["mask"]
        x0, y0, x1, y1 = [int(v) for v in box]
        # 选区的包围框（留 18% 余量，好看清边界外有没有被影响）
        pad = int(max(x1 - x0, y1 - y0) * 0.18) + 8
        cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
        cx1, cy1 = min(self.w, x1 + pad), min(self.h, y1 + pad)

        # ① 元数据：用户选了什么、参数是什么、结果如何
        in_base = int((self.dots_base & mask).sum())
        in_now = int((self.dots & mask).sum())
        out_changed = int((self.dots[~mask] != self.dots_base[~mask]).sum())
        meta = {
            "导出时间": datetime.now().isoformat(timespec="seconds"),
            "原图": str(self.src_path),
            "上机档": str(self.bmp_path) if self.bmp_path else None,
            "渲染尺寸": [self.w, self.h],
            "用户圈的框_px": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
            "吸附后轮廓_点数": int(len(self.last["snapped"])),
            "吸附后轮廓_前8点": [[round(float(p[0]), 1), round(float(p[1]), 1)]
                              for p in self.last["snapped"][:8]],
            "吸附诊断": {
                "轮廓梯度_原圈中位": round(self.last["med_rough"], 2),
                "轮廓梯度_吸后中位": round(self.last["med_best"], 2),
                "动了几个点": f"{self.last['moved']}/{N_POINTS}",
                "IoU": round(self.last["iou"], 3),
            },
            "羽化半径_px": round(self.last["fpx"], 2),
            "灰度减淡量": int(self.var_bright.get()),
            "圈内黑点": {"基线": in_base, "现在": in_now,
                       "比例": round(in_now / max(1, in_base), 3)},
            "全图墨点": {"基线": round(100.0 * self.dots_base.mean(), 2),
                       "现在": round(100.0 * self.dots.mean(), 2)},
            "★圈外点阵被改动的点数": out_changed,
            "圈内密度_中位": round(self.last["dens_in_med"], 3),
            "圈外密度_中位": round(self.last["dens_out_med"], 3),
        }
        (out / f"{tag}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # ② 成品点位（整图）：PNG 给人看 + 1bit BMP 若将来要上机
        dotsrgb = dots_panel(self.dots, self.dots_base & ~self.dots, self.h, self.w)
        Image.fromarray(dotsrgb).save(out / f"{tag}-成品点位.png")
        Image.fromarray(np.where(self.dots, 0, 255).astype(np.uint8)).convert("1").save(
            out / f"{tag}-成品1bit.bmp")

        # ③ 灰度（改后的）：让人看见"减淡"是怎么过渡的
        Image.fromarray(self.gray.astype(np.uint8)).save(out / f"{tag}-灰度改后.png")

        # ④ ★ 对比图：原 vs 改，各给"选区范围"和"2 倍放大"两档
        def crop(img: Image.Image, z: int) -> Image.Image:
            return img.crop((cx0, cy0, cx1, cy1)).resize(
                ((cx1 - cx0) * z, (cy1 - cy0) * z), Image.NEAREST)

        base_rgb = dots_panel(self.dots_base, None, self.h, self.w)
        now_rgb = dots_panel(self.dots, self.dots_base & ~self.dots, self.h, self.w)
        for z, suffix in ((1, "选区"), (2, "放大2x")):
            a = crop(Image.fromarray(base_rgb), z)
            b = crop(Image.fromarray(now_rgb), z)
            canvas = Image.new("RGB", (a.width * 2 + 10, a.height + 24), (255, 255, 255))
            canvas.paste(a, (0, 24)); canvas.paste(b, (a.width + 10, 24))
            dc = ImageDraw.Draw(canvas)
            dc.text((3, 6), f"改前（{dotsrgb.shape[1]}px 全图里的这一块，{z}x）", fill=(0, 0, 0))
            dc.text((a.width + 13, 6),
                    f"改后：灰度{int(self.var_bright.get()):+d}，圈内黑点 "
                    f"{in_base}→{in_now}", fill=(0, 0, 0))
            dc.rectangle([0, 24, a.width - 1, a.height + 23], outline=(255, 0, 0))
            canvas.save(out / f"{tag}-对比-{suffix}.png")

        self.say(f"已导出到 {out}\n"
                 f"  {tag}.json            你选了什么、参数、结果\n"
                 f"  {tag}-对比-选区.png    改前/改后\n"
                 f"  {tag}-对比-放大2x.png  放大看点数\n"
                 f"  {tag}-成品点位.png     整图成品\n"
                 f"\n圈内黑点 {in_base} → {in_now}　圈外被改动 {out_changed} 点")

    # ---------------- 绘制 ----------------
    def redraw(self, preview_drag: bool = False):
        mode = self.show.get()
        if mode == "bitmap":
            removed = self.dots_base & ~self.dots
            if self.hide_removed.get():
                removed = None
            vis = dots_panel(self.dots, removed, self.h, self.w)
        elif mode == "gray":
            vis = np.stack([self.gray] * 3, axis=-1).astype(np.uint8)
        else:
            r = 8
            m = self.last["mask"] if self.last else np.ones((self.h, self.w), dtype=bool)
            vis = colorize_density(local_density_masked(self.dots, m, r))

        img = Image.fromarray(vis)
        if self.scale != 1.0:
            img = img.resize((int(self.w * self.scale), int(self.h * self.scale)), Image.NEAREST)
        d = ImageDraw.Draw(img)

        if self.last is not None:
            rough = [self.to_canvas(p[0], p[1]) for p in self.last["pts"]]
            d.line(rough + rough[:1], fill=(255, 200, 0), width=2)
            sn = [self.to_canvas(p[0], p[1]) for p in self.last["snapped"]]
            d.line(sn + sn[:1], fill=(0, 220, 90), width=2)
        if preview_drag and self.drag_from and self.drag_to:
            a, b = self.drag_from, self.drag_to
            box = [min(a[0], b[0]) * self.scale, min(a[1], b[1]) * self.scale,
                   max(a[0], b[0]) * self.scale, max(a[1], b[1]) * self.scale]
            d.rectangle(box, outline=(255, 200, 0), width=2)

        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)

    def say(self, text: str):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end"); self.txt.insert("1.0", text)
        self.txt.configure(state="disabled")


def main() -> int:
    # --selftest 是开关，不是路径（别把它当文件名）
    selftest = "--selftest" in sys.argv
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = Path(paths[0]) if len(paths) > 0 else DEF_SRC
    bmp = Path(paths[1]) if len(paths) > 1 else DEF_BMP
    if not src.exists():
        print(f"找不到原图：{src}"); return 2
    print(f"原图 = {src}")
    print(f"上机档 = {bmp if bmp.exists() else '（没找到，将自仿色）'}")

    # ★ 自检开关：--selftest 不弹可见窗口，只跑一次"圈选→减淡→导出"。
    #   参谋长的眼睛只能读文件，所以导出这条路必须先验通。
    root = tk.Tk()
    if selftest:
        root.withdraw()
    app = TestBed2(root, src, bmp if bmp.exists() else None)
    if selftest:
        app.do_snap((185, 45, 265, 85))          # 圈右眉
        app.var_bright.set(40)
        app.on_bright_move()
        app.on_export()
        root.update_idletasks()
    else:
        print("窗口已开。左键拖一个圈 → 松手吸附 → 拖『灰度减淡』滑块。")
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
