"""orders.py —— 工程/订单持久化层（两级：工程 → 订单，订单内按版本留档）。

用户拍板（决策 #16）：产出要"按工程和订单区分"；删除走"归档式两步"——
  删 = 自动打 zip 保险 + 移入回收站(可还原)；清空回收站才真删。

目录约定（环境变量 BESTPIC_ORDERS_DIR 可覆盖，测试隔离用）：
    assets/orders/<工程>/
        <订单>/
            session.json   整单归档（meta + history + pending + 指标）
            src_<原名>      原图副本
            out/            每版 PNG（预览）+ BMP（1bit 上机档）
    assets/orders/.trash/   回收站（可还原，清空前不真删）
    assets/archive/         自动 zip 保险档

版本历史：v1 平铺单层 → v2 工程/订单两级（老目录启动时自动迁入「默认工程」）。
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PROJECT_DEFAULT = "默认工程"
TRASH_NAME = ".trash"
ARCHIVE_NAME = "archive"


def orders_root() -> Path:
    """订单根目录；测试可用环境变量 BESTPIC_ORDERS_DIR 隔离。"""
    env = os.environ.get("BESTPIC_ORDERS_DIR")
    return Path(env) if env else ROOT / "assets" / "orders"


def trash_dir() -> Path:
    return orders_root() / TRASH_NAME


def archive_dir() -> Path:
    """zip 保险档目录（orders 的上级，避免被当工程扫描）。"""
    return orders_root().parent / ARCHIVE_NAME


def _rewrite_order_paths(project_dir: Path, order_id: str) -> None:
    """迁移/搬移后修正 session.json 里的绝对路径（指向新位置）。

    v1 平铺 → v2 工程两级：订单目录位置变了，但归档里 src_path / history.img /
    thumb / last_report 都存着旧绝对路径 → 回放会打不开图。把旧前缀替换成新目录。
    幂等：旧前缀不存在时自动跳过。
    """
    d = project_dir / order_id
    f = d / "session.json"
    if not f.is_file():
        return
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    old_prefix = str(orders_root() / order_id)  # v1 平铺时的绝对路径前缀
    new_dir = str(d)
    if old_prefix == new_dir:
        return
    changed = False

    def fix(v):
        nonlocal changed
        if isinstance(v, str):
            if old_prefix in v:
                changed = True
                return v.replace(old_prefix, new_dir)
            return v
        if isinstance(v, list):
            return [fix(x) for x in v]
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items()}
        return v

    data = fix(data)
    if changed:
        tmp = f.with_name("session.json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(f)


def ensure_structure() -> None:
    """启动时调用一次：建目录 + v1 平铺老订单迁入「默认工程」（幂等），
    并修正一切指向旧位置的归档路径（含之前迁移中断留下的坏档）。"""
    root = orders_root()
    root.mkdir(parents=True, exist_ok=True)
    default = root / PROJECT_DEFAULT
    for d in root.iterdir():
        if d.is_dir() and not d.name.startswith(".") and d.name != PROJECT_DEFAULT:
            if (d / "session.json").is_file():
                default.mkdir(exist_ok=True)
                dst = default / d.name
                if not dst.exists():
                    d.rename(dst)
                _rewrite_order_paths(default, d.name)
    default.mkdir(exist_ok=True)
    # 兜底：把历史迁移可能留下的旧路径全部修正（幂等，开销小）
    for pid in _project_ids(root):
        pd = root / pid
        for sub in pd.iterdir():
            if sub.is_dir() and (sub / "session.json").is_file():
                _rewrite_order_paths(pd, sub.name)
    archive_dir().mkdir(exist_ok=True)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ts_suffix() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


# ---------- 查询 ----------
def _project_ids(root: Path) -> list[str]:
    return sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )


def list_projects() -> list[dict]:
    """工程列表：默认工程恒排第一，其余按最近更新时间倒序。"""
    ensure_structure()
    root = orders_root()
    others: list[dict] = []
    for pid in _project_ids(root):
        d = root / pid
        count = 0
        last = ""
        for sub in d.iterdir():
            f = sub / "session.json"
            if sub.is_dir() and f.is_file():
                count += 1
                try:
                    meta = json.loads(f.read_text(encoding="utf-8"))
                    u = str(meta.get("updated_at") or "")
                    if u > last:
                        last = u
                except Exception:  # noqa: BLE001
                    pass
        if pid == PROJECT_DEFAULT:
            others.insert(0, {"id": pid, "order_count": count, "updated_at": last})
        else:
            others.append({"id": pid, "order_count": count, "updated_at": last})
    default_first = [p for p in others if p["id"] == PROJECT_DEFAULT]
    rest = sorted(
        (p for p in others if p["id"] != PROJECT_DEFAULT),
        key=lambda p: p["updated_at"], reverse=True,
    )
    return default_first + rest


def list_orders(project: str | None = None) -> list[dict]:
    """订单摘要（跨工程按更新时间倒序）；project 给定则只列该工程。"""
    ensure_structure()
    root = orders_root()
    out: list[dict] = []
    pids = [project] if project else _project_ids(root)
    for pid in pids:
        pd = root / pid
        if not pd.is_dir():
            continue
        for d in pd.iterdir():
            f = d / "session.json"
            if not d.is_dir() or not f.is_file():
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 —— 单个坏档不拖垮整列
                continue
            out.append({
                "order_id": data.get("order_id") or d.name,
                "project": pid,
                "src_name": data.get("src_name") or d.name,
                "created_at": data.get("created_at") or "",
                "updated_at": data.get("updated_at") or "",
                "thumb": data.get("thumb"),
                "n_ver": data.get("n_ver") or 0,
            })
    out.sort(key=lambda o: o["updated_at"], reverse=True)
    return out


def list_latest_order() -> dict | None:
    lst = list_orders()
    return lst[0] if lst else None


def order_dir(order_id: str, project: str | None = None) -> Path:
    return orders_root() / (project or PROJECT_DEFAULT) / order_id


def load_order(order_id: str, project: str | None = None) -> dict | None:
    """读整单归档；不存在/坏档返回 None。meta 里补 project 字段。"""
    f = order_dir(order_id, project) / "session.json"
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    data["project"] = (project or PROJECT_DEFAULT)
    return data


# ---------- 写入 ----------
def save_order(
    order_id: str,
    *,
    history: list,
    src_path: str | None,
    src_name: str,
    project: str | None = None,
    last_report: dict | None = None,
    created_at: str | None = None,
    pending: dict | None = None,
    first_request: str | None = None,
    first_mm: float | None = None,
    local_ops: list | None = None,
) -> Path:
    """整单落盘（原子写：先写 .tmp 再 replace，防写一半）。

    pending: 尚未执行完的"出首版/反馈"任务——落盘后刷新也能自动续跑。
    local_ops: ③ 九宫格累积的局部调整（全量口径）——随订单落盘，重开/刷新后全量重放。
    """
    pid = project or PROJECT_DEFAULT
    d = order_dir(order_id, pid)
    d.mkdir(parents=True, exist_ok=True)

    thumb = None
    n_ver = 0
    for h in history:
        if h.get("img"):
            thumb = h["img"]
            n_ver += 1

    data = {
        "order_id": order_id,
        "project": pid,
        "src_path": src_path,
        "src_name": src_name,
        "created_at": created_at or _now_iso(),
        "updated_at": _now_iso(),
        "last_report": last_report,
        "thumb": thumb,
        "n_ver": n_ver,
        "pending": pending,
        "first_request": first_request,
        "first_mm": first_mm,
        "local_ops": list(local_ops or []),
        "history": history,
    }
    f = d / "session.json"
    tmp = d / "session.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)
    return f


# ---------- 保险 + 回收站 ----------
def export_order_zip(order_id: str, project: str | None = None) -> Path | None:
    """把整单打成 zip 到 archive/（原图+对话+全部版本），返回 zip 路径。"""
    src = order_dir(order_id, project)
    if not src.is_dir():
        return None
    base = archive_dir() / f"{order_id}-{_ts_suffix()}"
    return Path(shutil.make_archive(str(base), "zip", root_dir=str(src)))


def _into_trash(src: Path, origin: dict) -> Path:
    """进回收站：复制进 .trash 再删源（rename 在沙箱下偶发拒绝；复制更稳）。"""
    trash_dir().mkdir(parents=True, exist_ok=True)
    marker = src / ".origin.json"
    marker.write_text(json.dumps(origin, ensure_ascii=False), encoding="utf-8")
    dst = trash_dir() / f"{_ts_suffix()}-{src.name}"
    if dst.exists():
        dst = trash_dir() / f"{_ts_suffix()}-{int(time.time() * 1000)}-{src.name}"
    shutil.copytree(src, dst)
    shutil.rmtree(src, ignore_errors=True)
    return dst


def trash_order(order_id: str, project: str | None = None) -> Path:
    """删订单=归档式两步之一：自动 zip 保险 → 移回收站。"""
    pid = project or PROJECT_DEFAULT
    export_order_zip(order_id, pid)   # 保险
    return _into_trash(order_dir(order_id, pid), {"kind": "order", "order_id": order_id, "project": pid})


def trash_project(project: str) -> list[Path]:
    """删工程：先给工程内每个订单打 zip 保险，再把整个工程目录移入回收站。"""
    if project == PROJECT_DEFAULT:
        raise ValueError("默认工程不能删除")
    root = orders_root()
    src = root / project
    if not src.is_dir():
        raise FileNotFoundError(f"工程不存在: {project}")
    for sub in src.iterdir():
        if sub.is_dir() and (sub / "session.json").is_file():
            export_order_zip(sub.name, project)
    return [_into_trash(src, {"kind": "project", "project": project})]


def list_trash() -> list[dict]:
    """回收站内容：每个条目含原始归属（读 .origin.json）。"""
    t = trash_dir()
    out: list[dict] = []
    if t.is_dir():
        for d in sorted(t.iterdir(), key=lambda p: p.name, reverse=True):
            if not d.is_dir():
                continue
            origin = {"kind": "unknown"}
            mf = d / ".origin.json"
            if mf.is_file():
                try:
                    origin = json.loads(mf.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    pass
            out.append({"trash_path": str(d), "name": d.name, "origin": origin})
    return out


def restore_trash(trash_path: str | Path) -> Path:
    """从回收站还原（回到原工程/原单号位置；目标已存在则报错）。"""
    item = Path(trash_path)
    mf = item / ".origin.json"
    origin = {"kind": "unknown"}
    if mf.is_file():
        try:
            origin = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    root = orders_root()
    if origin.get("kind") == "project":
        dst = root / str(origin["project"])
    elif origin.get("kind") == "order":
        dst = root / str(origin.get("project", PROJECT_DEFAULT)) / str(origin["order_id"])
    else:
        raise ValueError("回收站条目缺少来源标记，无法自动还原")
    if dst.exists():
        raise FileExistsError(f"目标位置已存在：{dst}（请先处理同名项）")
    dst.parent.mkdir(parents=True, exist_ok=True)
    item.rename(dst)
    return dst


def purge_trash(trash_path: str | Path) -> None:
    """彻底删除回收站里的一个条目（不可恢复，UI 需二次确认）。"""
    shutil.rmtree(Path(trash_path), ignore_errors=True)


def purge_all_trash() -> int:
    n = 0
    for item in list_trash():
        shutil.rmtree(item["trash_path"], ignore_errors=True)
        n += 1
    return n
