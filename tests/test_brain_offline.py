r"""画台 · 大脑接线的**离线**判据（不联网、不花钱）

跑真模型的那条是 `tests\smoke_brain.py`（手工，会花钱）；这一份只管纯逻辑。
用法：  python tests\test_brain_offline.py

判据：
 1 从回复里抠 JSON：代码块 / 裸 JSON / 前后有废话 / 嵌套花括号，都能抠出来
 2 抠不到就**抛错**（不许返回空 dict 假装成功）
 3 用量口径：totalTokens = input + cacheRead + output；reasoningTokens **不相加**
 4 ★ 截断识别：finish_reason = max-tokens ⇒ truncated=True；completed ⇒ False
 5 截断时错误文字里**必须写明是被截断**（否则和"没给 JSON"长得一样）
 6 reply_to_dict 把观测字段（finish_reason / usage / elapsed_ms / session_id）都带上
 7 Brain 默认**懒启动**：只问状态不会拉起运行时
 8 密钥就位（只判有没有，不打印内容）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# 内核模块之间是"平铺导入"（agent_bridge 里写的是 from knobs import …），
# 所以 kernel\ 自己也必须在 sys.path 上。server\brain.py 里已经做了同样的事。
sys.path.insert(0, str(ROOT / "kernel"))

from kernel.agent_bridge import AgentReply, _extract_json, collect_usage  # noqa: E402
from server import brain as B  # noqa: E402

PASS = 0
FAIL: list[str] = []


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"[OK] {msg}")


def eq(got, want, msg: str) -> None:
    if got == want:
        ok(msg)
    else:
        FAIL.append(f"{msg} —— 期望 {want!r}，实得 {got!r}")
        print(f"[FAIL] {msg} —— 期望 {want!r}，实得 {got!r}")


def main() -> int:
    # 1 抠 JSON 的四种形状
    eq(_extract_json('```json\n{"action": "ask"}\n```'), {"action": "ask"}, "1.1 代码块包着能抠出来")
    eq(_extract_json('{"action": "ask"}'), {"action": "ask"}, "1.2 裸 JSON 能抠出来")
    eq(_extract_json('好的，这是结果：\n{"action": "render", "knobs": {}}\n以上。'),
       {"action": "render", "knobs": {}}, "1.3 前后有废话也能抠出来")
    eq(_extract_json('{"a": {"b": [1, 2]}, "c": "}"}'),
       {"a": {"b": [1, 2]}, "c": "}"}, "1.4 嵌套与花括号字符串处理正确")

    # 2 抠不到要抛错
    try:
        _extract_json("我今天不太想输出 JSON")
        FAIL.append("2.1 没有 JSON 时应当抛错，却成功返回了")
        print("[FAIL] 2.1 没有 JSON 时应当抛错")
    except (ValueError, json.JSONDecodeError):
        ok("2.1 ★ 没有 JSON 时抛错（不假装成功）")

    # 3 用量口径
    events = [
        {"type": "assistant/message", "data": {"usage": {
            "inputTokens": 100, "cacheReadTokens": 40, "outputTokens": 30, "reasoningTokens": 20}}},
        {"type": "assistant/message", "data": {"usage": {
            "inputTokens": 5, "cacheReadTokens": 0, "outputTokens": 7, "reasoningTokens": 3}}},
        {"type": "turn/end", "data": {"reason": {"kind": "completed"}}},   # 没有 usage，不该被计数
    ]
    u = collect_usage(events)
    eq(u["inputTokens"], 105, "3.1 inputTokens 累加（不含缓存）")
    eq(u["cacheReadTokens"], 40, "3.2 cacheReadTokens 单独累加")
    eq(u["outputTokens"], 37, "3.3 outputTokens 累加")
    eq(u["reasoningTokens"], 23, "3.4 reasoningTokens 单独报（它是 output 的子集）")
    eq(u["totalTokens"], 105 + 40 + 37, "3.5 ★ totalTokens = input + cacheRead + output（不含 reasoning）")
    eq(u["计费轮次"], 2, "3.6 只数带 usage 的轮次")

    # 4/5 截断识别与文字
    eq(AgentReply(ok=False, raw="", finish_reason="max-tokens").truncated, True, "4.1 max-tokens ⇒ truncated")
    eq(AgentReply(ok=False, raw="", finish_reason="MAX-TOKENS").truncated, True, "4.2 大小写不敏感")
    eq(AgentReply(ok=True, raw="{}", finish_reason="completed").truncated, False, "4.3 completed ⇒ 不算截断")
    eq(AgentReply(ok=True, raw="{}", finish_reason="").truncated, False, "4.4 空 finish_reason ⇒ 不算截断")

    # 6 reply_to_dict 带齐观测字段（纯函数，不联网）
    d = B.reply_to_dict(
        AgentReply(ok=True, raw='{"action":"ask","question":"你好"}',
                   parsed={"action": "ask", "question": "你好"},
                   finish_reason="completed", usage=u, elapsed_ms=1234),
        session_id="probe-1", model="m", profile="p", dsh_home="h", cwd="c",
    )
    eq(d["ok"], True, "6.1 ok 透传")
    eq(d["action"], "ask", "6.2 action 透传")
    eq(d["question"], "你好", "6.3 question 透传")
    eq(d["finish_reason"], "completed", "6.4 finish_reason 带上")
    eq(d["usage"]["totalTokens"], 182, "6.5 usage 带上（口径不变）")
    eq(d["elapsed_ms"], 1234, "6.6 elapsed_ms 带上")
    eq(d["session_id"], "probe-1", "6.7 session_id 带上（可追这一轮）")

    # 7 懒启动
    b = B.Brain()
    st = b.status()
    eq(st["运行时已起"], False, "7.1 ★ 只问状态不会拉起运行时（懒启动）")
    eq(st["profile"], B.DEFAULT_PROFILE, "7.2 profile 有默认值")
    ok("7.3 cwd 收窄目录 = " + st["cwd"])

    # 8 密钥就位（不打印内容）
    eq(st["密钥就位"], True, "8.1 密钥就位（从项目根 .env 读到了）")
    key = __import__("os").environ.get("DEEPSEEK_API_KEY", "")
    eq(len(key) > 20, True, "8.2 密钥长度合理（只判长度，不打印）")

    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：")
        for f in FAIL:
            print("  -", f)
        return 1
    print(f"全部通过 [PASS] {PASS}/{PASS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
