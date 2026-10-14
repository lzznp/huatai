r"""实验 4b：用一个**指定的 SDK 环境**测"图片提示能不能通"（★ 会花钱，很小）

为什么要它：`tests\exp_vision_probe.py` 已经证明——运行时认图片块，但报
  `SDK image prompt requires an attachment store`；
PyPI 自述又写明 **`sdk-minimal` 是瘦身装配**、完整能力在 **`sdk` / `web`** profile 里。
所以这里换 **SDK 版本 / profile** 各试一次，看哪一档能让图片提示真正落地。

用法（用**哪个 python** 决定 SDK 版本，别用错解释器）：
  <venv>\Scripts\python.exe tests\check_image_prompt.py --profile sdk
  <venv>\Scripts\python.exe tests\check_image_prompt.py --profile sdk-minimal
  <venv>\Scripts\python.exe tests\check_image_prompt.py --profiles      # 只列有什么档
环境变量：HUATAI_CHECK_HOME（隔离家目录，默认 D:\画台\.tmp-tests\dsh-check-home）
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\画台")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kernel"))


def load_env_file(path: Path) -> None:
    """自己读 .env（**不依赖 python-dotenv**，好让临时 venv 也能跑）。

    只认 `KEY=VALUE` 这种行；已存在的环境变量不覆盖（与 dotenv 的默认行为一致）。
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


load_env_file(ROOT / ".env")

PROBE_IMG = ROOT / ".tmp-tests" / "exp-vision-probe" / "视觉探针-四色块加数字.png"
SECRET = "7"          # 图上写的数字：看不见就不可能答对


def build_harness(profile: str, home: Path):
    from deepseek_harness import DeepSeekHarness
    return DeepSeekHarness(
        provider="deepseek-official", model="deepseek-v4-flash", max_tokens=1024,
        cwd=str((ROOT / ".agent-cwd").resolve()),
        dsh_home=str(home.resolve()), profile=profile,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="sdk-minimal")
    ap.add_argument("--profiles", action="store_true", help="只跑一次让运行时自举，然后列出可用 profile")
    ap.add_argument("--home", default=str(ROOT / ".tmp-tests" / "dsh-check-home"))
    args = ap.parse_args()

    import deepseek_harness as SDK
    home = Path(args.home)
    home.mkdir(parents=True, exist_ok=True)
    print(f"SDK 版本 = {getattr(SDK, '__version__', '?')}（来自 {SDK.__file__}）")
    print(f"内置运行时 = {SDK.DeepSeekHarnessConfig if False else ''}")
    from deepseek_harness_runtime import bundled_runtime_path
    try:
        print(f"运行时 = {bundled_runtime_path()}")
    except Exception as e:  # noqa: BLE001
        print(f"运行时定位失败：{e}")
    print(f"隔离家目录 = {home}")
    print(f"profile = {args.profile}\n")

    if args.profiles:
        # 用一次真实调用让 profile 自举出来，然后看家目录里生成了哪些 profile
        try:
            h = build_harness(args.profile, home)
            h.run("只回一个词：好", session_id=f"boot-{int(time.time())}")
            h.close()
        except Exception as e:  # noqa: BLE001
            print("自举调用报错（也要看下面生成了什么）：", type(e).__name__, str(e)[:200])
        prof = home / "profiles"
        print(f"\n家目录里出现的 profile：{sorted(p.name for p in prof.iterdir()) if prof.is_dir() else '（无）'}")
        return 0

    if not PROBE_IMG.is_file():
        print(f"找不到探针图 {PROBE_IMG}（先跑 tests\\exp_vision_probe.py）")
        return 2
    b64 = base64.b64encode(PROBE_IMG.read_bytes()).decode("ascii")
    blocks = [
        {"type": "text", "text": "看这张图，两行回答：①左上角和中上两个方块分别是什么颜色？"
                                 f"②图上写的字是什么？看不到就直接说“看不到图”。"},
        {"type": "image", "mimeType": "image/png", "data": b64},
    ]
    h = build_harness(args.profile, home)
    try:
        t0 = time.monotonic()
        res = h.run(blocks, session_id=f"vis-{args.profile}-{int(time.time())}")
        dt = time.monotonic() - t0
        ans = res.final_response or ""
        ok_text = ("红" in ans and "蓝" in ans) or ("red" in ans.lower() and "blue" in ans.lower())
        ok_num = SECRET in ans
        print(f"用时 {dt:.1f}s　finish={res.finish_reason}")
        print(f"回答 = {ans}")
        print(f"\n判据：说出红蓝 = {ok_text}　| 说出数字 {SECRET} = {ok_num}"
              f" ⇒ {'★ 真能看到图' if (ok_text or ok_num) else '看不到图（或没答对）'}")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"★ 报错：{type(e).__name__}: {str(e)[:500]}")
        return 1
    finally:
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
