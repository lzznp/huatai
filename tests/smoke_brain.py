r"""画台 · 大脑真机冒烟（第 4a 步：只读往返）

⚠️ **这一份会联网、会花钱**（一次极小的请求），所以它**不在**离线测试里，
   要手工跑：  python tests\smoke_brain.py

它验的是四件离线验不了的事：
 1 运行时真的能起来（首次 10~60s）
 2 拿回的是**合法 JSON**（不是散文）
 3 结束原因与用量**如实回来**（含"有没有被截断"）
 4 这一轮是谁、在哪、什么配置，都能追（session_id / model / dsh_home / cwd）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import brain as B  # noqa: E402

PASS = 0
FAIL: list[str] = []


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"[OK] {msg}")


def check(cond: bool, msg: str, detail: str = "") -> None:
    if cond:
        ok(msg)
    else:
        FAIL.append(f"{msg} —— {detail}")
        print(f"[FAIL] {msg} —— {detail}")


def main() -> int:
    print("=== 画台 · 大脑真机冒烟（会花钱，一次极小请求）===")
    brain = B.Brain()
    st = brain.status()
    print(f"模型     = {st['model']}")
    print(f"profile  = {st['profile']}")
    print(f"dsh_home = {st['dsh_home']}")
    print(f"cwd      = {st['cwd']}")
    print(f"密钥就位 = {st['密钥就位']}")
    print("（首次会拉起运行时，可能要等十几秒…）")

    res = brain.probe()

    print("\n--- 这一轮的账 ---")
    print(f"ok            = {res.get('ok')}")
    print(f"finish_reason = {res.get('finish_reason')}")
    print(f"truncated     = {res.get('truncated')}")
    print(f"elapsed_ms    = {res.get('elapsed_ms')}")
    print(f"session_id    = {res.get('session_id')}")
    u = res.get("usage") or {}
    print(f"usage         = input {u.get('inputTokens')} / cacheRead {u.get('cacheReadTokens')} / "
          f"output {u.get('outputTokens')} / reasoning {u.get('reasoningTokens')} / total {u.get('totalTokens')}")
    print(f"raw           = {str(res.get('raw'))[:200]}")
    if res.get("error"):
        print(f"error         = {res.get('error')}")

    print("\n--- 判据 ---")
    if not res.get("ok"):
        check(False, "1 拿到合法 JSON 回复", f"error={res.get('error')} detail={res.get('detail')}")
        print("\n失败：链路没通。")
        return 1
    check(True, "1 运行时起来了、并回了话")
    check(isinstance(res.get("parsed"), dict) and bool(res["parsed"]),
          "2 ★ 拿回的是合法 JSON 对象（不是散文）", f"parsed={res.get('parsed')!r}")
    check(bool(res.get("finish_reason")), "3 ★ 结束原因如实回来", f"finish_reason={res.get('finish_reason')!r}")
    check(int(u.get("计费轮次") or 0) >= 1, "4 ★ 用量如实回来", f"usage={u!r}")
    check(int(u.get("totalTokens") or 0) ==
          int(u.get("inputTokens") or 0) + int(u.get("cacheReadTokens") or 0) + int(u.get("outputTokens") or 0),
          "5 用量口径自洽（total = input + cacheRead + output）")
    check(int(res.get("elapsed_ms") or 0) > 0, "6 这一轮花了多久有记录")
    check(bool(res.get("session_id")), "7 会话可追（session_id 在）")
    check(not res.get("truncated"), "8 这一轮没被截断（若被截断，判据 3/5 会照样成立，但要显式看见）",
          f"finish_reason={res.get('finish_reason')}")

    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：")
        for f in FAIL:
            print("  -", f)
        return 1
    print(f"真机冒烟通过 [PASS] {PASS}/{PASS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
