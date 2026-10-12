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
import shutil
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
    """工程列表：内核给的订单统计 + 我们补的显示名。

    ★ 藏掉**空的「默认工程」**：内核每次调用都会自动建它（`ensure_structure()` 里无条件 mkdir，
    删了还会再建），而它 0 单时对用户只是噪音（用户 2026-10-12 提）。
    **但它一旦有单就必须照常显示** —— 我们只藏空的，绝不藏数据。
    """
    _bind()
    out: list[dict] = []
    for p in _orders.list_projects():
        if p["id"] == _orders.PROJECT_DEFAULT and not p["order_count"]:
            continue
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


def latest_order() -> dict | None:
    """**最近动过的那一单**（跨工程），没有就返回 None。

    为什么放在后端而不是前端：界面"重开就回到上次"这条行为，
    如果写在前端就是一段没人验得着的猜测；放在这里，**无头自检能直接验**。
    （注意：工程列表恒把「默认工程」排第一，所以前端不能靠"取第一个工程"来猜最近用过哪个。）
    """
    _bind()
    lst = _orders.list_orders(None)          # 跨工程、按 updated_at 倒序
    if not lst:
        return None
    o = lst[0]
    return {
        "project": o.get("project"),
        "order_id": o.get("order_id"),
        "src_name": o.get("src_name"),
        "updated_at": o.get("updated_at"),
        "n_ver": o.get("n_ver") or 0,
    }


def get_order(project: str, order_id: str) -> dict | None:
    _bind()
    return _orders.load_order(order_id, project)


def save_render(project: str, order_id: str, *, history: list, last_report: dict,
                local_ops: list | None = None, created_at: str | None = None) -> Path:
    """出图之后更新整单归档。

    ★ 必须**保留原有字段**（`src_path` / `src_name` / `pending` / `first_request` / `first_mm`）——
    只覆盖 `history` / `last_report` / `local_ops`。
    否则就是"旋钮静默归零"那一类 bug 在**订单层**的翻版：一次出图把别的东西悄悄冲掉了。
    """
    _bind()
    data = get_order(project, order_id) or {}
    return _orders.save_order(
        order_id,
        history=history,
        src_path=data.get("src_path"),
        src_name=data.get("src_name") or "",
        project=project,
        last_report=last_report,
        created_at=created_at or data.get("created_at"),
        pending=data.get("pending"),
        first_request=data.get("first_request"),
        first_mm=data.get("first_mm"),
        local_ops=list(local_ops if local_ops is not None else (data.get("local_ops") or [])),
    )


def order_image(project: str, order_id: str, which: str = "png", *, ver: int | None = None) -> dict:
    """把某一版产物读成 data URL 给界面显示（壳只搬字节，不解图）。

    which: "png"（预览）或 "bmp"（上机档点阵）
    ver:   要哪一版；不给就取最新那一版
    ★ 每张都带 sha256 —— 界面显示的和账里记的是不是同一张，一对便知。
    """
    import base64
    import hashlib

    data = get_order(project, order_id)
    if data is None:
        raise FileNotFoundError(f"没找到这张单：{project}\\{order_id}")

    history = [h for h in (data.get("history") or []) if h.get(_IMG_KEY[which])]
    if not history:
        raise FileNotFoundError("这一单还没有出过图（先让助手出一版）")

    if ver is None:
        item = history[-1]
    else:
        match = [h for h in history if int(h.get("ver") or 0) == int(ver)]
        if not match:
            raise FileNotFoundError(f"没有第 {ver} 版")
        item = match[-1]

    p = Path(item[_IMG_KEY[which]])
    if not p.is_file():
        raise FileNotFoundError(f"账里有这一版，但文件不在了：{p}")

    raw = p.read_bytes()
    mime = "image/png" if p.suffix.lower() == ".png" else "image/bmp"
    return {
        "路径": str(p),
        "名字": p.name,
        "字节": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "版本": int(item.get("ver") or 0),
        "data_url": f"data:{mime};base64," + base64.b64encode(raw).decode("ascii"),
    }


# ================================================================ 订单（单 = 一张图 + 一段对话）
#
# 账的形状（一单一个目录，**只进不改 + 只追加**）：
#     projects\<工程>\<订单>\
#         session.json     整单归档（版本链 / 指标 / 局部调整）—— 内核 orders.py 的格式
#         src_<原名>       原图副本（★ 只进不改：进来之后任何代码都不许改写它）
#         out\             每版产物：<stem>.png（预览）+ <stem>.bmp（1bit 上机档）
#         transcript.jsonl 与小助手的对话流水（一行一回合，**只追加**，不重写）
#
# 为什么单 = 一张图：跟内核一致（bestpic 决策 #7「每张图/每单活 = 一个 session_id」）。
# 一个工程可以有很多单（很多张图）。

TRANSCRIPT_NAME = "transcript.jsonl"

