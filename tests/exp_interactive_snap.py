r"""交互试验台：**圈选 + 磁性吸附 + 稀疏/加密**（用完即扔，不进画台）

为什么要有它（2026-10-16 用户拍板"先把眼前的交互弄好"）：
  · 上一场的磁吸数据（嘴唇 IoU 0.83）用的是**手写死的方框**——算法对，但**手感没验过**；
  · 所以这一台只回答三个问题，答完就扔：
      ① 这么圈、这么吸，手感对不对？
      ② 眉毛那块到底吸成什么样？（实测信号比 0.46，门槛 0.6 ⇒ 预期"吸不住"）
      ③ "圈一块"这个动作愿不愿意这么用？

三层分离（别混着谈）：
  ① 手势：按住左键拖 → 松手才吸附（拖的过程中不吸，免得抖）
  ② 反馈：黄=你圈的 / 绿=吸完的 / 红=最终选区；吸不住时**明说**并建议换个圈法
  ③ 效果：稀疏 / 加密 —— ★ 直接作用在**点阵**上（改灰度再重仿色是另一条路，本台不做）

用法：
    python tests\exp_interactive_snap.py                 # 默认用美女那张真图
    python tests\exp_interactive_snap.py <图片路径>

★ 本文件是实验品，不是画台的一部分。手感定了之后，再把定下来的交互搬进画台。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 本机控制台是 GBK：先声明 UTF-8 输出，否则中文会 UnicodeEncodeError 崩掉
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent

import numpy as np  # noqa: E402
import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402
from PIL import Image, ImageDraw, ImageTk  # noqa: E402

# ---- 真图（与上一场磁吸实验同一张，便于对照）----
DEFAULT_REAL = Path(r"D:\画台\projects\美女玻璃画\order-20261012-165706\src_one.jpeg")

# ---- 吸附参数（与 exp_circle_snap3.py 同口径，便于对照）----
N_POINTS = 96        # 轮廓离散成多少个点
SEARCH_R = 18        # 每点沿法线最多挪多少像素（硬上限，防跑远）
DIST_PENALTY = 1.2   # 距离惩罚：挪得越远越要"边更强"才值
SMOOTH_WIN = 7       # 位移的中值平滑窗口

# ---- "吸住了"的判定门槛（梯度中位数）----
# 出处：exp_circle_snap3.py 的判定 `median(best_g) < 6 ⇒ 边太弱`；这里沿用同一口径
EDGE_WEAK = 6.0

# ---- 显示 ----
VIEW_SCALE = 1.6     # 初始放大（400×380 的图放大看更清楚）
MAX_VIEW = 3.0
MIN_VIEW = 1.0

# ---- 点阵口径（★ 与 kernel\image_lib\pipeline.py 的 _fs_dither 逐字同口径）----
DITHER_WHITE_AT = 127.5
# 稀疏：在这一带（半径）内找最近的未删点，越近越优先删
SPARSE_NEIGHBORHOOD = 3.0


# ============================================================
# 一、纯计算（不碰界面，方便单独测）
# ============================================================

def fs_dither(gray: np.ndarray) -> np.ndarray:
    """Floyd–Steinberg 仿色，返回 bool 点阵（True = 黑点 = 要雕）。

    ★ 口径与 kernel\\image_lib\\pipeline.py 的 `_fs_dither` 逐字一致
      （阈值 127.5、误差扩散 7/16·3/16·5/16·1/16，纯确定性无随机）。
    这里返回 bool 而不是 {0,255}，纯粹是试验台内部方便。
    """
    h, w = gray.shape
    rows = gray.astype(np.float64).tolist()
    out = np.zeros((h, w), dtype=bool)
    c7, c3, c5, c1 = 7 / 16, 3 / 16, 5 / 16, 1 / 16
    for y in range(h):
        row = rows[y]
        nxt = rows[y + 1] if y + 1 < h else None
        outrow = out[y]
        for x in range(w):
            old = row[x]
            is_white = old >= DITHER_WHITE_AT
            outrow[x] = not is_white          # 白点=False，黑点=True
            err = old - (255.0 if is_white else 0.0)
            if x + 1 < w:
                row[x + 1] += err * c7
            if nxt is not None:
                if x > 0:
                    nxt[x - 1] += err * c3
                nxt[x] += err * c5
                if x + 1 < w:
                    nxt[x + 1] += err * c1
    return out


def gradient_mag(gray: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(gray)
    return np.hypot(gx, gy)


def ellipse_points(box, n: int = N_POINTS) -> np.ndarray:
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    rx, ry = max(1e-6, (x1 - x0) / 2.0), max(1e-6, (y1 - y0) / 2.0)
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([cx + rx * np.cos(t), cy + ry * np.sin(t)], axis=1)


def normals_of(pts: np.ndarray) -> np.ndarray:
    """相邻点切线的法线（单位向量）。"""
    tan = np.roll(pts, -1, axis=0) - np.roll(pts, 1, axis=0)
    nrm = np.stack([-tan[:, 1], tan[:, 0]], axis=1)
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    return nrm / np.maximum(ln, 1e-6)


def _sample(g: np.ndarray, x: float, y: float) -> float:
    h, w = g.shape
    xi, yi = int(round(x)), int(round(y))
    if xi < 0 or yi < 0 or xi >= w or yi >= h:
        return 0.0
    return float(g[yi, xi])


def snap_outline(pts: np.ndarray, grad: np.ndarray, r: int = SEARCH_R,
                 penalty: float = DIST_PENALTY):
    """磁吸：每点沿法线在 ±r 内找"代价 = −梯度 + 距离惩罚×位移"最小处。

    返回 (位移数组, 每点吸到的梯度, 原始圈上的梯度)。**硬上限 r 保证不可能跑远。**
    """
    nrm = normals_of(pts)
    offs = np.arange(-r, r + 1)
    disp = np.zeros(len(pts))
    best_g = np.zeros(len(pts))
    for i, (p, nv) in enumerate(zip(pts, nrm)):
        costs = [(-_sample(grad, p[0] + nv[0] * d, p[1] + nv[1] * d) + penalty * abs(d))
                 for d in offs]
        k = int(np.argmin(costs))
        disp[i] = offs[k]
        best_g[i] = _sample(grad, p[0] + nv[0] * offs[k], p[1] + nv[1] * offs[k])
    half = SMOOTH_WIN // 2
    if SMOOTH_WIN > 1 and half > 0:
        padded = np.concatenate([disp[-half:], disp, disp[:half]])
        disp = np.array([np.median(padded[i:i + SMOOTH_WIN]) for i in range(len(disp))])
    g_rough = np.array([_sample(grad, p[0], p[1]) for p in pts])
    return disp, best_g, g_rough


def polygon_mask(shape, pts: np.ndarray, expand: float = 0.0) -> np.ndarray:
    """多边形 → 布尔掩膜。expand>0 时先外扩（按质心方向推）。"""
    h, w = shape
    if expand > 0:
        c = pts.mean(axis=0)
        v = pts - c
        ln = np.linalg.norm(v, axis=1, keepdims=True)
        pts = pts + (v / np.maximum(ln, 1e-6)) * expand
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).polygon([tuple(p) for p in pts], fill=255)
    return np.asarray(m) > 0


# ---- 稀疏 / 加密：★ 直接作用在点阵上（不碰灰度）----

def _dots_from_distance(distance: np.ndarray, mask: np.ndarray, target: int,
                        usable_limit: float, prefer_far: bool = True) -> np.ndarray:
    """在 mask 内按距离场**精确**选 target 个点（不会因并列值多选/少选）。

    prefer_far=True（加密用）：选距离**最大**的 ⇒ 补在离已有黑点最远处；
    prefer_far=False（稀疏用）：选距离**最小**的 ⇒ 优先删最挤的点。
    ★ 用 argsort 精确定数：密点阵上距离取值只有 0/1，用阈值法会因并列而选空（踩过）。
    """
    out = np.zeros_like(mask)
    if target <= 0:
        return out
    work = np.where(mask, distance, -1.0)
    flat = work.ravel()
    cand = np.flatnonzero(flat >= 0)
    if cand.size == 0:
        return out
    target = min(target, cand.size)
    vals = flat[cand]
    order = np.argsort(-vals, kind="stable") if prefer_far else np.argsort(vals, kind="stable")
    chosen = cand[order[:target]]
    out.ravel()[chosen] = True
    return out


def _distance_to(seed: np.ndarray) -> np.ndarray:
    """到 seed(True) 的近似欧氏距离场（chamfer，**全向量化**，不依赖 scipy）。

    为什么不用逐像素循环：787×787 上图内约 62 万点，Python 层循环要几秒，
    拖滑块会卡死。这里用「前缀累积最小值」把每条横/纵扫描变成 O(w) 的 numpy 操作。

    seed 全为 False 时返回一个有限的大数场（调用方应避免这种输入）。
    """
    h, w = seed.shape
    big = float(h + w) * 4.0
    BIGI = np.inf
    d = np.where(seed, 0.0, BIGI)
    D1, D2 = 1.0, 1.41421356

    def accum_min_axis(a: np.ndarray, fwd: bool) -> None:
        """沿最后一维做「d[i] = min(d[i], d[i-1] + D1)」的累计最小（向量化）。"""
        idx = np.arange(a.shape[-1], dtype=np.float64)
        k = idx if fwd else idx[::-1]
        b = a - D1 * k if fwd else a + D1 * k
        m = np.minimum.accumulate(b, axis=-1)
        v = m + D1 * k if fwd else m - D1 * k
        np.copyto(a, np.minimum(a, v))

    # 第 1 趟：上 → 下
    accum_min_axis(d, fwd=True)
    d[1:, :] = np.minimum(d[1:, :], d[:-1, :] + D1)
    if w > 1:
        d[1:, 1:] = np.minimum(d[1:, 1:], d[:-1, :-1] + D2)
        d[1:, :-1] = np.minimum(d[1:, :-1], d[:-1, 1:] + D2)
    accum_min_axis(d, fwd=True)

    # 第 2 趟：下 → 上
    accum_min_axis(d, fwd=False)
    d[:-1, :] = np.minimum(d[:-1, :], d[1:, :] + D1)
    if w > 1:
        d[:-1, 1:] = np.minimum(d[:-1, 1:], d[1:, :-1] + D2)
        d[:-1, :-1] = np.minimum(d[:-1, :-1], d[1:, 1:] + D2)
    accum_min_axis(d, fwd=False)

    d[~np.isfinite(d)] = big
    return d


def dots_edit(dots: np.ndarray, mask: np.ndarray, factor: float,
              neighborhood: float = SPARSE_NEIGHBORHOOD) -> tuple[np.ndarray, str]:
    """在 mask 内稀疏/加密点阵。factor<1 变稀，>1 变密。

    返回 (新的点阵, 说明文字)。**只在 mask 内动，mask 外逐像素不变。**
    """
    out = dots.copy()
    inside = int(mask.sum())
    if inside == 0:
        return dots, "圈内没有像素"
    cur_black = int((dots & mask).sum())
    want = int(round(cur_black * factor))
    want = max(0, min(inside, want))

    if factor == 1.0:
        return dots, "没改（比例 100%）"

    if factor < 1.0:
        # ---- 变稀：**只删不补**（关键！补点会把背景涂黑，"稀疏"就变成"搬点"了）----
        need = cur_black - want
        if need <= 0:
            return dots, "已经比目标还稀，没得删"
        cand = dots & mask
        # 优先删**最挤**的黑点：取它到最近**其它**黑点的距离，最小的一批删掉。
        # 这样留下的是相对分散的点 ⇒ 视觉上就是"变稀"。
        self_dist = _distance_to_local(cand, neighborhood)
        kill = _dots_from_distance(self_dist, cand, need, neighborhood, prefer_far=False)
        out[mask] = False
        out[cand & ~kill] = True
        return out, (f"删了 {int((cand & kill).sum())} 个黑点"
                     f"（圈内 {cur_black} → {int((out & mask).sum())}），一个都没补")

    # ---- 变密：补黑点（可以补，因为背景本来就是白的，补点只是变密）----
    add = want - cur_black
    if add <= 0:
        return dots, "已经比目标还密，没得加"
    cand = dots & mask
    # 从 mask 边缘与已有黑点一起起算 ⇒ 优先补"离已有黑点最远"的位置
    edge = mask & ~_erode(mask)
    dist = _distance_to(cand | edge)
    newdots = _dots_from_distance(dist, mask, add, neighborhood, prefer_far=True)
    out |= newdots
    return out, f"加了 {int((out & mask).sum()) - cur_black} 个黑点"


def _distance_to_local(dots: np.ndarray, radius: float) -> np.ndarray:
    """每个黑点到**最近的其它黑点**的距离（非黑点为 0）。

    做法：**分层腐蚀**——半径 t 的腐蚀正好保留"离边界 ≥t"的点，
    所以"已经消失"的那个 t 就是该点到最近其它点的距离（切比雪夫距离，够用）。
    全向量化，最多 radius 轮，不用逐点循环（逐点在几万点上会卡死界面）。
    """
    h, w = dots.shape
    r = int(max(1, round(radius))) + 1
    out = np.zeros((h, w), dtype=np.float64)
    cur = dots.copy()
    for t in range(1, r + 1):
        prev = cur
        cur = _erode(cur)
        gone = prev & ~cur          # 这一轮刚消失的点 ⇒ 距离 = t-1
        out[gone] = float(t - 1)
    out[cur] = float(r)             # 一直没消失的（很孤立）给上限
    out[~dots] = 0.0
    return out


def _erode(mask: np.ndarray) -> np.ndarray:
    m = mask
    e = m.copy()
    e[1:, :] &= m[:-1, :]
    e[:-1, :] &= m[1:, :]
    e[:, 1:] &= m[:, :-1]
    e[:, :-1] &= m[:, 1:]
    return e


# ============================================================
# 二、界面
# ============================================================

class TestBed:
    def __init__(self, root: tk.Tk, img_path: Path):
        self.root = root
        self.img_path = img_path

        src = Image.open(img_path)
        self.src_size = src.size                      # (w, h)
        self.gray = np.asarray(src.convert("L"), dtype=np.float64)
        self.h, self.w = self.gray.shape
        self.grad = gradient_mag(self.gray)           # ★ 只算一次（拖动时不重算）

        # 底图（灰度，给眼睛看形状）
        self.gray_rgb = np.stack([self.gray] * 3, axis=-1).astype(np.uint8)

        # 基线点阵（一次性仿色；稀疏/加密都在它上面做）
        self.dots_base = fs_dither(self.gray)
        self.dots = self.dots_base.copy()
        self.black_pct = 100.0 * self.dots.mean()

        self.scale = VIEW_SCALE
        self.drag_from = None
        self.drag_to = None
        self.last = None          # 上一次吸附的结果字典
        self._photo = None

        self._build_ui()
        self.redraw()

    # ---------- 界面搭建 ----------
    def _build_ui(self):
        self.root.title(f"交互试验台 · 圈选+磁吸+稀疏/加密  —  {self.img_path.name}")
        wrap = ttk.Frame(self.root, padding=6)
        wrap.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(wrap, width=int(self.w * self.scale),
                                height=int(self.h * self.scale),
                                highlightthickness=1, highlightbackground="#888",
                                cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="nw")
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<MouseWheel>", self.on_wheel)

        side = ttk.Frame(wrap, padding=(10, 0))
        side.grid(row=0, column=1, sticky="nw")

        # —— 参数 ——
        ttk.Label(side, text="吸附搜索半径（硬上限，防跑远）").pack(anchor="w")
        self.var_r = tk.IntVar(value=SEARCH_R)
        ttk.Scale(side, from_=4, to=40, variable=self.var_r, orient="horizontal",
                  length=200).pack(anchor="w")

        ttk.Label(side, text="距离惩罚（越大越不爱挪）").pack(anchor="w", pady=(8, 0))
        self.var_pen = tk.DoubleVar(value=DIST_PENALTY)
        ttk.Scale(side, from_=0.2, to=4.0, variable=self.var_pen,
                  orient="horizontal", length=200).pack(anchor="w")

        ttk.Label(side, text="外扩（像素，吸完再往外推）").pack(anchor="w", pady=(8, 0))
        self.var_exp = tk.IntVar(value=0)
        ttk.Scale(side, from_=0, to=12, variable=self.var_exp,
                  orient="horizontal", length=200).pack(anchor="w")

        # —— 效果：稀疏 / 加密 ——
        ttk.Separator(side).pack(fill="x", pady=10)
        ttk.Label(side, text="★ 效果：圈内点阵密度").pack(anchor="w")
        ttk.Label(side, text="100% = 不动；<100% 变稀；>100% 变密",
                  foreground="#666").pack(anchor="w")
        self.var_ratio = tk.IntVar(value=100)
        self.lbl_ratio = ttk.Label(side, text="100%")
        ttk.Scale(side, from_=10, to=200, variable=self.var_ratio,
                  orient="horizontal", length=200,
                  command=lambda _=None: self.on_ratio_move()).pack(anchor="w")
        self.lbl_ratio.pack(anchor="w")

        ttk.Button(side, text="把密度固定下来（成为新的基线）",
                   command=self.on_apply).pack(anchor="w", pady=(6, 0))
        ttk.Button(side, text="撤销全部密度改动（回到基线）",
                   command=self.on_reset).pack(anchor="w", pady=(4, 0))

        # —— 状态文字 ——
        ttk.Separator(side).pack(fill="x", pady=10)
        self.txt = tk.Text(side, width=38, height=14, wrap="word",
                           relief="flat", background="#f5f5f5")
        self.txt.pack(anchor="w")
        self.txt.configure(state="disabled")

        # —— 操作提示 ——
        ttk.Label(side, text=("左键拖一个圈 → 松手吸附\n"
                              "滚轮：缩放\n"
                              "黄=你圈的  绿=吸完的  红=最终选区（点阵）"),
                  foreground="#555").pack(anchor="w", pady=(8, 0))

    # ---------- 坐标换算 ----------
    def to_canvas(self, x, y):
        return x * self.scale, y * self.scale

    def to_image(self, cx, cy):
        return cx / self.scale, cy / self.scale

    # ---------- 鼠标 ----------
    def on_press(self, e):
        self.drag_from = self.to_image(e.x, e.y)
        self.drag_to = self.drag_from

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
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        if (x1 - x0) < 4 or (y1 - y0) < 4:
            self.say("圈太小（不足 4px），当误点忽略了。重新拖大一点。")
            self.redraw()
            return
        self.do_snap((x0, y0, x1, y1))

    def on_wheel(self, e):
        factor = 1.1 if e.delta > 0 else 1 / 1.1
        new = max(MIN_VIEW, min(MAX_VIEW, self.scale * factor))
        if abs(new - self.scale) < 1e-3:
            return
        self.scale = new
        self.canvas.configure(width=int(self.w * self.scale),
                              height=int(self.h * self.scale))
        self.redraw()

    # ---------- 吸附 ----------
    def do_snap(self, box_px):
        x0, y0, x1, y1 = box_px
        r = int(self.var_r.get())
        penalty = float(self.var_pen.get())
        expand = int(self.var_exp.get())

        pts = ellipse_points((x0, y0, x1, y1))
        rough = polygon_mask((self.h, self.w), pts)
        disp, best_g, g_rough = snap_outline(pts, self.grad, r, penalty)
        snapped = np.clip(pts + normals_of(pts) * disp[:, None], 0, [self.w - 1, self.h - 1])
        snapped_mask = polygon_mask((self.h, self.w), snapped, expand=expand)

        med_best = float(np.median(best_g))
        med_rough = float(np.median(g_rough))
        moved = int((np.abs(disp) > 2).sum())
        inter = int((rough & snapped_mask).sum())
        union = int((rough | snapped_mask).sum())
        iou = inter / max(1, union)

        self.last = {
            "box": (x0, y0, x1, y1),
            "pts": pts, "snapped": snapped,
            "rough_mask": rough, "mask": snapped_mask,
            "moved": moved, "iou": iou, "expand": expand,
            "med_best": med_best, "med_rough": med_rough,
            "area_rough": int(rough.sum()), "area_new": int(snapped_mask.sum()),
        }

        # ★ 反馈层：吸不住就明说，并建议换个圈法
        weak = med_best < EDGE_WEAK
        lines = [
            f"【你圈的】{x1 - x0}×{y1 - y0}px，面积 {self.last['area_rough']}px",
            f"【吸完的】面积 {self.last['area_new']}px"
            f"（{self.last['area_new'] / max(1, self.last['area_rough']):.2f}×），外扩 {expand}px",
            f"轮廓梯度：原圈 {med_rough:.1f} → 吸附后 {med_best:.1f}",
            f"动了(>2px)的点：{moved}/{N_POINTS}　IoU {iou:.2f}",
        ]
        if weak:
            lines += [
                "",
                "★ 判定：**这块吸不住**（边太弱）。",
                f"  理由：吸附后轮廓梯度中位数 {med_best:.1f} < 门槛 {EDGE_WEAK:.0f}。",
                "  ⇒ 系统故意**没有硬吸**：硬吸会把你圈到鼻子或脸颊上去。",
                "  ★ 建议换个圈法，任选一种：",
                "    · 圈小一点、只圈你要改的那一条（别把整块都圈进来）",
                "    · 往边明显的地方挪一下再圈（比如贴着眉毛下缘）",
                "    · 干脆不要它吸 —— 把「吸附搜索半径」拉到 4，就用你圈的形状",
            ]
        else:
            lines += ["", f"★ 判定：吸到了较明显的边（梯度 {med_rough:.1f} → {med_best:.1f}）。"]
        self.say("\n".join(lines))
        self.redraw()

    # ---------- 密度 ----------
    def on_ratio_move(self):
        pct = int(self.var_ratio.get())
        self.lbl_ratio.configure(text=f"{pct}%")
        self.apply_ratio(pct)

    def apply_ratio(self, pct: int):
        """只重做点阵那一层，不重算吸附（所以拖滑块快）。

        ★ 每次从**基线点阵**重做，而不是在上一次结果上叠加——
          否则滑块来回拖会把改动越叠越多（已修）。
        """
        if not self.last:
            self.say("先圈一块，再调密度。")
            return
        mask = self.last["mask"]
        self.dots = self.dots_base.copy()          # ★ 每次从基线起算
        before = int((self.dots & mask).sum())
        factor = pct / 100.0
        if factor != 1.0:
            self.dots, note = dots_edit(self.dots, mask, factor)
        else:
            note = "没改（比例 100%）"
        after = int((self.dots & mask).sum())
        total = 100.0 * self.dots.mean()
        self.say(f"圈内黑点 {before} → {after}（{note}）\n全图墨点 {total:.1f}%")
        self.redraw()

    def on_apply(self):
        if not self.last:
            self.say("先圈一块。")
            return
        self.dots_base = self.dots.copy()          # 把当前点阵变成新基线
        self.var_ratio.set(100)
        self.lbl_ratio.configure(text="100%")
        self.black_pct = 100.0 * self.dots.mean()
        self.say(f"已固定为新基线。全图墨点 {self.black_pct:.1f}%")

    def on_reset(self):
        self.dots = self.dots_base.copy()
        self.var_ratio.set(100)
        self.lbl_ratio.configure(text="100%")
        self.say("已撤销密度改动。")

    # ---------- 绘制 ----------
    def redraw(self, preview_drag: bool = False):
        vis = self.gray_rgb.astype(np.float64).copy()

        # 点阵：黑点画成暗红，白点保留灰度
        vis[self.dots] = vis[self.dots] * 0.25 + np.array([190, 40, 40]) * 0.75

        # 最终选区：红边框（用掩膜的边界）
        if self.last is not None:
            m = self.last["mask"]
            edge = m & ~_erode(m)
            vis[edge] = np.array([255, 60, 60])

        img = Image.fromarray(vis.astype(np.uint8))
        img = img.resize((int(self.w * self.scale), int(self.h * self.scale)),
                         Image.NEAREST)
        d = ImageDraw.Draw(img)

        # 黄 = 你圈的；绿 = 吸完的
        if preview_drag and self.drag_from and self.drag_to:
            pts = ellipse_points((min(self.drag_from[0], self.drag_to[0]),
                                  min(self.drag_from[1], self.drag_to[1]),
                                  max(self.drag_from[0], self.drag_to[0]),
                                  max(self.drag_from[1], self.drag_to[1])))
            seq = [self.to_canvas(p[0], p[1]) for p in pts]
            d.line(seq + seq[:1], fill=(255, 210, 0), width=2)
        elif self.last is not None:
            rough = [self.to_canvas(p[0], p[1]) for p in self.last["pts"]]
            d.line(rough + rough[:1], fill=(255, 210, 0), width=2)
            sn = [self.to_canvas(p[0], p[1]) for p in self.last["snapped"]]
            d.line(sn + sn[:1], fill=(60, 230, 120), width=2)

        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)

    # ---------- 状态文字 ----------
    def say(self, text: str):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", text)
        self.txt.configure(state="disabled")


# ============================================================
# 三、入口
# ============================================================

def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_REAL
    if not path.exists():
        print(f"找不到图：{path}")
        print(f"用法：python {Path(__file__).name} [图片路径]")
        return 2

    print(f"图 = {path}  ({Image.open(path).size[0]}×{Image.open(path).size[1]}px)")
    print("正在算基线点阵（Floyd–Steinberg，纯 Python 实现，可能几秒）…")
    root = tk.Tk()
    TestBed(root, path)
    print("窗口已开。左键拖一个圈 → 松手。")
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
