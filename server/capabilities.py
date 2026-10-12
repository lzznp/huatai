"""能力声明 —— 单一来源，由代码生成，**不许手写**。

为什么单独一个模块：小助手要能当场说"这个我做不到"，而这句话**不能是它临场编的**。
界面、运行态 agent、判据，三方都从这里读；改一处，三边的说法一起变。
（判据：改一处清单 → 小助手的回答跟着变。不变 = 它在编。）

权威来源：
- 旋钮的"已实现 / 缺口" ← `kernel/image_lib/pipeline.py` 的 `IMPLEMENTED_KNOBS` / `CAPABILITY_GAPS`
- 旋钮的定义           ← `kernel/knobs.py` 的 `KNOBS`
本模块只补两样内核里没有的东西：**工艺**与**料**。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNEL = ROOT / "kernel"
if str(KERNEL) not in sys.path:
    sys.path.insert(0, str(KERNEL))

import knobs as K  # noqa: E402
from image_lib import pipeline as PL  # noqa: E402

SCHEMA = 1

# ---------------------------------------------------------------- 料
# 第一版**只吃图片**（用户 2026-10-12 定：其他资料以后再说）。
# 其余一律走"明说读不了"这条路 —— 这本身就是"不许假成功"的一个真实用例。
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")

MATERIALS: list[dict] = [
    {
        "id": "image",
        "名": "图片",
        "能不能": True,
        "扩展名": list(IMAGE_EXTS),
        "怎么读": "Pillow 读入 → 转灰度；原图只进不改，副本进单目录",
        "证据": "bestpic 闭环实测（test.jpg 787×787 @200dpi）",
    },
    {
        "id": "pdf",
        "名": "PDF",
        "能不能": False,
        "为什么不能": "本版没有 PDF 解析器（用户 2026-10-12：其他资料以后再说）",
    },
    {
        "id": "sheet",
        "名": "表格（Excel / CSV）",
        "能不能": False,
        "为什么不能": "本版没有表格解析器",
    },
    {
        "id": "mesh",
        "名": "三维文件（STL / OBJ / 3DM）",
        "能不能": False,
        "为什么不能": "本项目只做位图工艺，不做三维建模",
    },
]

# ---------------------------------------------------------------- 工艺
# ★ 这一节就是"落在这个列表里做不到的，必须明说做不到"的凭据（参考包守则 §五）。
CRAFTS: list[dict] = [
    {
        "id": "glass",
        "名": "玻璃画",
        "能不能": True,
        "怎么做": "位图光栅：灰度 → 明暗/反差/细节/素描 → 3×3 局部 → Floyd–Steinberg 扩散仿色 → 1bit BMP 上机档",
        "料": ["image"],
        "产出": ["PNG 灰度预览", "1bit BMP 上机档（LightBurn 直接吃）", "指标：整图 + 3×3 分区"],
        "证据": "回归 9/9、orders 18/18、UI 冒烟 34/34；真机 agent 跑通（2026-09-12）",
    },
    {
        "id": "leaf",
        "名": "叶雕",
        "能不能": True,
        "怎么做": "与玻璃画同一条位图路线（蓝光机可直接吃位图光栅，无矢量化问题）",
        "料": ["image"],
        "产出": ["PNG 灰度预览", "1bit BMP 上机档"],
        "证据": "同玻璃画（同一条管线，未单独真机验证）",
    },
    {
        "id": "paper_carve",
        "名": "剪纸 · 只雕不切穿",
        "能不能": True,
        "怎么做": "同玻璃画的位图路线（不切穿就不需要矢量）",
        "料": ["image"],
        "产出": ["PNG 灰度预览", "1bit BMP 上机档"],
        "证据": "同玻璃画（同一条管线，未单独真机验证）",
    },
    {
        "id": "paper_cut",
        "名": "剪纸 · 镂空切割",
        "能不能": False,
        "为什么不能": "需要矢量内核（连通性分析 / 孤岛桥接 / 矢量化 / 最小线宽判据），本版未接；且用户的剪纸样张还要先解决 ComfyUI 生成的五官孤岛",
    },
    {
        "id": "model3d",
        "名": "三维模型",
        "能不能": False,
        "为什么不能": "本项目只做位图工艺，不做三维建模（这是产品边界，不是技术缺口）",
    },
]

# ---------------------------------------------------------------- 明确不做
# 参考包守则的做法：把"不做"显式写出来，落在里面就直接砍，不"试一下看看"。
NOT_DOING: list[str] = [
    "设备直连（雕刻机 / LightBurn 自动上机）——用户 2026-10-12：以后再说",
    "刀路（顺序 / 功率分层 / 进刀点 / G-code）",
    "材料标定与雕刻效果模拟",
    "矢量化（vtracer / Potrace / 轮廓简化）",
    "ComfyUI 内网算力与工作流调用",
    "Inkscape / Rhino 等外部内核适配（插槽留空）",
    "三维建模与自由曲面",
]


def knobs_declaration() -> list[dict]:
    """旋钮清单：定义来自 knobs.KNOBS，'已实现/缺口'来自 pipeline（都是代码里的真源）。"""
    implemented = set(PL.IMPLEMENTED_KNOBS)
    gaps = set(PL.CAPABILITY_GAPS)
    out: list[dict] = []
    for k in K.KNOBS:
        if k.name in implemented:
            state = "已实现"
        elif k.name in gaps:
            state = "缺口"          # 缺口不许假装生效，agent 必须报告
        else:
            state = "未知"          # 既不在一也不在二：说明两边清单漂了，如实暴露
        out.append({
            "名": k.name,
            "范围": [k.lo, k.hi],
            "默认": k.default,
            "含义": k.meaning,
            "作用": k.applies_to,
            "状态": state,
        })
    return out


def declaration() -> dict:
    """完整能力声明（界面与 agent 的唯一来源）。"""
    return {
        "schema": SCHEMA,
        "工艺": CRAFTS,
        "料": MATERIALS,
        "旋钮": knobs_declaration(),
        "局部调整": {
            "网格": "3×3（行优先，0=左上 … 8=右下）",
            "动作": list(K.ZONE_OP_ALLOWED),
            "单次上限": K.LOCAL_OP_MAX_AMOUNT,
        },
        "产出": ["PNG 灰度预览", "1bit BMP 上机档", "指标（整图 + 3×3 分区）"],
        "本版不做": NOT_DOING,
        "诚实边界": [
            "一张图只能到【可评审的工艺稿】，不承诺'上传一张图 ⇒ 完美成品'",
            "上机极性（暗→黑点）待用户真机验证；反了只改仿色映射，不动局部算子语义",
        ],
    }


def can_craft(craft_id: str) -> tuple[bool, str]:
    """这个工艺能不能做；不能就把理由原话给出来。"""
    for c in CRAFTS:
        if c["id"] == craft_id or c["名"] == craft_id:
            if c["能不能"]:
                return True, ""
            return False, c.get("为什么不能", "本版不做这个")
    return False, f"我没有这项能力：{craft_id}（不在我的能力清单里）"


def can_read_material(filename: str) -> tuple[bool, str]:
    """这种料能不能读（按扩展名判；本版只吃图片）。"""
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTS:
        return True, ""
    for m in MATERIALS:
        if ext in [e.lower() for e in m.get("扩展名", [])]:
            return True, ""
    return False, f"我读不了这种资料（{ext or '没有扩展名'}）：本版只吃图片（{'、'.join(IMAGE_EXTS)}）"


if __name__ == "__main__":  # 人读一眼：python server\capabilities.py
    import json
    print(json.dumps(declaration(), ensure_ascii=False, indent=2))
