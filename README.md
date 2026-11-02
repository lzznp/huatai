# 画台（huatai）

用**自然语言对话**把"玻璃激光雕刻画 / 剪纸画"的口头需求，变成**确定性**的参数与出图产物。

> 三个角色（2026-10-12 用户拍板）：
> **用户** 主要跟"小助手"对话干活；**小助手** 就是本项目的产品（被观察的对象）；
> **参谋长** 是 DSH 里的那个对话 —— 建小助手、写代码、定判据，不替小助手干活。

## 三层结构

| 层 | 目录 | 是什么 |
|---|---|---|
| 壳 | `shell/` | Wails 应用（Go + 前端；前端不用 npm，`dist` 直接 `go:embed`） |
| 服务 | `server/` | Python 服务（纯标准库 HTTP，**唯一写入口**）：`app.py` / `brain.py` / `capabilities.py` / `dispatch.py` / `intent.py` / `render.py` / `store.py` |
| 内核 | `kernel/` | 确定性图像内核：`image_lib/pipeline.py` / `knobs.py` / `orders.py` / `controller.py` / `region_canvas.py` / `regions.py` / `agent_bridge.py` / `规则手册.md` |
| 测试 | `tests/` | 离线测试与实验脚本（smoke / 探针 / 出图判据） |
| 文档 | `工作文档/` | ★ 项目记忆，入口是 [`工作文档/00-先读我.md`](工作文档/00-先读我.md)（接口文档） |
| 运行 | `运行/` | `画台.exe`（**不入库**，双击这个跑） |

## 怎么跑

```powershell
# 1) 直接跑（已构建好）
D:\画台\运行\画台.exe

# 2) 从源码构建（Go + Wails 环境）
cd D:\画台\shell
wails build          # 产物 shell\build\bin\画台.exe（中文 exe 名可用）
```

**Python 解释器**由 [`settings.json`](settings.json) 的 `python` 字段指定（默认 `bestpic` 环境，
必须装有 `numpy` / `Pillow` / `deepseek-harness-sdk`）；环境变量优先：
`HUATAI_PYTHON`（解释器）、`HUATAI_PROJECTS`（工程数据根）。

## 为什么整套在 `D:\画台`（工作区之外）

实测（不是照抄）：工作区里的 exe 是 **Low 完整性**（`S-1-16-4096`）→ WebView2 崩 `8000ffff`；
同一个 exe 放到 `D:\画台` 就是 **High 完整性**（`S-1-16-12288`）。只有位置这一个变量，cwd 无关。
详见 `工作文档/00-先读我.md` §一。

> ⚠️ 因此：DSH 会话要**改**这个目录，需要 `danger-full-access`；只读权限下参谋长只能看不能写。

## 这个仓库里**故意没有**什么（`.gitignore` 里挡着）

| 没入库 | 为什么 |
|---|---|
| `.env` | 里面有 `DEEPSEEK_API_KEY` 等真凭据 |
| `projects/` | 用户的工程项目数据（原图与产物，体积会很大）；它的备份是另一件事 |
| `.dsh_home/`、`.agent-cwd/` | 智能体运行期会话缓存（会无限增长，资产不该和运行时格式耦合） |
| `.tmp-tests/`、`archive/` | 临时物与旧归档 |
| `shell/build/`、`运行/`、`*.exe` | 构建产物与运行物（重新 `wails build` 即可） |
| `__pycache__/`、`*.log`、`.venv/` | 语言/工具垃圾 |

## 读文档的顺序

1. [`工作文档/00-先读我.md`](工作文档/00-先读我.md) —— **接口文档**：怎么干活 / 目录 / 已验判据 / 坑 / 下一步
2. [`工作文档/HANDOFF.md`](工作文档/HANDOFF.md) —— 交接包
3. [`工作文档/决策记录.md`](工作文档/决策记录.md) —— 决策表（**别重开已决事项**）
4. [`工作文档/待完善.md`](工作文档/待完善.md) —— 想到但先不做的清单
5. 各场 `会话报告-*.md` / `阶段总结-*.md` —— 逐场记录

## 历史

- `2026-10-12` 建立于 `D:\画台`（从上个形态 `D:\玻璃画和剪纸画` 搬出，`bestpic` 冻结为参考代码）。
- `2026-11-01` 首次上 GitHub：18 个提交，91 个跟踪文件（约 0.58 MB）。
