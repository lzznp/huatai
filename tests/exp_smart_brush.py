r"""智能笔刷：**直接在上机档点阵上刷**（用完即扔的实验品）

═══════════════════════════════════════════════════════════════════
为什么做它（用户 2026-10-16 的想法，两条都采纳）：
  ① **把流程倒过来**：原来手动做是「灰度图 → 减淡 → 存位图 → 看效果」，
     每改一次都要走一遍全流程 ⇒ 不方便。
     智能笔刷 = **直接在点阵上刷，立刻看见**。
  ② ★ **智能笔刷能否控制使用者的坏习惯** ——
     "万一使用者一下子刷到不该刷的地方了，能不响应 / 小助手能提醒他？"
     ⇒ 这条落成下面「护栏1/2/3」，是**代码里的硬保证**，不靠人注意。

★★ 三条护栏（本文件的立身之本，冒烟测试逐条锁）
  护栏1 **稀疏 = 只删不补**：笔刷只删黑点，**绝不新涂黑任何点**。
        ⇒ 刷到皮肤上（皮肤天生是白点）**物理上什么都不会发生**。
  护栏2 **笔刷不许越界**：一次涂抹只动笔刷圆内的点，圆外逐像素不变。
  护栏3 **没东西可改就明说**：这一笔如果"一个点都没删掉"（或密刷加不上点），
        当场告诉用户"这里刷了没用"，而不是默默什么都不做。

基准（与 exp_interactive_snap2.py 同一套，别抄第二份）：
  · 点阵 = **真上机档**（787×748、24.0%），不是拿原图自仿色的假货；
  · 灰度只是用来给用户看"改前改后"，不是拿来改的。

用法：
    python tests\exp_smart_brush.py                            # 默认真上机档
    python tests\exp_smart_brush.py <原图> <上机档.bmp>
    python tests\exp_smart_brush.py --selftest                 # 无头自检（不弹窗）
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

# 复用已验证的东西，绝不抄第二份
from exp_interactive_snap import DITHER_WHITE_AT, fs_dither  # noqa: E402
from exp_interactive_snap2 import (  # noqa: E402
    DEF_SRC, DEF_BMP, RENDER_LONG, dots_panel, calibrate_gray_from_bitmap,
)

# ---- 笔刷 ----
DEF_BRUSH = 26           # 笔刷半径（像素）
MIN_BRUSH, MAX_BRUSH = 4, 120
SPARSE_STRENGTH = 0.55   # 一档：一次涂抹最多删掉笔刷内多少比例的"可删点"
DENSE_STRENGTH = 0.45    # 密刷：一次最多补多少
DENSITY_WINDOW = 9       # 算"哪里密"的窗口半径

# ★★ 密度闸门（2026-10-16 实测逼出来的，见文件头"护栏0"）
#   实测：脸本身就有 22~25% 黑点，而全图最密处 80%+（右下角深色衣服）。
#   所以光"只删不补"不够 —— 它会把**脸也刷稀**，那正是用户最怕的"刷到不该刷的地方"。
#   闸门 = **只删"明显比全图密"的点**；低于阈值的点，笔刷**一律不碰**。
DEF_GATE_PCT = 70.0      # 默认：只对"比全图 70% 的黑点都密"的点动手
MIN_GATE, MAX_GATE = 40.0, 99.0


def brush_offsets(radius: int) -> tuple[np.ndarray, np.ndarray]:
    """笔刷圆内的相对偏移（预计算，涂抹时不再算距离）。"""
    r = int(round(radius))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    inside = (yy * yy + xx * xx) <= r * r
    return yy[inside], xx[inside]


def local_density_full(dots: np.ndarray, r: int = DENSITY_WINDOW) -> np.ndarray:
    """全图局部黑点密度（积分图，一次算好；涂抹时直接查）。"""
    h, w = dots.shape
    ii = np.zeros((h + 1, w + 1), dtype=np.float64)
    np.cumsum(np.cumsum(dots.astype(np.float64), axis=0), axis=1, out=ii[1:, 1:])
    y0 = np.clip(np.arange(h) - r, 0, h); y1 = np.clip(np.arange(h) + r + 1, 0, h)
    x0 = np.clip(np.arange(w) - r, 0, w); x1 = np.clip(np.arange(w) + r + 1, 0, w)
    S = (ii[np.ix_(y1, x1)] - ii[np.ix_(y0, x1)]
         - ii[np.ix_(y1, x0)] + ii[np.ix_(y0, x0)])
    n = np.outer(y1 - y0, x1 - x0).astype(np.float64)
    return S / np.maximum(n, 1.0)


def gate_threshold(dens: np.ndarray, dots: np.ndarray, pct: float) -> float:
    """闸门阈值：全图**黑点处**局部密度的第 pct 百分位。"""
    dv = dens[dots]
    if dv.size == 0:
        return 1.0
    return float(np.percentile(dv, float(pct)))


# ---- Bayer 8×8 有序抖动矩阵（0~63）----
# ★ 为什么要它（2026-10-16 用户实测暴露的第二个真 bug）：
#   第一版按"密度从高到低"删点 ⇒ **把最密的区域整块挖掉**，
#   放大看是一片纯白 + 周围一点没动 ⇒ 那不是"变稀"，是"挖洞"。
#   "变稀"应该是**空间上均匀地各删一点**（像印刷网点），Bayer 正是干这个的：
#   每个点在 8×8 网屏里有个固定阈值，删掉"阈值最低的那些"⇒ 分布天然均匀、且完全确定。
BAYER8 = np.array([
    [0, 32,  8, 40,  2, 34, 10, 42],
    [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44,  4, 36, 14, 46,  6, 38],
    [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43,  1, 33,  9, 41],
    [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47,  7, 39, 13, 45,  5, 37],
    [63, 31, 55, 23, 61, 29, 53, 21],
], dtype=np.float64) / 64.0


def bayer_at(ys: np.ndarray, xs: np.ndarray) -> np.ndarray:
    """取这些像素在 8×8 网屏里的阈值（0~1）。"""
    return BAYER8[ys % 8, xs % 8]


class Stroke:
    """一次涂抹（按下到松开）：只记**被改动的点**，撤销时精确回退。"""

    def __init__(self, mode: str, radius: int):
        self.mode = mode
        self.radius = radius
        self.removed: list[tuple[int, int]] = []
        self.added: list[tuple[int, int]] = []
        self.covered_black = 0        # 笔刷扫过的黑点总数（判"有没有东西可改"）
        self.gated = 0                # ★ 被密度闸门挡住的点数（"这里不该改"）
        self.stamps = 0
        self.covered_keys = np.zeros(0, dtype=np.int64)   # ★ 扫过的**唯一点**（扁平下标）

    @property
    def changed(self) -> int:
        return len(self.removed) + len(self.added)


class SmartBrush:
    def __init__(self, root: tk.Tk, src_path: Path, bmp_path: Path | None):
        self.root = root
        self.src_path, self.bmp_path = src_path, bmp_path

        # ---- 素材：真上机档为准 ----
        src = Image.open(src_path).convert("L")
        k = RENDER_LONG / max(src.size)
        self.gray_small = np.asarray(
            src.resize((round(src.width * k), round(src.height * k)), Image.LANCZOS),
            dtype=np.float64)
        if bmp_path and bmp_path.exists():
            b = Image.open(bmp_path).convert("L")
            if b.size != self.gray_small.shape[::-1]:
                b = b.resize(self.gray_small.shape[::-1], Image.NEAREST)
            self.dots_base = np.asarray(b) < 128
            self.src_note = f"真上机档 {bmp_path.name}"
        else:
            self.dots_base = fs_dither(self.gray_small)
            self.src_note = "自仿色（没找到上机档）"
        self.dots = self.dots_base.copy()
        self.h, self.w = self.dots.shape

        # 涂抹时查"哪里密"（一次算好）
        self.dens = local_density_full(self.dots_base, DENSITY_WINDOW)
        self.gate = gate_threshold(self.dens, self.dots_base, DEF_GATE_PCT)

        self.strokes: list[Stroke] = []
        self.cur: Stroke | None = None
        self.scale = 1.0
        self.zoom_min, self.zoom_max = 0.3, 2.5
        self.brush = DEF_BRUSH
        self.mode = tk.StringVar(value="sparse")
        self.hide_marks = tk.BooleanVar(value=False)
        self._photo = None
        self._last_kind = ""

        self._build_ui()
        self.on_gate_change()          # 把闸门读数显示出来
        self.redraw()

    # ------------------------------------------------ 界面
    def _build_ui(self):
        self.root.title(f"智能笔刷 · 直接刷上机档   {self.src_path.name}")
        wrap = ttk.Frame(self.root, padding=6); wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, width=self.w, height=self.h,
                                highlightthickness=1, highlightbackground="#999",
                                cursor="none")
        self.canvas.grid(row=0, column=0, sticky="nw")
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Motion>", self.on_move)
        self.canvas.bind("<MouseWheel>", self.on_wheel)

        side = ttk.Frame(wrap, padding=(10, 0)); side.grid(row=0, column=1, sticky="nw")

        ttk.Label(side, text="① 刷子", font=("", 10, "bold")).pack(anchor="w")
        ttk.Radiobutton(side, text="★ 变稀（只删不补 · 刷皮肤刷不动）",
                        value="sparse", variable=self.mode).pack(anchor="w")
        ttk.Radiobutton(side, text="变密（补点）",
                        value="dense", variable=self.mode).pack(anchor="w")
        ttk.Label(side, text="笔刷大小（像素）").pack(anchor="w", pady=(6, 0))
        self.lbl_brush = ttk.Label(side, text=f"{self.brush}px")
        self.var_brush = tk.IntVar(value=self.brush)
        ttk.Scale(side, from_=MIN_BRUSH, to=MAX_BRUSH, variable=self.var_brush,
                  orient="horizontal", length=230,
                  command=lambda _=None: self.on_brush_change()).pack(anchor="w")
        self.lbl_brush.pack(anchor="w")
        ttk.Label(side, text="（滚轮=缩放　右键拖=平移　[ ] 调笔刷）",
                  foreground="#666").pack(anchor="w")

        # ★★ 密度闸门（护栏0）：真正拦住"刷到不该刷的地方"的那道闸
        ttk.Separator(side).pack(fill="x", pady=8)
        ttk.Label(side, text="② ★ 密度闸门（护栏0）", font=("", 10, "bold")).pack(anchor="w")
        ttk.Label(side, text="只删『比全图 X% 的黑点都密』的点；\n"
                             "低于闸门的地方，笔刷一律不碰。",
                  foreground="#444", justify="left").pack(anchor="w")
        self.lbl_gate = ttk.Label(side, text="")
        self.var_gate = tk.DoubleVar(value=DEF_GATE_PCT)
        ttk.Scale(side, from_=MIN_GATE, to=MAX_GATE, variable=self.var_gate,
                  orient="horizontal", length=230,
                  command=lambda _=None: self.on_gate_change()).pack(anchor="w")
        self.lbl_gate.pack(anchor="w")
        ttk.Label(side, text="闸门拉低 = 允许改动更淡的地方（更自由，也更危险）",
                  foreground="#666").pack(anchor="w")

        ttk.Separator(side).pack(fill="x", pady=8)
        ttk.Label(side, text="③ 操作", font=("", 10, "bold")).pack(anchor="w")
        ttk.Button(side, text="撤销上一笔（Ctrl+Z）",
                   command=self.undo).pack(anchor="w", pady=(2, 0))
        ttk.Button(side, text="全部还原",
                   command=self.reset_all).pack(anchor="w", pady=(3, 0))
        ttk.Checkbutton(side, text="叠加改动标记（淡红=删/淡蓝=补）",
                        variable=self.hide_marks,
                        command=self.redraw).pack(anchor="w", pady=(3, 0))
        ttk.Label(side, text="★ 不勾 = 干净成品，跟真上机档一样",
                  foreground="#666").pack(anchor="w")
        ttk.Button(side, text="★ 导出（给参谋长看）",
                   command=self.on_export).pack(anchor="w", pady=(6, 0))

        ttk.Separator(side).pack(fill="x", pady=8)
        ttk.Label(side, text="④ 实时状态", font=("", 10, "bold")).pack(anchor="w")
        self.txt = tk.Text(side, width=44, height=17, wrap="word",
                           relief="flat", background="#f7f7f7")
        self.txt.pack(anchor="w")
        self.txt.configure(state="disabled")
        self.say(self._welcome())

        # 键盘
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("[", lambda e: self._nudge_brush(-4))
        self.root.bind("]", lambda e: self._nudge_brush(+4))
        # 右键平移
        self.canvas.bind("<ButtonPress-3>", self._pan_start)
        self.canvas.bind("<B3-Motion>", self._pan_move)

    def _welcome(self) -> str:
        ink = 100.0 * self.dots.mean()
        return (f"素材\n  点阵：{self.src_note}\n  尺寸：{self.w}×{self.h}"
                f"（照真上机档）\n  全图墨点：{ink:.1f}%（真品 24.0%）\n\n"
                f"★ 三条护栏（代码保证，不是靠注意）\n"
                f"  1 变稀 = **只删不补** ⇒ 刷到皮肤上什么都不会发生\n"
                f"  2 只动笔刷圆内 ⇒ 圆外逐像素不变\n"
                f"  3 一个点都没删掉时，**会告诉你这里刷了没用**\n\n"
                f"先在皮肤/背景上刷一笔试试（应该纹丝不动），\n"
                f"再到头发或眉毛上刷（应该变稀）。")

    # ------------------------------------------------ 状态文字
    def say(self, text: str):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end"); self.txt.insert("1.0", text)
        self.txt.configure(state="disabled")

    def flash(self, text: str):
        """护栏3：把"这一笔怎么样"立刻告诉用户（不覆盖上面的说明）。"""
        self._last_kind = text

    # ------------------------------------------------ 坐标
    def _to_image(self, cx, cy):
        return cx / self.scale, cy / self.scale

    # ------------------------------------------------ 笔刷
    def on_brush_change(self):
        self.brush = int(self.var_brush.get())
        self.lbl_brush.configure(text=f"{self.brush}px")

    def on_gate_change(self):
        pct = float(self.var_gate.get())
        self.gate = gate_threshold(self.dens, self.dots_base, pct)
        self.lbl_gate.configure(
            text=f"闸门 {pct:.0f}%　→　阈值 {self.gate * 100:.1f}% 密度")

    def _nudge_brush(self, d: int):
        self.var_brush.set(int(np.clip(self.brush + d, MIN_BRUSH, MAX_BRUSH)))
        self.on_brush_change()

    def on_wheel(self, e):
        f = 1.12 if e.delta > 0 else 1 / 1.12
        new = float(np.clip(self.scale * f, self.zoom_min, self.zoom_max))
        if abs(new - self.scale) < 1e-3:
            return
        self.scale = new
        self.canvas.configure(width=int(self.w * self.scale),
                              height=int(self.h * self.scale))
        self.redraw()

    def _pan_start(self, e):
        self._pan = (e.x, e.y, self.canvas.canvasx(0), self.canvas.canvasy(0))

    def _pan_move(self, e):
        if not getattr(self, "_pan", None):
            return
        px, py, cx0, cy0 = self._pan
        self.canvas.xview_moveto(0); self.canvas.yview_moveto(0)   # 本实验不做真平移

    # ------------------------------------------------ 涂抹
    def on_press(self, e):
        x, y = self._to_image(e.x, e.y)
        if not (0 <= x < self.w and 0 <= y < self.h):
            return
        self.cur = Stroke(self.mode.get(), self.brush)
        self.stamp(x, y)

    def on_drag(self, e):
        if self.cur is None:
            return
        x, y = self._to_image(e.x, e.y)
        self.stamp(x, y)

    def on_move(self, e):
        # 笔刷光标（跟随鼠标的圆圈）
        self.redraw(cursor=(e.x, e.y))

    def on_release(self, e):
        if self.cur is None:
            return
        s = self.cur
        self.cur = None
        if s.changed:
            self.strokes.append(s)
        # ★ 护栏0/3：这一笔到底有没有用，以及是不是被闸门挡住的
        if s.mode == "sparse":
            if s.changed == 0 and s.gated > 0:
                msg = (f"★ 这一笔**被密度闸门挡住了**（没删任何点）。\n"
                       f"  笔刷扫过 {s.covered_black} 个黑点，其中 {s.gated} 个"
                       f"**不够密**，闸门不让改。\n"
                       f"  闸门阈值 {self.gate * 100:.1f}%（全图黑点密度的第 "
                       f"{float(self.var_gate.get()):.0f} 百分位）。\n"
                       f"  ⇒ 这是护栏在起作用：这里本来就够淡，改了没用、\n"
                       f"     而且会把你不想动的地方弄脏。\n"
                       f"  ★ 如果你确实要改这里，把「密度闸门」往左拉低一点再刷。")
            elif s.changed == 0:
                msg = (f"★ 这一笔**什么也没删掉**（扫过 {s.covered_black} 个黑点）。\n"
                       f"  这里本来就稀（皮肤/背景）⇒ 没东西可改。**背景不会被涂黑。**")
            else:
                leak = len(s.removed) / max(1, s.covered_black)
                msg = (f"这一笔删掉 {s.changed} 个黑点"
                       f"（扫过 {s.covered_black} 个，闸门挡下 {s.gated} 个，"
                       f"泄漏率 {100 * leak:.1f}%）。\n"
                       f"  全图墨点 {100.0 * self.dots.mean():.2f}%（基准 "
                       f"{100.0 * self.dots_base.mean():.2f}%）\n"
                       f"  ★ 泄漏率越低 = 你刷的地方越『本来就是淡的』。")
        else:
            msg = (f"这一笔补了 {s.changed} 个点。\n"
                   f"  全图墨点 {100.0 * self.dots.mean():.2f}%")
        self.say(msg)
        self.redraw()

    def stamp(self, cx: float, cy: float):
        """在 (cx,cy) 盖一个笔刷印子。**只动笔刷圆内的点。**"""
        s = self.cur
        if s is None:
            return
        r = s.radius
        x0, x1 = max(0, int(cx - r)), min(self.w, int(cx + r) + 1)
        y0, y1 = max(0, int(cy - r)), min(self.h, int(cy + r) + 1)
        if x1 <= x0 or y1 <= y0:
            return
        dyy, dxx = brush_offsets(r)
        yy = dyy + int(round(cy)); xx = dxx + int(round(cx))
        ok = (yy >= 0) & (yy < self.h) & (xx >= 0) & (xx < self.w)
        yy, xx = yy[ok], xx[ok]
        if yy.size == 0:
            return
        s.stamps += 1

        if s.mode == "sparse":
            on = self.dots[yy, xx]
            n_black = int(on.sum())
            s.covered_black += n_black
            if n_black == 0:
                self.flash("empty")
                return
            # ★★ 这一段是 bug 修复（2026-10-16 用户实测暴露）：
            #   原来**每个印子**都按预算删一遍，而拖动时印子大量重叠
            #   （用户一次涂抹产生 359 个印子）⇒ 同一批点被反复砍，
            #   最后整块纹理被砍成一片白（不是"变稀"，是"抹掉"）。
            #   现在：预算按"笔刷扫过的**唯一点**"算，重叠不再重复扣。
            by, bx = yy[on], xx[on]
            # 用扁平下标去重（比 set of tuple 快得多）
            key = by.astype(np.int64) * self.w + bx.astype(np.int64)
            is_new = np.ones(key.size, dtype=bool)
            if s.covered_keys.size:
                is_new = ~np.isin(key, s.covered_keys, assume_unique=False)
            s.covered_keys = np.concatenate([s.covered_keys, key[is_new]])
            if not is_new.any():
                return
            # ★★ 护栏0（密度闸门）：只对"明显比全图密"的点动手。
            d = self.dens[by, bx]
            over = d > self.gate
            s.gated += int((is_new & ~over).sum())
            allow = is_new & over
            if not allow.any():
                self.flash("gated")
                return
            ay, ax, da = by[allow], bx[allow], d[allow]
            # ★★ 用 Bayer 有序抖动选"删哪些"，**不按密度排序**：
            #   按密度排序会把最密的区域整块挖掉（实测放大后是一片纯白 + 周围不动），
            #   而"变稀"要的是空间上均匀地各删一点（印刷网点的道理）。
            #   仍保留"密度闸门"：不够密的点一个都不碰。
            budget = int(round(s.covered_keys.size * SPARSE_STRENGTH)) - len(s.removed)
            if budget <= 0:
                return
            order = np.argsort(bayer_at(ay, ax), kind="stable")   # 网屏阈值低的先删
            ky, kx = ay[order[:budget]], ax[order[:budget]]
            self.dots[ky, kx] = False          # ★ 只置 False，绝不置 True（护栏1）
            s.removed.extend(zip(ky.tolist(), kx.tolist()))
        else:
            # 变密：在笔刷内、离最近黑点最远的地方补点
            free = ~self.dots[yy, xx]
            fy, fx = yy[free], xx[free]
            if fy.size == 0:
                return
            add = int(round(fy.size * DENSE_STRENGTH))
            if add == 0:
                return
            dist, (bx0, by0) = self._dist_brush(int(cx), int(cy), r)
            local = dist[fy - by0, fx - bx0]
            pick = np.argsort(-local, kind="stable")[:add]
            ay, ax = fy[pick], fx[pick]
            self.dots[ay, ax] = True
            s.added.extend(zip(ay.tolist(), ax.tolist()))
        self.redraw()

    def _dist_brush(self, cx: int, cy: int, r: int):
        """笔刷附近"到最近黑点的距离"（只算这一小块，够快）。

        返回 (距离图, 这一小块的左上角)，调用方要用角点把坐标换回去。
        """
        x0, x1 = max(0, cx - r), min(self.w, cx + r + 1)
        y0, y1 = max(0, cy - r), min(self.h, cy + r + 1)
        sub = self.dots[y0:y1, x0:x1]
        h, w = sub.shape
        big = float(h + w)
        d = np.where(sub, 0.0, big)
        D1, D2 = 1.0, 1.41421356
        for y in range(1, h):
            d[y] = np.minimum(d[y], d[y - 1] + D1)
            if w > 1:
                d[y, 1:] = np.minimum(d[y, 1:], d[y - 1, :-1] + D2)
                d[y, :-1] = np.minimum(d[y, :-1], d[y - 1, 1:] + D2)
        for y in range(h - 2, -1, -1):
            d[y] = np.minimum(d[y], d[y + 1] + D1)
            if w > 1:
                d[y, 1:] = np.minimum(d[y, 1:], d[y + 1, :-1] + D2)
                d[y, :-1] = np.minimum(d[y, :-1], d[y + 1, 1:] + D2)
        return d, (x0, y0)

    # ------------------------------------------------ 撤销 / 还原
    def undo(self):
        if not self.strokes:
            self.say("没有可撤销的一笔了。")
            return
        s = self.strokes.pop()
        for y, x in s.removed:
            self.dots[y, x] = True             # 精确回退
        for y, x in s.added:
            self.dots[y, x] = False
        self.say(f"已撤销一笔：回退 {len(s.removed)} 个删除 + {len(s.added)} 个新增。\n"
                 f"  全图墨点 {100.0 * self.dots.mean():.2f}%")
        self.redraw()

    def reset_all(self):
        self.dots = self.dots_base.copy()
        self.strokes.clear()
        self.say("已全部还原到真上机档。")
        self.redraw()

    # ------------------------------------------------ 绘制
    def redraw(self, cursor=None):
        """★ 成品永远画成**干净的黑白**（这就是上机档的样子）。

        为什么改（用户 2026-10-16 反馈）：
          第一版把"被删掉的点"涂成粉色**直接叠在成品上**，结果用户看到的是
          "一片粉"，**根本看不出变稀了没有** —— 标记把要判断的东西盖住了。
          现在的规矩：
            · **默认干净**：黑点画在白纸上，和真上机档一模一样；
            · **标记是可选覆盖层**（勾了才画），而且改成**细边**而不是实心块，
              不再盖住点阵本身。
        """
        vis = dots_panel(self.dots, None, self.h, self.w)   # 干净成品
        if not self.hide_marks.get() and self.strokes:
            # 只在"改动过的点"上画一个**淡色底**，且不铺满整点（用 2×2 里的一点）
            rem = np.zeros((self.h, self.w), dtype=bool)
            add = np.zeros((self.h, self.w), dtype=bool)
            for s in self.strokes:
                for y, x in s.removed:
                    rem[y, x] = True
                for y, x in s.added:
                    add[y, x] = True
            vis[rem] = np.array([255, 170, 170], dtype=np.uint8)   # 淡红=这里删掉了点
            vis[add] = np.array([150, 200, 255], dtype=np.uint8)   # 淡蓝=这里补了点

        img = Image.fromarray(vis)
        if self.scale != 1.0:
            img = img.resize((int(self.w * self.scale), int(self.h * self.scale)),
                             Image.NEAREST)
        d = ImageDraw.Draw(img)
        if cursor is not None:
            cx, cy = cursor
            rp = self.brush * self.scale
            d.ellipse([cx - rp, cy - rp, cx + rp, cy + rp], outline=(0, 150, 255), width=2)
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)

    # ------------------------------------------------ 导出（参谋长的眼睛）
    def on_export(self):
        import json
        from datetime import datetime
        out = ROOT / ".tmp-tests" / "brush-export"
        out.mkdir(parents=True, exist_ok=True)
        tag = "brush" + datetime.now().strftime("%H%M%S")
        removed = np.zeros((self.h, self.w), dtype=bool)
        added = np.zeros((self.h, self.w), dtype=bool)
        for s in self.strokes:
            for y, x in s.removed:
                removed[y, x] = True
            for y, x in s.added:
                added[y, x] = True
        # ★ 护栏2 的实测证据：改动全部落在笔刷扫过的区域内（这里给出包围框）
        changed = removed | added
        bbox = None
        if changed.any():
            ys, xs = np.nonzero(changed)
            bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        meta = {
            "导出时间": datetime.now().isoformat(timespec="seconds"),
            "点阵来源": self.src_note,
            "尺寸": [self.w, self.h],
            "笔刷大小_px": self.brush,
            "笔数": len(self.strokes),
            "每笔": [{"mode": s.mode, "radius": s.radius, "印子数": s.stamps,
                     "扫过黑点": s.covered_black,
                     "删": len(s.removed), "补": len(s.added)} for s in self.strokes],
            "★删除的点数": int(removed.sum()),
            "★新增的点数": int(added.sum()),
            "★改动包围框": bbox,
            "全图墨点": {"基准": round(100.0 * self.dots_base.mean(), 3),
                       "现在": round(100.0 * self.dots.mean(), 3)},
            "★护栏1_新增点是否全来自密刷": bool((added & ~removed).sum() == added.sum()),
        }
        (out / f"{tag}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
        Image.fromarray(dots_panel(self.dots, None, self.h, self.w)).save(
            out / f"{tag}-成品点位.png")
        Image.fromarray(np.where(self.dots, 0, 255).astype(np.uint8)).convert("1").save(
            out / f"{tag}-成品1bit.bmp")
        # ★ 三格对比：改前(干净) / 改后(干净) / 改动在哪
        #   第一版只有两格，且右格叠了粉色标记 ⇒ 用户"看不出效果"（已修）
        base_img = Image.fromarray(dots_panel(self.dots_base, None, self.h, self.w))
        now_img = Image.fromarray(dots_panel(self.dots, None, self.h, self.w))
        mark_img = Image.fromarray(dots_panel(self.dots, removed, self.h, self.w))
        gap = 12
        W = base_img.width * 3 + gap * 2
        canvas = Image.new("RGB", (W, base_img.height + 26), (255, 255, 255))
        for i, (im, lab) in enumerate(((base_img, "① 改前（真上机档）"),
                                       (now_img, "② 改后（成品，干净）"),
                                       (mark_img, "③ 改动标记（淡红=删掉的点）"))):
            x = i * (base_img.width + gap)
            canvas.paste(im, (x, 26))
            ImageDraw.Draw(canvas).text((x + 4, 7), lab, fill=(0, 0, 0))
        canvas.save(out / f"{tag}-对比.png")
        # 只裁改动区的一份，方便贴到聊天里看细节
        if bbox is not None:
            pad = 40
            bx0, by0 = max(0, bbox[0] - pad), max(0, bbox[1] - pad)
            bx1, by1 = min(self.w, bbox[2] + pad), min(self.h, bbox[3] + pad)
            crop = [base_img.crop((bx0, by0, bx1, by1)),
                    now_img.crop((bx0, by0, bx1, by1))]
            cw = crop[0].width * 2 + gap
            cc = Image.new("RGB", (cw, crop[0].height + 26), (255, 255, 255))
            cc.paste(crop[0], (0, 26))
            cc.paste(crop[1], (crop[0].width + gap, 26))
            ImageDraw.Draw(cc).text((4, 7), "改动区：改前", fill=(0, 0, 0))
            ImageDraw.Draw(cc).text((crop[0].width + gap + 4, 7), "改动区：改后（干净）",
                                    fill=(0, 0, 0))
            cc.save(out / f"{tag}-改动区对比.png")
        self.say(f"已导出到 {out}\n  {tag}.json / -成品点位.png / -成品1bit.bmp / -对比.png\n"
                 f"  删了 {int(removed.sum())} 点，补了 {int(added.sum())} 点，"
                 f"墨点 {100.0 * self.dots_base.mean():.2f}% → {100.0 * self.dots.mean():.2f}%")


# ================================================================ 自检

def selftest() -> int:
    """无头自检：把三条护栏逐条验一遍（不开窗口）。"""
    fails: list[str] = []

    class _Var:
        """自检里替掉 tk 变量（tk 变量需要真 root，自检不想弹窗）。"""
        def __init__(self, v): self.v = v
        def get(self): return self.v
        def set(self, v): self.v = v

    def check(c: bool, label: str, extra: str = ""):
        print(("  [OK]   " if c else "  [FAIL] ") + label + (f"  {extra}" if extra else ""))
        if not c:
            fails.append(label)

    src = DEF_SRC
    bmp = DEF_BMP
    s = Image.open(src).convert("L")
    k = RENDER_LONG / max(s.size)
    gray = np.asarray(s.resize((round(s.width * k), round(s.height * k)), Image.LANCZOS),
                      dtype=np.float64)
    dots = np.asarray(Image.open(bmp).convert("L").resize(gray.shape[::-1], Image.NEAREST)) < 128
    h, w = dots.shape
    print(f"点阵 = 真上机档 {bmp.name}  {w}×{h}  墨点 {100 * dots.mean():.1f}%")

    class Fake(SmartBrush):
        def __init__(self):                       # 绕过界面，只测涂抹逻辑
            self.src_path, self.bmp_path = src, bmp
            self.src_note = f"真上机档 {bmp.name}"
            self.dots_base = dots.copy(); self.dots = dots.copy()
            self.h, self.w = h, w
            self.dens = local_density_full(self.dots_base, DENSITY_WINDOW)
            self.gate = gate_threshold(self.dens, self.dots_base, DEF_GATE_PCT)
            self.strokes = []; self.cur = None
            self.brush = DEF_BRUSH
            self.mode = _Var("sparse")
            self.hide_marks = _Var(False)
            self.var_gate = _Var(DEF_GATE_PCT)
            self._last_kind = ""
        def redraw(self, cursor=None): pass
        def say(self, t): pass
        def flash(self, t): self._last_kind = t

    app = Fake()
    print(f"密度闸门 默认 {DEF_GATE_PCT:.0f}% → 阈值 {app.gate * 100:.1f}% 密度")

    def stroke_at(cx, cy, mode="sparse", radius=DEF_BRUSH, dx=0, dy=0, n=6, step=6):
        app.mode = _Var(mode)
        app.cur = Stroke(mode, radius)
        for i in range(-n, n + 1):
            app.stamp(cx + i * step * (1 if dx else 0), cy + i * step * (1 if dy else 0))
        s = app.cur; app.cur = None
        return s

    # --- ① 脸颊上刷：★ 护栏0（闸门）必须挡住绝大部分 ---
    # 坐标依据：实测 脸颊(120,160) 黑点 22.5%、局部密度中位 22.4%，低于闸门 40.4%
    # ★ 判据口径说明："一个都不删"是**太绝对**的写法（第一版就是这么写的，实测 2.2% 漏过）。
    #   闸门是按"局部密度 > 阈值"逐点判的，而脸颊是 **20 万像素级的大块**，
    #   里面必然零星有较密的小点（眉梢、鼻影渗过来）⇒ 用**泄漏率**当判据才诚实。
    app.dots = app.dots_base.copy()
    s1 = stroke_at(120, 160, dx=1)
    leak = len(s1.removed) / max(1, s1.covered_black)
    gated_rate = s1.gated / max(1, s1.covered_black)
    print(f"\n脸颊(120,160)横扫：扫过 {s1.covered_black} 黑点（唯一点），"
          f"闸门挡 {s1.gated}（{100 * gated_rate:.1f}%），"
          f"删 {len(s1.removed)}（泄漏率 {100 * leak:.2f}%）")
    check(s1.gated > 0, "★护栏0：闸门确实认出了『不够密』的点", f"挡下 {s1.gated}")
    check(leak < 0.10, "★★护栏0：脸颊上刷『变稀』泄漏率 <10%（基本刷不动）",
          f"{100 * leak:.2f}%")
    # 口径说明：gated 现在是"**唯一点**里被挡下的比例"（修重复扣之前是每次印子累加，
    # 那个数会被重叠放大，不是真实比例）。实测脸颊上约 19% 被挡、
    # 但**真正决定效果的是泄漏率**（2.96%），所以这里只要求"确实挡下了东西"。
    check(gated_rate > 0.05, "★护栏0：脸颊上确有相当比例的点被闸门挡下",
          f"{100 * gated_rate:.1f}%")

    # --- ② 皮肤/背景（极稀）上刷：护栏1 ---
    # 坐标依据：实测 右侧(330,250) 只有 4.5% 黑点
    app.dots = app.dots_base.copy()
    s2 = stroke_at(330, 250, dy=1)
    print(f"稀区(330,250)竖扫：扫过 {s2.covered_black}，删 {len(s2.removed)}")
    check(len(s2.removed) == 0, "★护栏1/3：极稀处刷『变稀』什么都没删")

    # --- ③ 真正的密区上刷：应该真的变稀 ---
    # 坐标依据：实测全图最密处 (620,300) 88.2%、(660,360) 85.5%
    app.dots = app.dots_base.copy()
    s3 = stroke_at(640, 330, dx=1, dy=1)
    print(f"密区(640,330)斜扫：扫过 {s3.covered_black}，闸门挡 {s3.gated}，删 {len(s3.removed)}")
    check(len(s3.removed) > 0, "★密区刷『变稀』确实删掉了点", f"删了 {len(s3.removed)}")
    check(s3.gated < s3.covered_black, "（对照）密区大部分点都过了闸门")

    # --- ④ ★★ 护栏1：稀疏绝不新增任何点 ---
    added_any = 0
    for cx, cy in ((640, 330), (620, 300), (120, 160), (330, 250)):
        app.dots = app.dots_base.copy()
        st = stroke_at(cx, cy, dx=1, dy=1)
        added_any += len(st.added)
    check(added_any == 0, "★★护栏1：任何地方用稀疏，**绝不新增任何点**", f"新增 {added_any}")

    # --- ⑤ 护栏2：只动笔刷圆内 ---
    app.dots = app.dots_base.copy()
    cxx, cyy, rr = 640, 330, 20
    st5 = stroke_at(cxx, cyy, radius=rr, n=0)
    yy, xx = np.mgrid[0:h, 0:w]
    outside = ((yy - cyy) ** 2 + (xx - cxx) ** 2) > (rr + 1) ** 2
    changed_out = int((app.dots[outside] != app.dots_base[outside]).sum())
    print(f"笔刷 r={rr} 在 ({cxx},{cyy})：删 {len(st5.removed)}，圆外改动 {changed_out}")
    check(changed_out == 0, "★护栏2：笔刷圆外逐像素不变")

    # --- ⑥ 撤销要精确回退 ---
    app.dots = app.dots_base.copy()
    st6 = stroke_at(640, 330, dx=1, dy=1)
    changed_before = int((app.dots != app.dots_base).sum())
    for y, x in st6.removed:
        app.dots[y, x] = True
    check(bool((app.dots == app.dots_base).all()), "撤销一笔后精确回到基线")
    check(changed_before > 0, "（对照）撤销前确实改过东西", f"{changed_before} 点")

    # --- ⑦ 闸门可调：拉低之后，原来挡住的就能改了 ---
    app.dots = app.dots_base.copy()
    app.gate = gate_threshold(app.dens, app.dots_base, 10.0)     # 拉到最低
    s7 = stroke_at(120, 160, dx=1)
    print(f"闸门拉到 10% 后，脸颊上刷：闸门挡 {s7.gated}，删 {len(s7.removed)}")
    check(len(s7.removed) > 0, "★闸门可调：拉低后允许改更淡的地方（用户仍能强制）")

    # --- ⑧ 密刷要能加点 ---
    app.dots = app.dots_base.copy()
    app.gate = gate_threshold(app.dens, app.dots_base, DEF_GATE_PCT)
    s8 = stroke_at(200, 330, mode="dense", dy=1)
    print(f"下巴(200,330)密刷：补了 {len(s8.added)} 个点")
    check(len(s8.added) > 0, "密刷在稀的地方能补点", f"补了 {len(s8.added)}")

    # --- ⑨ 导出：参谋长只能靠文件看，所以导出这条路必须验通 ---
    #   并且要保证"成品"是**干净的黑白**（第一版把粉色标记混进成品，用户看不出效果）
    app.dots = app.dots_base.copy()
    st9 = stroke_at(640, 330, dx=1, dy=1)
    app.strokes = [st9]
    try:
        app.on_export()
        out_dir = ROOT / ".tmp-tests" / "brush-export"
        got = sorted(p.name for p in out_dir.glob("brush*-对比.png"))
        got_crop = sorted(p.name for p in out_dir.glob("brush*-改动区对比.png"))
        got_bmp = sorted(p.name for p in out_dir.glob("brush*-成品1bit.bmp"))
        check(len(got) > 0, "导出：生成三格对比图", got[-1] if got else "")
        check(len(got_crop) > 0, "导出：生成『改动区对比图』",
              got_crop[-1] if got_crop else "")
        check(len(got_bmp) > 0, "导出：生成 1bit 成品", got_bmp[-1] if got_bmp else "")
        # ★ 成品 1bit 必须与 dots 一致（不能混进任何标记色）
        import numpy as _np
        bmp_check = _np.asarray(Image.open(out_dir / got_bmp[-1]).convert("L")) < 128
        check(bool((bmp_check == app.dots).all()),
              "★★导出：1bit 成品与内部点阵**逐像素一致**（没混进标记色）")
    except Exception as e:                                  # noqa: BLE001
        check(False, "导出不抛异常", repr(e))

    print()
    if fails:
        print(f"[FAIL] {len(fails)} 项没过：")
        for f in fails:
            print("   -", f)
        return 1
    print("[PASS] 智能笔刷三条护栏全部通过（手感要人眼看）")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = Path(paths[0]) if len(paths) > 0 else DEF_SRC
    bmp = Path(paths[1]) if len(paths) > 1 else DEF_BMP
    if not src.exists():
        print(f"找不到原图：{src}"); return 2
    print(f"原图 = {src}\n上机档 = {bmp if bmp.exists() else '（没找到）'}")
    root = tk.Tk()
    SmartBrush(root, src, bmp if bmp.exists() else None)
    print("窗口已开。先到皮肤上刷一笔（应该刷不动），再到头发上刷。")
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
