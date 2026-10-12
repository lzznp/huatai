package main

// app.go —— 壳暴露给前端的全部能力。
//
// ★ 规矩：这里**不做任何业务判断**，只把请求转给内核（Python），把回执原样交给前端。
// 业务在 server\dispatch.py；账在 projects\；壳只负责"起进程、搬 JSON、显示"。

import (
	"context"
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
