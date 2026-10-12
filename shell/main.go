package main

import (
	"embed"
	"os"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	app := NewApp()

	// 无头自检：不开窗口把整条链验一遍（"看不见界面 = 验不了"的解法）
	// --with-brain 会真调用一次模型（花钱），默认不做。
	// 注意：先把两个开关都扫完再动手 —— 否则 `--selfcheck --with-brain` 会因为
	// 先碰到 --selfcheck 就直接退出，把后面的参数漏掉。
	withBrain, doCheck := false, false
	for _, a := range os.Args[1:] {
		switch a {
		case "--with-brain":
			withBrain = true
		case "--selfcheck", "-selfcheck":
			doCheck = true
		}
	}
	if doCheck {
		os.Exit(selfcheck(app, withBrain))
	}

	err := wails.Run(&options.App{
		Title:     "画台",
		Width:     1280,
		Height:    840,
		MinWidth:  980,
		MinHeight: 620,
		AssetServer: &assetserver.Options{
			Assets: assets,
		},
		BackgroundColour: &options.RGBA{R: 27, G: 38, B: 54, A: 1},
		OnStartup:        app.startup,
		OnShutdown:       app.shutdown,
		Bind: []interface{}{
			app,
		},
	})

	if err != nil {
		println("Error:", err.Error())
	}
}
