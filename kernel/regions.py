r"""位置词表（区域）：把"**人怎么说位置**"变成"**一块确定性的像素区域**"。

为什么要有这个文件（2026-10-13 实测依据）：
  · 用户明确否掉了"九宫格格号"（"太机械了"）——但**没有位置词，小助手只能猜**；
  · 实测：让 LLM 自己给像素坐标 = 必然漂；让它从**固定词表**里挑一个 = 可校验、可复现、能进账；
  · 所以位置词表 = 小助手和用户之间那份"共同语言"，**唯一来源是这份代码**，
    提示词里渲染它（`server\capabilities.py` 的同一套纪律：**绝不在提示词里手写第二份**）。

词表的形状：
  · 名字用**人话**（"左边一列"、"上三分之一"、"正中一块"…），因为用户嘴里说的就是这些；
  · 每个词给一个**归一化形状**（0~1 的分数坐标）⇒ 与图片尺寸无关 ⇒ 换尺寸/换分辨率都稳；
  · 形状两种：`rect`（矩形，贴边切）与 `ellipse`（椭圆，适合"中间那块脸"这类）。

口径：分数坐标 (fx0, fy0, fx1, fy1)，左上为原点；**像素范围由 `rect_px()` 唯一决定**，
      两个地方（界面裁剪、"局部调整"作用范围）必须都调它，不许各算一套。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Region:
    """一个位置词：人话名字 + 归一化形状。"""

    key: str                      # 机器用的键（agent JSON 里写它）
    label: str                    # 给人看的中文名
    fx0: float
    fy0: float
    fx1: float
    fy1: float
    shape: str = "rect"           # rect | ellipse

    def rect_px(self, w: int, h: int) -> tuple[int, int, int, int]:
        """像素范围 (x0, y0, x1, y1)，**左闭右开**；两个调用方都走这里。"""
        x0 = int(round(self.fx0 * w))
        y0 = int(round(self.fy0 * h))
        x1 = int(round(self.fx1 * w))
        y1 = int(round(self.fy1 * h))
        x0 = max(0, min(w - 1, x0))
        y0 = max(0, min(h - 1, y0))
        x1 = max(x0 + 1, min(w, x1))
        y1 = max(y0 + 1, min(h, y1))
        return x0, y0, x1, y1

    def mask(self, w: int, h: int) -> np.ndarray:
        """布尔掩膜（True = 属于这块）。rect/ellipse 都在这里定死。"""
        x0, y0, x1, y1 = self.rect_px(w, h)
        m = np.zeros((h, w), dtype=bool)
        if self.shape == "rect":
            m[y0:y1, x0:x1] = True
            return m
        # ellipse：填在这个外接矩形里的椭圆
        cy, cx = (y0 + y1 - 1) / 2.0, (x0 + x1 - 1) / 2.0
        ry, rx = max(1e-6, (y1 - y0) / 2.0), max(1e-6, (x1 - x0) / 2.0)
        ys, xs = np.mgrid[0:h, 0:w]
        m[((ys - cy) / ry) ** 2 + ((xs - cx) / rx) ** 2 <= 1.0] = True
        return m


# ---- 词表本体（只追加；改一条要同时改判据）----
REGIONS: tuple[Region, ...] = (
    Region("left",       "左边一列",      0.00, 0.00, 0.34, 1.00),
    Region("right",      "右边一列",      0.66, 0.00, 1.00, 1.00),
    Region("top",        "上面三分之一",  0.00, 0.00, 1.00, 0.34),
    Region("bottom",     "下面三分之一",  0.00, 0.66, 1.00, 1.00),
    Region("center",     "正中一块",      0.30, 0.30, 0.70, 0.70, shape="ellipse"),
    Region("upper_left", "左上角",        0.00, 0.00, 0.50, 0.50),
    Region("upper_right", "右上角",       0.50, 0.00, 1.00, 0.50),
    Region("lower_left", "左下角",        0.00, 0.50, 0.50, 1.00),
    Region("lower_right", "右下角",       0.50, 0.50, 1.00, 1.00),
    Region("upper_mid",  "上中",          0.34, 0.00, 0.66, 0.34),
    Region("mid_left",   "左中",          0.00, 0.34, 0.34, 0.66),
    Region("mid_right",  "右中",          0.66, 0.34, 1.00, 0.66),
    Region("lower_mid",  "下中",          0.34, 0.66, 0.66, 1.00),
    Region("whole",      "整张",          0.00, 0.00, 1.00, 1.00),
)

REGION_MAP: dict[str, Region] = {r.key: r for r in REGIONS}


def get(key: str) -> Region:
    """按键取区域；未知键抛 ValueError（**不许静默**）。"""
    r = REGION_MAP.get(str(key))
    if r is None:
        raise ValueError(f"未知区域：{key!r}（只能是 {sorted(REGION_MAP)}）")
    return r


def validate(key) -> tuple[bool, str]:
    if not isinstance(key, str) or not key.strip():
        return False, f"region 必须是非空字符串，收到 {key!r}"
    if key not in REGION_MAP:
        return False, f"未知区域 {key!r}（清单里没有，属于缺口，请报告而不是发明）"
    return True, ""


def render_for_prompt() -> str:
    """渲染进提示词用的清单（★ 与代码同源，绝不手写第二份）。"""
    lines = ["【位置词表】（用户说「哪里」时，**只能从这里挑**；挑了就要在 message 里说出你挑的那个中文名）"]
    for r in REGIONS:
        kind = "矩形" if r.shape == "rect" else "椭圆"
        lines.append(f"- {r.key} = {r.label}（{kind}：x {r.fx0:.2f}~{r.fx1:.2f}, y {r.fy0:.2f}~{r.fy1:.2f}）")
    lines.append("（想指「右下角那块小的」这种清单里没有的 ⇒ 挑**最接近**的一个，"
                 "并在 message 里说清「我按右下角处理，不对你告诉我」，**不许自己编坐标**）")
    return "\n".join(lines)


def coerce(value) -> str:
    """把 agent 给的 region 值压低成 key：支持 'left' 或 {'hard': 'left'} 两种写法。"""
    if isinstance(value, dict):
        for k in ("hard", "key", "region", "name"):
            if isinstance(value.get(k), str):
                return value[k]
        raise ValueError(f"region 对象里找不到键名：{value!r}")
    if isinstance(value, str):
        return value
    raise ValueError(f"region 写法不认识：{value!r}")
