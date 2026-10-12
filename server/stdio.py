r"""画台 · stdio 传输（壳默认走这条，**不占端口**）

形状照 DSH 自己的做法：**起一个子进程，走 stdin/stdout 传 JSON 行；诊断只走 stderr**
（stdout 上只有协议帧，混进别的东西就会把壳的解析搞坏）。

请求（一行一个 JSON）：
    {"id": 1, "action": "projects.list", "payload": {}}
响应（一行一个 JSON）：
    {"id": 1, "ok": true,  "status": 200, "result": {...}}
    {"id": 1, "ok": false, "status": 400, "error": "…", "detail": "…"}

约定：
- `id` 原样回传（壳靠它配对；没有 id 就回 null）
- 一行解析不了 → 回一个 `ok=false` 的坏帧响应，**不退出、不静默**
- stdin 到 EOF（壳死了/关了管道）→ **自己退出**，不留僵尸
- `{"action":"shutdown"}` → 回一帧后退出

用法： python server\stdio.py   （或 python -m server --stdio）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import dispatch as D  # noqa: E402


def _force_utf8() -> None:
    """Windows 控制台默认 GBK，中文 JSON 会炸 —— 必须显式改成 UTF-8。"""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 —— 有些环境下不可重配，能跑就行
            pass


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()          # 壳在等这一行，必须立刻冲出去


def _err(req_id, status: int, error: str, detail: str = "") -> None:
    _send({"id": req_id, "ok": False, "status": status, "error": error, "detail": detail})


def main() -> int:
    _force_utf8()
    print(f"{D.SERVICE} v{D.VERSION} stdio 通道就绪（一行一个 JSON 请求）", file=sys.stderr, flush=True)

    for line in sys.stdin:                      # EOF 自动结束循环 → 进程退出
        # 去空白，并**去掉可能存在的 BOM**：别家工具/编辑器写出来的第一行常带 BOM，
        # 不清掉的话第一帧会被判成坏帧（本文件建立当天就撞到过这个形状）。
        line = line.strip().lstrip("\ufeff").strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            _err(None, 400, "帧不是合法 JSON", f"{e}；收到：{line[:120]}")
            continue

        if not isinstance(req, dict):
            _err(None, 400, "帧必须是 JSON 对象", f"收到 {type(req).__name__}")
            continue

        req_id = req.get("id")
        action = req.get("action")
        payload = req.get("payload") or {}

        status, body = D.handle(action, payload)
        if status < 400:
            _send({"id": req_id, "ok": True, "status": status, "result": body})
        else:
            _err(req_id, status, body.get("error", "未知错误"), body.get("detail", ""))

        if action == "shutdown":
            print("收到 shutdown，退出", file=sys.stderr, flush=True)
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
