r"""小助手 · 猜意图（第 4b 步）

用户可能只是把料丢给你，**还没说要做什么**。这一轮要做的就是"搞清楚他要什么"：
先猜、拿不准就问、要的东西做不到就**当场明说做不到**。

三条设计纪律（都是别处踩过的）：
1. **能力清单从同一份代码渲染**（`capabilities.render_for_prompt()`）——
   绝不在提示词里手写第二份清单，手写必漂，漂了就是"假装生效"。
2. **上下文封顶**（参考包判据 8）：每轮现拼一张要点卡 + 只带**最近 N 轮、每轮截断**。
   让会话无限堆积 ⇒ 输入量随对话变长没有上限，迟早出事。
3. **它说的话要校验**：工艺 id 不在清单里、action 不认识 ⇒ 整轮标记为不合法（提示词是引导，校验器才是法律）。
"""
from __future__ import annotations

from datetime import datetime

from . import brain as BRAIN_MOD
from . import capabilities as CAP
from . import render as RENDER_MOD
from . import store as ST

# 内核的旋钮校验（提示词是引导，校验器才是法律）
import sys as _sys
from pathlib import Path as _Path
_KERNEL = _Path(__file__).resolve().parent.parent / "kernel"
if str(_KERNEL) not in _sys.path:
    _sys.path.insert(0, str(_KERNEL))
import knobs as K  # noqa: E402
import regions as RG  # noqa: E402 —— 位置词表（与提示词同源）

# 上下文封顶（数字是起点，将来按实测调）
RECENT_ROUNDS = 6      # 只带最近几轮
RECENT_WIDTH = 200     # 每轮最多几个字

ACTIONS_OK = ("ask", "plan", "done", "render")


def recent_context(entries: list[dict], *, rounds: int = RECENT_ROUNDS,
                   width: int = RECENT_WIDTH) -> str:
    """把最近的流水压成几行（**封顶**：轮数封顶、每轮字数封顶）。"""
    if not entries:
        return "（还没有对话）"
    tail = entries[-rounds:]
    lines: list[str] = []
    for e in tail:
        kind = str(e.get("kind") or "?")
        text = str(e.get("text") or "").replace("\n", " ").strip()
        if len(text) > width:
            text = text[:width] + "…"
        lines.append(f"[{kind}] {text}")
    return "\n".join(lines)


def render_order_state(project: str, order: dict, src_path: str) -> str:
    from pathlib import Path
    name = order.get("src_name") or Path(src_path).name
    return (f"- 工程：{project}\n"
            f"- 这一单：{order.get('order_id')}\n"
            f"- 料：{name}（图片，可读）")


