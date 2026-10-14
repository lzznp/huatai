r"""画台 · 位置对齐（区域）离线判据（不联网、不花钱）

用户 2026-10-13 的诉求原话：用户否掉九宫格格号（"太机械了"），要"直接圈"；
先做的是更省事的那半：**小助手说"我理解的是哪一块" → 界面把那一块裁出来 → 用户认了才动手**。

判据：
  1 位置词表**同源**：提示词里渲染的键 = 代码里的键（不许手写第二份）
  2 词表是**确定的**：同一个词在任何尺寸下给同一个像素范围；未知词抛错（不静默）
  3 ★ **"先给你看"这条路能走通**：假大脑回 `region=left` ⇒ 界面拿到裁剪图 + sha
  4 ★ 界面上看到的那张裁剪图**与回执 sha256 一致**（图和回执是同一张）
  5 ★ 裁剪预览**不许落 projects**（只回给界面看，不记账）
  6 小助手说错位置（region 不在词表里）⇒ **整轮作废并记账**（不许静默改成别的）
  7 `region` 写进 `local` 之后**真的改变了产物**，而且**动的是那块地方**（别的区域基本不动）
  8 九宫格老路（zone）**一点没坏**：老写法仍合法、仍能出图
  9 region 也能 reset（把该区从累积里摘掉）
 10 未知 region 在归并形态（regions 列表）里也会被拒

用法：  python tests\test_region_offline.py
数据根：HUATAI_PROJECTS → D:\画台\.tmp-tests\region-projects（**不碰真实工程**）
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kernel"))

TMP = ROOT / ".tmp-tests" / "region-projects"
if TMP.exists():
    shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)
os.environ["HUATAI_PROJECTS"] = str(TMP)

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import knobs as K  # noqa: E402
import regions as RG  # noqa: E402
from image_lib import pipeline as PL  # noqa: E402

from server import dispatch as D  # noqa: E402
from server import intent as INT  # noqa: E402
from server import region as REG  # noqa: E402
from server import render as R  # noqa: E402
from server import store as ST  # noqa: E402

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


class FakeBrain:
    """替身大脑：**不联网、不花钱**，按脚本回固定 JSON。用来验"小助手这一轮怎么走"。"""

    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.calls = 0

    def ask(self, prompt: str, *, tag: str = "probe", session_id: str | None = None) -> dict:
        self.prompts.append(prompt)
        self.calls += 1
        parsed = self.replies.pop(0) if self.replies else {"action": "done"}
        return {
            "ok": True, "parsed": dict(parsed), "raw": "{}", "error": None, "activity": [],
            "truncated": False, "finish_reason": "completed",
            "usage": {"inputTokens": 10, "cacheReadTokens": 0, "outputTokens": 5,
                      "reasoningTokens": 1, "totalTokens": 15},
            "elapsed_ms": 1, "session_id": "fake-1", "model": "fake", "profile": "fake",
            "dsh_home": "", "cwd": "",
        }


def main() -> int:
    print(f"数据根（隔离）= {TMP}")

    img = ROOT / ".tmp-tests" / "region.png"
    im = Image.new("L", (240, 240), 170)
    d = ImageDraw.Draw(im)
    for i in range(0, 240, 6):
        d.line([(i, 0), (i, 240)], fill=45, width=1)
    d.ellipse([50, 50, 190, 190], outline=15, width=4)
    im.save(img)

    # ---- 1 提示词与代码同源 ----
    fake = FakeBrain([{"action": "ask", "question": "先确认工艺", "message": "先确认工艺"}])
    D.handle("projects.create", {"name": "位置测试"})
    code, body = D.handle("orders.create", {"project": "位置测试", "src": str(img)})
    oid = body["order_id"]
    ok(f"0.1 备好一单：{oid}")

    out = INT.round_("位置测试", oid, "做成玻璃画", brain=fake)
    prompt = out["prompt"]
    rendered = RG.render_for_prompt()
    eq(rendered in prompt, True, "1.1 ★ 位置词表进了提示词（与 regions.py 同源）")
    eq(all(r.key in rendered for r in RG.REGIONS), True, "1.2 词表里每个键都渲染了")
    eq("只能从这里挑" in rendered, True, "1.3 词表里写明了'不许自己编坐标'")

    # ---- 2 词表是确定的 ----
    eq(RG.get("left").rect_px(400, 380), (0, 0, 136, 380), "2.1 left 在 400×380 上的像素范围确定")
    eq(RG.get("left").rect_px(800, 760), (0, 0, 272, 760), "2.2 同一个词换尺寸后按比例走（与图片尺寸无关）")
    try:
        RG.get("nose")
        eq(False, True, "2.3 未知词必须抛错")
    except ValueError as e:
        eq("未知区域" in str(e), True, "2.3 ★ 未知词抛错（不静默）")

    # ---- 3/4/5 "先给你看"这条路 ----
    fake2 = FakeBrain([
        {"action": "ask", "region": "left", "question": "你要调的是不是左边一列这块？",
         "message": "我理解成左边一列，先给你看这块。"},
        {"action": "render", "craft": "glass", "local": [{"region": "left", "op": "brighten", "amount": 0.3}],
         "message": "好，我把左边一列提亮一点。"},
    ])
    out2 = INT.round_("位置测试", oid, "左边看着有点闷", brain=fake2)
    eq(out2["合法"], True, "3.1 它给的位置回答合法")
    eq(out2.get("确认位置"), "left", "3.2 ★ 这一轮它要确认的位置回给了界面（left）")
    entry = [e for e in ST.read_transcript("位置测试", oid)["entries"] if e["kind"] == "assistant"][-1]
    eq((entry.get("data") or {}).get("region"), "left", "3.3 ★ 账里也记下了它想确认的位置")

    pv = REG.preview("位置测试", oid, "left")
    eq(str(pv["data_url"]).startswith("data:image/png;base64,"), True, "4.1 界面拿到可直接显示的裁剪图")
    import base64
    import hashlib
    raw = base64.b64decode(pv["data_url"].split(",", 1)[1])
    eq(hashlib.sha256(raw).hexdigest(), pv["sha256"], "4.2 ★ 界面上那张图与回执 sha256 一致")
    eq("不落 projects" in pv["说明"], True, "5.1 返回里写明'只是给界面看的'（不记账）")

    before = sorted(p.name for p in (ST.order_path("位置测试", oid)).iterdir())
    REG.preview("位置测试", oid, "center")
    REG.preview("位置测试", oid, "lower_right")
    after = sorted(p.name for p in (ST.order_path("位置测试", oid)).iterdir())
    eq(before, after, "5.2 ★ 连裁三次，这一单目录里的东西一个没多（预览不落盘）")

    # ---- 6 它说错位置 ⇒ 整轮作废并记账 ----
    fake3 = FakeBrain([{"action": "ask", "region": "nose", "question": "是不是鼻子那块？"}])
    n_before = len(ST.read_transcript("位置测试", oid)["entries"])
    out3 = INT.round_("位置测试", oid, "鼻子那块不对", brain=fake3)
    eq(out3["合法"], False, "6.1 ★ region 不在词表里 ⇒ 整轮作废")
    eq("region" in (out3.get("不合法原因") or ""), True, "6.2 作废理由说明了是 region 不合法")
    entries = ST.read_transcript("位置测试", oid)["entries"]
    eq(len(entries) > n_before, True, "6.3 ★ 作废这件事也记了账（不许静默丢掉）")
    eq(entries[-1]["kind"], "system", "6.4 记的是一条 system 行")

    # ---- 7 region 真的生效，而且动的是那块地方 ----
    code, r1 = D.handle("render.run", {"project": "位置测试", "order": oid,
                                       "knobs": {"素描感强度": 0.6}})
    eq(code, 201, "7.1 先出一版基线")
    code, r2 = D.handle("render.run", {"project": "位置测试", "order": oid,
                                       "local": [{"region": "left", "op": "brighten", "amount": 0.6}]})
    eq(code, 201, "7.2 ★ 用 region 出图 201")
    z1, z2 = r1["分区"], r2["分区"]
    left_col = [z1[i]["ink_pct"] for i in (0, 3, 6)], [z2[i]["ink_pct"] for i in (0, 3, 6)]
    right_col = [z1[i]["ink_pct"] for i in (2, 5, 8)], [z2[i]["ink_pct"] for i in (2, 5, 8)]
    d_left = sum(b - a for a, b in zip(*left_col)) / 3
    d_right = sum(b - a for a, b in zip(*right_col)) / 3
    print(f"      左列墨点变化 {d_left:+.1f} 个点／右列 {d_right:+.1f} 个点")
    eq(d_left < -1.0, True, "7.3 ★ 提亮确实生效（左列墨点下降）")
    eq(abs(d_right) < abs(d_left), True, "7.4 ★ 主要动的是它说的那块（右列变化更小）")
    ln = [e for e in ST.read_transcript("位置测试", oid)["entries"] if e["kind"] == "action"][-1]
    eq(ln["data"]["参数"]["local_ops"], [{"op": "brighten", "amount": 0.6, "region": "left"}],
       "7.5 账里记的是 region 形态（可复现）")

    # ---- 8 九宫格老路没坏 ----
    okz, errz = K.validate_local_ops([{"zone": 4, "op": "brighten", "amount": 0.3}])
    eq(okz, True, "8.1 老写法（zone）仍然合法")
    code, r3 = D.handle("render.run", {"project": "位置测试", "order": oid,
                                       "local": [{"zone": 4, "op": "brighten", "amount": 0.3}]})
    eq(code, 201, "8.2 ★ 老写法照样能出图（不许把老账读坏）")

    # ---- 9 region reset ----
    merged = K.merge_local_ops([{"region": "left", "op": "brighten", "amount": 0.4}],
                               [{"region": "left", "op": "reset"}])
    eq(merged, [], "9.1 ★ region 的 reset 把该区从累积里摘掉了")
    merged2 = K.merge_local_ops([{"region": "left", "op": "brighten", "amount": 0.4},
                                 {"region": "top", "op": "brighten", "amount": 0.4}],
                                [{"region": "left", "op": "reset"}])
    eq([m["region"] for m in merged2], ["top"], "9.2 reset 只摘掉它指的那一块")

    # ---- 10 归并形态里的未知 region 也拒 ----
    try:
        PL._prepare_local_ops([{"op": "brighten", "amount": 0.3, "regions": ["left", "nose"]}])
        eq(False, True, "10.1 归并形态的未知 region 必须抛错")
    except ValueError as e:
        eq("未知区域" in str(e), True, "10.1 ★ 归并形态的未知 region 抛错（不静默）")

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
