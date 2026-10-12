"""agent_bridge.py —— DSH SDK 封装：拉起 headless 运行时，让判断员干活。

职责边界：
- 本模块只负责「和 agent 说话、收结构化回复」，不做任何业务判断。
- 业务判断在 controller.py（定流程），图像执行在 image_lib（定算法）。
- 运行时 agent 按《规则手册.md》只输出 JSON；本模块负责把回复里的
  JSON 抠出来并校验。

依赖：
- 环境变量/`.env`：DEEPSEEK_API_KEY（必填）
- 系统已装 deepseek-harness-sdk（conda env: bestpic）
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from deepseek_harness import DeepSeekHarness

from knobs import validate_knobs, validate_local_ops

# 项目根 = 本文件所在目录（bestpic/）
ROOT = Path(__file__).resolve().parent


@dataclass
class AgentReply:
    """agent 一次回复的结构化结果。"""

    ok: bool                       # 解析+校验是否通过
    raw: str                       # agent 原始回复全文
    parsed: dict = field(default_factory=dict)   # 解析出的 JSON
    error: str = ""                # 失败原因（ok=False 时有用）
    activity: list[str] = field(default_factory=list)  # agent 处理过程摘要（给人看）
    # 便捷访问
    @property
    def action(self) -> str:
        return str(self.parsed.get("action", ""))

    @property
    def knobs(self) -> dict:
        return dict(self.parsed.get("knobs", {}) or {})

    @property
    def message(self) -> str:
        return str(self.parsed.get("message", ""))

    @property
    def question(self) -> str:
        return str(self.parsed.get("question", ""))

    @property
    def local_ops(self) -> list:
        """局部调整（③ 九宫格）：agent 回的 local 字段，取不到就是空列表。"""
        return list(self.parsed.get("local", []) or [])


def summarize_events(events: list[dict], *, max_lines: int = 30) -> list[str]:
    """把 SDK 返回的 events 压成人类可读的过程摘要。

    只挑关键事件：agent 说过的中间话 / 工具动作 / 回合结束。
    太长的文本截断，避免刷屏。噪音事件（收据等）直接跳过。
    """
    lines: list[str] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        etype = str(ev.get("type", ""))
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        if etype == "assistant/message":
            msg = data.get("message")
            content = (msg.get("content") if isinstance(msg, dict) else data.get("content"))
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = str(block.get("text") or "").strip()
                        if text:
                            lines.append("[agent] " + text[:200])
        # 工具动作（本框架 v1 禁止 agent 用工具；若出现也如实展示）
        elif "tool" in etype.lower() or "command" in etype.lower():
            name = data.get("name") or data.get("tool") or etype
            lines.append(f"[工具] {name}: {str(data)[:160]}")
        elif etype in ("turn/start", "turn/end", "agent/status"):
            state = data.get("status") or data.get("reason") or ""
            if isinstance(state, dict):
                state = state.get("kind", "")
            if state:
                lines.append(f"[状态] {etype}: {state}")
        if len(lines) >= max_lines:
            lines.append("…（过程过长，已截断）")
            break
    return lines


def _load_key() -> str:
    """读 .env 里的 DEEPSEEK_API_KEY。"""
    load_dotenv(ROOT / ".env")
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key or key == "sk-xxxx":
        raise RuntimeError("没找到 DEEPSEEK_API_KEY：请把 bestpic/.env.example 复制成 .env 并填入真实 Key")
    return key


def _extract_json(text: str) -> dict:
    """从 agent 回复里抠第一个 JSON 对象。

    容忍 agent 用 ```json 代码块包着、或前后有说明文字。
    抠不到就抛 ValueError。
    """
    # 先试代码块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        return json.loads(m.group(1))
    # 再试裸 JSON 对象（从第一个 { 到最后一个 }）
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("回复里找不到 JSON 对象")


class AgentBridge:
    """和「判断员」agent 对话的桥。

    用法：
        bridge = AgentBridge()
        reply = bridge.ask(规则手册 + 当前问题, session_id="订单-001")
        bridge.close()
    """

    def __init__(
        self,
        *,
        model: str = "deepseek-v4-flash",
        profile: str = "sdk-minimal",
        dsh_home: str | Path | None = None,
        workspace: str | Path | None = None,
    ) -> None:
        self._harness: DeepSeekHarness | None = None
        self._api_key = _load_key()
        self._model = model
        self._profile = profile
        # dsh_home：隔离的运行时家目录，首次自动生成 profile，别污染 ~/.dsh
        self._dsh_home = Path(dsh_home) if dsh_home else ROOT / ".dsh_home"
        # workspace：给 agent 看到的"现场"——放 assets，图片在这里交接
        self._workspace = Path(workspace) if workspace else ROOT / "assets"

    def _ensure_harness(self) -> DeepSeekHarness:
        if self._harness is None:
            self._harness = DeepSeekHarness(
                provider="deepseek-official",
                model=self._model,
                # 8192：输出预算大一点，防 agent 长上下文下 JSON 没写完就被截断
                # （曾出现 turn/end: max-tokens → 回复里找不到 JSON）
                max_tokens=8192,
                api_key=self._api_key,
                cwd=str(self._workspace.resolve()),
                dsh_home=str(self._dsh_home.resolve()),
                profile=self._profile,
            )
        return self._harness

    def ask(self, prompt: str, *, session_id: str | None = None) -> AgentReply:
        """发一句话给 agent，返回结构化回复。

        注意：如果 prompt 里让 agent 看图（把预览路径给它），它会用
        多模态看；但 v1 先走纯文字（JSON 判断），看图迭代放 v2。
        """
        harness = self._ensure_harness()
        result = harness.run(prompt, session_id=session_id)
        raw = result.final_response or ""
        reply = AgentReply(ok=False, raw=raw, activity=summarize_events(result.events))
        try:
            reply.parsed = _extract_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            reply.error = f"JSON 解析失败: {e}"
            return reply
        # 若带 knobs，校验合法性（铁律：不许发明旋钮、不许超范围）
        if reply.parsed.get("knobs"):
            ok, err = validate_knobs(reply.parsed["knobs"])
            if not ok:
                reply.ok = False
                reply.error = err
                return reply
        # 若带 local（九宫格局部调整），同样校验（格子越界/未知动作/超范围一律拒）
        if "local" in reply.parsed:
            ok, err = validate_local_ops(reply.parsed.get("local"))
            if not ok:
                reply.ok = False
                reply.error = f"局部调整不合法：{err}"
                return reply
        reply.ok = True
        return reply

    def close(self) -> None:
        if self._harness is not None:
            self._harness.close()
            self._harness = None

    def __enter__(self) -> "AgentBridge":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


if __name__ == "__main__":
    # 冒烟测试：拉起运行时，问 agent 一句废话，验证 SDK 链路通不通。
    # 跑法：conda activate bestpic && python agent_bridge.py
    print("=== AgentBridge 冒烟测试 ===")
    with AgentBridge() as bridge:
        reply = bridge.ask(
            '你是一个测试助手。请只输出 JSON：{"action": "render", "knobs": {"整体明暗": 0.2}, '
            '"message": "冒烟测试通过"}。不要输出别的。',
            session_id="smoke-test-001",
        )
        print("ok =", reply.ok)
        print("action =", reply.action)
        print("message =", reply.message)
        if reply.error:
            print("error =", reply.error)
            print("raw =", reply.raw[:500])
