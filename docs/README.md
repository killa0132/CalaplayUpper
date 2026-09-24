# CalaplayUpper 文档索引

> **对外首页** = 根目录的 **`README.md`**（面向使用者：功能介绍 / 下载 / 五步上手 / 界面预览）
> 与 **`README.en.md`**（英文版）。
> **开发与参考文档** = 本目录的 **`DEVELOPER_GUIDE.md`**（原 README 全文移过来的）与
> **`DEVELOPER_GUIDE.en.md`**。
> 跨会话的开工规则与当前状态在 **`AGENTS.md`**。

## 先看哪一份

| 你想知道 | 看这里 |
|---|---|
| 这工具是干什么的、怎么下载、怎么用 | `..\README.md`（英文 `..\README.en.md`） |
| CLI 开关、A0~A7 判据、原理、体积 | `.\DEVELOPER_GUIDE.md` |
| 界面每个文件是干什么的、怎么起开发服务器 | `.\DEVELOPER_GUIDE.md` §5 与 §12 |
| 跨会话续做要遵守什么、当前进度到哪 | `..\AGENTS.md` |
| 每次改完要跑哪些验证 | `.\DEVELOPER_GUIDE.md` §12.3 |

## 本目录的文件

| 文件 | 讲什么 | 状态 |
|---|---|---|
| `DEVELOPER_GUIDE.md` | **开发者/参考文档全集**（原 `README.md` 全文）：CLI 使用与开关、安全机制、A0~A7 判据、原理、体积、GUI 各轮迭代、开发与调试指南、更多界面图集 | 2026-09-24 从仓库根目录移到此处；内容即当时的最新版 |
| `DEVELOPER_GUIDE.en.md` | 上面那份的**英文版** | 同上 |
| `2026-09-23_gui_design.md` | GUI（G0）的**原始设计**：进程边界（FastAPI + PyWebView）、令牌守卫、SSE 日志通道、为什么 GUI 必须复用 `core.builder.Builder`、`gui/dist` 随包的决定 | 设计意图仍有效，但界面细节已被后续六轮迭代超过；以 `DEVELOPER_GUIDE.md` §10 为准 |
| `cleanup_plan_20260924.md` | 2026-09-24 的**文件梳理清单**：待删（≈3.46 GB）、必须保留的三处（`tools-src\obj` / `fakegame` 沙箱 / venv）、执行脚本与验收顺序 | 已按用户确认执行（`scripts\clean.ps1 -Apply -IncludeLogs`） |
| `images/` | README 与开发文档里用到的截图 / 动图 / 猫图（截图已压成 JPEG） | 随仓库走；`logs/` 里的原始 PNG 不进 git |

## 相关但不在本目录

| 位置 | 内容 |
|---|---|
| `..\README.md` | 对外首页（中文）：功能介绍、下载、五步上手、界面预览、注意事项 |
| `..\README.en.md` | 对外首页英文版（两份顶部互链） |
| `..\scripts\clean.ps1` | 文件梳理（默认 dry-run，`-Apply` 才删） |
| `..\scripts\check_dist.ps1` | 交付 Kit 的文件清单契约校验 |
| `..\scripts\publish_release.ps1` | 把 `dist\release\*.zip` 传到 GitHub Release（可选 `-Proxy`） |
| `..\logs\` | 每轮自检 / 回归的日志与截图（当前证据，不进 git）；历史证据在 `..\logs\archive\` |
| `..\..\CalabiyauGalMaker\docs\PROJECT_HANDOFF.md` | 上游工程的逆向取证与历史交付件（CP-32 为止，已到第 62 节） |
