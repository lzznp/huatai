"""controller.py —— 确定性流程骨架（导演）。

铁律（三权分离）：
- 本模块定"流程"，绝不让 agent 自由发挥拼流程。
- agent（判断员）只在分叉点被调用：意图理解 → 参数选择 → 迭代收敛。
- 图像函数库（image_lib）只执行，不改判断。
- 人（用户）最终拍板。

v1 流程（极简，先跑通）：
    1. 收输入：原图路径 + 用户一句话 + 物理尺寸(mm)
    2. 意图理解：问 agent「这是什么工艺、目标是什么」
    3. 参数选择：问 agent「把用户话翻译成旋钮取值」
    4. 渲染：调 image_lib 出图
    5. 给人看，等人反馈；反馈回来 → 回第 3 步微调（上限 N 轮）
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from agent_bridge import AgentBridge, AgentReply
from knobs import DEFAULT_KNOBS, KNOB_MAP, ZONE_COUNT, ZONE_OP_ALLOWED, ZONE_OP_CN
from image_lib.pipeline import render_grayscale, CAPABILITY_GAPS

ROOT = Path(__file__).resolve().parent

# 规则手册全文，注入每条会话的开场
RULES = (ROOT / "规则手册.md").read_text(encoding="utf-8")

# 一次订单最多迭代几轮（防止 agent 无限调参烧 token）
MAX_ITERATIONS = 5


def _local_brief() -> str:
    """③ 九宫格局部调整：给判断员的词汇表 + JSON 形态 + 定位说明（自动同步 knobs）。"""
    op_txt = "、".join(f'{k}（{ZONE_OP_CN[k]}）' for k in ZONE_OP_ALLOWED)
    return f"""[九宫格局部调整（3×3 分区）]
图片被切成 3×3 九格，编号**行优先**（第 1 格=左上，第 2 格=上中，第 3 格=右上，
第 4 格=左中，第 5 格=正中，第 6 格=右中，第 7 格=左下，第 8 格=下中，第 9 格=右下）。
- 你可以在输出的 JSON 里加 `local` 字段做**局部**调整：
  "local": [{{"zone": 4, "op": "brighten", "amount": 0.3}}]
  · zone：0~{ZONE_COUNT - 1}（=第 1~9 格，行优先）；一次可给多格（多条或多格都行）
  · op：{op_txt}
  · amount：0~1（可省略，省略=0.5）；**单次建议 ≤0.5**，下手过猛会毁掉过渡
- `local` 是**全量口径**：每次输出都要把你认为该生效的全部局部调整写全（界面也会替你累积，
  但你要以"报告里 zones 的数字 + 用户话"为准重新判断）；某格要**还原**就写
  {{"zone": 4, "op": "reset"}}，表示"这一格不要任何局部调整"。
- 方向（按视觉直觉，与上机极性解耦）：brighten/whiten = 该处**变亮**（墨点变稀）；
  darken/blacken = 该处**变暗**（墨点变密）。whiten/blacken 是"往白/往黑推"的强动作，
  适合"背景修白""这块压黑"；brighten/darken 是温和的线性加减光。
- 定位规则：报告里的 zones 是 9 格实测数字（0~8 行优先，含 mean/dark_pct/light_pct/ink_pct）。
  用户说"左上亮一点/额头太黑/下巴压暗"这类话时，**先对照 zones 数字找出是哪一格**，
  再决定 op 与 amount，并在 message 里复述"我按第 X 格处理"，避免认错格子。
- 边界说明：局部调整只作用于该格（格边有羽化过渡，不会出现硬接缝），
  不要用局部调整替代整体旋钮；整图性问题仍走旋钮。"""


def _zone_delta_brief(prev_zones, cur_zones) -> str:
    """渲染前后对照（E 拍板：agent 预告目标 / 页面给实测）。

    prev_zones = 上一版报告的 zones；cur_zones = 本版实测 zones。
    """
    if not prev_zones or not cur_zones or len(prev_zones) != len(cur_zones):
        return ""
    rows = []
    for i, (p, c) in enumerate(zip(prev_zones, cur_zones)):
        dm = c["mean"] - p["mean"]
        di = c["ink_pct"] - p["ink_pct"]
        if abs(dm) >= 1.0 or abs(di) >= 0.5:
            rows.append(
                f"  第 {i + 1} 格：均值 {p['mean']}→{c['mean']}（{dm:+.1f}）"
                f"｜墨点 {p['ink_pct']}%→{c['ink_pct']}%（{di:+.1f}）"
            )
    if not rows:
        return ""
    return "局部实测变化（本版 vs 上一版，只列有明显变化的格）：\n" + "\n".join(rows)


def _build_session_context(session_id: str) -> str:
    """构造 agent 的持久上下文（规则 + 它自己的身份/任务记录位置）。

    session_id 复用 = 同一条订单的对话续上；换 id = 新订单。
    """
    return f"""{RULES}

--- 会话开始 ---
你是本订单(session: {session_id})的判断员。后续消息中：
- 用户的话 / 图片情况会直接给你；
- 你按《规则手册》只输出合法 JSON。
"""


def _capability_brief() -> str:
    """当前图像库的能力现状（自动同步 pipeline，避免硬编码漂移）。"""
    from image_lib.pipeline import IMPLEMENTED_KNOBS, CAPABILITY_GAPS

    return (
        f"已实现能力旋钮：{'、'.join(IMPLEMENTED_KNOBS) or '无'}\n"
        f"能力缺口旋钮（尚未实现，agent 不应假装生效，需报告）：{'、'.join(CAPABILITY_GAPS) or '无'}"
    )


def _ask_knobs(bridge: AgentBridge, session_id: str, user_text: str, feedback: str = "") -> AgentReply:
    """分叉点：让 agent 把用户话翻译成旋钮。"""
    knobs_desc = "\n".join(
        f"- {k.name}: 范围[{k.lo},{k.hi}] 含义: {k.meaning}（作用:{k.applies_to}）"
        for k in KNOB_MAP.values()
    )
    prompt = f"""{_build_session_context(session_id)}

