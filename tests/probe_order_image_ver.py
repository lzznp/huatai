r"""只读/隔离探针：验 `order.image` 的 `ver` 参数语义（**不碰真实工程**）。

要回答的问题（一条推断要升级成实锤）：
    前端/壳传 `ver=0`（JS 拿不到 null，只能给 0）时，`store.order_image` 是取"最新一版"，
    还是走"找第 0 版"⇒ 找不到就报错？

数据根：HUATAI_PROJECTS → D:\画台\.tmp-tests\probe-ver-projects（自隔离）。
**不联网、不花钱**（只调确定性管线）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = ROOT / ".tmp-tests" / "probe-ver-projects"
if TMP.exists():
    shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)
os.environ["HUATAI_PROJECTS"] = str(TMP)

from PIL import Image  # noqa: E402

from server import render as R  # noqa: E402
from server import store as ST  # noqa: E402


def mkimg(p: Path) -> Path:
    """造一张有高频细节的图（按坑 22：别用平滑渐变测细节类旋钮）。"""
    import numpy as np
    rng = np.random.default_rng(7)
    a = (rng.random((240, 240)) * 255).astype("uint8")
    Image.fromarray(a, mode="L").save(p)
    return p


def show(name: str, fn) -> None:
    try:
        r = fn()
        print(f"[OK ] {name} -> 版本={r['版本']} 名字={r['名字']} sha={r['sha256'][:12]} 字节={r['字节']}")
    except Exception as e:  # noqa: BLE001
        print(f"[ERR] {name} -> {type(e).__name__}: {e}")


def main() -> int:
    print(f"数据根（隔离）= {TMP}")
    p = mkimg(TMP / "probe.png")
    proj = "探针工程"
    ST.create_project(proj)
    oid = ST.create_order(proj, str(p))["order_id"]
    print(f"工程={proj} 单={oid}")

    key = "素描感强度"
    v1 = R.render_order(proj, oid, knobs={key: 0.3})
    v2 = R.render_order(proj, oid, knobs={key: 0.7})
    print(f"出了两版：{v1['版本']} sha={Path(v1['产物']['png']).name}")
    print(f"           {v2['版本']} sha={Path(v2['产物']['png']).name}")

    hist = ST.get_order(proj, oid)["history"]
    print("history:", json.dumps([{"ver": h["ver"], "note": h.get("note")} for h in hist], ensure_ascii=False))

    # ① ver=None（dispatch 在"没给 ver"时的走法）应取最新
    show("ver=None（不给）", lambda: ST.order_image(proj, oid, "png", ver=None))
    # ② ★ ver=0（当前前端/壳实际传的值）——这就是要判的那条
    show("ver=0（前端现在传的）", lambda: ST.order_image(proj, oid, "png", ver=0))
    # ③ 显式取第 1 版
    show("ver=1", lambda: ST.order_image(proj, oid, "png", ver=1))
    # ④ 越界版本
    show("ver=9（不存在）", lambda: ST.order_image(proj, oid, "png", ver=9))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
