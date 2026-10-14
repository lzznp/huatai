r"""区域预览：把"小助手理解的**位置**"裁出来给用户看一眼（2026-10-13 加）

为什么要有这个动作：
  用户否掉了九宫格格号（"太机械了"），但**位置这件事总得对齐**。
  实测（`tests\exp_position.py`）：让 LLM 自己写像素坐标 = 必漂；让它从固定词表挑 = 可校验。
  ⇒ 光有词表还不够：**得让用户看见"它挑的是哪一块"**，一眼认出来才算对齐。

做法：
  · 在一张"底图"上裁出该区域的**外接矩形**（底图优先用**最新一版产物**，
    因为用户判的是"这一版哪里不对"；没有产物时才退回原图）；
  · 裁出来的那一块用**半透明红色**盖住 + 红色描边（区域是椭圆时按椭圆盖），
    没被盖住的部分保持原样 ⇒ 用户能看出"它理解的是这一块"；
  · ★ 裁剪图**只回给界面看**，不落 projects、不记账（和"试算候选"同一条纪律）。
"""
from __future__ import annotations

import base64
import hashlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNEL = ROOT / "kernel"
if str(KERNEL) not in sys.path:
    sys.path.insert(0, str(KERNEL))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import regions as RG  # noqa: E402

from . import store as ST  # noqa: E402

PAD_FRAC = 0.12          # 裁剪时四周留白（占长边比例），免得裁到只剩一条线
MAX_SIDE = 900           # 预览图最长边上限（别把整图塞进界面）


def _base_image(project: str, order_id: str) -> tuple[Image.Image, str]:
    """底图：优先最新一版产物 PNG；没有就退回原图。返回 (图, 说明)。"""
    data = ST.get_order(project, order_id) or {}
    hist = [h for h in (data.get("history") or []) if h.get("img")]
    if hist:
        p = Path(hist[-1]["img"])
        if p.is_file():
            return Image.open(p).convert("RGB"), f"第 {hist[-1].get('ver')} 版产物"
    src = data.get("src_path")
    if src and Path(src).is_file():
        return Image.open(src).convert("RGB"), "原图（还没出过图）"
    raise FileNotFoundError(f"这一单既没有产物也没有原图：{project}\\{order_id}")


def preview(project: str, order_id: str, region_key: str, *, return_image: bool = False):
    """裁出该区域并高亮。返回给界面/账看的字典（含 data URL）。"""
    r = RG.get(region_key)                      # 未知键抛 ValueError（不静默）
    img, base_note = _base_image(project, order_id)
    W, H = img.size
    x0, y0, x1, y1 = r.rect_px(W, H)

    # 高亮：整块区域盖半透明红（椭圆区域按椭圆盖），再描边
    vis = img.convert("RGB").copy()
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    if r.shape == "ellipse":
        od.ellipse([x0, y0, x1 - 1, y1 - 1], fill=(230, 40, 40, 90), outline=(255, 60, 60, 255), width=3)
    else:
        od.rectangle([x0, y0, x1 - 1, y1 - 1], fill=(230, 40, 40, 90), outline=(255, 60, 60, 255), width=3)
    vis = Image.alpha_composite(vis.convert("RGBA"), ov).convert("RGB")

    # 裁外接矩形 + 留白
    pad = int(max(x1 - x0, y1 - y0) * PAD_FRAC)
    cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
    cx1, cy1 = min(W, x1 + pad), min(H, y1 + pad)
    crop = vis.crop((cx0, cy0, cx1, cy1))
    cw, ch = crop.size
    if max(cw, ch) > MAX_SIDE:
        s = MAX_SIDE / max(cw, ch)
        crop = crop.resize((max(1, int(cw * s)), max(1, int(ch * s))), Image.LANCZOS)

    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    raw = buf.getvalue()
    out = {
        "区域": r.key,
        "名字": r.label,
        "形状": r.shape,
        "底图": base_note,
        "区域占全图": round(float(r.mask(W, H).mean()) * 100, 1),
        "裁剪像素": [cx1 - cx0, cy1 - cy0],
        "在底图上的位置": [x0, y0, x1, y1],
        "底图尺寸": [W, H],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "data_url": "data:image/png;base64," + base64.b64encode(raw).decode("ascii"),
        "说明": "★ 这张只是给界面看的（不落 projects、不记账）",
    }
    if return_image:
        return out, crop
    return out


def all_previews_meta(w: int = 400, h: int = 380) -> list[dict]:
    """词表总览（排查用）：每个区域的像素范围与占比。"""
    return [{"键": r.key, "名字": r.label, "形状": r.shape,
             "像素范围": list(r.rect_px(w, h)),
             "占比%": round(float(r.mask(w, h).mean()) * 100, 1)} for r in RG.REGIONS]


if __name__ == "__main__":  # 手工看一眼：python -m server.region
    import json
    print(json.dumps(all_previews_meta(), ensure_ascii=False, indent=1))
