"""工程 / 订单数据层：`D:\\画台\\projects\\<工程>\\<订单>\\`

接法：**内核零改动** —— 订单层直接复用搬过来的 `kernel/orders.py`，
只是把它的数据根（环境变量 `BESTPIC_ORDERS_DIR`）指到 `projects\\`。

两条血账（来自参考包，专治将来会咬人的事）：
1. **显示名 ≠ 目录名**：目录名要安全、要截断（Windows 路径长度），显示名给人看，两者分开存。
2. **改名只加后缀、不换全新路径**（换路径会把会话与账指丢）—— 本版先只做新建，改名未实现。

数据根可用环境变量 `HUATAI_PROJECTS` 覆盖（测试隔离用，绝不碰真实工程）。
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNEL = ROOT / "kernel"
if str(KERNEL) not in sys.path:
    sys.path.insert(0, str(KERNEL))

import orders as _orders  # noqa: E402  （必须在 sys.path 设置之后导入）

SCHEMA = 1
META_NAME = "meta.json"
MAX_DIRNAME = 40  # Windows 路径长度很紧，目录名留短一点

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


# ---------------------------------------------------------------- 路径
def projects_root() -> Path:
    """工程项目根；测试可用 HUATAI_PROJECTS 隔离。"""
    env = os.environ.get("HUATAI_PROJECTS")
    return Path(env) if env else ROOT / "projects"


def _bind() -> Path:
    """把内核订单层的数据根指到 projects\\（这就是'零改动复用'的接法）。"""
    root = projects_root()
    os.environ["BESTPIC_ORDERS_DIR"] = str(root)
    return root


def project_path(project_id: str) -> Path:
    return projects_root() / project_id


def meta_path(project_id: str) -> Path:
    return project_path(project_id) / META_NAME


# ---------------------------------------------------------------- 名字
def safe_dirname(display_name: str) -> str:
    """显示名 → 安全目录名。非法字符替换、去尾点尾空格、限长、避开保留名。

    额外一条：**如果替换完只剩下划线与空格，说明这个名字没有可用内容 → 拒绝**。
    （否则用户打 "///" 会被静默变成一个叫 "___" 的工程，那比报错更让人困惑。）
    """
    s = _ILLEGAL.sub("_", (display_name or "").strip())
    s = s.strip().rstrip(" .")
    if not s or not re.search(r"[^_\s]", s):
        raise ValueError("工程名不合法：去掉非法字符后没有剩下可用内容，请换个名字")
    if s.upper() in _RESERVED:
        s = "_" + s
    if len(s) > MAX_DIRNAME:
        s = s[:MAX_DIRNAME].rstrip(" .")
    return s


def _read_meta(project_id: str) -> dict:
    f = meta_path(project_id)
    if f.is_file():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 —— 坏档不拖垮整列，但要暴露
            return {"_坏档": str(f)}
    return {}


# ---------------------------------------------------------------- 写
def create_project(display_name: str) -> dict:
    """新建工程。同名（显示名或目录名相同）**直接拒绝**，不静默加后缀。

    理由：静默加后缀会造成'两个看起来一模一样的工程'，那是比报错更坏的结果。
    """
    display = (display_name or "").strip()
    if not display:
        raise ValueError("工程名不能为空")

    _bind()
    root = projects_root()
    root.mkdir(parents=True, exist_ok=True)

    pid = safe_dirname(display)

    if (root / pid).exists():
        raise FileExistsError(f"已经有一个工程叫「{display}」（目录名 {pid}）")

    for p in _orders.list_projects():
        meta = _read_meta(p["id"])
        if str(meta.get("显示名") or "") == display:
            raise FileExistsError(f"已经有一个工程叫「{display}」（目录名 {p['id']}）")

    d = root / pid
    d.mkdir(parents=True)
    meta = {
        "schema": SCHEMA,
        "工程目录名": pid,
        "显示名": display,
        "建项时间": datetime.now().isoformat(timespec="seconds"),
        "来源": "用户新建",
    }
    meta_path(pid).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


# ---------------------------------------------------------------- 读
def list_projects() -> list[dict]:
    """工程列表：内核给的订单统计 + 我们补的显示名。"""
    _bind()
    out: list[dict] = []
    for p in _orders.list_projects():
        meta = _read_meta(p["id"])
        out.append({
            "id": p["id"],
            "显示名": str(meta.get("显示名") or p["id"]),
            "order_count": p["order_count"],
            "updated_at": p["updated_at"],
            "建项时间": str(meta.get("建项时间") or ""),
            "有meta": meta_path(p["id"]).is_file(),
        })
    return out


def list_orders(project: str | None = None) -> list[dict]:
    _bind()
    return _orders.list_orders(project)


def get_order(project: str, order_id: str) -> dict | None:
    _bind()
    return _orders.load_order(order_id, project)
