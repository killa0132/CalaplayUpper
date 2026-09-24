# CalaplayUpper 文档索引

> 工程主入口是根目录的 **`README.md`**（怎么用、原理、判据、体积、开发与调试指南）。
> 这里放的是"设计与过程文档"，按用途分类。跨会话的开工规则与当前状态在 **`AGENTS.md`**。

## 先看哪一份

| 你想知道 | 看这里 |
|---|---|
| 这工具怎么用、判据是什么、怎么重新构建 | `..\README.md` |
| 界面每个文件是干什么的、怎么起开发服务器 | `..\README.md` §5 与 §12 |
| 跨会话续做要遵守什么、当前进度到哪 | `..\AGENTS.md` |
| 每次改完要跑哪些验证 | `..\README.md` §12.3 |

## 本目录的文件

| 文件 | 讲什么 | 状态 |
|---|---|---|
| `2026-09-23_gui_design.md` | GUI（G0）的**原始设计**：进程边界（FastAPI + PyWebView）、令牌守卫、SSE 日志通道、为什么 GUI 必须复用 `core.builder.Builder`、`gui/dist` 随包的决定 | 设计意图仍有效，但界面细节已被后续三轮迭代超过；以 `README.md` §10 为准 |
| `cleanup_plan_20260924.md` | 2026-09-24 的**文件梳理清单**：待删（≈3.46 GB）、必须保留的三处（`tools-src\obj` / `fakegame` 沙箱 / venv）、执行脚本与验收顺序 | 已按用户确认执行（`scripts\clean.ps1 -Apply -IncludeLogs`） |

## 相关但不在本目录

| 位置 | 内容 |
|---|---|
| `..\README.md` | 工程主文档（中文）：怎么用、原理、判据、体积、GUI 各轮、开发与调试指南 |
| `..\README.en.md` | 同一份文档的**英文版**（面向 GitHub 国际访客，两份顶部互链） |
| `..\scripts\clean.ps1` | 文件梳理（默认 dry-run，`-Apply` 才删） |
| `..\scripts\check_dist.ps1` | 交付 Kit 的文件清单契约校验 |
| `..\logs\` | 每轮自检 / 回归的日志与截图（当前证据）；历史证据在 `..\logs\archive\` |
| `..\..\CalabiyauGalMaker\docs\PROJECT_HANDOFF.md` | 上游工程的逆向取证与历史交付件（CP-32 为止，已到第 62 节） |