def build_prompt(*, project: str, order: dict, src_path: str,
                 user_text: str = "", entries: list[dict] | None = None,
                 decl: dict | None = None) -> str:
    """拼这一轮的要点卡（纯函数，可离线测）。"""
    said = (user_text or "").strip() or "（用户还没说话，只是把料给了你）"
    prev_brief = render_prev_brief(order)
    return rf"""你是「画台」里的**小助手**：一个玻璃画 / 剪纸画 / 叶雕的**工艺助手**。
用户可能只是把料丢给你，**还没说要做什么**。你的第一件事是搞清楚他要什么。

【铁律】（违反即失败）
1. 你**只输出一个 JSON**，不写代码、不改文件、不跑命令。**图不是你画的**，是确定性管线按你给的参数算出来的。
2. 用户要的东西落在下面「你明确做不到的」里时，必须**当场明说做不到 + 为什么**，不许硬试、不许假装能做。
3. 拿不准就问，**别猜着往下做**。
4. 不许承诺"上传一张图 ⇒ 完美成品"；一张图最多到**可评审的工艺稿**。

{CAP.render_for_prompt(decl)}

{CAP.render_knobs_for_prompt(decl)}

{RG.render_for_prompt()}

【工艺默认底】（照手工流程的底子，别给全 0）
- 说"做个玻璃画"这类**空泛要求**时，默认给**「素描感强度」0.5~0.8**（手工是"反相 + 减淡"，全 0 出来是一张干净灰度，没有那个底）；
- 除非用户明确说要**写实 / 照片感**。

【这一单的现状】
{render_order_state(project, order, src_path)}
- 用户的话：{said}
- 上一版参数与指标：{prev_brief}

【最近几轮】（**已封顶**，别当全文）
{recent_context(entries or [])}

【这一轮你要做什么】
1. 先**猜**用户想做哪个工艺（只能从上面「你能做的工艺」里挑；都沾不上就直说做不到）
2. 还不能确定 ⇒ `action="ask"`，在 `question` 里写**你要问的那一句话**（像人一样问，例如「我猜你是想做玻璃画，是吗？」）
3. 用户要的是你做不到的 ⇒ `action="ask"` 或 `"done"`，在 `message` 里**明说做不到 + 为什么**
4. **工艺已明确**（用户说了"做成玻璃画"，或刚确认过）⇒ `action="render"`，填好 `knobs`（可加 `local`），
   在 `message` 里说清你这一版打算怎么调
5. 已经出过图、用户只是评价/提要求 ⇒ 也走 `action="render"`，**只改要改的那几个旋钮**
6. ★★ **位置**（2026-10-13 改：用户否掉了九宫格格号 ⇒ 改用**位置词 + 先给用户看**）：
   a) 用户的话**带位置**（"左边"、"上面那块"、"中间"、"右下角"…）时，**只从【位置词表】挑一个**
      （挑最接近的；清单里没有的也挑最近的，并在 `question` 里说清"我按 X 处理"），填进 `region` 字段；
   b) 这一轮 `action="ask"`，`question` 写成"你要调的是不是**这一块**（<你挑的中文名>）？"
      —— **不要**在同一轮给参数：位置没确认之前给的参数都是白给
      （界面会把那一块**裁出来高亮**给用户看，他点头才算确认）；
   c) 用户确认之后（他会说"对/是"，或界面上点确认）⇒ **下一轮**才 `action="render"`，
      把同一个位置写进 `local`：`{{"region":"left","op":"brighten","amount":0.3}}`
      （也可以写 `{{"zones":[0,3,6],...}}` 那种九宫格形态，但那是老路，优先用 `region`）；
   d) ★ 动手前仍要拿【上一版参数与指标】里的 9 格数字核一遍：用户说"太暗"但那块在数据上不暗 ⇒
      **先说破**（"数据上它不算暗，最暗的是…"）——用户会用眼睛说错位置，**你手里的数字比他的印象准**。
7. ★ `message` / `question` 是**给用户看的人话**：不写 `brighten`/`darken` 这类**内部动作名**，
   不贴 JSON，不写字段名（`zone`/`amount`/`knobs`/`region`）。说"提亮""加深""打点密一点"就行。

【输出格式】只输出一个 JSON 对象，不要解释、不要用代码块：
{{"action":"ask|render|done","craft":"工艺 id 或空串","knobs":{{"旋钮名":数值}},"local":[{{"region":"left","op":"brighten","amount":0.3}}],"region":"（只在 action=ask 且要确认位置时给）位置词表的键","question":"要问用户的那句话（action=ask 时必填）","message":"给用户看的一句话","reason":"你为什么这么判断（给人看）"}}
（`region` 只能取【位置词表】里的键；`op` 只能是 brighten/darken/whiten/blacken；
  老写法 `{{"zone":4,...}}`（0~8 九宫格）仍然接受，但**优先用 region**）
"""


