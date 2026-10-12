"""画台 · HTTP 传输（**保留**：调试入口 + 将来 JS/3D 展示那条路）

壳默认走 stdio（`server\\stdio.py`，不占端口）；这一份提供同样的业务能力，
走 `127.0.0.1:<port>`，用途：
  1. 参谋长排查问题时能用浏览器 / curl 直接看（不用开界面）
  2. 将来若用 JS 做 3D 展示，浏览器直接调它最自然

业务一行都不在这里 —— 全部转发给 `dispatch.py`。本文件只管搬 JSON。

    GET  /api/health                      健康与数据根现状
    GET  /api/capabilities                能力声明
    GET  /api/projects                    工程列表
    POST /api/projects  {"name": "…"}     新建工程
    GET  /api/orders?project=<工程>        订单列表
    GET  /api/order?project=<工程>&id=<单> 单条订单全文

错误约定：坏请求一律 4xx + {"error": …}，**绝不 200 带错误体**（不许静默）。
跑： python server\\app.py --port 8612   （或 python -m server --http --port 8612）
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import dispatch as D  # noqa: E402
from server import store as ST  # noqa: E402

# (方法, 路径) → 动作名；参数从 query 或 JSON body 里取
ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/api/health"): "health",
    ("GET", "/api/capabilities"): "capabilities",
    ("GET", "/api/projects"): "projects.list",
    ("POST", "/api/projects"): "projects.create",
    ("GET", "/api/orders"): "orders.list",
    ("GET", "/api/latest"): "session.latest",
    ("GET", "/api/order"): "order.get",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "HuataiServer/0.2"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[服务] %s - %s\n" % (self.address_string(), fmt % args))

    # ------------------------------------------------------------ 出站
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------ 入站
    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            raise ValueError('请求体是空的；需要 JSON，例如 {"name": "我的第一个工程"}')
        try:
            data = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError as e:
            raise ValueError(f"请求体不是合法 UTF-8：{e}") from e
        except json.JSONDecodeError as e:
            raise ValueError(f"请求体不是合法 JSON：{e}") from e
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def _run(self, method: str) -> None:
        u = urlparse(self.path)
        action = ROUTES.get((method, u.path))
        if action is None:
            # 路径存在但方法不对 → 405；路径压根没有 → 404
            known_path = any(p == u.path for _, p in ROUTES)
            if known_path:
                self._json(405, {"error": "不支持的方法", "detail": f"{method} {u.path}"})
            else:
                self._json(404, {"error": "未知接口", "detail": f"没有这个路由：{u.path}"})
            return

        try:
            payload = self._body() if method == "POST" else {k: v[0] for k, v in parse_qs(u.query).items()}
        except ValueError as e:
            self._json(400, {"error": "请求不合法", "detail": str(e)})
            return

        status, body = D.handle(action, payload)
        self._json(status, body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._run("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._run("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._json(405, {"error": "不支持的方法", "detail": "本版只支持 GET 与 POST"})

    do_DELETE = do_PUT
    do_PATCH = do_PUT


def serve(host: str, port: int) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    root = ST.projects_root()
    print(f"{D.SERVICE} v{D.VERSION}（HTTP 通道）已监听 http://{host}:{port}", flush=True)
    print(f"数据根 = {root}（存在={root.is_dir()}）", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("收到中断，退出", flush=True)
    finally:
        httpd.server_close()


def main() -> int:
    ap = argparse.ArgumentParser(description="画台服务（HTTP 通道）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8612)
    args = ap.parse_args()
    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
