r"""画台 · 内核冒烟（只读）：确认从 bestpic 搬来的 kernel 在新位置能直接用。

用法：
    python tests\smoke_kernel.py [数据根]
数据根省略时用环境变量 BESTPIC_ORDERS_DIR，再省略就用内核默认。
本脚本**只读**，不改任何文件。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # D:\画台
KERNEL = ROOT / "kernel"
sys.path.insert(0, str(KERNEL))

if len(sys.argv) > 1:
    os.environ["BESTPIC_ORDERS_DIR"] = sys.argv[1]

import orders  # noqa: E402  （必须在 sys.path 设置之后导入）


def main() -> int:
    print("kernel 目录      =", KERNEL)
    print("orders 模块来源  =", orders.__file__)
    print("orders_root()    =", orders.orders_root())
    print("trash_dir()      =", orders.trash_dir())
    print("archive_dir()    =", orders.archive_dir())
    print("数据根存在       =", orders.orders_root().is_dir())

    projects = orders.list_projects()
    print(f"list_projects()  -> {len(projects)} 个: {[p.get('id') for p in projects]}")
    for p in projects:
        pid = p["id"]
        olist = orders.list_orders(pid)
        print(f"  工程 [{pid}] -> {len(olist)} 单")
        for o in olist[:5]:
            oid = o.get("order_id") if isinstance(o, dict) else o
            print("    ", oid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