def format_zone_grid(zones: list[dict] | None) -> str:
    """把 9 格指标排成 3×3 的**文字网格**（要点卡用）。

    行优先 0=左上 1=上中 2=右上 / 3=左中 4=正中 5=右中 / 6=左下 7=下中 8=右下。
    每格给两个数：`墨点` = 这一格的打点占比（0=不打点，100=整格打满）；
    `暗部` = 这一格里"暗"的像素占比（越高说明原图这一块越黑）。

    为什么要这个：用户说"左上角太暗"，小助手**不该靠感觉**，而应该拿第 0 格的
    数字跟别格比一比——**对得上就干，对不上就问**。这是"它到底懂没懂"的可核对面。
    """
    if not zones or len(zones) < 9:
        return "（这一单还没有 9 格数据：可能是加这个功能之前出的图）"
    rows = []
    for r in range(3):
        cells = []
        for c in range(3):
            i = r * 3 + c
            z = zones[i] or {}
            cells.append(f"{i}:墨点{z.get('ink_pct', '?')}%/暗部{z.get('dark_pct', '?')}%")
        rows.append("　".join(cells))
    return "\n".join(rows)


def render_prev_brief(order: dict) -> str:
    """上一版用了什么、出来什么数（要点卡里的"现状"）。"""
    rep = order.get("last_report") or {}
    if not rep:
        return "（还没出过图）"
    k = rep.get("knobs_applied") or {}
    m = rep.get("metrics") or {}
    knobs_txt = "、".join(f"{a}={b}" for a, b in k.items() if b) or "（全默认）"
    return (f"第 {order.get('n_ver') or 0} 版｜旋钮：{knobs_txt}｜"
            f"暗部 {m.get('dark_pct')}% 亮部 {m.get('light_pct')}% 墨点 {m.get('ink_pct')}%\n"
            f"  9 格实测（格号：墨点/暗部，行优先 0=左上…8=右下）：\n"
            f"  {format_zone_grid(rep.get('zones'))}")


def validate_intent(parsed: dict, decl: dict | None = None) -> tuple[bool, str]:
    """校验小助手说的话合不合法（提示词是引导，这里才是法律）。"""
    d = decl or CAP.declaration()
    ids = {c["id"] for c in d["工艺"]}
    names = {c["名"]: c["id"] for c in d["工艺"]}

    action = str(parsed.get("action") or "")
    if action not in ACTIONS_OK:
        return False, f"action 不认识：{action!r}（只能是 {ACTIONS_OK}）"

    craft = str(parsed.get("craft") or "").strip()
    if craft:
        if craft in ids:
            pass
        elif craft in names:
            parsed["craft"] = names[craft]        # 允许它写中文名，归一成 id
        else:
            return False, f"craft 不在能力清单里：{craft!r}（不许发明工艺）"

    if action == "ask" and not str(parsed.get("question") or "").strip():
        return False, "action=ask 却没给 question（问了什么？）"

    # ★ 位置：给了就必须是词表里的键（界面拿它去裁图给用户看；错键要当场拒，不许静默）
    if parsed.get("region") not in (None, ""):
        try:
            key = RG.coerce(parsed["region"])
        except ValueError as e:
            return False, f"region 写法不认识：{e}"
        ok_r, err_r = RG.validate(key)
        if not ok_r:
            return False, f"region：{err_r}"
        parsed["region"] = key

    # 出图这一支：参数必须过校验器（提示词是引导，这里才是法律）
    if action == "render":
        kn = parsed.get("knobs")
        if kn is None:
            kn = {}
        if not isinstance(kn, dict):
            return False, f"knobs 必须是 JSON 对象，收到 {type(kn).__name__}"
        ok, err = K.validate_knobs(kn)
        if not ok:
            return False, err
        if "local" in parsed:
            ok, err = K.validate_local_ops(parsed.get("local"))
            if not ok:
                return False, f"局部调整不合法：{err}"
        if not kn and not parsed.get("local"):
            return False, "action=render 却既没给 knobs 也没给 local（那这一版出什么？）"
    return True, ""