[旋钮清单]
{knobs_desc}

{_capability_brief()}

{_local_brief()}

[用户原始要求]
{user_text}

[玻璃画工艺默认底]
工艺=玻璃画且用户**没明确要"写实/干净灰度"**时：首版应默认把「素描感强度」调到 0.5~0.8，
还原手工流程"美图反色+素描"的铅笔线稿底（白底深线）；用户再提的明暗/反差等要求在此基础之上微调。
只有用户明确要写实照片感时，素描感强度才用 0。
首版还没有渲染报告（没有 zones 数字），所以用户没指明位置时**先不要**给 local；
用户明确说了"左上/右上/中间/下排"这类位置时，可以按编号给 local。

{("[上一版之后的用户反馈]\n" + feedback + "\n") if feedback else ""}
[你的任务]
按规则手册，输出 action=render 的 JSON：把用户要求翻译成旋钮取值（必要时加 local）。
只输出 JSON，不要输出任何其他文字。
"""
    return bridge.ask(prompt, session_id=session_id)


def _ask_iterate(
    bridge: AgentBridge,
    session_id: str,
    feedback: str,
    last_report: dict,
    last_zones_before: list | None = None,
) -> AgentReply:
    """分叉点：用户看了预览后的反馈，agent 决定继续调还是收工。

    last_zones_before：上一版**之前**那版的 zones（可选）。给了就能把"上一版的局部实测变化"
    一并汇报给判断员，让它知道上次下手到底动了多少（E 拍板的目标/实测对照闭环）。
    """
    delta = _zone_delta_brief(last_zones_before, (last_report or {}).get("zones"))
    prompt = f"""{_build_session_context(session_id)}

{_capability_brief()}

{_local_brief()}

[上一版渲染报告]
{json.dumps(last_report, ensure_ascii=False, indent=2)}

{("[上一版相对再上一版的实测变化]\n" + delta + "\n") if delta else ""}
报告里的 metrics（暗部/亮部/墨点占比）是**整图**量化指标；zones 是**3×3 每格**指标
（0~8 行优先）。用户说"不够白/太黑/点太密"这类话时先对照数字确认方向再决定调什么：
整图性问题 → 调旋钮；只涉及某一块（"左上太黑""背景这块脏"）→ 用 local 精准处理。
报告里的 local_ops 是当前生效的局部调整（全量口径），你要在此基础上增删改后再输出 local。

[用户反馈]
{feedback}

[你的任务]
按规则手册判断：
- 还能通过旋钮/局部调整微调改善 → 输出 action=render + 新 knobs +（必要时）local + 一句 message；
  message 里要写清你**打算达到什么**（例如"目标：第 5 格暗部 28%→约 15%"），便于用户核对；
- 用户已满意/要导出 → 输出 action=done + message；
- 反馈太模糊没法调 → 输出 action=ask + question。
- 用户要求的能力在当前是缺口时，在 reason 里如实注明，不假装生效。
只输出 JSON。
"""
    return bridge.ask(prompt, session_id=session_id)


def run_order(
    src_image: str | Path,
    user_text: str,
    physical_mm: float = 100.0,
    session_id: str | None = None,
    max_iter: int = MAX_ITERATIONS,
) -> list[dict]:
    """执行一条订单，返回完整过程记录（给人看/写日志）。

    返回的是"分步记录"列表，每步含 {step, reply, report} 等字段。
    """
    src_image = Path(src_image)
    if not src_image.exists():
        raise FileNotFoundError(f"原图不存在: {src_image}")

    session_id = session_id or f"order-{int(time.time())}"
    out_dir = ROOT / "assets" / "out"
    steps: list[dict] = []

    with AgentBridge() as bridge:
        # 第 1 步：意图理解 —— v1 简化为直接走玻璃画灰度路线（后续再让 agent 分流工艺）
        steps.append({"step": "intent", "note": "v1: 固定玻璃画·位图光雕路线, 不接矢量", "reply_raw": ""})

        # 第 2 步：参数选择
        reply = _ask_knobs(bridge, session_id, user_text)
        steps.append({"step": "knobs", "reply": reply.parsed, "reply_raw": reply.raw, "ok": reply.ok})
        if not reply.ok:
            steps.append({"step": "abort", "note": f"agent 回复不合法，终止: {reply.error}"})
            return steps

        # 第 3 步：渲染第一版
        knobs = dict(DEFAULT_KNOBS)
        knobs.update(reply.knobs)
        report = render_grayscale(src_image, out_dir, knobs=knobs, physical_mm=physical_mm)
        steps.append({"step": "render", "knobs": knobs, "report": report})

        # 第 4~N 步：迭代（v1 由外部调用方喂反馈，这里留接口）
        # 注：真正"人看 → 反馈 → 再调"的循环在页面/调用方驱动，
        # 因为要等人说话。run_order 只出第一版，见 main.py 的循环。

    return steps


if __name__ == "__main__":
    # 命令行自检：python controller.py
    demo = ROOT.parent / "测试原图" / "test.jpg"
    steps = run_order(demo, "做成玻璃画，背景白一点", physical_mm=100)
    for s in steps:
        print("== step:", s.get("step"))
        if s.get("reply"):
            print(json.dumps(s["reply"], ensure_ascii=False))
        if s.get("report"):
            print(json.dumps({k: s["report"][k] for k in ("output", "pixels", "knobs_applied")}, ensure_ascii=False))
        if s.get("note"):
            print("note:", s["note"])
