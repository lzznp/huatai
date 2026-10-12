package main

// app.go —— 壳暴露给前端的全部能力。
//
// ★ 规矩：这里**不做任何业务判断**，只把请求转给内核（Python），把回执原样交给前端。
// 业务在 server\dispatch.py；账在 projects\；壳只负责"起进程、搬 JSON、显示"。

import (
	"context"
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

// IntentRound ★ 猜意图一轮：把小助手的话拿回来。**要给足超时**（要真调用模型）。
func (a *App) IntentRound(project string, order string, text string) Reply {
	return a.k.Call("intent.round",
		map[string]any{"project": project, "order": order, "text": text}, brainTimeout)
}

// CapabilityPrompt 看清小助手眼里的能力清单（与界面读的是同一份）——排查用。
func (a *App) CapabilityPrompt() Reply {
	return a.k.Call("capabilities.prompt", nil, 20*time.Second)
}
