r"""画台服务入口：两条通道，同一份业务。

    python -m server --stdio              壳走这条（默认，不占端口）
    python -m server --http --port 8612  调试 / 将来 JS 展示走这条

省略 --stdio/--http 时默认 **stdio**（因为壳是主要使用者）。
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="画台服务（两条通道）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--stdio", action="store_true", help="走标准输入输出（默认，不占端口）")
    g.add_argument("--http", action="store_true", help="走本地 HTTP（调试 / JS 前端）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8612)
    args, _unknown = ap.parse_known_args()

    if args.http:
        from server import app as A
        A.serve(args.host, args.port)
        return 0

    from server import stdio as S
    return S.main()


if __name__ == "__main__":
    sys.exit(main())
