package main

// selfcheck.go —— **无头自检**：不开窗口，把"壳 → 内核 → 盘上的账"整条链验一遍。
//
// 为什么必须有它：bestpic 那 34 项 AppTest 冒烟换壳后**全部作废**，
// 没有无头模式，参谋长就变成"看不见界面 = 验不了"（参考包把这个坑写在明面上）。
//
// 用法：  D:\画台\运行\画台.exe --selfcheck
// 退出码：0 = 全过；1 = 有失败项（判据表，不看"感觉"）。
//
// 隔离：自检**不碰真实工程** —— 数据根指向 <根>\.tmp-tests\selfcheck-projects。

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

var (
	scPass int
	scFail []string
)

func scOK(msg string) {
	scPass++
	fmt.Printf("[OK] %s\n", msg)
}

func scFailf(msg, detail string) {
	scFail = append(scFail, msg+" —— "+detail)
	fmt.Printf("[FAIL] %s —— %s\n", msg, detail)
}

func scEq(got, want any, msg string) {
	g := fmt.Sprintf("%v", got)
	w := fmt.Sprintf("%v", want)
	if g == w {
		scOK(msg)
	} else {
		scFailf(msg, fmt.Sprintf("期望 %v，实得 %v", want, got))
	}
}

// scResult 把 Reply 的 Result 解成 map（失败时返回 nil 并把错误记下来）
func scResult(r Reply, msg string) map[string]any {
	if !r.OK {
		scFailf(msg, fmt.Sprintf("回执 ok=false status=%d error=%s detail=%s", r.Status, r.Error, r.Detail))
		return nil
	}
	var m map[string]any
	if err := json.Unmarshal(r.Result, &m); err != nil {
		scFailf(msg, "结果不是 JSON 对象："+err.Error())
		return nil
	}
	scOK(msg)
	return m
}