# 订单历史里产物的键名：预览图叫 "img"（内核 orders.py 的老约定），上机档叫 "bmp"。
# 别拿 which 直接当键去查 —— 本文件建立当天就因为这个取不到图（测试抓出来的）。
_IMG_KEY = {"png": "img", "bmp": "bmp"}

# 流水里每行都必须带 kind —— 参考包判据「流水三分」：人说的话 / 壳塞进去的材料 /
# 机器出的结论，**三者不许混**（界面要分开显示，否则聊天里掺满内部日志）。
KINDS = ("user", "assistant", "material", "action", "system")


def order_path(project: str, order_id: str) -> Path:
    return projects_root() / project / order_id


def transcript_path(project: str, order_id: str) -> Path:
    return order_path(project, order_id) / TRANSCRIPT_NAME


def _new_order_id(project: str) -> str:
    base = "order-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    oid, n = base, 1
    while order_path(project, oid).exists():
        n += 1
        oid = f"{base}-{n}"
    return oid


def create_order(project: str, src: str, *, origin: str = "用户投料") -> dict:
    """投料：把一张图收进某个工程，建一张单。

    规矩：
    - 工程必须已存在（不偷偷新建）
    - 只吃图片（其余料明说读不了 —— 凭据在 capabilities）
    - 源文件必须真的存在，且**复制**进来（原件不动）
    - 复制进来的副本此后**只进不改**
    """
    from server import capabilities as CAP  # 局部导入，避免循环

    _bind()
    pdir = project_path(project)
    if not pdir.is_dir():
        raise FileNotFoundError(f"没有这个工程：{project}（先建工程再投料）")

    src_p = Path(src)
    if not src_p.is_file():
        raise FileNotFoundError(f"找不到这个文件：{src}")

    ok, why = CAP.can_read_material(src_p.name)
    if not ok:
        raise ValueError(why)

    oid = _new_order_id(project)
    d = order_path(project, oid)
    (d / "out").mkdir(parents=True)

    # 原图副本：只进不改
    dst = d / f"src_{src_p.name}"
    shutil.copy2(src_p, dst)

    _orders.save_order(
        oid,
        history=[],
        src_path=str(dst),
        src_name=src_p.name,
        project=project,
    )
    # 空流水先落一个文件，让"账的形状"一眼可见（内容是追加出来的）
    transcript_path(project, oid).touch()

    append_transcript(project, oid, {
        "kind": "material",
        "text": f"投料：{src_p.name}",
        "data": {"原件": str(src_p), "副本": str(dst), "来源": origin},
    })

    return {
        "order_id": oid,
        "project": project,
        "目录": str(d),
        "src": str(dst),
        "原件": str(src_p),
    }


def append_transcript(project: str, order_id: str, entry: dict) -> dict:
    """往对话流水里追加**一行**（只追加，绝不重写整份）。

    每行必须带 kind（见 KINDS）——不许把"人说的话"和"机器给的结论"混成一行。
    """
    p = order_path(project, order_id)
    if not p.is_dir():
        raise FileNotFoundError(f"没有这张单：{project}\\{order_id}")

    if not isinstance(entry, dict):
        raise ValueError("流水条目必须是 JSON 对象")
    kind = entry.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind 必须是 {KINDS} 之一，收到 {kind!r}")

    line = {
        "at": entry.get("at") or datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "text": str(entry.get("text") or ""),
    }
    if isinstance(entry.get("data"), dict):
        line["data"] = entry["data"]

    f = transcript_path(project, order_id)
    with f.open("a", encoding="utf-8") as fh:      # ★ 追加，不是重写
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        fh.flush()
    return line


def read_transcript(project: str, order_id: str) -> dict:
    """读回对话流水。坏行**不丢**，单独报出来（不许静默吞掉）。"""
    f = transcript_path(project, order_id)
    if not f.is_file():
        return {"entries": [], "坏行": 0}
    entries, bad = [], 0
    for raw in f.read_text(encoding="utf-8").splitlines():
        raw = raw.strip().lstrip("\ufeff")
        if not raw:
            continue
        try:
            entries.append(json.loads(raw))
        except json.JSONDecodeError:
            bad += 1
    return {"entries": entries, "坏行": bad}


def order_detail(project: str, order_id: str) -> dict:
    """一单的全貌：归档 + 流水 + 产物清单（界面用）。"""
    data = get_order(project, order_id)
    if data is None:
        raise FileNotFoundError(f"没找到这张单：{project}\\{order_id}")
    d = order_path(project, order_id)
    out = d / "out"
    files = []
    if out.is_dir():
        files = sorted(p.name for p in out.iterdir() if p.is_file())
    tr = read_transcript(project, order_id)
    return {
        "订单": data,
        "目录": str(d),
        "产物": files,
        "流水": tr["entries"],
        "流水坏行": tr["坏行"],
    }
