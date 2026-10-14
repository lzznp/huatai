package main

// app.go —— 壳暴露给前端的全部能力。
//
// ★ 规矩：这里**不做任何业务判断**，只把请求转给内核（Python），把回执原样交给前端。
// 业务在 server\dispatch.py；账在 projects\；壳只负责"起进程、搬 JSON、显示"。

import (
	"context"
	"encoding/json"
	"strings"
	"time"

	wailsRuntime "github.com/wailsapp/wails/v2/pkg/runtime"
)

type App struct {
	ctx context.Context
	k   *Kernel
}

func NewApp() *App {
	return &App{k: NewKernel()}
}

func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
}

func (a *App) shutdown(ctx context.Context) {
	a.k.Stop()
}

// ---------------------------------------------------------------- 诊断（不是业务）

// KernelStatus 给界面看内核子进程的现状：根目录、解释器、PID、最近的诊断。
func (a *App) KernelStatus() Status {
	return a.k.Status()
}

// ---------------------------------------------------------------- 业务（一字不加地转发）

func (a *App) Health() Reply {
	return a.k.Call("health", nil, 0)
}

func (a *App) Capabilities() Reply {
	return a.k.Call("capabilities", nil, 0)
}

func (a *App) Projects() Reply {
	return a.k.Call("projects.list", nil, 0)
}

func (a *App) NewProject(name string) Reply {
	return a.k.Call("projects.create", map[string]any{"name": name}, 0)
}

func (a *App) Orders(project string) Reply {
	return a.k.Call("orders.list", map[string]any{"project": project}, 0)
}

// SessionLatest ★ 最近动过的那一单（跨工程）——界面一打开就靠它回到上次，
// 这样"切工程/重开窗口 看不到对话"这类事不会再有。
func (a *App) SessionLatest() Reply {
	return a.k.Call("session.latest", nil, 20*time.Second)
}

// ---------------------------------------------------------------- 大脑（第 4a 步：只读往返）

// BrainStatus 大脑配置与运行时状态（不花钱、不联网）。
func (a *App) BrainStatus() Reply {
	return a.k.Call("brain.status", nil, 20*time.Second)
}

// BrainProbe 问一句、拿回 JSON。★ **要给足超时**：首次要拉起运行时（10~60s），
// 加上模型本身的往返，所以这里给 5 分钟，不能用默认的 60 秒。
func (a *App) BrainProbe(prompt string) Reply {
	p := map[string]any{}
	if prompt != "" {
		p["prompt"] = prompt
	}
	return a.k.Call("brain.probe", p, brainTimeout)
}

const brainTimeout = 5 * time.Minute

// ---------------------------------------------------------------- 投料与对话（第 4b 步）

// PickImage 弹系统的选图对话框（只有壳能做这件事，Python 那边做不了）。
// 取消选择返回空串 —— **那是正常结果，不是错误**。
func (a *App) PickImage() string {
	path, err := wailsRuntime.OpenFileDialog(a.ctx, wailsRuntime.OpenDialogOptions{
		Title: "选一张图（玻璃画 / 叶雕 / 剪纸）",
		Filters: []wailsRuntime.FileFilter{
			{DisplayName: "图片 (*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff;*.webp)",
				Pattern: "*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff;*.webp"},
		},
	})
	if err != nil {
		return ""
	}
	return path
}

// NewOrder 投料建单（把选到的图收进某个工程）。
func (a *App) NewOrder(project string, src string) Reply {
	return a.k.Call("orders.create", map[string]any{"project": project, "src": src}, 60*time.Second)
}

// OrderDetail 一单全貌：归档 + 流水 + 产物。
func (a *App) OrderDetail(project string, order string) Reply {
	return a.k.Call("order.detail", map[string]any{"project": project, "id": order}, 30*time.Second)
}

// OrderImage 取某一版产物给界面显示（壳只搬字节，不解图）。
// which: "png" 预览 / "bmp" 上机档点阵；ver<=0 表示要最新那一版。
func (a *App) OrderImage(project string, order string, which string, ver int) Reply {
	p := map[string]any{"project": project, "order": order}
	if strings.TrimSpace(which) != "" {
		p["which"] = which
	}
	if ver > 0 {
		p["ver"] = ver
	}
	return a.k.Call("order.image", p, 60*time.Second)
}

// RegionPreview ★ 把某个「位置词」裁出来高亮（2026-10-13）：
// 小助手说"左边一列"，界面就把那一块裁出来给用户看，**认了才动手**。
// 壳同样只搬字节：裁剪与高亮都在 Python 侧做，这里只转发。
func (a *App) RegionPreview(project string, order string, region string) Reply {
	return a.k.Call("region.preview", map[string]any{
		"project": project, "order": order, "region": region,
	}, 60*time.Second)
}

// RegionList 位置词表总览（排查用：每个词的像素范围与占比）。
func (a *App) RegionList() Reply {
	return a.k.Call("region.list", nil, 30*time.Second)
}

// RenderRun 手动出一版（★ 界面平时靠"小助手一轮"自动出；这个是给自检和排查用的）。
func (a *App) RenderRun(project string, order string, knobsJSON string, localJSON string) Reply {
	p := map[string]any{"project": project, "order": order}
	if strings.TrimSpace(knobsJSON) != "" {
		var k map[string]any
		if err := json.Unmarshal([]byte(knobsJSON), &k); err != nil {
			return Reply{OK: false, Status: 400, Error: "knobs 不是合法 JSON", Detail: err.Error()}
		}
		p["knobs"] = k
	}
	if strings.TrimSpace(localJSON) != "" {
		var ops []any
		if err := json.Unmarshal([]byte(localJSON), &ops); err != nil {
			return Reply{OK: false, Status: 400, Error: "local 不是合法 JSON 数组", Detail: err.Error()}
		}
		p["local"] = ops
	}
	return a.k.Call("render.run", p, 2*time.Minute)
}

// IntentRound ★ 猜意图一轮：把小助手的话拿回来。**要给足超时**（要真调用模型）。
func (a *App) IntentRound(project string, order string, text string) Reply {
	return a.k.Call("intent.round",
		map[string]any{"project": project, "order": order, "text": text}, brainTimeout)
}

// CapabilityPrompt 看清小助手眼里的能力清单（与界面读的是同一份）——排查用。
func (a *App) CapabilityPrompt() Reply {
	return a.k.Call("capabilities.prompt", nil, 20*time.Second)
}
