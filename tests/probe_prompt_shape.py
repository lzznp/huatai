r"""侧检：小助手每轮实际看到的提示词，**信息构成**是什么（离线，不联网、不花钱）

为什么量这个：
  用户要的是"用自然语言指挥，但数据要准"。那 LLM 那一侧的**输入**里，
  到底有多少是"这一单的真数据"（9 格数字、上一版参数），多少是固定说明？
  如果真数据只占几个百分点，那"它到底懂没懂"就只能靠它猜——这不是模型的问题，是喂得不够。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kernel"))

from server import intent as INT  # noqa: E402

# 造一个"已经出过两版"的单（数据就用我们刚在真机上量到的那组形状）
zones = [
    {"mean": 118.0, "dark_pct": 33.4, "light_pct": 12.0, "ink_pct": 62.0},
    {"mean": 131.0, "dark_pct": 28.1, "light_pct": 18.3, "ink_pct": 58.4},
    {"mean": 143.0, "dark_pct": 22.9, "light_pct": 25.6, "ink_pct": 54.1},
    {"mean": 120.0, "dark_pct": 32.7, "light_pct": 12.9, "ink_pct": 61.3},
    {"mean": 135.0, "dark_pct": 27.6, "light_pct": 19.4, "ink_pct": 57.2},
    {"mean": 147.0, "dark_pct": 21.4, "light_pct": 27.1, "ink_pct": 53.0},
    {"mean": 126.0, "dark_pct": 30.8, "light_pct": 15.2, "ink_pct": 60.1},
    {"mean": 139.0, "dark_pct": 25.9, "light_pct": 22.5, "ink_pct": 55.8},
    {"mean": 151.0, "dark_pct": 20.2, "light_pct": 29.4, "ink_pct": 51.7},
]
order = {
    "order_id": "order-20261012-165706",
    "n_ver": 2,
    "src_name": "src_one.jpeg",
    "last_report": {
        "knobs_applied": {"素描感强度": 0.7, "整体明暗": 0.2},
        "metrics": {"dark_pct": 2.2, "light_pct": 62.9, "ink_pct": 18.0, "mean": 210.0},
        "zones": zones,
    },
}
entries = [
    {"kind": "material", "text": "src_one.jpeg"},
    {"kind": "user", "text": "做个玻璃画"},
    {"kind": "assistant", "text": "我猜你是想做玻璃画，是吗？"},
]

prompt = INT.build_prompt(project="美女玻璃画", order=order,
                          src_path=r"D:\画台\projects\美女玻璃画\order-20261012-165706\src_one.jpeg",
                          user_text="左上角太暗了，提亮一点", decl=None, entries=entries)

# 切块：按小标题把提示词分段（段名 -> 字符数）
import re
blocks = re.split(r"\n(?=【)", prompt)
print(f"提示词总长 = {len(prompt)} 字符（口径：UTF-8 字符数，非 token）\n")
for b in blocks:
    head = b.split("\n", 1)[0][:28]
    print(f"  {len(b):6d} 字符  {head}")

# "这一单的真数据" = 现状块里那 9 格 + 上一版参数那几行
real_markers = ["9 格实测", "上一版参数", "用户的话", "这一单"]
real_len = 0
for b in blocks:
    if any(m in b for m in real_markers):
        real_len += len(b)
print(f"\n其中【这一单的真数据】≈ {real_len} 字符，占 {(real_len / len(prompt) * 100):.1f}%")
print("（含：单号 / 料名 / 用户这句话 / 上一版旋钮与指标 / 9 格数字）")

dump = ROOT / ".tmp-tests" / "prompt-dump.txt"
dump.parent.mkdir(parents=True, exist_ok=True)
dump.write_text(prompt, encoding="utf-8")
print(f"\n整张提示词已存：{dump}")
