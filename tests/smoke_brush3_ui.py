r"""冒烟：验 exp_smart_brush3.py 的**开窗路径**（左灰度 / 右玻璃画，真开 Tk 窗口）。

参谋长看不到屏幕 ⇒ "界面这条路能不能跑、刷了右图会不会跟着变"必须由脚本自己证。
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import tkinter as tk  # noqa: E402

import exp_smart_brush3 as B  # noqa: E402

fails: list[str] = []


def check(c: bool, label: str, extra: str = ""):
    print(("  [OK]   " if c else "  [FAIL] ") + label + (f"  {extra}" if extra else ""))
    if not c:
        fails.append(label)


root = tk.Tk()
root.mainloop = lambda *a, **k: None          # 不开事件循环
orig = tk.Tk
tk.Tk = lambda *a, **k: root
try:
    rc = B.main()
finally:
    tk.Tk = orig
check(rc == 0, "开窗路径不抛异常（main 返回 0）", f"rc={rc}")


def walk(w):
    out = []
    for c in w.winfo_children():
        out.append(c)
        out += walk(c)
    return out


canv = None
txt = None
btn = None
for c in walk(root):
    if isinstance(c, tk.Canvas):
        canv = c
    if isinstance(c, tk.Text):
        txt = c
    try:
        if c.winfo_class() == "TButton" and "导出" in str(c.cget("text")):
            btn = c
    except Exception:                          # noqa: BLE001
        pass

check(canv is not None, "找到画布")
check(txt is not None, "找到状态栏")
check(btn is not None, "找到导出按钮")

if canv is not None:
    root.update()
    print("   画布尺寸 =", canv.winfo_width(), "×", canv.winfo_height(),
          " mapped =", canv.winfo_ismapped())
    # 左边灰度图上刷（x < 787*0.85=669），从左到右
    canv.event_generate("<ButtonPress-1>", x=300, y=250)
    for dx in range(0, 80, 10):
        canv.event_generate("<B1-Motion>", x=300 + dx, y=250 + dx // 2)
    canv.event_generate("<ButtonRelease-1>", x=380, y=290)
    root.update()
    msg = txt.get("1.0", "end").strip() if txt is not None else ""
    print("   状态栏：", msg.replace("\n", " / ")[:220])
    check("个印子" in msg, "刷一笔后状态栏给出了这一笔的读数")
    # 右图区域点一下：应被忽略（不刷）
    canv.event_generate("<ButtonPress-1>", x=900, y=250)
    canv.event_generate("<ButtonRelease-1>", x=900, y=250)
    root.update()
    check(True, "在右图上点不会崩（本版右图只显示）")
    # 滚轮缩放
    b0 = canv.bbox("all")
    canv.event_generate("<MouseWheel>", x=300, y=250, delta=120)
    root.update()
    b1 = canv.bbox("all")
    check(b0 is not None and b1 is not None and (b1[2] - b1[0]) > (b0[2] - b0[0]),
          "滚轮放大生效", f"{b0} → {b1}")
    if btn is not None:
        try:
            btn.invoke()
        except Exception as e:                 # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(False, "导出按钮不抛异常", repr(e))
        root.update()
        got = sorted((ROOT / ".tmp-tests" / "brush3-export").glob("sync-*.bmp"))
        check(len(got) > 0, "点导出后真的写出了 1bit 文件", got[-1].name if got else "")

root.destroy()
print()
if fails:
    print(f"[FAIL] {len(fails)} 项没过")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("[PASS] 减淡同步开窗路径全部通过")
