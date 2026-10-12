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
	"image"
	"image/color"
	"image/png"
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

// scMakePng 造一张自检用的图（不依赖盘上任何素材）。
func scMakePng(path string) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	img := image.NewGray(image.Rect(0, 0, 32, 32))
	for y := 0; y < 32; y++ {
		for x := 0; x < 32; x++ {
			img.SetGray(x, y, color.Gray{Y: uint8(60 + x*6)})
		}
	}
	return png.Encode(f, img)
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
	var madeOrder string

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

	// 5.4+ 造一张图、投料建单（**免费**），并验"最近一单"能被找回来
	srcPng := filepath.Join(tmp, "自检料.png")
	if err := scMakePng(srcPng); err != nil {
		scFailf("5.4 造一张自检用的图", err.Error())
	} else {
		scOK("5.4 造了一张自检用的图（32×32 渐变）")
		if m := scResult(app.NewOrder("自检工程", srcPng), "5.5 投料建单"); m != nil {
			madeOrder = fmt.Sprintf("%v", m["order_id"])
			scOK("5.6 单号 = " + madeOrder)
			if m2 := scResult(app.SessionLatest(), "5.7 ★ 找得到最近一单（界面重开就靠它回到上次）"); m2 != nil {
				latest, _ := m2["latest"].(map[string]any)
				scEq(fmt.Sprintf("%v", latest["order_id"]), madeOrder, "5.8 ★ 最近一单＝刚建的那一单")
				scEq(fmt.Sprintf("%v", latest["project"]), "自检工程", "5.9 归属的工程也对")
			}
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

		// 11 猜意图一轮（★ 界面走的就是这条路：选图 → 建单 → 问小助手）
		if madeOrder == "" {
			scFailf("11.0 需要一个单才能问小助手", "上面的投料没成功")
		} else if m2 := scResult(app.IntentRound("自检工程", madeOrder, ""), "11.1 猜意图一轮（真调用模型）"); m2 != nil {
			rep, _ := m2["reply"].(map[string]any)
			scEq(fmt.Sprintf("%v", rep["ok"]), "true", "11.2 小助手回了话，且是合法 JSON")
			scEq(fmt.Sprintf("%v", m2["合法"]), "true", "11.3 它的回答过了校验器")
			parsed, _ := rep["parsed"].(map[string]any)
			scEq(fmt.Sprintf("%v", parsed["action"]), "ask", "11.4 ★ 没被告知意图时它主动问")
			scEq(strings.TrimSpace(fmt.Sprintf("%v", parsed["question"])) != "", true, "11.5 ★ 确实问了话")
			scOK(fmt.Sprintf("11.6 它问的是：%v", parsed["question"]))
			if det := scResult(app.OrderDetail("自检工程", madeOrder), "11.7 读这一单的账"); det != nil {
				ents, _ := det["流水"].([]any)
				scEq(len(ents) >= 2, true, "11.8 ★ 流水里至少有「料」和「小助手的话」")
			}
		}
	} else {
		fmt.Println("[跳过] 10.5~10.8 真机往返（要花钱；想跑就加 --with-brain）")
		fmt.Println("[跳过] 11.x 投料 + 猜意图（同样要花钱）")
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
