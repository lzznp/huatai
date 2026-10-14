r"""真机实验 2：**输出预算**该给多少？（`max_tokens` 与 `reasoning_effort`）

★ **会联网、会花钱**。授权：用户 2026-10-13「只管测试，各种想法都试试，不怕花钱」。

背景（实测，不是猜）：
  `tests\exp_position.py` 跑了 3 组，其中 **2 组在"带位置的局部调整"那一轮撞上
  `finish_reason=max-tokens`** ⇒ 整轮作废（回 `{}`），一次烧掉约 1.2 万 token、等 50 秒。
  内核 `agent_bridge.py` 原先把 `max_tokens` **写死 8192**，且**没有**把 SDK 的
  `reasoning_effort` 接出来。这个脚本就是量"把这两个旋钮交出来之后，代价与收益各是多少"。

口径：
  · 每一组 = 一张**全新的单**（真图副本，先出一版基图），跑固定 3 轮，会话连续（= 真机使用时的样子）
  · 只看**关键那两句**（带位置 + 与数据对不上），因为它们是唯一会爆掉的
  · 报：是否被截断 / 是否给出了局部调整 / totalTokens / 耗时

用法：
  python tests\exp_effort.py                    # 默认 2 组，用当前默认（8192，不设 effort）
  python tests\exp_effort.py 2 minimal          # 2 组，reasoning_effort=minimal
  python tests\exp_effort.py 2 minimal 16384    # 再加输出预算
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kernel"))

TMP = ROOT / ".tmp-tests" / "exp-effort"
if TMP.exists():
    shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)
os.environ["HUATAI_PROJECTS"] = str(TMP)

REAL = Path(r"D:\画台\projects\美女玻璃画\order-20261012-165706\src_one.jpeg")

from server import brain as B  # noqa: E402
from server import intent as INT  # noqa: E402
from server import render as R  # noqa: E402
from server import store as ST  # noqa: E402


def main() -> int:
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    effort = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None
    max_tok = int(sys.argv[3]) if len(sys.argv) > 3 else None
    scenario = sys.argv[4] if len(sys.argv) > 4 else "A"

    print("=== 真机实验 2：输出预算该给多少 ===")
    print(f"隔离数据根 = {TMP}")
    print(f"这一轮配置：reasoning_effort={effort!r}　max_tokens={max_tok or '(默认)'}　场景={scenario}")
    brain = B.Brain(reasoning_effort=effort, max_tokens=max_tok)
    print(f"Brain 实际配置：max_tokens={brain.max_tokens} reasoning_effort={brain.reasoning_effort!r}")
    print(f"料 = {REAL.name} 的副本")
    src = TMP / "exp_effort_src.jpg"
    shutil.copy2(REAL, src)

    rows = []
    for t in range(1, trials + 1):
        proj = f"预算实验{t}"
        ST.create_project(proj)
        oid = ST.create_order(proj, str(src))["order_id"]
        R.render_order(proj, oid, knobs={"素描感强度": 0.7})
        base = ST.get_order(proj, oid)["last_report"]["zones"]
        mean = [z["mean"] for z in base]
        lightest = mean.index(max(mean))
        print(f"\n########## 第 {t} 组｜单={oid}｜最亮格={lightest} ##########")

        # 场景 A = 用户用"左边"这种**方向词**（模糊，指着的地方可能和数据不符）
        # 场景 B = 用户**明说格号**（指向的方向与数据一致）⇒ 用它排掉"是词的问题还是 effort 的问题"
        if scenario == "B":
            turns = [
                ("确认工艺", "你把这张图做成玻璃画吧"),
                ("明说格号（应落格）", "把第 0 格和第 3 格提亮一点，左边一列看着闷"),
                ("明说格号2（应落格）", "第 5 格再压暗一点吧"),
            ]
        elif scenario == "C":
            # 对照：**同样明说格号**，但 effort 换回默认（不设）⇒ 用来分清
            # "是 effort 治好的" 还是 "是'明说格号'这句措辞治好的"
            turns = [
                ("确认工艺", "你把这张图做成玻璃画吧"),
                ("明说格号（应落格）", "把第 0 格和第 3 格提亮一点，左边一列看着闷"),
                ("明说格号2（应落格）", "第 5 格再压暗一点吧"),
            ]
        else:
            turns = [
                ("确认工艺", "你把这张图做成玻璃画吧"),
                ("带位置（关键）", "左边看着有点闷，弄亮一点"),
                ("与数据对不上（关键）", f"第 {lightest} 格那块太暗了，给我提亮一点"),
            ]
        for tag, text in turns:
            out = INT.round_(proj, oid, text, brain=brain)
            r = out.get("reply") or {}
            p = r.get("parsed") or {}
            u = r.get("usage") or {}
            fr = r.get("finish_reason")
            loc = p.get("local")
            n_zone = len([x for x in (loc or []) if isinstance(x, dict) and x.get("zone") is not None])
            ok = (fr != "max-tokens") and bool(out.get("合法"))
            rows.append({"tag": tag, "fr": fr, "tok": int(u.get("totalTokens") or 0),
                         "ms": int(r.get("elapsed_ms") or 0), "zone": n_zone,
                         "合法": bool(out.get("合法"))})
            print(f"  {tag:20s} 结束={fr!s:12s} 合法={bool(out.get('合法'))!s:5s} "
                  f"局部格数={n_zone} token={u.get('totalTokens')} 耗时={r.get('elapsed_ms')}ms")
            print(f"      message = {(p.get('message') or '')[:90]}")

    key = [x for x in rows if ("关键" in x["tag"] or "格号" in x["tag"])]
    print("\n========== 汇总 ==========")
    print(f"关键轮（带位置 / 与数据对不上）共 {len(key)} 次：")
    bad = [x for x in key if x["fr"] == "max-tokens" or not x["合法"]]
    print(f"  截断或作废 = {len(bad)}/{len(key)}")
    print(f"  给出了局部格 = {len([x for x in key if x['zone'] > 0])}/{len(key)}")
    if key:
        toks = sorted(x["tok"] for x in key)
        mss = sorted(x["ms"] for x in key)
        print(f"  token：中位 {toks[len(toks)//2]}　最大 {toks[-1]}　（全部 {toks}）")
        print(f"  耗时：中位 {mss[len(mss)//2]}ms　最大 {mss[-1]}ms")
    print(f"  这次总 token = {sum(x['tok'] for x in rows)}（{len(rows)} 次调用）")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
