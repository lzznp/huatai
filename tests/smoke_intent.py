r"""画台 · 猜意图真机冒烟（第 4b 步）

⚠️ **会联网、会花钱**（三轮小请求），不在离线测试里：
    python tests\smoke_intent.py

判据（第 3 条是硬骨头）：
 0 备好一单（真图投料）
 1 ★ 用户没说话 ⇒ 它**主动问**（action=ask 且有 question），不是直接开干
 2 用户说"做成玻璃画" ⇒ 它**不说做不到**（这是能做的），并往下走
 3 ★★ **同一句话**、只把能力清单里"玻璃画"翻成做不到 ⇒ 它**改口说做不到**
    —— 这一条才真正证明它是在**读清单**，不是在背台词
 4 全程落账：用户的话 / 它的话 / 这一轮的用量与结束原因
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kernel"))

TMP = ROOT / ".tmp-tests" / "intent-projects"
if TMP.exists():
    shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)
os.environ["HUATAI_PROJECTS"] = str(TMP)

from PIL import Image  # noqa: E402

from server import brain as B  # noqa: E402
from server import intent as INT  # noqa: E402
from server import store as ST  # noqa: E402

PASS = 0
FAIL: list[str] = []

CANNOT_WORDS = ("做不到", "不能做", "没法", "无法", "不支持", "不具备", "帮不了", "做不了")


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


def says_cannot(parsed: dict) -> tuple[bool, str]:
    text = " ".join(str(parsed.get(k) or "") for k in ("question", "message", "reason"))
    hit = [w for w in CANNOT_WORDS if w in text]
    return bool(hit), (hit[0] if hit else "")


def show(tag: str, out: dict) -> dict:
    r = out["reply"]
    parsed = r.get("parsed") or {}
    u = r.get("usage") or {}
    print(f"\n--- {tag} ---")
    print(f"  它说的（question）：{parsed.get('question') or '（空）'}")
    print(f"  它说的（message） ：{parsed.get('message') or '（空）'}")
    print(f"  它的理由（reason）：{parsed.get('reason') or '（空）'}")
    print(f"  action={parsed.get('action')}  craft={parsed.get('craft')!r}  "
          f"合法={out.get('合法')}  不合法原因={out.get('不合法原因') or '（无）'}")
    print(f"  账：finish_reason={r.get('finish_reason')}  truncated={r.get('truncated')}  "
          f"elapsed={r.get('elapsed_ms')}ms  total={u.get('totalTokens')} token  session={r.get('session_id')}")
    return parsed


def main() -> int:
    print("=== 画台 · 猜意图真机冒烟（会花钱，三轮）===")
    print(f"隔离数据根 = {TMP}")

    img = ROOT / ".tmp-tests" / "yangyang.png"
    Image.new("L", (32, 32), 180).save(img)

    ST.create_project("冒烟工程")
    info = ST.create_order("冒烟工程", str(img))
    oid = info["order_id"]
    ok(f"0.1 备好一单：{oid}（料 src_yangyang.png）")

    brain = B.Brain()

    # 1 用户没说话 ⇒ 主动问
    out1 = INT.round_("冒烟工程", oid, "", brain=brain)
    p1 = show("第 1 轮：用户什么都没说", out1)
    check(out1.get("合法"), "1.1 它的回答合法（过了校验器）", out1.get("不合法原因", ""))
    check(str(p1.get("action")) == "ask", "1.2 ★ action=ask", f"action={p1.get('action')!r}")
    check(bool(str(p1.get("question") or "").strip()), "1.3 ★ 主动问了话（有 question）")
    check(not says_cannot(p1)[0], "1.4 这一轮不该说做不到", f"命中「{says_cannot(p1)[1]}」")

    # 2 说"做成玻璃画" ⇒ 不该说做不到
    out2 = INT.round_("冒烟工程", oid, "你把这张图做成玻璃画吧", brain=brain)
    p2 = show("第 2 轮：用户说做成玻璃画（清单里能做）", out2)
    check(out2.get("合法"), "2.1 回答合法", out2.get("不合法原因", ""))
    hit2 = says_cannot(p2)
    check(not hit2[0], "2.2 ★ 没说做不到（玻璃画是能做的）", f"命中「{hit2[1]}」")

    # 3 ★★ 同一句话，只把清单翻一下
    os.environ["HUATAI_CAP_SWAP"] = "glass:0"
    try:
        out3 = INT.round_("冒烟工程", oid, "你把这张图做成玻璃画吧", brain=brain)
    finally:
        del os.environ["HUATAI_CAP_SWAP"]
    p3 = show("第 3 轮：★ 同一句话，但清单里「玻璃画」被翻成做不到", out3)
    check(out3.get("合法"), "3.1 回答合法", out3.get("不合法原因", ""))
    hit3 = says_cannot(p3)
    check(hit3[0], "3.2 ★★ 它改口说做不到（同一句话、只改了清单）", f"没命中任何'做不到'类说法；回答={p3}")

    # 4 落账
    tr = ST.read_transcript("冒烟工程", oid)
    kinds = [e["kind"] for e in tr["entries"]]
    check(tr["坏行"] == 0, "4.1 流水没有坏行")
    check(kinds.count("assistant") >= 3, "4.2 三轮它的话都落了账", f"kinds={kinds}")
    check(kinds.count("user") == 2, "4.3 用户说的两句都落了账", f"kinds={kinds}")
    first_assistant = next(e for e in tr["entries"] if e["kind"] == "assistant")
    check(bool((first_assistant.get("data") or {}).get("usage")), "4.4 ★ 流水里带着当轮用量（可核账）")
    check(bool((first_assistant.get("data") or {}).get("finish_reason")), "4.5 ★ 流水里带着结束原因")

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
