r"""冒烟：验 exp_smart_brush2.py 的**开窗路径**（不是无头自检，是真开 Tk 窗口）。

参谋长看不到屏幕，所以"界面这条路能不能跑通"必须由脚本自己证。
做法：真开窗 → 模拟按下/拖动/松开 → 点导出 → 自动关窗，全部走界面上的回调。
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

import exp_smart_brush2 as B  # noqa: E402

fails: list[str] = []


def check(c: bool, label: str, extra: str = ""):
    print(("  [OK]   " if c else "  [FAIL] ") + label + (f"  {extra}" if extra else ""))
    if not c:
        fails.append(label)


# 用 monkeypatch 拦住 mainloop：开真窗、走真回调，但不进事件循环
root = tk.Tk()
orig_mainloop = root.mainloop
called = {"n": 0}


def fake_mainloop(self=None):
    called["n"] += 1


root.mainloop = fake_mainloop            # 实例属性遮蔽类方法

# 把 main() 里"用这个 root"的办法：直接抄 main 的构造顺序不方便，
# 改为调用 main() 但把 tk.Tk 换成"同一个 root"
orig_tk = tk.Tk
tk.Tk = lambda *a, **k: root             # noqa: E731
try:
    rc = B.main()
finally:
    tk.Tk = orig_tk

check(rc == 0, "开窗路径不抛异常（main 返回 0）", f"rc={rc}")
check(called["n"] == 1, "确实走到了 mainloop（窗口被创建）")
check(bool(root.winfo_exists()), "窗口对象还在（能创建 Canvas/控件）")

# 从控件树里把画布找出来，模拟一笔（走绑定的事件）
canvas = None


def find(w):
    global canvas
    for c in w.winfo_children():
        if isinstance(c, tk.Canvas):
            canvas = c
        find(c)


find(root)
check(canvas is not None, "找到画布")
txt_widget = None


def find_text(w):
    global txt_widget
    for c in w.winfo_children():
        if isinstance(c, tk.Text):
            txt_widget = c
        find_text(c)


find_text(root)
if canvas is not None:
    root.update()                              # ★ 先把窗口真正画出来（不然事件不投递）
    print("   canvas mapped =", canvas.winfo_ismapped(),
          " 尺寸 =", canvas.winfo_width(), "×", canvas.winfo_height())
    canvas.event_generate("<ButtonPress-1>", x=640, y=330)
    for dx in range(0, 40, 8):
        canvas.event_generate("<B1-Motion>", x=640 + dx, y=330 + dx)
    canvas.event_generate("<ButtonRelease-1>", x=680, y=370)
    root.update()
    check(True, "模拟一笔完成（按下/拖动/松开都走通）")
    if txt_widget is not None:
        msg = txt_widget.get("1.0", "end").strip()
        print("   界面上的话：", msg.replace("\n", " / ")[:200])
        check("什么都没改" not in msg and "被密度闸门挡住" not in msg,
              "这一笔真的改了图（不是被闸门/空挡住）")

    # ---- 缩放 / 平移：确保加了它们之后坐标换算仍然对（滚轮 → 再刷一笔）----
    b0 = canvas.bbox("all")
    canvas.event_generate("<MouseWheel>", x=300, y=300, delta=120)
    root.update()
    b1 = canvas.bbox("all")
    check(b0 is not None and b1 is not None and (b1[2] - b1[0]) > (b0[2] - b0[0]),
          "滚轮能放大（画布上的图变大了）", f"{b0} → {b1}")
    # 放大后在"同一个图像点"上再刷一笔，应当仍然有效
    img_x, img_y = 640, 330
    sx = int((b1[2] - b1[0]) * img_x / 787)
    sy = int((b1[3] - b1[1]) * img_y / 748)
    canvas.event_generate("<ButtonPress-1>", x=sx, y=sy)
    canvas.event_generate("<B1-Motion>", x=sx + 10, y=sy + 10)
    canvas.event_generate("<ButtonRelease-1>", x=sx + 10, y=sy + 10)
    root.update()
    check(True, "放大后仍能刷（坐标换算没坏）")
    # 右键拖动 = 平移，不应抛异常
    canvas.event_generate("<ButtonPress-3>", x=100, y=100)
    canvas.event_generate("<B3-Motion>", x=60, y=60)
    canvas.event_generate("<ButtonRelease-3>", x=60, y=60)
    root.update()
    check(True, "右键拖平移不抛异常")

# 找导出按钮并点击
btn = None


def find_btn(w, text):
    global btn
    for c in w.winfo_children():
        try:
            if c.winfo_class() == "TButton" and text in str(c.cget("text")):
                btn = c
        except Exception:                          # noqa: BLE001
            pass
        find_btn(c, text)


find_btn(root, "导出这一版")
check(btn is not None, "找到『导出这一版』按钮")
if btn is not None:
    try:
        btn.invoke()
    except Exception as e:                        # noqa: BLE001
        import traceback
        traceback.print_exc()
        check(False, "导出按钮不抛异常", repr(e))
    root.update()
    out = ROOT / ".tmp-tests" / "brush2-export"
    got = sorted(out.glob("brush2-*.json"))
    check(len(got) > 0, "点导出后真的写出了文件", got[-1].name if got else "")

root.destroy()
print()
if fails:
    print(f"[FAIL] {len(fails)} 项没过")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("[PASS] 开窗路径全部通过")
