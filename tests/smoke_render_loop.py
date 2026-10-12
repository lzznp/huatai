r"""画台 · 出图闭环真机冒烟（第 4c 步）

⚠️ **会联网、会花钱**（三轮小请求），不在离线测试里：
    python tests\smoke_render_loop.py

判据（这是整条产品的核心一圈）：
 1 投料后**什么都没说** ⇒ 它主动问（不是直接开干）
 2 说"做个玻璃画" ⇒ 它给参数（`action=render`）⇒ **图由确定性管线出来**，产物真落盘
 3 ★ 它给的参数守"工艺默认底"（空泛要求时 素描感强度 在 0.5~0.8，别给全 0）
 4 ★ 独立回读（从 BMP 反算）与管线自报对得上
 5 ★ 说"左上角太暗" ⇒ 它走**局部调整**（local 里是 brighten/darken 之类），并且**局部真的改变了产物**
 6 全程落账：料 / 你 / 它 / 动作四条都在
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kernel"))

TMP = ROOT / ".tmp-tests" / "render-loop"
if TMP.exists():
    shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)
os.environ["HUATAI_PROJECTS"] = str(TMP)

from PIL import Image, ImageDraw  # noqa: E402

from server import brain as B  # noqa: E402
from server import intent as INT  # noqa: E402
from server import store as ST  # noqa: E402

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


def show(tag: str, out: dict) -> dict:
    r = out["reply"]
    p = r.get("parsed") or {}
    u = r.get("usage") or {}
    print(f"\n--- {tag} ---")
    print(f"  action={p.get('action')}  craft={p.get('craft')!r}  合法={out.get('合法')} {out.get('不合法原因') or ''}")
    print(f"  它说：{p.get('question') or p.get('message') or '(空)'}")
    print(f"  knobs={p.get('knobs')}  local={p.get('local')}")
    if out.get("出图"):
        o = out["出图"]
        print(f"  出图 {o['版本']}：{o['指标']}  产物={Path(o['产物']['png']).name}")
    if out.get("出图失败"):
        print(f"  ⚠️ 出图失败：{out['出图失败']}")
    print(f"  账：finish_reason={r.get('finish_reason')} elapsed={r.get('elapsed_ms')}ms total={u.get('totalTokens')}")
    return p


def main() -> int:
    print("=== 画台 · 出图闭环真机冒烟（会花钱，三轮）===")
    print(f"隔离数据根 = {TMP}")

    src = ROOT / ".tmp-tests" / "renwu.png"
    im = Image.new("L", (260, 260), 175)
    d = ImageDraw.Draw(im)
    for i in range(0, 260, 6):
        d.line([(i, 0), (i, 260)], fill=55, width=1)
    d.ellipse([60, 50, 200, 190], outline=20, width=5)      # "脸"
    d.ellipse([100, 100, 125, 120], fill=12)                # "眼"
    d.rectangle([0, 200, 260, 260], fill=235)               # "背景"
    im.save(src)

    ST.create_project("闭环工程")
    info = ST.create_order("闭环工程", str(src))
    oid = info["order_id"]
    ok(f"0.1 备好一单：{oid}")

    brain = B.Brain()

    # 1 什么都没说 ⇒ 主动问
    out1 = INT.round_("闭环工程", oid, "", brain=brain)
    p1 = show("第 1 轮：只投了料，没说话", out1)
    check(out1.get("合法"), "1.1 回答合法", out1.get("不合法原因", ""))
    check(p1.get("action") == "ask", "1.2 ★ 主动问，不是直接开干", f"action={p1.get('action')!r}")
    check(bool(str(p1.get("question") or "").strip()), "1.3 ★ 确实有问句")
    check(not out1.get("出图"), "1.4 这一轮不该出图")

    # 2 说"做个玻璃画" ⇒ 给参数 ⇒ 出图
    out2 = INT.round_("闭环工程", oid, "做个玻璃画", brain=brain)
    p2 = show("第 2 轮：用户说「做个玻璃画」", out2)
    check(out2.get("合法"), "2.1 回答合法", out2.get("不合法原因", ""))
    check(p2.get("action") == "render", "2.2 ★ 它转换为'给参数出图'", f"action={p2.get('action')!r}")
    check(bool(out2.get("出图")), "2.3 ★ 图真的出来了", out2.get("出图失败", ""))
    if out2.get("出图"):
        o = out2["出图"]
        png, bmp = Path(o["产物"]["png"]), Path(o["产物"]["bmp"])
        check(png.is_file() and png.stat().st_size > 0, "2.4 ★ PNG 预览真的落盘")
        check(bmp.is_file() and bmp.stat().st_size > 0, "2.5 ★ 1bit BMP 上机档真的落盘")
        check(o["回读"]["对得上"], "4.1 ★ 独立回读（BMP 反算）与自报对得上",
              f"BMP {o['回读']['bmp里的黑点占比']}% vs 自报 {o['回读']['管线自报的黑点占比']}%")
        sk = (o["旋钮生效"] or {}).get("素描感强度")
        check(sk is not None and 0.3 <= float(sk) <= 0.9, "3.1 ★ 守了'工艺默认底'（素描感 0.5~0.8 一带）",
              f"素描感强度={sk}")
        check(not o["本次写了但没生效的旋钮"], "3.2 没有'写了却不生效'的旋钮",
              f"{o['本次写了但没生效的旋钮']}")

    # 3 反馈"左上角太暗" ⇒ 走局部调整
    out3 = INT.round_("闭环工程", oid, "左上角太暗了，提亮一点", brain=brain)
    p3 = show("第 3 轮：用户说「左上角太暗了，提亮一点」", out3)
    check(out3.get("合法"), "3.1 回答合法", out3.get("不合法原因", ""))
    local = p3.get("local") or []
    check(len(local) > 0, "5.1 ★ 它用了局部调整（local 非空）", f"local={local}")
    if out3.get("出图"):
        eff = out3["出图"].get("局部调整") or []
        check(len(eff) > 0, "5.2 ★ 局部调整真的进了这一版", f"{eff}")
    else:
        check(False, "5.2 这一轮应当也出一版（带局部调整）", f"action={p3.get('action')}")

    # 6 账
    tr = ST.read_transcript("闭环工程", oid)
    kinds = [e["kind"] for e in tr["entries"]]
    check(tr["坏行"] == 0, "6.1 流水没有坏行")
    check(kinds.count("assistant") >= 3, "6.2 它说的话都落账了", f"{kinds}")
    check(kinds.count("action") >= 2, "6.3 每次出图都留了 action 行", f"{kinds}")
    check(all(e.get("data", {}).get("usage") for e in tr["entries"] if e["kind"] == "assistant"),
          "6.4 ★ 每轮都带着用量（可核账）")
    data = ST.get_order("闭环工程", oid)
    check(data["n_ver"] >= 2, "6.5 session.json 里版本数 >= 2", f"n_ver={data['n_ver']}")

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
