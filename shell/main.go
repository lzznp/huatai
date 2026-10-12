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
	for _, a := range os.Args[1:] {
		if a == "--selfcheck" || a == "-selfcheck" {
			os.Exit(selfcheck(app))
		}
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
