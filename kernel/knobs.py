"""旋钮清单：运行态 agent 唯一允许调节的项。

每个旋钮都是"人话 ↔ 图像处理参数"之间的桥梁。
底层几十个图像参数不允许 agent 直接碰，只允许通过这里的旋钮间接调。

约定：
- 范围一律 [0,1] 或 [-1,1]
- 默认值 0 表示"不额外处理"（相对基线）
- 每个旋钮配一段"对人话的解释"，供 agent 翻译用户口语用
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Knob:
    """一个旋钮的定义（数据，不是逻辑）。"""

    name: str                    # 旋钮名，agent JSON 里用的 key
    lo: float                    # 下限
    hi: float                    # 上限
    default: float = 0.0         # 默认值
    meaning: str = ""            # 对人话的解释（agent 读）
    applies_to: str = "全局"     # 作用区域：全局 / 背景 / 脸部（能力未实现前仅"全局"可用）


# fmt: off
KNOBS: list[Knob] = [
    Knob("整体明暗",    -1.0, 1.0, 0.0, "整体变深(-)或变浅(+)；对应'整体太深了/太白了'", "全局"),
    Knob("明暗反差",    -1.0, 1.0, 0.0, "对比度：(-)更柔和灰、(+)更黑白分明；对应'对比太强/太灰'", "全局"),
    Knob("细节保留度",   0.0, 1.0, 0.0, "保留头发/皱纹等高频细节；对应'头发糊了/脸太平'", "全局"),
    Knob("背景纯净度",   0.0, 1.0, 0.0, "把背景压得更干净/更接近纯色；对应'背景脏/背景不够白'", "背景"),
    Knob("脸部提亮",     0.0, 1.0, 0.0, "单独把脸部区域提亮；对应'脸有点黑/看不清'", "脸部"),
    Knob("疏密细腻度",   0.0, 1.0, 0.0, "雕刻打点的细腻程度：低=粗犷省时，高=细腻费时", "全局"),
    Knob("素描感强度",   0.0, 1.0, 0.0, "笔触/素描风格化强度（复刻美图秀秀素描感的程序化近似）", "全局"),
]
# fmt: on

KNOB_MAP: dict[str, Knob] = {k.name: k for k in KNOBS}

DEFAULT_KNOBS: dict[str, float] = {k.name: k.default for k in KNOBS}


def validate_knobs(knobs: dict) -> tuple[bool, str]:
    """校验 agent 给的旋钮 JSON 是否合法。

    返回 (是否合法, 错误信息)。合法时错误信息为空串。
    """
    for name, value in knobs.items():
        if name not in KNOB_MAP:
            return False, f"未知旋钮: {name}（清单里没有，属于能力缺口，请报告而非发明）"
        knob = KNOB_MAP[name]
        if not (isinstance(value, (int, float)) and knob.lo <= value <= knob.hi):
            return False, f"旋钮 {name} 取值 {value!r} 超出范围 [{knob.lo}, {knob.hi}]"
    return True, ""


# ========== 局部调整词汇表（③ 九宫格局部调整，决策 #17/#18）==========
# 3×3 九宫格，行优先编号：0=左上 1=上中 2=右上 3=左中 4=正中 5=右中 6=左下 7=下中 8=右下。
# 运行态 agent 只允许用这份词汇表选"哪一格 + 做什么动作"，不许发明动作或字段。
ZONE_COUNT = 9
ZONE_OPS: tuple[str, ...] = ("brighten", "darken", "whiten", "blacken")
# reset 不是"图像算子"，而是"把该格从累积 local_ops 里移除"（还原语义）：
# 不做反向抵消（数值不精确、会漂），见 工作文档\任务包·九宫格局部调整.md §5。
ZONE_RESET_OP = "reset"
ZONE_OP_ALLOWED: tuple[str, ...] = ZONE_OPS + (ZONE_RESET_OP,)

ZONE_OP_CN: dict[str, str] = {
    "brighten": "提亮",
    "darken": "压暗",
    "whiten": "更白",
    "blacken": "更黑",
    "reset": "还原此格",
}

LOCAL_OP_ALLOWED_FIELDS: tuple[str, ...] = ("zone", "op", "amount", "region")
LOCAL_OP_DEFAULT_AMOUNT = 0.5
LOCAL_OP_MAX_AMOUNT = 1.0


def zone_label(zone: int) -> str:
    """0~8 的格子编号 → 用户看得懂的"第 N 格"。"""
    return f"第 {zone + 1} 格"


def validate_local_ops(ops) -> tuple[bool, str]:
    """校验 agent 给的局部调整 JSON 是否合法。

    合法形态：单个对象、对象列表、或 None/[]（=没有局部调整）。
    规则（"不许发明"）：
    - 只允许 zone / region / op / amount 四个字段，多一个未知字段即拒绝；
    - **指哪儿**：`zone`（整数 0~8 的九宫格）**或** `region`（位置词表的键，人话位置，
      见 kernel\\regions.py）——两者必居其一；`region` 也可以写成 `{"hard": "left"}`；
    - zone：整数 0~8，且不能是布尔（Python 里 True==1，必须显式挡掉）；
    - op：必须是 ZONE_OP_ALLOWED 里的动作；
    - amount：可选（缺省 0.5），数字且落在 [0, 1]。

    返回 (是否合法, 错误信息)。合法时错误信息为空串。
    """
    if ops is None:
        return True, ""
    if isinstance(ops, dict):
        items = [ops]
    elif isinstance(ops, list):
        items = ops
    else:
        return False, f"局部调整必须是对象或对象列表，收到 {type(ops).__name__}"
    if not items:
        return True, ""
    for i, item in enumerate(items):
        where = f"local[{i}]"
        if not isinstance(item, dict):
            return False, f"{where} 必须是对象，收到 {type(item).__name__}"
        extra = [k for k in item if k not in LOCAL_OP_ALLOWED_FIELDS]
        if extra:
            return False, f"{where} 含未知字段 {extra}（只允许 {list(LOCAL_OP_ALLOWED_FIELDS)}）"
        has_zone = "zone" in item
        has_region = "region" in item
        if not has_zone and not has_region:
            return False, (f"{where} 既没 zone 也没 region（要指哪儿？"
                           f"zone 是 0~{ZONE_COUNT - 1} 的九宫格；region 是位置词表的键）")
        if has_zone and has_region:
            return False, f"{where} 同时给了 zone 和 region（只能给一个：九宫格 或 位置词）"
        if has_region:
            # 延迟导入：避免 kernel 顶层出现循环依赖
            import regions as RG
            key = item["region"]
            if isinstance(key, dict):
                try:
                    key = RG.coerce(key)
                except ValueError as e:
                    return False, f"{where} 的 region {e}"
            ok_r, err = RG.validate(key)
            if not ok_r:
                return False, f"{where} 的 region：{err}"
        else:
            zone = item["zone"]
            if isinstance(zone, bool) or not isinstance(zone, int):
                return False, f"{where} 的 zone 必须是整数 0~{ZONE_COUNT - 1}，收到 {zone!r}"
            if not 0 <= zone <= ZONE_COUNT - 1:
                return False, f"{where} 的 zone={zone} 越界（只能是 0~{ZONE_COUNT - 1}）"
        op = item.get("op")
        if op not in ZONE_OP_ALLOWED:
            return False, f"{where} 的 op={op!r} 不在允许动作 {list(ZONE_OP_ALLOWED)} 里"
        amount = item.get("amount", LOCAL_OP_DEFAULT_AMOUNT)
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            return False, f"{where} 的 amount 必须是数字，收到 {amount!r}"
        if not 0.0 <= float(amount) <= LOCAL_OP_MAX_AMOUNT:
            return False, f"{where} 的 amount={amount} 超出范围 [0, {LOCAL_OP_MAX_AMOUNT}]"
    return True, ""


def _explode_ops(ops) -> list[dict]:
    """把两种形态统一成"一格一条目"的词汇表形态。

    - 词汇表形态：{"zone": 4, "op": "brighten", "amount": 0.3}
    - 已归并形态：{"op": "brighten", "amount": 0.3, "zones": [3, 4, 5]}（merge/normalize 的产物，
      会被再次喂回 merge 做累积，必须接受）
    """
    items = [] if ops is None else ([ops] if isinstance(ops, dict) else list(ops))
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            out.append(item)   # 交给校验器报错
            continue
        if "zones" in item:
            base = {k: v for k, v in item.items() if k != "zones"}
            for z in item["zones"]:
                one = dict(base)
                one["zone"] = z
                out.append(one)
        else:
            out.append(dict(item))
    return out


def normalize_local_ops(ops) -> list[dict]:
    """把合法 local_ops 规范成"有序操作列表"（合并同 op 条目），供全量重放。

    - **九宫格形态**（zone）与老版本逐字一致：同一条 op 里多格 → 并成一个条目 + zones 列表；
    - **位置词形态**（region，2026-10-13 加）：按 (op, amount, region) 分组，
      产物是 `{"op":…, "amount":…, "regions":[…]}` 或 `{"op":…, "amount":…, "region":…}`；
    - 两种形态**不混在一条里**（字段不同），各自成条目 ⇒ 老判据与老账都不受影响。
    """
    flat = _explode_ops(ops)
    ok, err = validate_local_ops(flat)
    if not ok:
        raise ValueError(err)
    keep_region = any(isinstance(i, dict) and "region" in i for i in flat)

    zgroups: dict[tuple, dict] = {}
    zorder: list[tuple] = []
    rgroups: dict[tuple, dict] = {}
    rorder: list[tuple] = []
    for item in flat:
        op = str(item["op"])
        amount = float(item.get("amount", LOCAL_OP_DEFAULT_AMOUNT))
        if "region" in item:
            import regions as RG
            key = RG.coerce(item["region"])
            gkey = (op, round(amount, 6), key)
            if gkey not in rgroups:
                rgroups[gkey] = {"op": op, "amount": amount, "region": key}
                rorder.append(gkey)
            continue
        if keep_region:
            # 九宫格形态与位置词形态**不混流**：真需要混时也各自成条目，语义不相互污染
            pass
        zone = int(item["zone"])
        if op == ZONE_RESET_OP:
            continue  # reset 由 merge 阶段消化，不进渲染计划
        key = (op, round(amount, 6))
        if key not in zgroups:
            zgroups[key] = {"op": op, "amount": amount, "zones": []}
            zorder.append(key)
        if zone not in zgroups[key]["zones"]:
            zgroups[key]["zones"].append(zone)
    out: list[dict] = []
    for key in zorder:
        g = zgroups[key]
        out.append({"op": g["op"], "amount": g["amount"], "zones": sorted(g["zones"])})
    for key in rorder:
        g = rgroups[key]
        out.append({"op": g["op"], "amount": g["amount"], "region": g["region"]})
    return out


def merge_local_ops(base_ops, new_ops) -> list[dict]:
    """累积局部调整：应用 reset（移除该区全部条目）后再并入新条目。

    这是"还原"的实现方式 —— 从累积列表里去掉那条目后重放，
    而不是加一条"反向抵消"（数值不精确且会漂）。
    两种形态（词汇表 / 已归并）都能进出，方便"取出累积 → 并入新动作 → 存回"。
    ★ region 也能 reset：`{"region": "left", "op": "reset"}`（判据在 test_version_compare / 区域判据里）。
    """
    base = _explode_ops(base_ops)
    new = _explode_ops(new_ops)
    ok, err = validate_local_ops(base)
    if not ok:
        raise ValueError(f"累积 local_ops 不合法: {err}")
    ok, err = validate_local_ops(new)
    if not ok:
        raise ValueError(f"新 local_ops 不合法: {err}")

    def keyset(items) -> set:
        """把一个条目压成"它作用在哪些位置上"的键集合（zone 与 region 都算）。"""
        out = set()
        for i in items:
            if not isinstance(i, dict):
                continue
            if "zone" in i:
                out.add(("zone", int(i["zone"])))
            elif "region" in i:
                import regions as RG
                out.add(("region", RG.coerce(i["region"])))
        return out

    resets: set = set()
    for i in new:
        if i.get("op") == ZONE_RESET_OP:
            resets |= keyset([i])
    kept = [dict(i) for i in base if not (keyset([i]) & resets)]
    kept += [dict(i) for i in new if i.get("op") != ZONE_RESET_OP]
    return normalize_local_ops(kept)


if __name__ == "__main__":
    # 自检：打印清单，方便人工核对
    print(f"{'旋钮':<10}{'范围':<14}{'含义'}")
    print("-" * 70)
    for k in KNOBS:
        print(f"{k.name:<10}[{k.lo:+.0f},{k.hi:+.0f}]  {k.meaning}（{k.applies_to}）")
    print()
    print("局部调整词汇表（3×3 九宫格，行优先 0~8）：")
    print("  动作:", "、".join(f"{k}={v}" for k, v in ZONE_OP_CN.items()))
    print("  形态: local=[{\"zone\": 4, \"op\": \"brighten\", \"amount\": 0.3}]")
