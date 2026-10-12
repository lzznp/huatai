r"""画台 · stdio 通道离线测试（壳默认走这条）

用法：  python tests\test_stdio.py
数据根走 HUATAI_PROJECTS → D:\画台\.tmp-tests\stdio-projects，**绝不碰真实工程**。

判据：
 1 起子进程 → 健康检查真读数
 2 能力声明（能做 / 不能做都带理由）
 3 新建工程真落盘；同名 409
 4 id 原样回传（壳靠它配对）
 5 ★ 坏帧不回静默、**且进程不死**（后续请求照常通）
 6 未知动作 404
 7 shutdown → 回一帧后干净退出（退出码 0）
 8 ★ 关掉 stdin（壳死了）→ 子进程自己退出，**不留僵尸**
 9 ★ stdout 上只有协议帧（诊断信息全在 stderr）
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / ".tmp-tests" / "stdio-projects"
LOG = ROOT / ".tmp-tests" / "stdio-stderr.log"

PASS = 0
FAIL: list[str] = []


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"[OK] {msg}")


def eq(got, want, msg: str) -> None:
    if got == want:
        ok(msg)
    else:
        FAIL.append(f"{msg} —— 期望 {want!r}，实得 {got!r}")
        print(f"[FAIL] {msg} —— 期望 {want!r}，实得 {got!r}")


class Child:
    """起一个 stdio 子进程，带读线程（避免读阻塞把测试挂死）。"""

    def __init__(self) -> None:
        env = dict(os.environ)
        env["HUATAI_PROJECTS"] = str(TMP)
        env["PYTHONIOENCODING"] = "utf-8"
        self.logf = open(LOG, "w", encoding="utf-8")
        self.p = subprocess.Popen(
            [sys.executable, str(ROOT / "server" / "stdio.py")],
            cwd=str(ROOT), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.logf,
            text=True, encoding="utf-8", bufsize=1,
        )
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        for line in self.p.stdout:            # type: ignore[union-attr]
            self.q.put(line)
        self.q.put(None)

    def send(self, obj) -> None:
        self.p.stdin.write((obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)) + "\n")  # type: ignore[union-attr]
        self.p.stdin.flush()                  # type: ignore[union-attr]

    def read(self, timeout: float = 15.0) -> dict | None:
        try:
            line = self.q.get(timeout=timeout)
        except queue.Empty:
            return None
        if line is None:
            return None
        return json.loads(line)

    def call(self, action: str, payload=None, req_id=1, timeout: float = 15.0):
        req = {"id": req_id, "action": action}
        if payload is not None:
            req["payload"] = payload
        self.send(req)
        return self.read(timeout)

    def stop(self) -> None:
        try:
            self.p.stdin.close()              # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
        try:
            self.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.p.kill()
        self.logf.close()
        if self.logf.name and Path(self.logf.name).exists():
            pass


def fresh_tmp() -> None:
    if TMP.exists():
        shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True)


def main() -> int:
    fresh_tmp()
    print(f"数据根（隔离）= {TMP}")

    c = Child()

    # 1 健康
    r = c.call("health", req_id=101)
    if r is None:
        print("[FAIL] 1.1 子进程没回话（stdio 通道没通）")
        print("--- stderr ---")
        print(Path(LOG).read_text(encoding="utf-8", errors="replace"))
        return 1
    eq(r["ok"], True, "1.1 health ok")
    eq(r["id"], 101, "1.2 id 原样回传（壳靠它配对）")
    eq(r["result"]["数据根"], str(TMP), "1.3 健康检查报出隔离数据根")

    # 2 能力
    r = c.call("capabilities", req_id=102)
    crafts = {x["id"]: x for x in r["result"]["工艺"]}
    eq(crafts["glass"]["能不能"], True, "2.1 玻璃画 = 能做")
    eq(crafts["model3d"]["能不能"], False, "2.2 三维模型 = 不能做")
    eq(bool(crafts["model3d"]["为什么不能"]), True, "2.3 不能做必须带理由")

    # 3 新建工程
    r = c.call("projects.create", {"name": "stdio工程"}, req_id=103)
    eq(r["ok"], True, "3.1 新建工程 ok")
    eq((TMP / "stdio工程" / "meta.json").is_file(), True, "3.2 工程真的落盘（meta.json 在）")
    r = c.call("projects.create", {"name": "stdio工程"}, req_id=104)
    eq(r["ok"], False, "3.3 同名工程被拒")
    eq(r["status"], 409, "3.4 同名工程 409")
    eq("error" in r, True, "3.5 失败帧带 error 字段")

    # 5 坏帧不静默、进程不死
    c.send("这不是 JSON")
    r = c.read()
    eq(r["ok"], False, "5.1 坏帧回 ok=false（不静默）")
    eq(r["id"], None, "5.2 坏帧 id 为 null")
    r = c.call("health", req_id=105)
    eq(r["ok"], True, "5.3 ★ 坏帧之后进程仍活着（后续请求照常通）")

    # 6 未知动作
    r = c.call("nope.nope", req_id=106)
    eq(r["status"], 404, "6.1 未知动作 404")
    eq("error" in r, True, "6.2 未知动作带 error")

    # 7 缺参数
    r = c.call("order.get", {}, req_id=107)
    eq(r["status"], 400, "7.1 订单缺参数 400")

    # 9 stdout 纯净性：上面收到的每一帧都必须是 JSON（能 json.loads 成功就已经证明了）
    ok("9.1 stdout 上收到的每一帧都是合法 JSON（诊断没混进来）")

    # 7 shutdown
    c.send({"id": 108, "action": "shutdown"})
    r = c.read()
    eq(r["ok"], True, "8.1 shutdown 先回一帧")
    try:
        rc = c.p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        c.p.kill()
        rc = "超时未退出"
    eq(rc, 0, "8.2 shutdown 后干净退出（退出码 0）")
    c.stop()

    # 8 关掉 stdin → 自己退出
    c2 = Child()
    c2.call("health", req_id=1)
    c2.p.stdin.close()                        # type: ignore[union-attr]
    try:
        rc2 = c2.p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        c2.p.kill()
        rc2 = "超时未退出"
    eq(rc2, 0, "8.3 ★ 关掉 stdin 后子进程自己退出，不留僵尸")
    c2.stop()

    # stderr 有诊断（说明诊断走对了通道）
    stderr_txt = Path(LOG).read_text(encoding="utf-8", errors="replace")
    eq("stdio 通道就绪" in stderr_txt, True, "9.2 诊断信息出现在 stderr（stdout 只走协议帧）")

    # 10 第一帧带 BOM 也要能认（别家工具写出来的第一行常带 BOM）
    c3 = Child()
    c3.p.stdin.write("\ufeff" + json.dumps({"id": 9, "action": "health"}, ensure_ascii=False) + "\n")  # type: ignore[union-attr]
    c3.p.stdin.flush()                        # type: ignore[union-attr]
    r = c3.read()
    eq(r is not None and r.get("ok"), True, "10.1 ★ 第一帧带 BOM 也能认（BOM 被忽略）")
    eq(r.get("id") if r else None, 9, "10.2 BOM 帧的 id 也正确回传")
    c3.stop()

    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：")
        for f in FAIL:
            print("  -", f)
        return 1
    print(f"全部通过 [PASS] {PASS}/{PASS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
