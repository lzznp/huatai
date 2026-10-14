r"""实验 4a：**这个模型到底能不能看图？**（★ 会花钱，很小）

用户 2026-10-13：「我们要先试试，视觉模型能否分类，打标签？……能否我们直接在对话中测试」

为什么要先测这一步：
  · 我们整条链路（`agent_bridge` → SDK）**只发过文本**，从没发过图；
  · 现在的模型是 `deepseek-v4-flash`，**支不支持视觉输入，未知**；
  · SDK 侧已确认有通道（`api.normalize_input` 直通 `contentBlocks`，`client.session_prompt` 发它），
    但**块的确切字段名**在打包快照里、磁盘上看不到 ⇒ 直接实测。

判据（**能让它作弊都不行**）：给一张自造的图——4 个色块 + 大字"画台 7" + 一条斜线。
  · 真能看到 ⇒ 它会说出**颜色位置**和**那个数字 7**（数字是我随口定的，它猜不到）；
  · 看不到 ⇒ 它会说"我看不到图/没有图片"，或者瞎编一个不存在的数字。

用法：  python tests\exp_vision_probe.py            # 只试块格式 + 看图
        python tests\exp_vision_probe.py reads      # 直接读我们产物图（灰度预览）
"""
from __future__ import annotations

import base64
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kernel"))

from PIL import Image, ImageDraw  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")                      # 密钥只在项目根这一处

from deepseek_harness import DeepSeekHarness  # noqa: E402

OUT = ROOT / ".tmp-tests" / "exp-vision-probe"
OUT.mkdir(parents=True, exist_ok=True)

SECRET_NUMBER = "7"        # 图上写的数字：它看不见就不可能说出来
CANDIDATE_SHAPES = [
    # 三种候选字段名（ACP 谱系用 mimeType+data；也有用 mediaType 的变体）
    ("mimeType+data", lambda b64: {"type": "image", "mimeType": "image/png", "data": b64}),
    ("mediaType+data", lambda b64: {"type": "image", "mediaType": "image/png", "data": b64}),
    ("mimeType+base64", lambda b64: {"type": "image", "mimeType": "image/png", "base64": b64}),
]


def make_test_image() -> Path:
    """自造一张"看得见就一定答得出"的图：4 色块 + 神秘数字 + 一条斜线。"""
    im = Image.new("RGB", (420, 260), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 100, 100], fill=(230, 30, 30))          # 左上 红
    d.rectangle([110, 0, 210, 100], fill=(30, 120, 230))       # 上中 蓝
    d.rectangle([0, 110, 100, 210], fill=(30, 190, 90))        # 左中 绿
    d.rectangle([110, 110, 210, 210], fill=(250, 220, 40))     # 中中 黄
    d.line([(230, 20), (400, 230)], fill=(0, 0, 0), width=9)   # 一条斜线
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 72)
    except Exception:                                          # noqa: BLE001
        font = None
    d.text((240, 120), f"画台 {SECRET_NUMBER}", fill=(0, 0, 0), font=font)
    p = OUT / "视觉探针-四色块加数字.png"
    im.save(p)
    return p


def try_shape(harness: DeepSeekHarness, name: str, factory, img: Path) -> tuple[bool, str]:
    b64 = base64.b64encode(img.read_bytes()).decode("ascii")
    blocks = [
        {"type": "text", "text": "看这张图，回答两件事，各一行：①左上角和中上两个方块分别是什么颜色？"
                                 "②图上写的字是什么？如果看不到图，就直接说“看不到图”。"},
        factory(b64),
    ]
    t0 = time.monotonic()
    try:
        res = harness.run(blocks, session_id=f"vis-{name}-{int(time.time())}")
        dt = time.monotonic() - t0
        return True, f"{res.final_response or '(空)'}   [finish={res.finish_reason} {dt:.1f}s]"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:300]}"


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    img = make_test_image()
    print(f"探针图 = {img.name}（红色块在左上、蓝色块在上中，图上写着「画台 {SECRET_NUMBER}」）")
    print(f"★ 判据：它必须说出 红/蓝 与「画台 {SECRET_NUMBER}」——数字是我随口定的，看不见就不可能答对\n")

    h = DeepSeekHarness(
        provider="deepseek-official", model="deepseek-v4-flash", max_tokens=1024,
        cwd=str((ROOT / ".agent-cwd").resolve()), dsh_home=str((ROOT / ".dsh_home").resolve()),
        profile="sdk-minimal", api_key=None,
    )
    try:
        if mode == "probe":
            for name, factory in CANDIDATE_SHAPES:
                ok, out = try_shape(h, name, factory, img)
                print(f"--- 块格式 {name} ---")
                print(f"   {'接口接受' if ok else '★接口报错'}：{out}\n")
        else:
            for p in sorted((ROOT / ".tmp-tests" / "exp-vision").glob("*.png")):
                ok, out = try_shape(h, p.stem[:12], CANDIDATE_SHAPES[0][1], p)
                print(f"--- {p.name} ---")
                print(f"   {'接口接受' if ok else '★接口报错'}：{out}\n")
    finally:
        h.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
