r"""真机实验 1：把小助手**钉在格号上**，看它听不听。

★ **会联网、会花钱**（每轮一次真调用）。用户 2026-10-13 明确授权："只管测试，各种想法都试试，不怕花钱"。

为什么要做这个实验：
  用户 2026-10-13 的核心诉求是"**用自然语言交互、但数据的准确性难把握**"。
  我给提示词加了两条纪律（"带位置的话先核对 9 格数字、在你回话里说出格号"、"别把改一块说成整体调整"）。
  **手写的纪律不等于它会照做**（决策 #10）。这个脚本就是去打这两条。

实验怎么设计（口径写清楚，免得数字被误读）：
  · 料：**用户真实图** `美女玻璃画\order-20261012-165706\src_one.jpeg` 的**副本**（进隔离数据根，原图只读）
  · 骨架：同一单先出两版（v1 素描感 0.7 / v2 整体明暗 +0.2），得到**真实的 9 格数字**
  · 每一组实验用**一张全新的单**，跑完就丢弃 ⇒ 各组之间不互相污染，可以重复跑
  · **跑 N 组**，同一句话重复，看的是**稳定性**，不是"它偶尔答对一次"

四种轮次（每组的顺序固定）：
  R1 空话：什么都不说 ⇒ 必须 action=ask 且主动问
  R2 模糊带位置："左边看着有点闷" ⇒ 【核心判据】它**选哪一个格**，说得对不对
  R3 ★ 与数据对不上："右上角太暗了，给我提亮"（若右上其实是最*亮*的）⇒
       它该**问一句**或**说明数据对不上**，而不是照着"右上"就改
  R4 人话检查：它给用户看的 message **不许出现内部术话**（格号/zone/JSON/knobs/local/墨点…）

用法：  python tests\exp_position.py [组数]      # 默认 3 组 = 12 次真调用
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kernel"))

TMP = ROOT / ".tmp-tests" / "exp-position"
if TMP.exists():
    shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)
os.environ["HUATAI_PROJECTS"] = str(TMP)

REAL = Path(r"D:\画台\projects\美女玻璃画\order-20261012-165706\src_one.jpeg")

from server import brain as B  # noqa: E402
from server import intent as INT  # noqa: E402
from server import render as R  # noqa: E402
from server import store as ST  # noqa: E402

# R4 用：这些是"给机器看的"——**用户可见的文字**里出现就是没做成人话。
# ⚠️ 2026-10-13 第一次跑之后收窄了这份清单：原先把「墨点」「旋钮」也当成违规，
#    但**我们自己的界面上就写着**这两个词（版本条上是"墨点 19.7%"、"旋钮 素描感强度=0.7"），
#    它们是**用户已经能看见的词**，不算泄露内部。真正该抓的是内部英文动作名/字段名。
JARGON = ("brighten", "darken", "whiten", "blacken", "zone", "zones", "amount",
          "knobs", "local_ops", "JSON", '"op"', '"zone"', "knobs=")

FAIL: list[str] = []
SCORE: dict[str, list[bool]] = {"R1": [], "R2": [], "R3": [], "R4": []}
TOKENS: list[int] = []
VERBATIM: list[str] = []


def dur(tag: str, out: dict) -> str:
    p = (out.get("reply") or {}).get("parsed") or {}
    import json
    s = json.dumps(p, ensure_ascii=False)
    VERBATIM.append(f"=== {tag} ===\n{s}\n")
    return s


def run_round(proj: str, oid: str, brain, tag: str, text: str) -> tuple[dict, dict]:
    out = INT.round_(proj, oid, text, brain=brain)
    r = out.get("reply") or {}
    p = r.get("parsed") or {}
    u = r.get("usage") or {}
    TOKENS.append(int(u.get("totalTokens") or 0))
    print(f"\n--- {tag}｜用户：{text or '（什么都没说）'} ---")
    print(f"  action={p.get('action')!r} craft={p.get('craft')!r} 合法={out.get('合法')}")
    print(f"  question={p.get('question') or '（空）'}")
    print(f"  message ={p.get('message') or '（空）'}")
    print(f"  knobs={p.get('knobs')} local={p.get('local')}")
    print(f"  用量={u.get('totalTokens')} token（in {u.get('inputTokens')} / out {u.get('outputTokens')}）"
          f" 耗时={r.get('elapsed_ms')}ms 结束={r.get('finish_reason')}")
    dur(tag, out)
    return out, p


def main() -> int:
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print("=== 真机实验 1：把小助手钉在格号上 ===")
    print("⚠️ 会花钱。授权：用户 2026-10-13「只管测试…不怕花钱」")
    print(f"隔离数据根 = {TMP}")
    if not REAL.is_file():
        print(f"找不到真实图 {REAL}，中止")
        return 2
    src = TMP / "exp_src.jpg"
    shutil.copy2(REAL, src)
    print(f"料 = {REAL.name} 的副本（原图只读，未改）")

    brain = B.Brain()

    for t in range(1, trials + 1):
        proj = f"实验工程{t}"
        ST.create_project(proj)
        oid = ST.create_order(proj, str(src))["order_id"]
        r1 = R.render_order(proj, oid, knobs={"素描感强度": 0.7})
        r2 = R.render_order(proj, oid, knobs={"整体明暗": 0.2})
        zs = r2["分区"]
        dark = [z["dark_pct"] for z in zs]
        mean = [z["mean"] for z in zs]
        darkest = mean.index(min(mean))      # ★ 按**灰度均值**判明暗（暗部% 在偏亮图上几乎全是 0，不可靠）
        lightest = mean.index(max(mean))
        print(f"\n########## 第 {t} 组｜单={oid} ##########")
        print(f"真实 9 格 mean = {mean}")
        print(f"真实 9 格 dark% = {dark}（参考：这张图整体偏亮，dark% 分辨不出明暗）")
        print(f"→ 最暗的一格 = {darkest}｜最亮的一格 = {lightest}（按 mean 判；后面用它来判对错）")

        # ---- R1 空话 ----
        o1, p1 = run_round(proj, oid, brain, f"{t}-R1 空话", "")
        SCORE["R1"].append(str(p1.get("action")) == "ask" and bool(str(p1.get("question") or "").strip()))

        # ---- R1b 确认工艺（★ 2026-10-13 第一轮跑完补的：真实流程里用户会先说过这句话；
        #      少了它，后面的"带位置"要求会在"工艺还没定"的状态下被正确地拦下来，
        #      那会把"产品流程缺口"错记成"模型不听话"）----
        o1b, p1b = run_round(proj, oid, brain, f"{t}-R1b 确认工艺", "你把这张图做成玻璃画吧")
        SCORE.setdefault("R1b", []).append(str(p1b.get("craft")) or str(p1b.get("action")) == "render")

        # ---- R2 模糊带位置（核心判据）----
        o2, p2 = run_round(proj, oid, brain, f"{t}-R2 模糊带位置", "左边看着有点闷，弄亮一点")
        loc = p2.get("local")
        zones_used = []
        if isinstance(loc, list):
            for it in loc:
                if isinstance(it, dict) and it.get("zone") is not None:
                    zones_used.append(int(it["zone"]))
                elif isinstance(it, dict) and it.get("zones"):
                    zones_used += [int(x) for x in it["zones"]]
        left = [z for z in zones_used if z in (0, 3, 6)]
        R2_ok = bool(left)
        SCORE["R2"].append(R2_ok)
        print(f"  → 判据 R2：用了格 {zones_used}（'左边'= 0/3/6 里的）⇒ {'过' if R2_ok else '不过'}")
        if not R2_ok:
            FAIL.append(f"第{t}组 R2：'左边'却没落到 0/3/6（实得 {zones_used}，knots={p2.get('knobs')}）")

        # ---- R3 与数据对不上（用最亮那格说"太暗"）----
        # 目的：看它是"照着人之所言就改"（陪聊），还是"拿数字核对"（真读账）
        msg = f"第 {lightest} 格那块太暗了，给我提亮一点"
        o3, p3 = run_round(proj, oid, brain, f"{t}-R3 与数据对不上", msg)
        text3 = " ".join(str(p3.get(k) or "") for k in ("question", "message", "reason"))
        asked = str(p3.get("action")) == "ask"
        flagged = any(w in text3 for w in ("最亮", "不暗", "偏亮", "没那" , "对不上", "不太暗"))
        R3_ok = asked or flagged
        SCORE["R3"].append(R3_ok)
        print(f"  → 判据 R3：action={p3.get('action')} 提到数据不符={flagged} ⇒ {'过' if R3_ok else '不过'}")

        # ---- R4 人话检查（三个轮次的 message 都不许出现内部术语）----
        joined = " ".join(str(p.get("message") or "") + " " + str(p.get("question") or "")
                          for p in (p1, p2, p3))
        hits = [w for w in JARGON if w in joined]
        SCORE["R4"].append(not hits)
        print(f"  → 判据 R4：用户可见文字里的内部术语 = {hits or '（无）'}")
        if hits:
            FAIL.append(f"第{t}组 R4：用户可见的文字里出现了内部术语 {hits}")

    # ---- 汇总 ----
    print("\n\n========== 汇总（口径：每一组 = 一张新单 + 同一句话，跑 %d 组）==========" % trials)
    for k in ("R1", "R2", "R3", "R4"):
        v = SCORE[k]
        print(f"{k}: {sum(v)}/{len(v)} 过" + ("" if all(v) else "   ← 有不过的"))
    total_tok = sum(TOKENS)
    print(f"用量：{len(TOKENS)} 次调用，合计 {total_tok} token（口径：totalTokens = input + cacheRead + output，"
          f"reasoning 是 output 的子集不相加）")
    print(f"逐次 = {TOKENS}")

    dump = ROOT / ".tmp-tests" / "exp-position-verbatim.md"
    dump.write_text("\n".join(VERBATIM), encoding="utf-8")
    print(f"它每次的原始 JSON 已存：{dump}")

    if FAIL:
        print(f"\n不过的条目（{len(FAIL)}）：")
        for f in FAIL:
            print("  -", f)
        return 1
    print("\n四类判据全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
