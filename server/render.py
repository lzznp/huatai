r"""出图（第 4c 步）：把**参数**交给那条验过的确定性管线，把**产物与指标**落账。

分工（铁律）：
- **小助手只给参数**（`knobs` / `local`），它**永远不画图**；
- 图由 `kernel\image_lib\pipeline.py` 算出来（纯函数、无随机）；
- 本模块只做三件事：**校验参数 → 调管线 → 落账 + 独立回读**。

两条硬判据：
1. **产物真的落盘**（不看回执，看文件）；
2. ★ **独立回读**：管线自报的墨点占比，我们再**从 BMP 反算一遍**——
   同一个函数既改图又算分，那叫"同源自证"；从产物反算才是证据。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNEL = ROOT / "kernel"
if str(KERNEL) not in sys.path:
    sys.path.insert(0, str(KERNEL))

import knobs as K  # noqa: E402
from image_lib import pipeline as PL  # noqa: E402

from . import store as ST  # noqa: E402

DEFAULT_MM = 100.0
DEFAULT_DPI = PL.DEFAULT_DPI
# 回读与自报的容差（个百分点）。同一条 binary 算出来的两个数，本来就该几乎相等；
# 留一点缝是因为 BMP 可能有行填充。
INK_TOLERANCE_PCT = 1.0


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def readback_bmp(path: str | Path) -> dict:
    """★ 独立回读：只读上机档 BMP，反算黑点占比与尺寸。

    这是"证据"，不是"自报"——它不碰管线内存里的任何东西。
    """
    import numpy as np
    from PIL import Image

    p = Path(path)
    im = Image.open(p)
    arr = np.asarray(im)
    if arr.dtype == bool:                 # PIL 读 1bit 图 → bool
        black = float((~arr).mean() * 100)
    else:
        black = float((arr == 0).mean() * 100)
    return {
        "路径": str(p),
        "字节": p.stat().st_size,
        "sha256": _sha256(p),
        "尺寸": list(im.size),
        "模式": im.mode,
        "bmp里的黑点占比": round(black, 1),
    }


def render_order(project: str, order_id: str, *,
                 knobs: dict | None = None,
                 local_ops: list | None = None,
                 physical_mm: float = DEFAULT_MM,
                 dpi: int = DEFAULT_DPI,
                 note: str = "") -> dict:
    """出图一版：校验 → 调管线 → 独立回读 → 落账。返回给人/界面看的结构。"""
    data = ST.get_order(project, order_id)
    if data is None:
        raise FileNotFoundError(f"没找到这张单：{project}\\{order_id}")

    src = data.get("src_path")
    if not src or not Path(src).is_file():
        raise FileNotFoundError(f"这一单的原图不在了：{src}")

    # ---- 校验（提示词是引导，这里才是法律）----
    new_knobs = {str(k): v for k, v in (knobs or {}).items()}
    ok, err = K.validate_knobs(new_knobs)
    if not ok:
        raise ValueError(err)
    ops = list(local_ops if local_ops is not None else (data.get("local_ops") or []))
    ok, err = K.validate_local_ops(ops)
    if not ok:
        raise ValueError(f"局部调整不合法：{err}")

    # ---- ★ 旋钮是"累积状态"，不是"某次回复的残影" ----
    # 上一版生效过的值从 last_report.knobs_applied 读回来；本次只覆盖它**明确写出来**的那几个。
    # 否则就是老项目那个 bug：说一句"背景白一点"，只写一个旋钮 ⇒ 之前调好的素描感被静默归零。
    prev = {k: v for k, v in ((data.get("last_report") or {}).get("knobs_applied") or {}).items()
            if k in K.KNOB_MAP}
    effective = {**K.DEFAULT_KNOBS, **prev, **new_knobs}

    # ---- 版本号与产物名 ----
    n_ver = int(data.get("n_ver") or 0) + 1
    tag = f"v{n_ver}"
    out_dir = ST.order_path(project, order_id) / "out"

    # ---- 调管线（纯函数、无随机）----
    report = PL.render_grayscale(
        src, out_dir, knobs=effective, physical_mm=physical_mm, dpi=dpi,
        tag=tag, local_ops=ops,
    )

    # ---- 判据 1：产物真的在盘上 ----
    png, bmp = Path(report["output"]), Path(report["bmp"])
    if not png.is_file() or not bmp.is_file():
        raise RuntimeError(f"管线说产出了，但盘上没有：{png} / {bmp}")

    # ---- 判据 2：独立回读 ----
    rb = readback_bmp(bmp)
    self_ink = float((report.get("metrics") or {}).get("ink_pct") or 0)
    diff = round(abs(rb["bmp里的黑点占比"] - self_ink), 2)
    rb["管线自报的黑点占比"] = self_ink
    rb["差"] = diff
    rb["对得上"] = diff <= INK_TOLERANCE_PCT
    if not rb["对得上"]:
        # 不许静默：自报与回读差太多，说明有一边错了，直接报出来
        raise RuntimeError(
            f"独立回读与管线自报对不上：BMP 反算 {rb['bmp里的黑点占比']}% vs 自报 {self_ink}%（差 {diff}）")

    # ---- ★ 缺口旋钮必须**喊出来**（不许假装生效）----
    # 缺口旋钮的名字是合法的（在 KNOBS 里），但背后能力没实现 ⇒ 写了也不会有任何效果。
    # 静默忽略就是"假装生效"，所以这里三处都留痕：返回值、账、给人看的 text。
    gaps_used = [k for k in new_knobs if k in set(PL.CAPABILITY_GAPS)]

    # ---- 落账：一条 action 行（谁、什么参数、出来什么数）----
    line = ST.append_transcript(project, order_id, {
        "kind": "action",
        "text": f"出图 {tag}：墨点 {self_ink}%（BMP 反算 {rb['bmp里的黑点占比']}%）"
                f" ｜ {report['pixels'][0]}×{report['pixels'][1]}px @{dpi}dpi"
                f" ｜ 暗部 {report['metrics']['dark_pct']}%"
                + (f"　⚠️ 这些旋钮还没实现、写了不生效：{'、'.join(gaps_used)}" if gaps_used else ""),
        "data": {
            "来源": "render.order",
            "版本": tag,
            "参数": {
                "本次改的": new_knobs,          # 意图：这一次要改什么
                "生效的": report.get("knobs_applied"),   # 状态：这一版真正生效的全量
                "local_ops": report.get("local_ops"),
                "physical_mm": physical_mm,
                "dpi": dpi,
            },
            "指标": report.get("metrics"),
            "回读": rb,
            "产物": {"png": str(png), "bmp": str(bmp),
                     "png_sha256": _sha256(png), "bmp_sha256": rb["sha256"]},
            "note": note,
        },
    })

    # ---- 更新整单归档（**保留原有字段**，只追加历史与最新报告）----
    history = list(data.get("history") or [])
    history.append({
        "who": "小助手",
        "ver": n_ver,
        "img": str(png),
        "bmp": str(bmp),
        "note": note,
        "knobs": report.get("knobs_applied"),
        "local_ops": report.get("local_ops"),
        "metrics": report.get("metrics"),
        # ---- ★ 版本对比要用的两样（2026-10-13 加）----
        # png_sha256：界面显示的那张图与账里记的**是不是同一张**，拿它一对便知
        #             （以前只在 action 行里，history 里没有 ⇒ 界面无从核对）。
        # zones：9 格指标（每格 mean/dark_pct/light_pct/ink_pct）——界面上的九宫格标签、
        #        以及要点卡里"哪一格更暗"都要用它。**旧版 history 没有这两项**，
        #        读的人必须按"可能缺"处理（界面/测试都不许因此炸）。
        "png_sha256": _sha256(png),
        "zones": report.get("zones"),
    })
    ST.save_render(project, order_id, history=history, last_report=report,
                   local_ops=ops, created_at=data.get("created_at"))

    return {
        "版本": tag,
        "n_ver": n_ver,
        "产物": {"png": str(png), "bmp": str(bmp)},
        "指标": report.get("metrics"),
        "分区": report.get("zones"),
        "像素": report.get("pixels"),
        "物理毫米": report.get("physical_mm"),
        "dpi": dpi,
        "旋钮生效": report.get("knobs_applied"),
        "旋钮缺口": report.get("knobs_gap"),
        "本次写了但没生效的旋钮": gaps_used,
        "局部调整": report.get("local_ops"),
        "回读": rb,
        "账": line,
    }
