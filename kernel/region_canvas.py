"""region_canvas.py —— 鼠标勾选区域的纯逻辑（无 streamlit 依赖，方便离线测试）。

第 1 步（技术验证）只放这些：
- 浏览器回传的 mask PNG（白底 + **alpha 通道**是笔迹）→ 8bit 'L' mask
- 校准靶图的生成（带已知坐标的红十字，用来验"点得准"）
- 覆盖率/量化刻度/羽化过渡这些可量化的检查
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image, ImageDraw

# 前端导出前把 alpha 量化到这个刻度（同一笔迹 → 同一字节，可复现）
QUANT = 17

# 送进浏览器的底图最长边（更大肉眼看不出差别，白占内存）
MAX_SIDE = 1100

# 校准靶图上的红十字中心（归一化坐标，行优先）——"点得准"的期望值来源
MARKERS: list[tuple[float, float]] = [
    (0.15, 0.15), (0.5, 0.5), (0.85, 0.85), (0.85, 0.15), (0.15, 0.85),
]


def decode_mask(b64: str) -> tuple[Image.Image | None, str]:
    """浏览器回传的 PNG → 8bit 'L' 图（像素值 = 笔迹 alpha）。

    ⚠️ 关键：前端导出的是 RGBA，**信息在 alpha 通道里**（RGB 统一是白）。
    早期写法用 convert("L") 会把 alpha 丢掉 → 整张图变成 255（覆盖率恒 100%）。
    必须取 A 通道。
    """
    if not b64:
        return None, "空 mask"
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(b64)
    except Exception as e:  # noqa: BLE001
        return None, f"base64 解码失败: {e}"
    try:
        img = Image.open(io.BytesIO(raw))
    except Exception as e:  # noqa: BLE001
        return None, f"PNG 解码失败: {e}"
    if img.mode in ("RGBA", "LA", "P"):
        out = img.convert("RGBA").getchannel("A")
    else:
        out = img.convert("L")   # 已经是灰度就按灰度用（兼容旧数据）
    return out, f"{len(raw) / 1024:.1f} KB"


def to_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def demo_source(search_paths: list[Path] | None = None, size: tuple[int, int] = (1024, 1024)) -> Image.Image:
    """造"校准靶图"：底图 + 九宫格参考线 + 5 个红十字（中心坐标 = MARKERS，已知）。"""
    src = None
    for p in (search_paths or []):
        if p.is_file():
            src = p
            break
    img = Image.open(src).convert("RGB") if src else Image.new("RGB", size, "white")
    w, h = img.size
    d = ImageDraw.Draw(img)

    # 九宫格参考线（细红）
    step_x, step_y = w / 3.0, h / 3.0
    lw = max(1, min(w, h) // 400)
    for i in (1, 2):
        d.line([(step_x * i, 0), (step_x * i, h)], fill=(255, 0, 0), width=lw)
        d.line([(0, step_y * i), (w, step_y * i)], fill=(255, 0, 0), width=lw)

    # 红十字校准标记
    r = max(10, min(w, h) // 45)
    for i, (nx, ny) in enumerate(MARKERS):
        cx, cy = nx * w, ny * h
        d.line([(cx - r, cy), (cx + r, cy)], fill=(255, 45, 85), width=3)
        d.line([(cx, cy - r), (cx, cy + r)], fill=(255, 45, 85), width=3)
        d.text((cx + r * 0.6, cy - r * 1.4), f"P{i + 1}", fill=(255, 45, 85))
    return img


def mask_stats(mask: Image.Image) -> dict:
    """可量化的检查：覆盖率 / 量化刻度 / 边界过渡占比。"""
    w, h = mask.size
    px = mask.load()
    hist = mask.histogram()
    solid = sum(hist[9:])                         # >8 视为已涂
    off_grid = sum(c for v, c in enumerate(hist) if c and v % QUANT != 0)
    cy = h // 2
    row = [px[x, cy] for x in range(w)]
    soft = sum(1 for v in row if 0 < v < 255)
    return {
        "size": (w, h),
        "coverage_pct": round(solid / float(w * h) * 100, 3),
        "quant_ok": off_grid == 0,
        "quant_off": off_grid,
        "soft_ratio_pct": round(soft / float(w) * 100, 3),
    }


def calib_errors(points: list, img_w: int, img_h: int,
                 markers: list[tuple[float, float]] | None = None) -> list[dict]:
    """校准点与靶图标记中心的像素误差（验证"显示 ↔ 图像像素"对齐）。"""
    marks = markers or MARKERS
    out: list[dict] = []
    for i, p in enumerate(points or []):
        if i >= len(marks) or not img_w or not img_h:
            continue
        ex, ey = marks[i][0] * img_w, marks[i][1] * img_h
        gx, gy = float(p[0]) * img_w, float(p[1]) * img_h
        out.append({
            "点": i + 1,
            "期望(px)": f"({ex:.1f}, {ey:.1f})",
            "实际(px)": f"({gx:.1f}, {gy:.1f})",
            "误差(px)": round(((gx - ex) ** 2 + (gy - ey) ** 2) ** 0.5, 2),
        })
    return out
