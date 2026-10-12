r"""只读探测：DSH SDK 的 RunResult 到底给了哪些字段（不调用模型、不花钱）。

用法： python tests\probe_sdk.py
"""
from __future__ import annotations

import dataclasses
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kernel"))


def main() -> int:
    import deepseek_harness as dh
    from deepseek_harness import DeepSeekHarness

    print("sdk 模块   =", dh.__file__)
    print("sdk 版本属性 =", [a for a in ("__version__",) if hasattr(dh, a)])

    # RunResult 的形状
    for name in ("RunResult", "DeepSeekHarnessConfig", "Notification"):
        obj = getattr(dh, name, None) or getattr(__import__("deepseek_harness.models", fromlist=["x"]), name, None)
        if obj is None:
            print(f"\n{name}: 找不到")
            continue
        print(f"\n{name}:")
        if dataclasses.is_dataclass(obj):
            for f in dataclasses.fields(obj):
                print(f"   - {f.name}: {f.type}")
        else:
            try:
                print("   字段:", [k for k in dir(obj) if not k.startswith("_")][:20])
            except Exception as e:  # noqa: BLE001
                print("   看不出来:", e)

    print("\nDeepSeekHarness.__init__ 参数:")
    try:
        print("  ", list(inspect.signature(DeepSeekHarness.__init__).parameters))
    except Exception as e:  # noqa: BLE001
        print("   拿不到:", e)

    print("\nrun() 签名:")
    try:
        print("  ", inspect.signature(DeepSeekHarness.run))
    except Exception as e:  # noqa: BLE001
        print("   拿不到:", e)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
