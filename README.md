# 画台

画台是面向玻璃激光雕刻图和剪纸图的本地图像处理工具。用户通过对话描述效果，程序将要求转换为处理参数，生成预览和导出文件，并保存工程记录。

## 项目结构

桌面界面使用 Go + Wails，Python 服务负责业务处理，图像内核负责按参数出图。桌面端默认通过 stdio 与 Python 子进程交换 JSON；HTTP 接口用于独立调试。

| 路径 | 内容 |
|---|---|
| `shell/` | Wails 桌面应用，前端资源从 `frontend/dist/` 嵌入 |
| `server/` | 对话、意图解析、出图调度与工程存储 |
| `kernel/` | 图像处理流水线、参数、区域编辑和模型接口 |
| `tests/` | 离线测试、接口测试与出图实验 |
| `工作文档/` | 接口说明、设计决策与开发记录 |
| `settings.json` | 本地解释器配置 |

各工艺的支持范围见 [server/capabilities.py](server/capabilities.py)，图像处理约定见[内核规则手册](kernel/规则手册.md)。

## 配置与启动

目前的桌面开发环境为 Windows。构建需要 Go、Wails 和 WebView2；Python 环境主要使用 NumPy、Pillow、python-dotenv 和 deepseek-harness-sdk。

先在 [settings.json](settings.json) 中设置 `python` 解释器路径，也可以通过环境变量覆盖：

| 变量 | 用途 |
|---|---|
| `HUATAI_PYTHON` | Python 解释器路径，优先于配置文件 |
| `HUATAI_PROJECTS` | 工程数据目录 |
| `HUATAI_MODEL` | 对话模型 |

模型服务密钥放在项目根目录的 `.env` 中，变量名为 `DEEPSEEK_API_KEY`。

在仓库根目录执行：

```powershell
cd shell
wails build
.\build\bin\画台.exe
```

产物位于 `shell/build/bin/`。程序通过向上查找 `server/stdio.py` 定位项目根目录，因此移动 exe 时应保留可定位到源码目录的层级关系。前端资源直接嵌入，无需另跑 npm 构建。

## 服务与测试

桌面端会启动自己的 Python 子进程，无需预先运行 HTTP 服务。独立调试可在仓库根目录执行：

```powershell
python -m server --http --port 8612
```

离线测试入口：

```powershell
powershell -File tests/run_offline_all.ps1
```

仓库中另有调用真实模型的 smoke 和 probe 脚本，运行这些脚本需要模型服务配置，并会产生 API 用量。

## 数据与部署记录

`projects/` 保存原图、处理结果和对话记录，需要单独备份。`.env`、模型会话缓存、日志和构建产物不纳入版本控制。

此前在受限开发工作区运行 exe 时出现过 WebView2 `8000ffff` 错误，移到普通开发目录后恢复。相关环境和排查过程保留在[项目说明](工作文档/00-先读我.md)中，供遇到相同问题时参考。

## 开发文档

- [接口、运行环境与测试说明](工作文档/00-先读我.md)
- [交接记录](工作文档/HANDOFF.md)
- [设计决策](工作文档/决策记录.md)
- [后续事项](工作文档/待完善.md)
