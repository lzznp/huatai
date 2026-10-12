r"""大脑接线 · 第 4a 步（**只读往返**）

目的：先把"能不能跟大模型说上话"这件不确定的事问清楚，**不接任何业务**。
判据：① 运行时真起来 ② 拿回的是**合法 JSON**（不是散文）③ JSON 抠不出来时**明确报错**
④ 用量 / 耗时 / 结束原因都如实带回来（含**截断**）。

铁律（跟着项目走，不放松）：
- 运行态 agent **只出 JSON**；它不写代码、不改文件（甲方案：界面转述它的话）
- 密钥从**项目根** `D:\画台\.env` 读；`dsh_home` 与 `cwd` 都显式给，**不碰 `~/.dsh`**
- `cwd` 收窄到一个**空目录**（agent 少看见点东西，就少一点乱来的机会）

依赖：conda env `bestpic` 里的 `deepseek-harness-sdk` + `python-dotenv`
"""
from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNEL = ROOT / "kernel"
if str(KERNEL) not in sys.path:
    sys.path.insert(0, str(KERNEL))

from dotenv import load_dotenv  # noqa: E402

# ★ 密钥从项目根读。内核自带的 agent_bridge 只在 kernel\.env 找，
#   我们**不把密钥复制到第二处**（一份秘密只留一个地方）。
load_dotenv(ROOT / ".env")

from agent_bridge import AgentBridge, AgentReply  # noqa: E402

DEFAULT_MODEL = os.environ.get("HUATAI_MODEL", "deepseek-v4-flash")
DEFAULT_PROFILE = os.environ.get("HUATAI_PROFILE", "sdk-minimal")

# 4a 只读探测用的最小问题：只要求一个 JSON，别的都不要。
PROBE_PROMPT = (
    "你是一个测试应答器。请**只输出一个 JSON 对象**，不要解释、不要用代码块、不要加任何前后文字：\n"
    '{"action": "ask", "question": "往返测试通过"}'
)


def reply_to_dict(reply: AgentReply, *, session_id: str, model: str, profile: str,
                  dsh_home: str, cwd: str) -> dict:
    """把一次回复整理成给界面/账看的字典（**纯函数**，可离线测）。

    数字一律带口径（见 agent_bridge.collect_usage 的说明）。
    """
    return {
        "ok": bool(reply.ok),
        "action": reply.action,
        "question": reply.question,
        "message": reply.message,
        "parsed": reply.parsed,
        "raw": reply.raw,
        "error": reply.error,
        "activity": reply.activity,
        # ---- 观测（FIX-2：这几项以前是缺的，缺了就只能猜）----
        "truncated": bool(reply.truncated),
        "finish_reason": reply.finish_reason,
        "usage": reply.usage,
        "elapsed_ms": reply.elapsed_ms,
        # ---- 这一轮是谁、在哪、什么配置 ----
        "session_id": session_id,
        "model": model,
        "profile": profile,
        "dsh_home": dsh_home,
        "cwd": cwd,
    }


class Brain:
    """和运行态 agent 说话的桥。**懒启动**（第一次用才拉运行时）+ 串行（一次一回合）。"""

    def __init__(self, *, model: str = DEFAULT_MODEL, profile: str = DEFAULT_PROFILE,
                 dsh_home: str | Path | None = None, cwd: str | Path | None = None) -> None:
        self.model = model
        self.profile = profile
        self.dsh_home = Path(dsh_home) if dsh_home else ROOT / ".dsh_home"
        # cwd 收窄：一个空目录。agent 看得见的东西越少，越不容易跑偏。
        self.cwd = Path(cwd) if cwd else ROOT / ".agent-cwd"
        self._bridge: AgentBridge | None = None
        self._lock = threading.Lock()          # 一次只跑一个回合（SDK 不支持并发 run）
        self.started_at = ""
        self.last_error = ""

    # ---------------------------------------------------------------- 生命周期
    def _ensure(self) -> AgentBridge:
        if self._bridge is None:
            self.dsh_home.mkdir(parents=True, exist_ok=True)
            self.cwd.mkdir(parents=True, exist_ok=True)
            self._bridge = AgentBridge(
                model=self.model,
                profile=self.profile,
                dsh_home=self.dsh_home,
                workspace=self.cwd,
            )
            self.started_at = datetime.now().isoformat(timespec="seconds")
        return self._bridge

    def close(self) -> None:
        with self._lock:
            if self._bridge is not None:
                try:
                    self._bridge.close()
                finally:
                    self._bridge = None

    def status(self) -> dict:
        return {
            "运行时已起": self._bridge is not None,
            "model": self.model,
            "profile": self.profile,
            "dsh_home": str(self.dsh_home),
            "cwd": str(self.cwd),
            "密钥就位": bool(os.environ.get("DEEPSEEK_API_KEY", "").strip()),
            "起于": self.started_at,
            "上次错误": self.last_error,
        }

    # ---------------------------------------------------------------- 一次问答
    def _new_session_id(self, tag: str = "probe") -> str:
        # 每轮**新** id：同一个 id 换进程复用会被运行时报 already exists（实测过）
        return f"{tag}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"

    def ask(self, prompt: str, *, tag: str = "probe", session_id: str | None = None) -> dict:
        """问一句、拿回结构化结果。**耗时可观（首次拉起运行时 10~60s）**，调用方要给足超时。"""
        sid = session_id or self._new_session_id(tag)
        with self._lock:
            try:
                bridge = self._ensure()
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"
                return {
                    "ok": False, "error": "拉不起大脑（运行时）", "detail": self.last_error,
                    "session_id": sid, "model": self.model, "profile": self.profile,
                    "dsh_home": str(self.dsh_home), "cwd": str(self.cwd),
                }
            try:
                reply = bridge.ask(prompt, session_id=sid)
            except Exception as e:  # noqa: BLE001 —— 绝不静默
                self.last_error = f"{type(e).__name__}: {e}"
                return {
                    "ok": False, "error": "问大脑的时候出错了", "detail": self.last_error,
                    "session_id": sid, "model": self.model, "profile": self.profile,
                    "dsh_home": str(self.dsh_home), "cwd": str(self.cwd),
                }
        return reply_to_dict(
            reply, session_id=sid, model=self.model, profile=self.profile,
            dsh_home=str(self.dsh_home), cwd=str(self.cwd),
        )

    def probe(self, prompt: str | None = None) -> dict:
        """4a：只读往返。默认问那句最小的问题。"""
        return self.ask(prompt or PROBE_PROMPT, tag="probe")


if __name__ == "__main__":  # 手工冒烟：python server\brain.py
    import json
    t0 = time.monotonic()
    out = Brain().probe()
    out["总耗时_ms"] = int((time.monotonic() - t0) * 1000)
    print(json.dumps(out, ensure_ascii=False, indent=2))