def round_(project: str, order_id: str, user_text: str = "",
           brain=None) -> dict:
    """走一轮：记下用户的话 → 拼要点卡 → 问小助手 → 校验 → 落账 → 返回。

    `brain` 要有一个 `ask(prompt, tag=...) -> dict` 方法（`server.brain.Brain` 就是）。
    ★ 2026-10-13：这里以前写死 `BRAIN_MOD.Brain()`，导致"小助手这一轮怎么走"
    只能靠**花钱的真机**才能验。现在允许**注入替身**（测试里给一个返回固定 JSON 的假大脑），
    于是"位置确认 → 再出图"这条路**离线免费可验**（见 tests\\test_region_offline.py）。
    """
    order = ST.get_order(project, order_id)
    if order is None:
        raise FileNotFoundError(f"没找到这张单：{project}\\{order_id}")

    src_path = str(order.get("src_path") or "")
    entries = ST.read_transcript(project, order_id)["entries"]

    if (user_text or "").strip():
        ST.append_transcript(project, order_id, {"kind": "user", "text": user_text.strip()})
        entries = entries + [{"kind": "user", "text": user_text.strip()}]

    prompt = build_prompt(project=project, order=order, src_path=src_path,
                          user_text=user_text, entries=entries)

    b = brain or BRAIN_MOD.Brain()
    res = b.ask(prompt, tag="intent")

    out: dict = {"prompt": prompt, "reply": res, "合法": False, "不合法原因": ""}

    if not res.get("ok"):
        ST.append_transcript(project, order_id, {
            "kind": "system",
            "text": "小助手没给出可用的 JSON：" + str(res.get("error") or "") + " " + str(res.get("detail") or ""),
            "data": {"finish_reason": res.get("finish_reason"), "truncated": res.get("truncated")},
        })
        return out

    parsed = dict(res.get("parsed") or {})
    ok, why = validate_intent(parsed)
    out["合法"], out["不合法原因"] = ok, why

    if ok:
        text = str(parsed.get("question") or parsed.get("message") or "(空)")
        ST.append_transcript(project, order_id, {
            "kind": "assistant", "text": text,
            "data": {
                "来源": "intent.round",
                "action": parsed.get("action"), "craft": parsed.get("craft"),
                # ★ region：这一轮它想确认的位置（界面据此裁图给用户看，见 决策：位置对齐）
                "region": parsed.get("region"),
                "message": parsed.get("message"), "reason": parsed.get("reason"),
                "finish_reason": res.get("finish_reason"), "truncated": res.get("truncated"),
                "usage": res.get("usage"), "elapsed_ms": res.get("elapsed_ms"),
                "session_id": res.get("session_id"), "model": res.get("model"),
            },
        })
        # 把这一轮它想确认的位置也回给界面（界面**不猜**，直接用）
        if parsed.get("region"):
            out["确认位置"] = parsed["region"]
        # ---- 它说要出图 ⇒ 由**确定性管线**出，它只管给参数 ----
        if parsed.get("action") == "render":
            try:
                out["出图"] = RENDER_MOD.render_order(
                    project, order_id,
                    knobs=parsed.get("knobs") or {},
                    local_ops=parsed.get("local") if "local" in parsed else None,
                    note=str(parsed.get("reason") or ""),
                )
            except (ValueError, FileNotFoundError, RuntimeError) as e:
                out["出图失败"] = f"{type(e).__name__}: {e}"
                ST.append_transcript(project, order_id, {
                    "kind": "system", "text": "出图没成功：" + out["出图失败"],
                })
    else:
        # ★ 越界即整轮作废，并且**把越界这件事写进账**（不许静默丢掉）
        ST.append_transcript(project, order_id, {
            "kind": "system", "text": "小助手的回答不合法，整轮作废：" + why,
            "data": {"parsed": parsed, "finish_reason": res.get("finish_reason")},
        })

    out["流水"] = ST.read_transcript(project, order_id)["entries"][-RECENT_ROUNDS:]
    return out