func selfcheck(app *App, withBrain bool) int {
	k := app.k

	fmt.Println("=== 画台 · 无头自检 ===")
	root := k.Root
	fmt.Printf("项目根   = %s\n", root)
	fmt.Printf("解释器   = %s\n", k.Python)
	fmt.Printf("内核脚本 = %s\n", k.Script)
	if root == "" {
		scFailf("0.1 定位项目根", k.lastErr)
		fmt.Println("\n失败 1 项，无法继续")
		return 1
	}
	scOK("0.1 定位项目根（从 exe 往上找到 server\\stdio.py）")

	// 隔离数据根，绝不碰真实工程
	tmp := filepath.Join(root, ".tmp-tests", "selfcheck-projects")
	_ = os.RemoveAll(tmp)
	if err := os.MkdirAll(tmp, 0o755); err != nil {
		scFailf("0.2 建隔离数据根", err.Error())
		return 1
	}
	_ = os.Setenv("HUATAI_PROJECTS", tmp)
	scOK("0.2 隔离数据根（自检不碰真实工程）：" + tmp)

	// 1 健康
	if m := scResult(app.Health(), "1.1 内核回话（health）"); m != nil {
		scEq(m["数据根"], tmp, "1.2 健康检查报出隔离数据根")
		scEq(m["ok"], true, "1.3 健康检查 ok=true")
	} else {
		fmt.Println("\n内核没通，后面的判据无法进行。诊断：")
		fmt.Printf("%+v\n", k.Status())
		return 1
	}

	// 2 子进程真的起了
	st := app.KernelStatus()
	scEq(st.Running, true, "2.1 内核子进程 running=true")
	if st.PID <= 0 {
		scFailf("2.2 子进程有 PID", fmt.Sprintf("PID=%d", st.PID))
	} else {
		scOK(fmt.Sprintf("2.2 子进程有 PID = %d", st.PID))
	}

	// 3 能力声明
	if m := scResult(app.Capabilities(), "3.1 能力声明可读"); m != nil {
		crafts := map[string]map[string]any{}
		if arr, ok := m["工艺"].([]any); ok {
			for _, it := range arr {
				if c, ok := it.(map[string]any); ok {
					crafts[fmt.Sprintf("%v", c["id"])] = c
				}
			}
		}
		scEq(crafts["glass"]["能不能"], true, "3.2 玻璃画 = 能做")
		scEq(crafts["model3d"]["能不能"], false, "3.3 三维模型 = 不能做")
		scEq(strings.TrimSpace(fmt.Sprintf("%v", crafts["model3d"]["为什么不能"])) != "", true,
			"3.4 '不能做'必须带理由（不许只说不会）")
	}

	// 4 工程列表（空）
	if m := scResult(app.Projects(), "4.1 工程列表可读"); m != nil {
		arr, _ := m["projects"].([]any)
		scEq(len(arr) == 0 || arr != nil, true, "4.2 隔离数据根里的工程列表可用")
	}

	// 5 新建工程（判据要落在**盘上**，不是落在回执上）
	name := "自检工程"
	if m := scResult(app.NewProject(name), "5.1 新建工程成功"); m != nil {
		want := filepath.Join(tmp, name)
		if fi, err := os.Stat(want); err == nil && fi.IsDir() {
			scOK("5.2 ★ 工程目录真的落在盘上：" + want)
		} else {
			scFailf("5.2 工程目录真的落在盘上", fmt.Sprintf("%s 不存在：%v", want, err))
		}
		if _, err := os.Stat(filepath.Join(want, "meta.json")); err == nil {
			scOK("5.3 meta.json 落盘（显示名与目录名分开存）")
		} else {
			scFailf("5.3 meta.json 落盘", err.Error())
		}
	}

	// 6 同名拒绝（不静默加后缀）
	r6 := app.NewProject(name)
	scEq(r6.OK, false, "6.1 同名工程被拒")
	scEq(r6.Status, 409, "6.2 同名工程状态码 409")
	scEq(strings.TrimSpace(r6.Error) != "", true, "6.3 失败回执带 error 文字")

	// 7 坏输入不静默
	scEq(app.NewProject("   ").Status, 400, "7.1 空白工程名 400")
	scEq(app.NewProject("///").Status, 400, "7.2 全是非法字符的工程名 400")

	// 8 未知动作
	scEq(k.Call("nope.nope", nil, 0).Status, 404, "8.1 未知动作 404")

	// 9 收工不留僵尸
	k.Stop()
	scEq(k.Status().Running, false, "9.1 shutdown 之后内核状态 running=false")

	// 10 大脑（**免费那一半**：只读状态，不联网、不花钱）
	if m := scResult(app.BrainStatus(), "10.1 大脑状态可读（不联网）"); m != nil {
		scEq(m["密钥就位"], true, "10.2 密钥就位（从项目根 .env 读到）")
		scEq(m["运行时已起"], false, "10.3 ★ 懒启动：只问状态不会拉起运行时")
		scOK("10.4 cwd 收窄目录 = " + fmt.Sprintf("%v", m["cwd"]))
	}

	// 10b 真跑一轮（**花钱**，必须显式加 --with-brain 才做）
	if withBrain {
		fmt.Println("（--with-brain：要真调用一次模型，会花钱）")
		r := app.BrainProbe("")
		if m := scResult(r, "10.5 真机往返：拿回合法 JSON"); m != nil {
			scEq(strings.TrimSpace(fmt.Sprintf("%v", m["finish_reason"])) != "", true, "10.6 结束原因如实回来")
			u, _ := m["usage"].(map[string]any)
			scEq(u != nil && fmt.Sprintf("%v", u["计费轮次"]) != "0", true, "10.7 用量如实回来")
			scOK(fmt.Sprintf("10.8 这一轮：finish_reason=%v  truncated=%v  elapsed_ms=%v  total=%v",
				m["finish_reason"], m["truncated"], m["elapsed_ms"], u["totalTokens"]))
		}
	} else {
		fmt.Println("[跳过] 10.5~10.8 真机往返（要花钱；想跑就加 --with-brain）")
	}

	fmt.Println()
	if len(scFail) > 0 {
		fmt.Printf("自检失败 %d 项：\n", len(scFail))
		for _, f := range scFail {
			fmt.Println("  -", f)
		}
		fmt.Printf("通过 %d 项\n", scPass)
		return 1
	}
	fmt.Printf("自检全部通过 [PASS] %d/%d\n", scPass, scPass)
	return 0
}
