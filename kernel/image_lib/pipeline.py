"""图像函数库：确定性、可复现的图像处理。

铁律：
- 纯函数风格：同样的 (输入图, 旋钮, 物理尺寸, DPI) 永远得到同样的输出。
- 本模块不调用 agent、不读网络、无随机性（回归测试依赖这一点）。
- 每个旋钮背后必须有真实能力；没实现的旋钮要如实报"能力缺口"，
  不许假装处理了。

v2 范围：
- 输出雕刻位图：8-bit 灰度 PNG，嵌入物理尺寸 × DPI
- 已实现旋钮：整体明暗、明暗反差、细节保留度、素描感强度（程序化铅笔素描）
- 未实现（能力缺口，后续再做）：背景纯净度、脸部提亮、疏密细腻度

v3 范围（③ 九宫格局部调整，决策 #17/#18）：
- 报告新增 zones：3×3 分区指标（行优先 0~8），让判断员能"读每格数字"调局部；
- 新增 local_ops：局部调整算子（提亮/压暗/更白/更黑），羽化过渡无接缝，
  作用在"旋钮处理之后、仿色之前"的灰度图上；一次渲染内全量重放 → 可复现。
- 方向定义（拍板 F）：**按视觉直觉，与 BMP 上机极性解耦**——
  brighten/whiten = 该处变亮（灰阶值升高、成品墨点变稀）；
  darken/blacken = 该处变暗（灰阶值降低、成品墨点变密）。
  真机若发现 BMP 极性反了，只改仿色映射（_fs_dither/_save_1bit_bmp），不动本算子语义。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许 "python image_lib/pipeline.py" 直接运行时也能 import 到 bestpic 根下的模块
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageFilter

from knobs import (
    DEFAULT_KNOBS,
    KNOB_MAP,
    ZONE_COUNT,
    ZONE_OPS,
    normalize_local_ops,
    validate_local_ops,
)

# 雕刻输出默认：每英寸点数。LightBurn 按此换算物理尺寸。
DEFAULT_DPI = 200

# 未实现的旋钮（= 能力缺口清单，运行时 agent 见到应报告而不是发明）
CAPABILITY_GAPS: list[str] = [
    name for name, knob in KNOB_MAP.items() if knob.applies_to in ("背景", "脸部")
]
CAPABILITY_GAPS += ["疏密细腻度"]

# 已实现旋钮（改了实现记得同步这里 + 对应 _apply 函数）
IMPLEMENTED_KNOBS: list[str] = ["整体明暗", "明暗反差", "细节保留度", "素描感强度"]


def _clamp(x: float, lo: float = 0.0, hi: float = 255.0) -> float:
    return max(lo, min(hi, x))


def _apply_sketch(img: Image.Image, strength: float) -> Image.Image:
    """程序化铅笔素描：复刻"反色+素描"那类笔触感的雕刻预处理。

    经典三步（全确定性，无随机）：
      1. 灰度图反色；
      2. 反色图高斯模糊（模糊半径随强度增大，笔触更粗犷）；
      3. 颜色减淡 dodge 混合：白底 + 深色"笔触/边缘"结构，模拟铅笔素描。
    strength ∈ [0,1]；0 = 原灰度几乎不变（仍有轻微纸感），1 = 强素描。
    """
    gray = img.convert("L")
    inv = gray.point(lambda p: 255 - p)

    # 模糊半径随强度增大：0.5→约5px，1.0→约15px 的"笔"感
    radius = max(0.5, strength * 15.0)
    blur = inv.filter(ImageFilter.GaussianBlur(radius=radius))

    # dodge: out = gray*255/(255-blur)，除零保护
    g = np.asarray(gray, dtype=np.float32)
    b = np.asarray(blur, dtype=np.float32)
    denom = 255.0 - b
    denom = np.clip(denom, 1.0, 255.0)
    out = np.clip(g * 255.0 / denom, 0.0, 255.0).astype(np.uint8)
    sketched = Image.fromarray(out, mode="L")

    # 按强度与原灰度混合：strength=0 → 原图；=1 → 全素描
    if strength >= 1.0:
        return sketched
    return Image.blend(gray, sketched, strength)


def _zone_bounds(total: int, n: int = 3) -> list[tuple[int, int]]:
    """把 total 行/列切成 n 段：前 n-1 段向下取整，余数留给最后一段。

    例：787 → [(0,262),(262,524),(524,787)]；10 → [(0,3),(3,6),(6,10)]。
    余数集中给最后一格（与集成测试的面积加权口径一致，保证 9 格加权 = 整图）。
    """
    step = int(total // n)
    bounds: list[tuple[int, int]] = []
    start = 0
    for i in range(n):
        end = total if i == n - 1 else start + step
        bounds.append((start, end))
        start = end
    return bounds


# 羽化坡长：占格边长的比例（0.25 → 格内两侧各 25% 做坡，中间 50% 是满权重平台）
FEATHER_RAMP_FRAC = 0.25


def _axis_window(bounds: list[tuple[int, int]]) -> list[np.ndarray]:
    """一条轴上每一格的权重曲线：**平台 + 两侧羽化坡**（任务包 §3.2 的做法）。

    第 i 格（跨 [lo, hi)，长 L，坡长 p = max(1, round(L·FEATHER_RAMP_FRAC)))：
        w = 1.0        在格中间的平台上（[lo+p, hi-p)）
        w = 0 → 0.5 → 1.0   从格边界向格内线性升（跨界处恰为 0.5）
        w = 1.0 → 0.5 → 0   从平台向格边界线性降
    - 格**边界处恰为 0.5**（"中心 1.0、跨界 0.5 → 0 平滑过渡"）；
    - 格**外恒为 0**：所以改动只会渗到相邻格的一小条羽化带（坡长 p 像素），
      非指定格中心区域完全不受影响；多格连选时用 maximum 取并集，不会叠加双倍。
    - 纯 numpy、无随机 → 可复现。
    """
    out: list[np.ndarray] = []
    for lo, hi in bounds:
        length = hi - lo
        ramp = max(1, min(int(round(length * FEATHER_RAMP_FRAC)), max(1, length // 2)))
        # 注意：每段必须独立新建数组——早期版本复用了同一个数组并原地改坡，
        # 结果三段曲线全变成最后一段，遮罩横向铺满整行（真机上表现为"改一格动一整排"）。
        w = np.ones(length, dtype=np.float64)
        idx = np.arange(length, dtype=np.float64)
        # 上升坡：格边界 0.5 → 平台起点 1.0
        w[:ramp] = 0.5 + 0.5 * (idx[:ramp] + 0.5) / float(ramp)
        # 下降坡：平台终点 1.0 → 格边界 0.5
        w[length - ramp:] = 1.0 - 0.5 * (idx[length - ramp:] - (length - ramp) + 0.5) / float(ramp)
        out.append(w)
    return out


def _zone_weight(zone: int, h: int, w: int) -> np.ndarray:
    """第 zone 格（0~8，行优先）的二维羽化权重遮罩，形状 (h, w)，值域 [0,1]。

    行方向的窗只在"本格那几行"非零、其余行权重为 0（列同理），
    故格外像素权重恒为 0 —— 只有本格（含跨界半权重带）被改。
    """
    if not 0 <= int(zone) < ZONE_COUNT:
        raise ValueError(f"zone 越界: {zone!r}（只能是 0~{ZONE_COUNT - 1}）")
    ys = _zone_bounds(h)
    xs = _zone_bounds(w)
    r, c = divmod(int(zone), 3)
    y0, y1 = ys[r]
    x0, x1 = xs[c]
    mask = np.zeros((h, w), dtype=np.float64)
    # 注意：这里必须用"先算乘积再赋值"，不要写 mask[:, x0:x1] *= win[None, :]。
    # 本项目环境的 numpy 2.5.3 对"2D 切片原地 *= (1,n) 广播"存在异常：
    # 实测 (9,9)[:, 3:6] *= [0.75,1,0.75] 会把中间列漏掉（结果 0.5625, 0.75, 0.5625），
    # 导致遮罩横向铺满整行、改一格动一整排。显式广播赋值可绕开。
    wy = _axis_window(ys)[r][:, None]      # (格高, 1)
    wx = _axis_window(xs)[c][None, :]      # (1, 格宽)
    mask[y0:y1, x0:x1] = wy * wx
    return mask


def _zone_mask(zones, shape: tuple[int, int]) -> np.ndarray:
    """多格权重取并集（maximum），避免相邻格叠加出双倍效果。"""
    h, w = shape
    mask = np.zeros((h, w), dtype=np.float64)
    for z in sorted({int(z) for z in zones}):
        np.maximum(mask, _zone_weight(z, h, w), out=mask)
    return mask


def _apply_local_ops(arr: np.ndarray, node_ops: list[dict]) -> np.ndarray:
    """按给定顺序施加局部调整（确定性：纯逐元素算术，浮点运算顺序固定）。

    - brighten / darken：该区线性偏置（±60·amount 灰阶），复用"整体明暗"思路；
    - whiten：向 255 推，且把暗部一并抬起来（模拟"把背景修白"）；
    - blacken：向 0 推，同时压亮部（模拟"让这块更黑"）。
    每步用羽化遮罩与原图做加权混合：格中心权重 1.0、跨界 0.5 → 平滑无接缝。
    """
    if not node_ops:
        return arr
    work = arr.astype(np.float64)
    for item in node_ops:
        op = str(item["op"])
        amount = float(item.get("amount", 0.5))
        mask = _zone_mask(item["zones"], work.shape)
        if op == "brighten":
            target = np.clip(work + 60.0 * amount, 0.0, 255.0)
        elif op == "darken":
            target = np.clip(work - 60.0 * amount, 0.0, 255.0)
        elif op == "whiten":
            target = np.clip(work + 45.0 * amount, 0.0, 255.0)
            target = np.clip(target + (target / 255.0) * 45.0 * amount, 0.0, 255.0)
        elif op == "blacken":
            target = np.clip(work - 45.0 * amount, 0.0, 255.0)
            target = np.clip(target - (1.0 - target / 255.0) * 45.0 * amount, 0.0, 255.0)
        else:  # normalize_local_ops 已白名单过滤，这里只是兜底
            raise ValueError(f"未知局部动作: {op!r}")
        work = work * (1.0 - mask) + target * mask
    return np.round(np.clip(work, 0.0, 255.0)).astype(np.uint8)


def _zone_metrics(gray: np.ndarray, binary: np.ndarray) -> list[dict]:
    """3×3 分区指标（行优先 0~8）：每格的 mean / dark / light / ink。

    gray   = 仿色前的最终灰度图（局部算子已生效）
    binary = FS 仿色后的 1bit 点阵（0=黑点）
    指标口径与整图 metrics 一致，故 9 格按面积加权 ≈ 整图（回归有断言）。
    """
    out: list[dict] = []
    ys = _zone_bounds(gray.shape[0])
    xs = _zone_bounds(gray.shape[1])
    for y0, y1 in ys:
        for x0, x1 in xs:
            g = gray[y0:y1, x0:x1]
            b = binary[y0:y1, x0:x1]
            out.append({
                "mean": round(float(g.mean()), 1),
                "dark_pct": round(float((g < 64).mean() * 100), 1),
                "light_pct": round(float((g > 192).mean() * 100), 1),
                "ink_pct": round(float((b == 0).mean() * 100), 1),
            })
    return out


def _fs_dither(gray: np.ndarray) -> np.ndarray:
    """Floyd–Steinberg 误差扩散仿色（复刻 PS「位图→扩散仿色」的疏密思想）。

    灰度 → 1bit：越暗的地方黑点越密，越亮越稀（这正是"灰度→疏密"的确定性实现）。
    误差按经典 7/16·3/16·5/16·1/16 扩散到右/左下/下/右下；纯确定性、无随机。
    返回与输入同尺寸的 {0,255} uint8（0=黑点=原图暗处）。
    """
    h, w = gray.shape
    rows = gray.astype(np.float64).tolist()  # 用 Python list 提速（v1 秒级可接受）
    out = np.zeros((h, w), dtype=np.uint8)
    c7, c3, c5, c1 = 7 / 16, 3 / 16, 5 / 16, 1 / 16
    for y in range(h):
        row = rows[y]
        nxt = rows[y + 1] if y + 1 < h else None
        outrow = out[y]
        for x in range(w):
            old = row[x]
            new = 255.0 if old >= 127.5 else 0.0
            outrow[x] = 255 if new else 0
            err = old - new
            if x + 1 < w:
                row[x + 1] += err * c7
            if nxt is not None:
                if x > 0:
                    nxt[x - 1] += err * c3
                nxt[x] += err * c5
                if x + 1 < w:
                    nxt[x + 1] += err * c1
    return out


def _save_1bit_bmp(binary: np.ndarray, path: str | Path, dpi: int) -> None:
    """把 {0,255} 二值数组存成 1bit BMP（可进 LightBurn）。

    注：BMP 格式不带 dpi 元数据，LightBurn 导入时选 200dpi 即可；
    像素尺寸已按 physical_mm@dpi 算好，物理大小不会错。
    """
    img1 = Image.fromarray(binary, mode="L").convert("1")
    img1.save(path, format="BMP")


def _prepare_local_ops(local_ops) -> list[dict]:
    """把外部传入的 local_ops 规范成"渲染计划"（有序节点操作列表）。

    接受两种形态：
    - 词汇表形态：{"zone": 4, "op": "brighten", "amount": 0.3} / [ … ]（agent 与界面用）；
    - 已归并形态：{"op": "brighten", "amount": 0.3, "zones": [3, 4, 5]}（累积重放用）。
    都为空 → 返回 []（= 不做局部调整）。
    """
    if not local_ops:
        return []
    items = [local_ops] if isinstance(local_ops, dict) else list(local_ops)
    if items and isinstance(items[0], dict) and "zones" in items[0]:
        plan: list[dict] = []
        for it in items:
            zones = [int(z) for z in it["zones"]]
            bad = [z for z in zones if not 0 <= z < ZONE_COUNT]
            if bad:
                raise ValueError(f"局部调整 zone 越界: {bad}（只能是 0~{ZONE_COUNT - 1}）")
            op = str(it["op"])
            if op not in ZONE_OPS:
                raise ValueError(f"未知局部动作: {op!r}（允许 {list(ZONE_OPS)}）")
            plan.append({"op": op, "amount": float(it.get("amount", 0.5)), "zones": zones})
        return plan
    return normalize_local_ops(items)


def render_grayscale(
    src: str | Path,
    out_dir: str | Path,
    *,
    knobs: dict | None = None,
    physical_mm: float = 100.0,
    dpi: int = DEFAULT_DPI,
    tag: str = "",
    local_ops: list[dict] | None = None,
) -> dict:
    """主入口：把原图变成一张可进 LightBurn 的雕刻位图。

    参数：
      src         原图路径
      out_dir     输出目录（assets/out）
      knobs       旋钮取值 dict（缺省用默认值）
      physical_mm 目标物理尺寸（长边，毫米）
      dpi         输出分辨率（决定像素密度）
      tag         输出文件名后缀（如 v1/v2），同一订单多版留档防覆盖
      local_ops   局部调整（③ 九宫格）：[{"zone": 4, "op": "brighten", "amount": 0.3}, ...]
                  也接受 {"zones": [0,1,2], ...} 这种已归并形态（累积重放内部使用）。
                  作用在"旋钮处理之后、仿色之前"；每次渲染全量重放 → 可复现。
                  非法输入抛 ValueError（不静默吞掉）。

    返回：描述本次产出的 dict（给人/日志看），含 metrics（整图）+ zones（9 格）。
    """
    merged = dict(DEFAULT_KNOBS)
    if knobs:
        merged.update({k: float(v) for k, v in knobs.items()})
    node_ops = _prepare_local_ops(local_ops)

    img = Image.open(src).convert("L")  # 灰度

    # ---- 已实现旋钮的执行 ----
    # 1) 整体明暗：绕中灰点的线性偏置
    bias = merged["整体明暗"]
    if bias:
        img = img.point(lambda p: int(_clamp(p + bias * 60)))

    # 2) 明暗反差：绕 128 缩放
    contrast = merged["明暗反差"]
    if contrast:
        scale = 1.0 + contrast * 1.2  # 0 不动，1 → 2.2x
        img = img.point(lambda p: int(_clamp(128 + (p - 128) * scale)))

    # 3) 细节保留度：USM 锐化（0 不动，越大越强调高频）
    detail = merged["细节保留度"]
    if detail:
        radius = 2.0
        percent = int(detail * 120)
        img = img.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=2))

    # 4) 素描感强度：程序化铅笔素描（v2 实现）
    sketch = merged["素描感强度"]
    if sketch:
        img = _apply_sketch(img, float(sketch))

    # ---- 尺寸与 DPI ----
    # 长边 = physical_mm，短边按比例；像素 = 毫米 / 25.4 * DPI
    w_mm, h_mm = _fit_mm(img.size, physical_mm)
    px_w = max(1, round(w_mm / 25.4 * dpi))
    px_h = max(1, round(h_mm / 25.4 * dpi))
    img = img.resize((px_w, px_h), Image.LANCZOS)

    # ---- ③ 局部调整（九宫格）：旋钮处理之后、仿色之前 ----
    if node_ops:
        img = Image.fromarray(_apply_local_ops(np.asarray(img, dtype=np.uint8), node_ops), mode="L")

    # ---- 量化指标（"数值眼睛"：给 agent/人判断方向用） ----
    arr = np.asarray(img, dtype=np.uint8)
    mean_v = float(arr.mean())
    dark_pct = float((arr < 64).mean() * 100)
    light_pct = float((arr > 192).mean() * 100)

    # ---- 末步：扩散仿色 → 1bit 上机档（教程的"位图-扩散仿色"自动化） ----
    binary = _fs_dither(arr)
    ink_pct = float((binary == 0).mean() * 100)  # 黑点(0)占比 = 会打点的区域占比

    # ---- 存 PNG（预览/对比，带 DPI 元数据）----
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(src).stem
    suffix = f"_{tag}" if tag else ""
    out_path = out / f"{stem}_engrave_{physical_mm:g}mm_{dpi}dpi{suffix}.png"
    img.save(out_path, dpi=(dpi, dpi))

    # ---- 存 1bit BMP（上机档；LightBurn 导入时选 dpi）----
    bmp_path = out_path.with_suffix(".bmp")
    _save_1bit_bmp(binary, bmp_path, dpi)

    # ---- 汇报（结构化，供人看 & 回归测试断言）----
    applied = {k: merged[k] for k in IMPLEMENTED_KNOBS}
    report = {
        "ok": True,
        "output": str(out_path),
        "bmp": str(bmp_path),
        "pixels": img.size,
        "physical_mm": (round(w_mm, 1), round(h_mm, 1)),
        "physical_mm_requested": physical_mm,
        "dpi": dpi,
        "knobs_applied": applied,
        "knobs_gap": CAPABILITY_GAPS,  # 哪些旋钮暂未实现（能力缺口）
        "metrics": {
            "mean": round(mean_v, 1),
            "dark_pct": round(dark_pct, 1),
            "light_pct": round(light_pct, 1),
            "ink_pct": round(ink_pct, 1),
        },
        # ③ 九宫格：9 格指标（行优先 0=左上 … 8=右下）+ 本次生效的局部调整（全量重放口径）
        "zones": _zone_metrics(arr, binary),
        "local_ops": node_ops,
    }
    return report


def _fit_mm(px_size: tuple[int, int], long_edge_mm: float) -> tuple[float, float]:
    """按长边换算物理毫米，保持宽高比。"""
    w_px, h_px = px_size
    if w_px >= h_px:
        return long_edge_mm, long_edge_mm * h_px / w_px
    return long_edge_mm * w_px / h_px, long_edge_mm


def weighted_zone_pct(report: dict, key: str) -> float:
    """把 9 格指标按格面积加权，换算回整图口径（回归断言用）。

    格面积用报告的 pixels 与 _zone_bounds 规则还原，因此格子大小不等时也准确。
    """
    w_px, h_px = report["pixels"]
    ys = _zone_bounds(h_px)
    xs = _zone_bounds(w_px)
    total = float(w_px * h_px)
    acc = 0.0
    for i, (y0, y1) in enumerate(ys):
        for j, (x0, x1) in enumerate(xs):
            z = report["zones"][i * 3 + j]
            acc += float(z[key]) * (y1 - y0) * (x1 - x0)
    return acc / total


if __name__ == "__main__":
    # 自检：用测试原图跑一遍，验证管线无异常、输出可复现
    import sys

    demo = Path(__file__).resolve().parents[2] / "测试原图" / "test.jpg"
    if not demo.exists():
        print(f"没找到测试原图: {demo}")
        sys.exit(1)
    # 注意：多次渲染写同一文件名，每次渲染后必须立即读走字节再渲染下一次
    r1 = render_grayscale(demo, "assets/out", knobs={"整体明暗": 0.3})
    b1 = Path(r1["output"]).read_bytes()
    r2 = render_grayscale(demo, "assets/out", knobs={"整体明暗": 0.3})
    b2 = Path(r2["output"]).read_bytes()
    same_file = b1 == b2
    # 素描效果验证：强度 0.9 的输出必须和 0 明显不同（证明真的生效，不是空旋钮）
    r_plain = render_grayscale(demo, "assets/out", knobs={})
    b_plain = Path(r_plain["output"]).read_bytes()
    r_sketch = render_grayscale(demo, "assets/out", knobs={"素描感强度": 0.9})
    b_sketch = Path(r_sketch["output"]).read_bytes()
    differs = b_plain != b_sketch
    # ③ 九宫格自检：9 格指标自洽 + 局部调整真生效（只动指定格）
    r_local = render_grayscale(demo, "assets/out", knobs={}, local_ops=[{"zone": 0, "op": "whiten", "amount": 0.9}])
    zone_dark_gap = abs(weighted_zone_pct(r_plain, "dark_pct") - r_plain["metrics"]["dark_pct"])
    local_delta = r_local["zones"][0]["dark_pct"] - r_plain["zones"][0]["dark_pct"]
    other_delta = max(abs(r_local["zones"][i]["dark_pct"] - r_plain["zones"][i]["dark_pct"]) for i in range(1, 9))
    print("输出:", r1["output"])
    print("像素:", r1["pixels"], "物理尺寸:", r1["physical_mm"], "DPI:", r1["dpi"])
    print("可复现(同输入两次输出字节一致):", same_file)
    print("素描感强度已生效(0 与 0.9 输出不同):", differs)
    print(f"分区指标格数: {len(r_plain['zones'])}，加权与整图误差: {zone_dark_gap:.3f} 个百分点")
    print(f"局部调整(第 1 格更白 0.9)：该格暗部 {local_delta:+.1f}，其他格最大变化 {other_delta:.1f}")
    print("已实现旋钮:", r1["knobs_applied"])
    print("未实现旋钮(能力缺口):", r1["knobs_gap"])
