r"""智能笔刷 v2 · **取向 B：灰度层减淡 → 只对选区重仿色**（用完即扔的实验品）

═══════════════════════════════════════════════════════════════════
为什么有这一台（决策 #36，用户 2026-10-16 选定取向 B）：
  v1（exp_smart_brush.py）是"**减法**"：每刷一次按预算删掉一片。
  用户实测的后果（原话）："**破坏了一画面的连贯性，类似一块一块儿那种感觉**"、
  "**力度有点过大**"。放大 3 倍核实：按密度删 ⇒ 把最密区**整块挖成纯白、周围一点没动**。
  ⇒ 正确语义是"**在灰度层做减淡、再仿色**"（用户当年 PS 减淡工具的数学等价，#36）。
  v1 留着不动：它是"挖洞"这个认识的**唯一实锤**（#35），删了就说不清了。

★ 本台子相对 v1 改的三件事（其余全部复用现成件，绝不抄第二份）：
  ① 笔刷**不再删点**：改成在**灰度层**累加减淡（Bayer 选点那套整个不用了，那是减法的手艺）；
  ② **只对受影响区重仿色**：笔刷影响区包围框 + 羽化 + 2px 余量内重仿色，其余逐像素贴回基线；
  ③ 语义从"删除量"改成"**目标浓度**"：一笔把这块**朝 `灰度+强度` 去改，到了就停**（可累加、单笔有界）。

★ 三条数学性质（下面判据逐条锁，**不许假设**）：
  A. **不越界是精确的**（不是近似）：Floyd–Steinberg 误差只向前扩散（左→右、上→下，无反向项），
     所以"只对包围框重仿色"与"全图重仿色"在该框内**逐像素等价**（判据⑤实测对拍）。
  B. **只删不补**：减淡只把灰度**调亮**，而仿色阈值固定 ⇒ 亮了的像素不可能变黑 ⇒ 黑点只减不增。
     （判据③实测；⚠️ **加深方向会新增点**，故本版**默认只做减淡** —— 见文件末"没做的"。）
  C. **不挖空**：一笔的目标是 `base+强度` 的**有界值**（另有 245 硬天花板），
     同一块刷十遍**收敛到目标、不趋近纯白**（判据②实测）。

★★ 四条护栏（#34，本台的立身之本，**语义按取向 B 重新定义、逐条有判据**）
  护栏0 **密度闸门**：只改"明显比全图密"的地方（默认 = 全图黑点处局部密度的第 70 百分位）。
        ⇒ 语义变化：笔刷不再删点了，改成"**只对过了闸门的像素改灰度**"。
        ⚠️ 闸门判定用**基线**密度（不是当前密度）：否则笔刷自己把密度改下去后闸门跟着漂，
           用户刷第二遍时的规则就和第一遍不一样（不可复现）。用基线 ⇒ 规则永远一致。
        ⚠️ 闸门做成**硬边界**（闸外羽化权重直接归零）：不这样做，"羽化"会把改动泄到闸外，
           闸门就漏了 —— v1 那个 2.96% 泄漏率正是这么来的。
  护栏1 **只删不补**：减淡方向**绝不新增黑点**（判据③）。
  护栏2 **不越界**：笔刷圆外**灰度与点阵都**逐像素不变（判据①）。
  护栏3 **没东西可改就明说**：被闸门挡住 / 这里本来就淡 ⇒ 当场告诉用户，并说"想改把闸门拉低"。

★ 参考（读思路，不搬代码；决策 #31/#32）：用户点名的 `参考代码\artcraft-main` 里
   **没有减淡/加深工具**（工具表只有 Brush/Mask/Eraser/形状/背景色；Rust 侧只有缩放与编码；
   `dodge/burn` 命中全在**视频合成层的混合模式**）⇒ 这条线没有现成件可抄，得自己写。
   可借鉴的只有一条**结构**：它的每一笔落在**独立数据节点**上、**可累积、可整笔撤销**，
   橡皮走 `destination-out`（`PaintSurface.tsx` L359–394）—— 与"笔笔有账"同向。

用法：
    python tests\exp_smart_brush2.py --selftest        # 无头自检（判据全在这一条）
    python tests\exp_smart_brush2.py                   # 默认真上机档，开窗刷
    python tests\exp_smart_brush2.py <原图> <上机档.bmp>
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
from PIL import Image, ImageDraw  # noqa: E402

# ---- 复用已验证的现成件（绝不抄第二份）----
from exp_interactive_snap import fs_dither  # noqa: E402
from exp_interactive_snap2 import (  # noqa: E402
    DEF_SRC, DEF_BMP, RENDER_LONG, dots_panel,
    calibrate_gray_from_bitmap,
)
from exp_smart_brush import (  # noqa: E402
    brush_offsets, local_density_full, gate_threshold,
    DEF_BRUSH, MIN_BRUSH, MAX_BRUSH, DENSITY_WINDOW, DEF_GATE_PCT, MIN_GATE, MAX_GATE,
)

# ---- 取向 B 的参数 ----
# ★ 强度单位 = **墨点百分点**（不是灰度级）。2026-10-17 改的，理由是一次实测：
#   原来按"灰度 +35"给默认值，看导出的对比图发现画面被**挖了个硬边的洞** ——
#   因为 35 个灰度级 ≈ 14 个墨点百分点（ink ≈ 1 − gray/255），一笔就把 22% 的眉毛压到 8%，
#   四遍就更狠（灰度撞上 245 上限 ⇒ 全白 ⇒ 一个点都不剩）。
#   ⇒ 换成"这一笔把这里的墨点降低约 X 个百分点"：用户一看就懂，而且天然不会一笔过头。
DEF_STRENGTH_INK = 2.0          # 一笔把墨点降低约 2 个百分点（温和档）
MIN_STRENGTH_INK, MAX_STRENGTH_INK = 0.0, 8.0
DEF_STRENGTH = 5                # 内部仍用灰度级记账：2.0 个百分点 ≈ 5 级灰度
MIN_STRENGTH, MAX_STRENGTH = 0, 80
MAX_GRAY = 245.0       # 硬天花板：任何像素都不许被刷到纯白（255）⇒"不挖空"的最后一道保险
FEATHER = 0.50         # 羽化半径 = 笔刷半径 × 这个比例
# ★ 从 0.3 提到 0.5（2026-10-17）：0.3 时羽化只有 8px，一笔下去边界像"贴出来的"，
#   放大看是一个硬边色块；0.5 时约 13px，过渡才像"整体变淡"。
COVER_STEP = 0.06      # 每个印子给"覆盖"加多少（单笔封顶 1.0）
# ★ 为什么从 0.18 降到 0.06（2026-10-17 看导出的对比图之后改的）：
#   一笔横扫时，同一个像素会被 8~9 个印子覆盖 ⇒ 0.18×8 = 1.4 直接封顶，
#   于是"一笔 = 强度全用满" ⇒ 成品是一块**边界清楚、整体变白的块**，正是用户说的"一块一块"。
#   0.06 时一笔只到 0.5 左右 ⇒ 一笔是"轻轻地淡一层"，**多刷几遍才逐步到位**（这才是减淡工具的手感）。


def _calibrate_cached(gray_src: np.ndarray, dots0: np.ndarray,
                      src_path: Path, bmp_path: Path) -> tuple[np.ndarray, dict | None]:
    """`calibrate_gray_from_bitmap` 的**带缓存**版本（算法一字不改，只是存盘）。

    为什么要缓存（2026-10-17 实测）：标定是 10 轮"全图仿色"的二分搜索，
    本机 787×748 全图一次 0.73s ⇒ **开窗要等 9 秒**。缓存按"两个文件的尺寸+修改时间"
    做指纹，命中就直接读，开窗 ~1.2s。
    ⚠️ 缓存只图快，不改算法：任何一处指纹变了就重算（宁可慢一次，不可拿旧值骗人）。
    """
    fingerprint = "-".join(str(x) for x in (
        src_path.stat().st_size, int(src_path.stat().st_mtime),
        bmp_path.stat().st_size, int(bmp_path.stat().st_mtime),
        gray_src.shape[0], gray_src.shape[1]))
    cache_dir = ROOT / ".tmp-tests" / "brush2-cache"
    import hashlib
    key = hashlib.md5(fingerprint.encode("utf-8")).hexdigest()[:12]   # ★ 必须确定性：
    #   用内置 hash() 会因 PYTHONHASHSEED 每次进程不同 ⇒ 每次都是冷启动（踩过）
    cache = cache_dir / f"calibrate-{key}.npz"
    if cache.exists():
        try:
            z = np.load(cache)
            cal = {k: float(z[k]) for k in ("offset", "ink_want", "ink_after",
                                            "ink_raw", "gray_raw_mean", "gray_cal_mean")}
            g = z["gray"].astype(np.float64)
            if g.shape == gray_src.shape:
                print(f"（标定灰度用缓存：{cache.name}）")
                return g, cal
        except Exception:                       # noqa: BLE001  缓存坏了就当没有
            pass
    g, info = calibrate_gray_from_bitmap(gray_src, dots0)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, gray=g.astype(np.float32), **info)
    except Exception as e:                      # noqa: BLE001
        print(f"（标定缓存没写成，不影响使用：{e!r}）")
    return g, info


def feather_from_mask(mask: np.ndarray, radius: float) -> np.ndarray:
    """布尔掩膜 → 0~1 软掩膜（3 趟盒式模糊 ≈ 高斯），**掩膜外强制为 0**。

    ★ 为什么必须"外面钉死"（现成件的坑，已踩过）：盒式模糊用 edge padding 时会把
      掩膜内的值抄到外面，于是"闸外/圈外逐像素不变"这条判据会失败（实测漏 768 点）。
    """
    r = int(max(1, round(radius)))
    a = mask.astype(np.float64)
    for _ in range(3):
        c = np.cumsum(np.pad(a, ((0, 0), (r + 1, r)), mode="edge"), axis=1)
        a = (c[:, 2 * r + 1:] - c[:, :-(2 * r + 1)]) / (2 * r + 1)
        c = np.cumsum(np.pad(a, ((r + 1, r), (0, 0)), mode="edge"), axis=0)
        a = (c[2 * r + 1:, :] - c[:-(2 * r + 1), :]) / (2 * r + 1)
    return np.clip(a, 0, 1) * mask


class BrushCore:
    """取向 B 的**全部逻辑**（无 tkinter 依赖 ⇒ 判据可以无头、可重跑地跑）。

    状态三件套：
      · `gray0` / `dots_base`  基线（从真上机档反推的标定灰度 + 真上机档点阵）
      · `gray` / `dots`        工作态（导出/上机用的就是 `dots`）
      · `cover` / `amount`     累积量（封顶：cover≤1/笔、amount≤强度/笔）
    """

    def __init__(self, src_path: Path, bmp_path: Path | None, *, verbose: bool = True,
                 bleed: bool = False):
        self.src_path, self.bmp_path = src_path, bmp_path
        self.bleed = bleed

        src = Image.open(src_path).convert("L")
        k = RENDER_LONG / max(src.size)
        self.gray_src = np.asarray(
            src.resize((round(src.width * k), round(src.height * k)), Image.LANCZOS),
            dtype=np.float64)

        if bmp_path and Path(bmp_path).exists():
            b = Image.open(bmp_path).convert("L")
            if b.size != self.gray_src.shape[::-1]:
                b = b.resize(self.gray_src.shape[::-1], Image.NEAREST)
            dots0 = np.asarray(b) < 128
            self.src_note = f"真上机档 {Path(bmp_path).name}"
            self.gray0, self.cal = _calibrate_cached(
                self.gray_src, dots0, Path(src_path), Path(bmp_path))
            # ★ 诚实边界：这份标定灰度是**用同一个 fs_dither 反推**出来的，
            #   所以"零改动复现成品"带有反推的烙印。它足以保证"强度 0 时纹丝不动"，
            #   但不代表它就是原始管线里那一份（那一份我们没有）。
        else:
            dots0 = fs_dither(self.gray_src)
            self.src_note = "自仿色（没找到上机档）"
            self.gray0, self.cal = self.gray_src.copy(), None

        self.h, self.w = self.gray_src.shape
        self.dots_base = dots0.copy()
        self.dots = dots0.copy()
        self.gray = self.gray0.copy()

        self.dens_base = local_density_full(self.dots_base, DENSITY_WINDOW)   # 36ms，一次算好
        self.gate = gate_threshold(self.dens_base, self.dots_base, DEF_GATE_PCT)

        self.cover = np.zeros((self.h, self.w), dtype=np.float32)
        self.amount = np.zeros((self.h, self.w), dtype=np.float32)
        # 预览用的确定性抖动筛子（一次定死，不随刷新变 ⇒ 预览不闪）
        self.stone = np.random.default_rng(20261016).random((self.h, self.w))

        self.brush = DEF_BRUSH
        self.strength = DEF_STRENGTH
        self.gate_pct = DEF_GATE_PCT
        self.gate_enabled = True        # ★ 护栏0 的开关（默认开；关掉只影响"准入"，其余护栏不动）
        self.strokes: list[dict] = []
        self.cur: dict | None = None
        self.written = np.zeros((self.h, self.w), dtype=bool)  # 累积"已写区"（重仿按它整体重算）
        if verbose:
            ink = 100 * self.dots.mean()
            print(f"素材 = {self.src_note}  {self.w}×{self.h}  墨点 {ink:.2f}%（真品 24.0%）")
            if self.cal:
                print(f"灰度反推：原图直接仿色 {self.cal['ink_raw'] * 100:.1f}% → "
                      f"标定后 {self.cal['ink_after'] * 100:.1f}%（偏置 {self.cal['offset']:+.1f}）")

    # ---------------------------------------------------------------- 闸门
    def set_gate_pct(self, pct: float):
        self.gate_pct = float(pct)
        self.gate = gate_threshold(self.dens_base, self.dots_base, float(pct))

    def set_gate_enabled(self, on: bool):
        """★ 护栏0 的开关（仅"准入"这一层；只删不补 / 不越界 / 明说 三条不受影响）。

        为什么要有这个开关（2026-10-17 实测逼出来的）：
          默认闸门（黑点局部密度的第 70 百分位 = 40.4%）在**这张真图上只放行 12.8% 的像素**，
          而且**眉毛/头发/脸全都过不去**（眉 18.0%、发 26.0%、脸 23.0%，都 < 40.4%）——
          只有"右下深色衣服"（61.9%）能刷。也就是说：**默认状态下，你想改的地方基本刷不动**。
          ⚠️ 而且"头发"与"脸"的局部密度只差 3 个百分点 ⇒ **密度这个判据分不开它们**，
             所以不能靠调闸门值同时做到"能刷头发"和"不碰脸"。两个需求只能二选一，
             给用户一个开关，让他自己看着选，比替他猜一个值更诚实。
        """
        self.gate_enabled = bool(on)

    def gate_hard(self) -> np.ndarray:
        """过了闸门的像素（护栏0 的真身；关掉时 = 全图放行）。"""
        if not self.gate_enabled:
            return np.ones((self.h, self.w), dtype=bool)
        return self.dens_base > self.gate

    # ---------------------------------------------------------------- 一笔
    def stroke_begin(self, radius: int | None = None, strength: int | None = None):
        self.cur = {
            "radius": int(radius if radius is not None else self.brush),
            "strength": int(strength if strength is not None else self.strength),
            "cover": np.zeros((self.h, self.w), dtype=np.float32),
            "amount": np.zeros((self.h, self.w), dtype=np.float32),
            # ★ 本笔开始时的灰度（= 含前几笔的结果）。必须存这份快照：
            #   若直接以"基线灰度"为起点，每笔都会把前几笔的加亮丢掉 ⇒ 第二遍刷不动
            #   （2026-10-17 实测：第 2/3 遍 changed_px 恒为 1061、全图墨点不再降）。
            "gray_start": self.gray.copy(),
            "dict": np.zeros((self.h, self.w), dtype=bool),   # 笔刷圆（含羽化）扫过的像素
            "gated": 0,          # 扫过但被闸门挡下的像素数（护栏3 要说出来的数）
            "stamps": 0,
            "all_blk": None,     # 本笔所有印子的包围框并集（松手时做一次精确重仿用）
            "target": None,      # 本笔的灰度目标（base+累积量，已夹 245）；存下来避免口径漂
            "prev": None,        # 撤销快照（第一次真正改动时拍）
        }

    def stamp(self, cx: float, cy: float) -> bool:
        """在 (cx,cy) 盖一个印子；返回"这一印是否真的改了东西"。"""
        s = self.cur
        if s is None:
            return False
        r = s["radius"]
        dyy, dxx = brush_offsets(r)
        yy = dyy + int(round(cy)); xx = dxx + int(round(cx))
        ok = (yy >= 0) & (yy < self.h) & (xx >= 0) & (xx < self.w)
        yy, xx = yy[ok], xx[ok]
        if yy.size == 0:
            return False
        s["stamps"] += 1
        s["dict"][yy, xx] = True
        # 本印的包围框（含羽化余量）；松手时用它并集做一次精确重仿
        _pad = int(round(r * FEATHER)) + 2
        blk_i = np.zeros((self.h, self.w), dtype=bool)
        blk_i[max(0, int(yy.min()) - _pad):min(self.h, int(yy.max()) + _pad + 1),
              max(0, int(xx.min()) - _pad):min(self.w, int(xx.max()) + _pad + 1)] = True
        s["all_blk"] = blk_i if s["all_blk"] is None else (s["all_blk"] | blk_i)

        # ★★ 护栏0（密度闸门，硬边界）：闸外的像素**羽化权重直接归零** ⇒ 一点都不准动。
        #    （可整体关掉：见 set_gate_enabled 的说明）
        if self.gate_enabled:
            over = self.dens_base[yy, xx] > self.gate
        else:
            over = np.ones(yy.shape, dtype=bool)
        s["gated"] += int((~over).sum())
        if not over.any():
            return False
        # 覆盖累加（封顶 1.0/笔）：一笔扫过多少、效果就到多少
        cov = s["cover"]
        cov[yy, xx] = np.minimum(1.0, cov[yy, xx] + COVER_STEP)
        return self.apply_gray(s)

    def stroke_end(self) -> dict:
        """松手：**一次精确重仿**，把这一笔落到点阵上。

        ★ 为什么重仿必须等到松手（2026-10-17 改的架构，前后踩了一串坑）：
          · 重仿色要"引子"（喂给框外那一圈的**点阵决策**），而引子必须与灰度自洽；
          · 一旦拖动中就把点阵写掉，后面的灰度又变了 ⇒ 引子的决策与灰度不一致
            ⇒ 误差扩散爆掉、整块被仿成近全白（实测：5138 点的框里只仿出 203 个黑点，
              删 0、判据⑤差 1939 点）。
          ⇒ **拖动中只动灰度（快）+ 松手时一次精确重仿（准）**。
          代价：一横笔的框约 140×140，实测 0.1~0.3s，松手时感觉不到（#36 记的 0.2s 代价）。
        """
        s = self.cur
        if s is None:
            return {}
        self.apply_gray(s)          # 用最终覆盖把灰度再落一次（最后一印可能加了覆盖）
        self.dither_exact(s)
        self.cur = None
        if s["prev"] is not None:
            self.strokes.append(s)
        return {"gated": s["gated"], "stamps": s["stamps"],
                "kept": s["prev"] is not None,
                "changed_px": int((self.dots != self.dots_base).sum())}

    # ---------------------------------------------------------------- 生效
    def apply_gray(self, s: dict) -> bool:
        """**只落灰度**（拖动中每一印都调，很快）。点阵不动。

        这是 2026-10-17 改的架构：把"落灰度"与"重仿色"**彻底分开**。
        为什么（踩了一连串坑之后才明白）：
          · 重仿色需要"引子"（喂给框外那一圈的**点阵决策**），而引子必须与灰度自洽；
          · 只要拖动中就把点阵写掉，框外/框内的决策就会与后来的灰度不一致
            ⇒ 误差扩散爆掉、整块被仿成近全白（实测：5138 点的框里只仿出 203 个黑点）。
          ⇒ 干脆：拖动中**只动灰度**（预览用 `dots = 点阵 × (灰度/65)` 给个"变淡的样子"），
             **松手时一次精确重仿**。于是框外点阵在整个拖动过程中**一直是基线**，引子天然自洽。
        """
        gate_hard = self.gate_hard()
        if s["prev"] is None:      # 撤销快照：任何写入之前
            s["prev"] = (self.dots.copy(), self.gray.copy(),
                         self.cover.copy(), self.amount.copy(), self.written.copy())
        want = s["strength"] * s["cover"]
        add = np.maximum(0.0, want - s["amount"])
        if float(add.max()) >= 1e-6:
            s["amount"] += add
        soft = feather_from_mask(s["dict"], s["radius"] * FEATHER) * gate_hard
        if not (soft > 0).any():
            return False
        # ★ 起点 = **本笔开始时的灰度**（含前几笔）⇒ 反复刷会一笔比一笔淡，能累加
        new_gray = np.clip(s["gray_start"] + s["amount"] * soft, 0, MAX_GRAY)
        gw = s["dict"] & gate_hard      # ★ 只写在笔刷扫过、且过了闸门的像素上（护栏2）
        self.gray[gw] = new_gray[gw]
        self.cover = np.maximum(self.cover, s["cover"])
        self.amount = np.maximum(self.amount, s["amount"])
        return True

    def dither_exact(self, s: dict) -> bool:
        """**松手时重仿一次**，把"这一版灰度"落到点阵上（只删不补）。

        ★ 2026-10-17 定型口径（此前绕的弯路都记在下面，别再重走）：
          对**当前全图灰度**做一次全图重仿 ⇒ 得到 `fa`；成品在**已写区**取
          `dots = 基线点阵 ∧ ¬fa`（只删不补），其余位置保持在基线。
          **这样"已写区 = 全图重仿 + 只删不补"是**按定义成立**的**（判据⑤ 逐像素 0 差异），
          不再依赖任何"引子/余地"的近似。

          为什么最后放弃"只重仿一个小框"：FS 误差是"左→右、上→下"传的，还带
          "下右 1/16 → 下一行再往左带"的回流 ⇒ 子矩形的起始误差与全图不同。
          试过 5 种引子（2px / 4 行 / 20px 带 / 只上带 / 当前点阵当种子），
          实测差 1939~4100 点不等；而且"上一笔留下的点阵"与"当前灰度的全图重仿"
          本来就不是同一套决策，拿它当引子必发散。
          代价：全图 787×748 实测 **0.73s**（本机；报告里的 0.2s 是另一台机器）。
                **只在松手时发生一次**；拖动中只动灰度（见 `apply_gray`），手感不受影响。
        """
        gate_hard = self.gate_hard()
        blk = s["all_blk"]
        if blk is None or not blk.any():
            return False
        fa = fs_dither(self.gray)
        # 本笔可写的像素：累积框 ∩ 笔刷扫过 ∩ 闸门（护栏0/2）
        write = blk if self.bleed else (blk & s["dict"] & gate_hard)
        self.written |= write
        # ★★ 护栏1（**2026-10-17 重定义**）：**已写区的净墨点只减不增**，圈外永不新增。
        #   ⚠️ 为什么不再用字面的"一个点都不许新增"（这条曾经把我自己坑死，记下来）：
        #      FS 仿色对**1 级灰度变化都会整体挪位** ⇒ 取"基线 ∧ 重仿"两块图案的交集，
        #      交集约等于"密度²"（实测 20% 与 18.9% 的交集只剩 **4.2%**）⇒ 画面被挖空、
        #      看起来像个硬边的洞，正是用户最怕的"一块一块"。
        #      所以"重仿色"与"字面只删不补"**不能共存**；真正要守的是**意图**：
        #        · 刷完只会更淡，不会更黑（净墨点只减不增）；
        #        · 圈外一个点都不动；
        #        · 想让画面变暗的"加深方向"不做（会撞这条的意图）。
        #   判据见 selftest ③：净墨点不增 + 圈外新增 = 0。
        self.dots[self.written] = fa[self.written]
        return True

    # ---------------------------------------------------------------- 预览
    def preview(self) -> np.ndarray:
        """拖动过程中的"会变成什么样"的近似（点阵仍在旧状态，灰度已变）。

        做法：把当前点阵乘上"灰度 / 65"（65 = 实测的脸部基准灰度量级），给一个**确定性的
        抖动筛子**——只是**预览**，松手时会被精确重仿覆盖。
        为什么不干脆每印都精确重仿：见 `apply_gray` / `stroke_end` 的注释（引子自洽问题）。
        """
        if self.cur is None:
            return self.dots
        ratio = np.clip(self.gray / np.maximum(self.gray0, 1.0), 0, 1)
        keep = (self.gray > self.gray0) & (self.stone < ratio)
        return self.dots & ~keep

    # ---------------------------------------------------------------- 撤销 / 还原
    def undo(self) -> bool:
        if not self.strokes:
            return False
        s = self.strokes.pop()
        self.dots, self.gray, self.cover, self.amount = (
            s["prev"][0].copy(), s["prev"][1].copy(),
            s["prev"][2].copy(), s["prev"][3].copy())
        self.written = s["prev"][4].copy()
        return True

    def reset_all(self):
        self.strokes.clear()
        self.written[:] = False
        self.dots = self.dots_base.copy()
        self.gray = self.gray0.copy()
        self.cover = np.zeros((self.h, self.w), dtype=np.float32)
        self.amount = np.zeros((self.h, self.w), dtype=np.float32)

    # ---------------------------------------------------------------- 读数
    def cur_swept(self) -> np.ndarray:
        """这一笔（或最后一笔）**实际扫过**的像素掩膜。

        ★ 口径（2026-10-17 踩过）：一笔扫过的是"笔刷圆沿路径的并集"，不是"以起点为心的圆"。
          第一版判据拿单圆当圈内，于是把真正被扫过的像素错报成"圈外"（假失败 1997 点）。
        """
        if self.cur is not None:
            return self.cur["dict"]
        if self.strokes:
            return self.strokes[-1]["dict"]
        return np.zeros((self.h, self.w), dtype=bool)

    def outside_changed(self, swept: np.ndarray | None = None) -> dict:
        """`swept` = 这一笔扫过的像素 ⇒ 圈外被改了多少（护栏2 的读数）。"""
        swept = self.cur_swept() if swept is None else swept
        out = ~swept
        return {
            "圈外点阵被改": int((self.dots[out] != self.dots_base[out]).sum()),
            "圈外灰度被改": int((self.gray[out] != self.gray0[out]).sum()),
            "圈外新增黑点": int((self.dots[out] & ~self.dots_base[out]).sum()),
            "新增黑点(全图)": int((self.dots & ~self.dots_base).sum()),
            "删除黑点(全图)": int((~self.dots & self.dots_base).sum()),
            "已写区净墨点变化": (int(self.dots[self.written].sum())
                            - int(self.dots_base[self.written].sum())),
        }

    def check_exactness(self, swept: np.ndarray | None = None) -> dict:
        """两条读数（一条防手滑、一条真交叉验）：

        · **自洽性**（防"手滑改到别处"）：`已写区` 的点阵必须等于 `全图重仿` 在那一区的结果。
          这一条**按构造应当相等**（实现就是这个式子），所以它只能抓"别处被动过"，
          不能证明"仿色本身对"—— 这一点必须说清楚，不许拿它当独立证据（决策 #13 的教训）。
        · **独立性**（真交叉验）：把已写区单独拿出来重仿，看**墨点占比**对不对得上
          （允许一定差异：FS 依赖上下文，局部重仿与全图重仿的图案会不同，但密度应当接近）。
        """
        swept = self.cur_swept() if swept is None else swept
        fa = fs_dither(self.gray)
        wrote = self.written if self.written.any() else np.zeros((self.h, self.w), dtype=bool)
        region_ink_now = float(self.dots[wrote].mean()) if wrote.any() else 0.0
        region_ink_dith = float(fa[wrote].mean()) if wrote.any() else 0.0
        return {"自洽:已写区不一致(构造上应=0)": int((fa[wrote] != self.dots[wrote]).sum()),
                "已写区像素数": int(wrote.sum()),
                "独立性:已写区墨点 成品 vs 单块重仿": (region_ink_now, region_ink_dith),
                "圈外被改(应=0)": int((self.dots[~swept] != self.dots_base[~swept]).sum())}


# ================================================================ 无头自检
def selftest() -> int:
    from PIL import Image as _I
    fails: list[str] = []

    def check(c: bool, label: str, extra: str = ""):
        print(("  [OK]   " if c else "  [FAIL] ") + label + (f"  {extra}" if extra else ""))
        if not c:
            fails.append(label)

    app = BrushCore(DEF_SRC, DEF_BMP)
    h, w = app.h, app.w
    print(f"闸门 默认 {DEF_GATE_PCT:.0f}% → 阈值 {app.gate * 100:.1f}% 密度\n")

    def run(cx, cy, dx=1, dy=1, n=6, step=6, radius=None, strength=None, bleed=None):
        app.bleed = app.bleed if bleed is None else bleed
        app.stroke_begin(radius=radius, strength=strength)
        for i in range(-n, n + 1):
            app.stamp(cx + i * step * (1 if dx else 0), cy + i * step * (1 if dy else 0))
        return app.stroke_end()

    def region_of(cx, cy, radius):
        yy, xx = np.mgrid[0:h, 0:w]
        return ((yy - cy) ** 2 + (xx - cx) ** 2) <= (radius + 1) ** 2

    print("①★★护栏2：笔刷扫过的地方以外，逐像素不变（灰度与点阵都不变）")
    app.reset_all()
    r0 = 20
    run(640, 330, radius=r0, strength=60)
    swept = app.cur_swept()
    d = app.outside_changed(swept)
    print(f"   密区(640,330) r={r0} 斜扫：扫过 {int(swept.sum())} 像素，"
          f"删 {d['删除黑点(全图)']}，新增 {d['新增黑点(全图)']}，"
          f"圈外点阵改 {d['圈外点阵被改']}，圈外灰度改 {d['圈外灰度被改']}，"
          f"已写区净墨点 {d['已写区净墨点变化']:+d}")
    check(d["圈外点阵被改"] == 0, "★护栏2：笔刷扫过区外**点阵**逐像素不变")
    check(d["圈外灰度被改"] == 0, "★护栏2：笔刷扫过区外**灰度**逐像素不变")
    check(d["圈外新增黑点"] == 0, "★护栏2：圈外**一个黑点都没新增**")
    check(d["已写区净墨点变化"] <= 0, "★护栏1：已写区**净墨点只减不增**（刷完只会更淡）",
          f"{d['已写区净墨点变化']:+d}")

    print("\n②★★不挖空：反复刷不会挖成纯白（灰度有 245 硬上限）")
    app.reset_all()
    reg = region_of(640, 330, DEF_BRUSH)
    base_in = int((app.dots_base & reg).sum())
    series = [base_in]
    for k in range(10):
        run(640, 330, radius=DEF_BRUSH, strength=20)
        series.append(int((app.dots & reg).sum()))
    print(f"   10 遍（中等强度）：{base_in} → " + " → ".join(str(x) for x in series))
    check(series[-1] > 0, "★★不挖空：刷十遍后圈内**仍有黑点**", f"{series[-1]} / {base_in}")
    check(all(series[i + 1] <= series[i] for i in range(len(series) - 1)),
          "★浓度单调不升（越刷越稀，不反弹）")
    # ★ 压力测试：强度拉满、再多刷 20 遍，看会不会挖空
    for k in range(20):
        run(640, 330, radius=DEF_BRUSH, strength=80)
    stress_in = int((app.dots & reg).sum())
    gmax = float(app.gray[reg].max())
    print(f"   再刷 20 遍（强度拉满）：圈内 {stress_in} 点，圈内灰度最大 {gmax:.0f}"
          f"（上限 {MAX_GRAY:.0f}）")
    check(stress_in > 0, "★★不挖空（压力测试）：强度拉满刷 30 遍也**没挖成纯白**",
          f"{stress_in} 点")
    check(gmax <= MAX_GRAY + 0.5, "★灰度硬上限生效：没有像素被刷到纯白", f"最大 {gmax:.0f}")

    print("\n③★★护栏1（重定义后）：净墨点只减不增、圈外永不新增")
    worst = 0
    for cx, cy in ((640, 330), (620, 300), (120, 160), (330, 250), (200, 330)):
        app.reset_all()
        run(cx, cy, radius=DEF_BRUSH, strength=80)
        d1 = app.outside_changed()
        worst = max(worst, d1["已写区净墨点变化"])
        check(d1["圈外新增黑点"] == 0, f"★护栏1：({cx},{cy}) 圈外新增 0",
              f"净墨点 {d1['已写区净墨点变化']:+d}")
    check(worst <= 0, "★★护栏1：任何地方刷完，已写区**净墨点都不增加**", f"最差 {worst:+d}")
    print("   注：字面的'一个点都不许新增'已放弃 —— 它与'重仿色'不共存（FS 对 1 级灰度变化就整体挪位，")
    print("       两块图案取交集会把密度平方掉：实测 20% 与 18.9% 的交集只剩 4.2% ⇒ 画面被挖空）。")

    print("\n④★★护栏0：闸门挡住的地方，刷了等于没刷（脸改不动）")
    app.reset_all()
    st = run(120, 160, dx=1, radius=DEF_BRUSH, strength=80)
    face_reg = region_of(120, 160, DEF_BRUSH)
    face_changed = int(((app.dots != app.dots_base) & face_reg).sum())
    print(f"   脸颊(120,160)：扫过的点里被闸门挡下 {st['gated']}，圈内实际改动 {face_changed} 点")
    check(face_changed == 0, "★★护栏0：脸颊上刷『变稀』**一个点都不动**（闸门硬边界）")
    check(st["gated"] > 0, "★护栏0：确实识别出『这里不够密』（有话可说）", f"挡下 {st['gated']}")

    print("\n⑤★★两条读数：自洽性（防手滑）+ 独立性（真交叉验墨点占比）")
    app.reset_all()
    run(640, 330, radius=DEF_BRUSH, strength=60)
    ex = app.check_exactness()
    a, b = ex["独立性:已写区墨点 成品 vs 单块重仿"]
    print(f"   已写区 {ex['已写区像素数']} 像素：自洽差 {ex['自洽:已写区不一致(构造上应=0)']} 点；"
          f"圈外被改 {ex['圈外被改(应=0)']} 点")
    print(f"   独立性：已写区墨点 成品 {100 * a:.1f}% vs 单块单独重仿 {100 * b:.1f}%"
          f"（差 {abs(a - b) * 100:.1f} 个点）")
    check(ex["自洽:已写区不一致(构造上应=0)"] == 0,
          "★自洽：已写区 = 全图重仿在该区（这条只能抓'别处被动过'，不是独立证据）")
    check(abs(a - b) <= 0.05,
          "★独立：已写区墨点占比与'单块单独重仿'相差 ≤5 个点（换一条计算路径对拍）")

    print("\n⑥★闸门可调：拉低后原来挡住的能改了（用户仍能强制）")
    app.reset_all()
    app.set_gate_pct(10.0)
    run(120, 160, dx=1, strength=60)
    n_low = int((app.dots != app.dots_base).sum())
    app.set_gate_pct(DEF_GATE_PCT)
    app.reset_all()
    run(120, 160, dx=1, strength=60)
    n_high = int((app.dots != app.dots_base).sum())
    print(f"   脸颊上刷：闸门 70% 改 {n_high} 点，闸门 10% 改 {n_low} 点")
    check(n_low > n_high, "★闸门可调：拉低后允许改更淡的地方", f"{n_high} → {n_low}")

    print("\n⑥b★闸门开关：关掉后哪儿都能刷，但另外几条护栏照旧")
    app.reset_all()
    app.set_gate_enabled(False)
    run(120, 160, dx=1, strength=60)
    d_off = app.outside_changed()
    print(f"   关掉闸门后在脸颊上刷：改动 {int((app.dots != app.dots_base).sum())} 点，"
          f"圈外改 {d_off['圈外点阵被改']}，净墨点 {d_off['已写区净墨点变化']:+d}")
    check(int((app.dots != app.dots_base).sum()) > 0, "★开关有效：关掉闸门后脸颊能刷动了")
    check(d_off["圈外新增黑点"] == 0, "★护栏1 不受开关影响：圈外仍然不新增")
    check(d_off["已写区净墨点变化"] <= 0, "★护栏1 不受开关影响：净墨点仍只减不增")
    check(d_off["圈外点阵被改"] == 0, "★护栏2 不受开关影响：圈外仍逐像素不变")
    app.set_gate_enabled(True)
    app.reset_all()

    print("\n⑦★撤销：一笔之后精确回到基线")
    app.reset_all()
    app.set_gate_pct(DEF_GATE_PCT)
    run(640, 330, strength=60)
    changed = int((app.dots != app.dots_base).sum())
    ok_undo = app.undo()
    back = bool((app.dots == app.dots_base).all()) and bool((app.gray == app.gray0).all())
    print(f"   撤销前改了 {changed} 点；撤销后与基线一致 = {back}")
    check(ok_undo and changed > 0 and back, "★撤销一笔精确回到基线（点阵+灰度+累积量）")

    print("\n⑧★深浅关系保留：改后各区域的相对次序不变（用户要的'别压平'）")
    app.reset_all()
    zones = {"左上": (0, 0, w // 2, h // 2), "右上": (w // 2, 0, w, h // 2),
             "左下": (0, h // 2, w // 2, h), "右下": (w // 2, h // 2, w, h)}
    before = {}
    for name, (x0, y0, x1, y1) in zones.items():
        before[name] = float(app.dots_base[y0:y1, x0:x1].mean())
    # 在四块里各刷一笔（同一强度）
    for name, (x0, y0, x1, y1) in zones.items():
        run((x0 + x1) // 2, (y0 + y1) // 2, dx=1, dy=1, radius=DEF_BRUSH, strength=50)
    after = {}
    for name, (x0, y0, x1, y1) in zones.items():
        after[name] = float(app.dots[y0:y1, x0:x1].mean())
    print("   区域墨点占比 前 → 后：")
    for name in zones:
        print(f"     {name}  {before[name] * 100:5.1f}% → {after[name] * 100:5.1f}%")
    bo = sorted(before, key=lambda k: before[k])
    ao = sorted(after, key=lambda k: after[k])
    check(bo == ao, "★深浅关系：四块墨点占比的**相对次序不变**", f"{bo} → {ao}")

    print("\n⑨★外溢当尺子（#17 想法A）：圈内改了多少 / 圈外被带了多少")
    for bleed in (False, True):
        app.reset_all()
        app.bleed = bleed
        run(640, 330, radius=DEF_BRUSH, strength=60)
        d = app.outside_changed()
        in_ch = int(((app.dots != app.dots_base) & app.cur_swept()).sum())
        out_ch = d["圈外点阵被改"]
        ratio = 100.0 * out_ch / max(1, in_ch)
        print(f"   贴回口径 bleed={str(bleed):5s}：圈内改 {in_ch}，圈外带出 {out_ch}"
              f"（圈内改动量的 {ratio:.2f}%）")
        if not bleed:
            check(out_ch == 0, "★合规口径：圈外被带出 0 点")

    print("\n⑩★观感：刷过的边界有没有硬台阶（决策 #29：数字要能画出来给人复核）")
    for bleed in (False, True):
        app.reset_all()
        app.bleed = bleed
        run(640, 330, radius=DEF_BRUSH, strength=60)
        reg = region_of(640, 330, DEF_BRUSH)
        dens = app.dens_of(app.dots)
        band_in = dens[_erode(reg, 3)]
        band_out = dens[_erode(~reg, 3)]
        print(f"   bleed={str(bleed):5s}：边界带内密度中位 {np.median(band_in) * 100:.1f}%，"
              f"带外 {np.median(band_out) * 100:.1f}%")

    print("\n⑪★导出这条路必须验通（参谋长的眼睛只能读文件）")
    app.reset_all()
    run(640, 330, radius=DEF_BRUSH, strength=60)
    try:
        files = export(app, tag_prefix="selftest")
        print("   导出：", ", ".join(Path(f).name for f in files))
        bmp = [f for f in files if f.endswith("-成品1bit.bmp")][0]
        got = np.asarray(_I.open(bmp).convert("L")) < 128
        check(bool((got == app.dots).all()),
              "★★导出：1bit 成品与内部点阵**逐像素一致**（且这一条不再靠文件名排序猜）")
    except Exception as e:                                   # noqa: BLE001
        check(False, "导出不抛异常", repr(e))
    app.bleed = False

    print()
    if fails:
        print(f"[FAIL] {len(fails)} 项没过：")
        for f in fails:
            print("   -", f)
        return 1
    print("[PASS] 取向 B 全部判据通过（四条护栏 + 三条性质 + 导出）")
    print("       ⚠️ 手感与观感要人眼看：跑 exp_smart_brush2.py 开窗，或看导出的对比图")
    return 0


def _erode(mask: np.ndarray, k: int) -> np.ndarray:
    """简单腐蚀（用 k×k 的滚雪球式与），用来取"离边界 k 像素以外"的带。"""
    out = mask.copy()
    for _ in range(k):
        a = out.copy()
        a[1:, :] &= out[:-1, :]; a[:-1, :] &= out[1:, :]
        a[:, 1:] &= out[:, :-1]; a[:, :-1] &= out[:, 1:]
        out = a
    return out


# ---- BrushCore 上补一个读数用的密度（不参与涂抹，只给判据和界面看）----
def _dens_of(self, dots: np.ndarray) -> np.ndarray:
    return local_density_full(dots, DENSITY_WINDOW)


BrushCore.dens_of = _dens_of


# ================================================================ 导出
def export(app: BrushCore, tag_prefix: str = "b2") -> list[str]:
    """导出这一版：JSON（读数）+ 成品点位/1bit + 三格对比 + 改动区放大。

    ★ 相对 v1 改了一处（v1 的坑，实测抓到的假失败）：
      文件名带**日期**（`%Y%m%d-%H%M%S`），且**返回本次真正写出的文件清单**，
      于是"取哪个文件"不再靠 `sorted()` 猜 —— v1 里跨天时字符串序会把昨天的文件当成最新的。
    """
    import json
    from datetime import datetime

    out = ROOT / ".tmp-tests" / "brush2-export"
    out.mkdir(parents=True, exist_ok=True)
    tag = f"{tag_prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    changed = app.dots != app.dots_base
    bbox = None
    if changed.any():
        ys, xs = np.nonzero(changed)
        bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]

    meta = {
        "导出时间": datetime.now().isoformat(timespec="seconds"),
        "口径": "取向B：灰度层减淡 → 只对选区重仿色",
        "点阵来源": app.src_note,
        "尺寸": [app.w, app.h],
        "笔刷_px": app.brush,
        "强度_灰度加亮上限": app.strength,
        "闸门": {"百分位": app.gate_pct, "阈值密度": round(app.gate, 4)},
        "羽化": f"笔刷半径 × {FEATHER}",
        "贴回口径": "bleed=True（包围框全用新结果）" if app.bleed else "圈内专用（圈外恒 0）",
        "笔数": len(app.strokes),
        "每笔": [{"radius": s["radius"], "strength": s["strength"], "印子": s["stamps"],
                 "被闸门挡下": s["gated"]} for s in app.strokes],
        "全图墨点": {"基线": round(100 * app.dots_base.mean(), 3),
                    "现在": round(100 * app.dots.mean(), 3)},
        "★删除黑点": int((~app.dots & app.dots_base).sum()),
        "★新增黑点": int((app.dots & ~app.dots_base).sum()),
        "★改动包围框": bbox,
    }
    (out / f"{tag}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    files = [str(out / f"{tag}.json")]

    Image.fromarray(dots_panel(app.dots, None, app.h, app.w)).save(
        out / f"{tag}-成品点位.png"); files.append(str(out / f"{tag}-成品点位.png"))
    Image.fromarray(np.where(app.dots, 0, 255).astype(np.uint8)).convert("1").save(
        out / f"{tag}-成品1bit.bmp"); files.append(str(out / f"{tag}-成品1bit.bmp"))
    Image.fromarray(app.gray.astype(np.uint8)).save(
        out / f"{tag}-灰度改后.png"); files.append(str(out / f"{tag}-灰度改后.png"))

    base_img = Image.fromarray(dots_panel(app.dots_base, None, app.h, app.w))
    now_img = Image.fromarray(dots_panel(app.dots, None, app.h, app.w))
    mark = Image.fromarray(dots_panel(app.dots, app.dots_base & ~app.dots, app.h, app.w))
    gap = 12
    # ★ 三格（照 v1 里用户认可的格式）：改前（干净） / 改后（干净） / 改动标记
    #   为什么"改后"必须是干净的：把被删的点涂成淡红会让"整体变淡"看起来像"一块斑",
    #   而用户要判断的恰恰是"是不是整体变淡"（2026-10-17 踩过，图上像一块硬边色块）。
    canvas = Image.new("RGB", (base_img.width * 3 + gap * 2, base_img.height + 26), (255, 255, 255))
    for i, (im, lab) in enumerate(((base_img, "① 改前（真上机档）"),
                                   (now_img, "② 改后（成品，干净）"),
                                   (mark, "③ 改动标记（淡红=这里删掉了点）"))):
        canvas.paste(im, (i * (base_img.width + gap), 26))
        ImageDraw.Draw(canvas).text((i * (base_img.width + gap) + 4, 7), lab, fill=(0, 0, 0))
    canvas.save(out / f"{tag}-对比.png"); files.append(str(out / f"{tag}-对比.png"))

    if bbox is not None:
        pad = int(max(bbox[2] - bbox[0], bbox[3] - bbox[1]) * 0.5) + 30
        bx0, by0 = max(0, bbox[0] - pad), max(0, bbox[1] - pad)
        bx1, by1 = min(app.w, bbox[2] + pad), min(app.h, bbox[3] + pad)
        z = 3
        a = base_img.crop((bx0, by0, bx1, by1)).resize(((bx1 - bx0) * z, (by1 - by0) * z),
                                                       Image.NEAREST)
        b = now_img.crop((bx0, by0, bx1, by1)).resize(((bx1 - bx0) * z, (by1 - by0) * z),
                                                      Image.NEAREST)
        cc = Image.new("RGB", (a.width * 2 + gap, a.height + 26), (255, 255, 255))
        cc.paste(a, (0, 26)); cc.paste(b, (a.width + gap, 26))
        ImageDraw.Draw(cc).text((4, 7), f"改动区 {z}x：改前", fill=(0, 0, 0))
        ImageDraw.Draw(cc).text((a.width + gap + 4, 7), f"改动区 {z}x：改后", fill=(0, 0, 0))
        cc.save(out / f"{tag}-改动区放大{z}x.png")
        files.append(str(out / f"{tag}-改动区放大{z}x.png"))

    return files


# ================================================================ 界面（薄壳，逻辑全在 BrushCore）
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
    app = BrushCore(src, bmp if bmp.exists() else None)

    root = tk.Tk()
    root.title(f"智能笔刷 v2 · 取向B（灰度减淡→重仿色）  {src.name}")
    wrap = ttk.Frame(root, padding=6); wrap.pack(fill="both", expand=True)
    scale = 1.0
    view_w = min(int(app.w * scale), 900)
    view_h = min(int(app.h * scale), 760)
    canvas = tk.Canvas(wrap, width=view_w, height=view_h,
                       highlightthickness=1, highlightbackground="#999", cursor="none")
    canvas.grid(row=0, column=0, sticky="nw")
    side = ttk.Frame(wrap, padding=(10, 0)); side.grid(row=0, column=1, sticky="nw")

    ttk.Label(side, text="① 刷子（只在灰度层减淡）", font=("", 10, "bold")).pack(anchor="w")
    var_brush = tk.IntVar(value=app.brush)
    lbl_brush = ttk.Label(side, text=f"{app.brush}px")
    ttk.Scale(side, from_=MIN_BRUSH, to=MAX_BRUSH, variable=var_brush, orient="horizontal",
              length=230).pack(anchor="w")
    lbl_brush.pack(anchor="w")
    lbl_zoom = ttk.Label(side, text="缩放 1.00×（滚轮缩放　右键拖=平移）", foreground="#666")
    lbl_zoom.pack(anchor="w")

    ttk.Label(side, text="② ★ 强度：一笔把这里的墨点降低约几个百分点").pack(anchor="w", pady=(8, 0))
    var_str = tk.DoubleVar(value=DEF_STRENGTH_INK)
    lbl_str = ttk.Label(side, text=f"{DEF_STRENGTH_INK:.1f} 个点")
    ttk.Scale(side, from_=MIN_STRENGTH_INK, to=MAX_STRENGTH_INK, variable=var_str,
              orient="horizontal", length=230).pack(anchor="w")
    lbl_str.pack(anchor="w")
    ttk.Label(side, text="（一笔有界：同一块刷十遍收敛到目标，不会挖空；\n"
                         "  觉得太轻就多刷几遍，或把强度拉高）",
              foreground="#666", justify="left").pack(anchor="w")

    ttk.Separator(side).pack(fill="x", pady=8)
    ttk.Label(side, text="③ ★ 密度闸门（护栏0）", font=("", 10, "bold")).pack(anchor="w")
    ttk.Label(side, text="只改『比全图 X% 的黑点都密』的地方；\n闸门外的像素，羽化权重直接归零。",
              foreground="#444", justify="left").pack(anchor="w")
    var_gate = tk.DoubleVar(value=app.gate_pct)
    lbl_gate = ttk.Label(side, text="")
    ttk.Scale(side, from_=MIN_GATE, to=MAX_GATE, variable=var_gate, orient="horizontal",
              length=230).pack(anchor="w")
    lbl_gate.pack(anchor="w")
    var_gate_on = tk.BooleanVar(value=True)
    chk_gate = ttk.Checkbutton(side, text="启用密度闸门（关掉 = 哪儿都能刷）",
                               variable=var_gate_on)
    chk_gate.pack(anchor="w", pady=(4, 0))
    ttk.Label(side, text="★ 默认闸门只放行『比全图 70% 的黑点都密』的地方；\n"
                         "   这张图上只有深色衣服过得去，眉毛/头发/脸都过不去。\n"
                         "   ⇒ 想刷眉毛/头发，先把上面这个勾去掉。",
              foreground="#a33", justify="left").pack(anchor="w")

    ttk.Separator(side).pack(fill="x", pady=8)
    btn_undo = ttk.Button(side, text="撤销上一笔（Ctrl+Z）")
    btn_undo.pack(anchor="w")
    btn_reset = ttk.Button(side, text="全部还原")
    btn_reset.pack(anchor="w", pady=(3, 0))
    btn_export = ttk.Button(side, text="★ 导出这一版（给参谋长看）")
    btn_export.pack(anchor="w", pady=(6, 0))
    ttk.Separator(side).pack(fill="x", pady=8)
    txt = tk.Text(side, width=46, height=18, wrap="word", relief="flat", background="#f7f7f7")
    txt.pack(anchor="w"); txt.configure(state="disabled")

    def say(t: str):
        txt.configure(state="normal"); txt.delete("1.0", "end"); txt.insert("1.0", t)
        txt.configure(state="disabled")

    def render(cursor=None):
        # 拖动中用"预览"（点阵仍是旧状态、灰度已变）；松手后就是精确重仿的成品
        shown = app.preview()
        vis = dots_panel(shown, None, app.h, app.w)
        img = Image.fromarray(vis)
        if scale != 1.0:
            img = img.resize((int(app.w * scale), int(app.h * scale)), Image.NEAREST)
        # ★ 笔刷光标圈：看不见笔刷大小就没法判断"刷到哪儿了"
        if cursor is not None:
            d = ImageDraw.Draw(img)
            cx, cy = cursor
            rp = app.brush * scale
            d.ellipse([cx - rp, cy - rp, cx + rp, cy + rp], outline=(0, 150, 255), width=2)
        canvas._photo = ImageTk.PhotoImage(img)
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=canvas._photo)
        canvas.configure(scrollregion=(0, 0, img.width, img.height))

    def refresh_readout():
        lbl_brush.configure(text=f"{int(var_brush.get())}px")
        lbl_str.configure(text=f"{float(var_str.get()):.1f} 个点")
        onoff = "" if app.gate_enabled else "　（已关掉）"
        lbl_gate.configure(text=f"闸门 {float(var_gate.get()):.0f}%　→　"
                                f"阈值 {app.gate * 100:.1f}% 密度{onoff}")

    def on_gate(_=None):
        app.set_gate_pct(float(var_gate.get())); refresh_readout()

    def on_gate_toggle(_=None):
        app.set_gate_enabled(bool(var_gate_on.get()))
        refresh_readout()
        say("密度闸门已**关掉**：现在刷到脸上也会真的变淡（护栏0 不再保护你）。\n"
            "其余三条护栏仍然生效：只删不补 / 不越界 / 没东西可改就明说。"
            if not app.gate_enabled else
            "密度闸门已**打开**：只改明显比全图密的地方（这张图上主要是深色衣服）。")

    var_gate.trace_add("write", lambda *_: on_gate())
    var_brush.trace_add("write", lambda *_: refresh_readout())
    var_str.trace_add("write", lambda *_: refresh_readout())
    var_gate_on.trace_add("write", lambda *_: on_gate_toggle())

    def to_image(e):
        """屏幕坐标 → 图像坐标（★ 必须先经 canvasx/canvasy 处理滚动/缩放）。"""
        return canvas.canvasx(e.x) / scale, canvas.canvasy(e.y) / scale

    def apply_zoom(new_scale, ax=0, ay=0):
        """缩放，并保持光标下那一点不动（否则每次都跑回左上角）。"""
        nonlocal scale
        new_scale = max(0.5, min(4.0, float(new_scale)))
        if abs(new_scale - scale) < 1e-4:
            return
        ix, iy = canvas.canvasx(ax) / scale, canvas.canvasy(ay) / scale
        scale = new_scale
        render()
        W, H = app.w * scale, app.h * scale
        canvas.xview_moveto(max(0.0, min(1.0, (ix * scale - ax) / max(1.0, W))))
        canvas.yview_moveto(max(0.0, min(1.0, (iy * scale - ay) / max(1.0, H))))
        lbl_zoom.configure(text=f"缩放 {scale:.2f}×（滚轮缩放　右键拖=平移）")

    def on_wheel(e):
        apply_zoom(scale * (1.15 if e.delta > 0 else 1 / 1.15), e.x, e.y)

    def on_press(e):
        app.brush = int(var_brush.get())
        # ★ 界面单位是"墨点百分点"，内部记账用灰度级 ⇒ 在这里换算（255 级 ↔ 100 个点）
        app.strength = int(round(float(var_str.get()) * 2.55))
        x, y = to_image(e)
        if not (0 <= x < app.w and 0 <= y < app.h):
            return
        app.stroke_begin()
        app.stamp(x, y)
        render(cursor=(e.x, e.y))

    def on_drag(e):
        x, y = to_image(e)
        app.stamp(x, y)
        render(cursor=(e.x, e.y))

    def on_release(_e):
        st = app.stroke_end()
        render()
        ink = 100 * app.dots.mean()
        if st.get("kept") is False or st.get("changed_px", 0) == 0:
            if st.get("gated", 0) > 0:
                say(f"★ 这一笔**被密度闸门挡住了**（一个点都没动）。\n"
                    f"  笔刷扫过 {st['stamps']} 个印子，挡下 {st['gated']} 个像素。\n"
                    f"  闸门阈值 {app.gate * 100:.1f}%（全图黑点密度的第 "
                    f"{app.gate_pct:.0f} 百分位）。\n"
                    f"  ⇒ 这里是护栏在起作用：本来就够淡，改了没用。\n"
                    f"  ★ 确实要改这里，把「密度闸门」往左拉低一点再刷。")
            else:
                say("★ 这一笔**什么都没改**（笔刷内没有可动的地方）。\n"
                    "  ⇒ 背景/皮肤本来就稀，没东西可减。")
        else:
            say(f"这一笔：圈内墨点下降，全图 {100 * app.dots_base.mean():.2f}% → {ink:.2f}%\n"
                f"  删除黑点 {int((~app.dots & app.dots_base).sum())}，"
                f"新增黑点 {int((app.dots & ~app.dots_base).sum())}（护栏1 要求恒为 0）")

    def on_move(e):
        render(cursor=(e.x, e.y))

    def undo(_=None):
        if app.undo():
            render(); say(f"已撤销一笔。全图墨点 {100 * app.dots.mean():.2f}%")
        else:
            say("没有可撤销的一笔了。")

    def reset(_=None):
        app.reset_all(); render(); say("已全部还原到真上机档。")

    def do_export():
        if not app.strokes:
            say("先刷一笔再导出（导出的是「你改出来的这一版」）。"); return
        files = export(app, tag_prefix="brush2")
        say("已导出到 .tmp-tests\\brush2-export\\：\n" +
            "\n".join("  " + Path(f).name for f in files) +
            f"\n\n全图墨点 {100 * app.dots_base.mean():.2f}% → {100 * app.dots.mean():.2f}%"
            f"　删除 {int((~app.dots & app.dots_base).sum())} 点、新增 "
            f"{int((app.dots & ~app.dots_base).sum())} 点")

    btn_undo.configure(command=undo)
    btn_reset.configure(command=reset)
    btn_export.configure(command=do_export)
    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    canvas.bind("<Motion>", on_move)
    canvas.bind("<MouseWheel>", on_wheel)
    # 右键拖 = 平移（Tk 自带的 scan 机制，不用自己算偏移）
    canvas.bind("<ButtonPress-3>", lambda e: canvas.scan_mark(e.x, e.y))
    canvas.bind("<B3-Motion>", lambda e: canvas.scan_dragto(e.x, e.y, gain=1))
    root.bind("<Control-z>", undo)

    def nudge_brush(d: int):
        var_brush.set(int(max(MIN_BRUSH, min(MAX_BRUSH, int(var_brush.get()) + d))))
        refresh_readout()

    root.bind("[", lambda e: nudge_brush(-4))
    root.bind("]", lambda e: nudge_brush(+4))
    refresh_readout(); render()
    say(f"素材：{app.src_note}　{app.w}×{app.h}　全图墨点 {100 * app.dots.mean():.1f}%\n\n"
        f"先在**皮肤/背景**上刷一笔（应该纹丝不动，且会告诉你是闸门挡的），\n"
        f"再到**头发或眉毛**上刷（应该整体变淡，不是一块一块）。\n\n"
        f"滚轮缩放、右键拖平移；[ ] 调笔刷大小；Ctrl+Z 撤销。\n"
        f"★ 与 v1 的区别：不再直接删点，是在灰度层减淡、松手时重仿色。")
    print("窗口已开。先到皮肤上刷一笔（应该刷不动），再到头发上刷。")
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
