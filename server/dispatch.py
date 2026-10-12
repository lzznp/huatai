"""画台 · 业务分发（**传输无关**）

原则：**通道只搬 JSON，业务只判对错**。两条通道（stdio / HTTP）共用这一份逻辑。
⇒ 加一条通道不用碰业务；改业务不用碰通道。

动作表（名字固定，通道自己映射过来）：
    health            服务与数据根现状
    capabilities      能力声明（小助手"我不会"的凭据）
    projects.list     工程列表
    projects.create   新建工程   payload {"name": "…"}
    orders.list       订单列表   payload {"project": "…"}（可省）
    order.get         单条订单   payload {"project": "…", "id": "…"}
    shutdown          让常驻进程收工（只对 stdio 有意义）

返回约定：`handle()` → `(status, payload)`。status < 400 时 payload 是结果，否则是
`{"error": …, "detail": …}`。**任何失败都必须带 error，绝不用成功码带错误体。**
"""
from __future__ import annotations

from datetime import datetime

from . import capabilities as CAP
from . import store as ST

SERVICE = "画台·服务"
VERSION = "0.2.0"

ACTIONS: dict[str, str] = {
    "health": "服务与数据根现状",
    "capabilities": "能力声明（小助手说我不会的凭据）",
    "projects.list": "工程列表",
    "projects.create": "新建工程（payload.name）",
    "orders.list": "订单列表（payload.project 可省）",
    "orders.create": "投料建单（payload.project + payload.src）",
    "order.get": "单条订单的整单归档（payload.project + payload.id）",
    "order.detail": "一单全貌：归档 + 流水 + 产物（payload.project + payload.id）",
    "transcript.append": "往对话流水追加一行（payload.project + payload.order + payload.entry）",
    "transcript.read": "读回对话流水（payload.project + payload.order）",
    "shutdown": "让常驻进程收工（仅 stdio）",
}

_BAD = (ValueError, TypeError)


def handle(action: str, payload: dict | None = None) -> tuple[int, dict]:
    """执行一个动作。传输层只负责把参数送进来、把结果送出去。"""
    if not isinstance(action, str) or not action:
        return 400, {"error": "缺动作名", "detail": f"可用动作：{sorted(ACTIONS)}"}
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return 400, {"error": "payload 必须是 JSON 对象", "detail": f"收到 {type(payload).__name__}"}

    try:
        # ---------------- 读
        if action == "health":
            root = ST.projects_root()
            return 200, {
                "ok": True,
                "服务": SERVICE,
                "版本": VERSION,
                "数据根": str(root),
                "数据根存在": root.is_dir(),
                "工程数": len(ST.list_projects()),
                "时间": datetime.now().isoformat(timespec="seconds"),
            }

        if action == "capabilities":
            return 200, CAP.declaration()

        if action == "projects.list":
            return 200, {"projects": ST.list_projects()}

        if action == "orders.list":
            project = payload.get("project") or None
            if project is not None and not isinstance(project, str):
                return 400, {"error": "project 必须是字符串", "detail": repr(project)}
            return 200, {"orders": ST.list_orders(project)}

        if action == "order.get":
            pid, oid = payload.get("project"), payload.get("id")
            if not pid or not oid:
                return 400, {"error": "缺参数", "detail": "需要 project 与 id"}
            data = ST.get_order(str(pid), str(oid))
            if data is None:
                return 404, {"error": "没找到这个订单", "detail": f"工程={pid} 订单={oid}"}
            return 200, data

        if action == "order.detail":
            pid, oid = payload.get("project"), payload.get("id")
            if not pid or not oid:
                return 400, {"error": "缺参数", "detail": "需要 project 与 id"}
            return 200, ST.order_detail(str(pid), str(oid))

        if action == "transcript.read":
            pid, oid = payload.get("project"), payload.get("order")
            if not pid or not oid:
                return 400, {"error": "缺参数", "detail": "需要 project 与 order"}
            return 200, ST.read_transcript(str(pid), str(oid))

        # ---------------- 写
        if action == "projects.create":
            name = payload.get("name")
            if not isinstance(name, str):
                return 400, {"error": "缺字段", "detail": "需要 payload.name，且是字符串"}
            meta = ST.create_project(name)
            return 201, {
                "created": True,
                "project": meta,
                "目录": str(ST.project_path(meta["工程目录名"])),
            }

        if action == "orders.create":
            pid, src = payload.get("project"), payload.get("src")
            if not pid or not src:
                return 400, {"error": "缺参数", "detail": "需要 project（工程）与 src（原图路径）"}
            return 201, ST.create_order(str(pid), str(src))

        if action == "transcript.append":
            pid = payload.get("project")
            oid = payload.get("order")
            entry = payload.get("entry")
            if not pid or not oid:
                return 400, {"error": "缺参数", "detail": "需要 project 与 order"}
            if not isinstance(entry, dict):
                return 400, {"error": "缺字段", "detail": "需要 entry（JSON 对象）"}
            return 201, {"appended": True, "line": ST.append_transcript(str(pid), str(oid), entry)}

        if action == "shutdown":
            return 200, {"bye": True}

        return 404, {"error": "未知动作", "detail": f"{action} 不在动作表里；可用：{sorted(ACTIONS)}"}

    except FileExistsError as e:
        return 409, {"error": "同名工程已存在", "detail": str(e)}
    except FileNotFoundError as e:
        return 404, {"error": "找不到", "detail": str(e)}
    except _BAD as e:
        return 400, {"error": "参数不合法", "detail": str(e)}
    except Exception as e:  # noqa: BLE001 —— 绝不静默
        import traceback
        traceback.print_exc()
        return 500, {"error": "服务内部错误", "detail": f"{type(e).__name__}: {e}"}
