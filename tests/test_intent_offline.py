r"""画台 · 猜意图的**离线**判据（不联网、不花钱）

跑真模型的是 `tests\smoke_intent.py`；这一份只管纯逻辑。
用法：  python tests\test_intent_offline.py

判据：
 1 能力清单渲染：能做的 / 做不到的 / 能读的料 / 读不了的料 / 诚实边界 都在
 2 ★ 渲染**同源**：改一处 declaration（能力钩子）⇒ 渲染出来的文本跟着变
 3 要点卡里带着"这一单的现状"（工程 / 单号 / 料名 / 用户的话）
 4 ★ 上下文**封顶**：只带最近 N 轮，每轮截断
 5 用户没说话时，要点卡要**显式写出**"还没说话"（不是留空让人猜）
 6 校验器：action 不认识 / 工艺不存在 / action=ask 却没 question ⇒ 一律拒
 7 校验器：允许它写中文工艺名，并归一成 id
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kernel"))

from server import capabilities as CAP  # noqa: E402
from server import intent as INT  # noqa: E402

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
    # 1 渲染内容齐不齐
    txt = CAP.render_for_prompt()
    for needle in ("玻璃画", "你明确做不到的", "三维模型", "你能读的料", "图片",
                   "你读不了的料", "PDF", "你能产出的", "诚实边界", "完美成品"):
        eq(needle in txt, True, f"1.x 渲染里有「{needle}」")
    eq("剪纸 · 镂空切割" in txt, True, "1.y 做不到的工艺也在（镂空切割）")

    # 2 ★ 同源：改一处清单，渲染跟着变
    os.environ["HUATAI_CAP_SWAP"] = "paper_cut:1"
    txt2 = CAP.render_for_prompt()
    del os.environ["HUATAI_CAP_SWAP"]
    before_cannot = "剪纸 · 镂空切割" in txt.split("【你明确做不到的】")[1].split("【你能读的料】")[0]
    after_cannot = "剪纸 · 镂空切割" in txt2.split("【你明确做不到的】")[1].split("【你能读的料】")[0]
    eq(before_cannot, True, "2.1 改之前：镂空切割在「做不到」里")
    eq(after_cannot, False, "2.2 ★ 改之后：它从「做不到」里消失了（渲染与清单同源）")
    eq("剪纸 · 镂空切割" in txt2.split("【你能做的工艺】")[1].split("【你明确做不到的】")[0], True,
       "2.3 改之后：它出现在「能做的」里")

    # 3 要点卡带现状
    order = {"order_id": "order-1", "src_name": "touxiang.png", "src_path": "X:\\src_touxiang.png"}
    p = INT.build_prompt(project="洋洋玻璃画", order=order, src_path=order["src_path"],
                         user_text="", entries=[])
    for needle in ("洋洋玻璃画", "order-1", "touxiang.png", "还没说话"):
        eq(needle in p, True, f"3.x 要点卡里有「{needle}」")

    # 5 用户没说话要显式写出
    eq("（用户还没说话，只是把料给了你）" in p, True, "5.1 ★ 没说话时显式写明（不留空）")
    p2 = INT.build_prompt(project="P", order=order, src_path=order["src_path"],
                          user_text="我想做个模型", entries=[])
    eq("我想做个模型" in p2, True, "5.2 用户的话原样进要点卡")

    # 4 上下文封顶
    entries = [{"kind": "user", "text": f"第{i}句" + "长" * 500} for i in range(20)]
    ctx = INT.recent_context(entries)
    eq(ctx.count("\n") + 1, INT.RECENT_ROUNDS, "4.1 ★ 只带最近 N 轮")
    eq("第19句" in ctx, True, "4.2 带的是**最近**的（第 19 句在）")
    eq("第0句" in ctx, False, "4.3 最早的没带（第 0 句不在）")
    eq(max(len(line) for line in ctx.splitlines()) <= INT.RECENT_WIDTH + 20, True, "4.4 ★ 每轮被截断")
    eq(ctx.count("…"), INT.RECENT_ROUNDS, "4.5 被截断的行有省略号（看得见被截了）")

    # 6/7 校验器
    decl = CAP.declaration()
    eq(INT.validate_intent({"action": "ask", "question": "是吗？"}, decl)[0], True, "6.1 合法 ask 通过")
    eq(INT.validate_intent({"action": "随便"}, decl)[0], False, "6.2 action 不认识 ⇒ 拒")
    eq(INT.validate_intent({"action": "ask"}, decl)[0], False, "6.3 ★ ask 却没 question ⇒ 拒")
    bad = INT.validate_intent({"action": "plan", "craft": "papercut"}, decl)
    eq(bad[0], False, "6.4 ★ 工艺不在清单里 ⇒ 拒（不许发明工艺）")
    eq("不在能力清单" in bad[1], True, "6.5 拒绝理由说得明白")
    chn = {"action": "plan", "craft": "玻璃画"}
    eq(INT.validate_intent(chn, decl)[0], True, "7.1 写中文工艺名也能过")
    eq(chn["craft"], "glass", "7.2 ★ 中文名被归一成 id")

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
