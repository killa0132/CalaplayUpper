# CalaplayUpper 文档索引

> **对外首页** = 根目录的 **`README.md`**（面向使用者：功能介绍 / 下载 / 五步上手 / 界面预览）
> 与 **`README.en.md`**（英文版）。
> **开发与参考文档** = 本目录的 **`DEVELOPER_GUIDE.md`**（原 README 全文移过来的）与
> **`DEVELOPER_GUIDE.en.md`**。
> 跨会话的开工规则与当前状态在本地 `AGENTS.md`（**内部工作笔记，不进仓库**）。

## 先看哪一份

| 你想知道 | 看这里 |
|---|---|
| 这工具是干什么的、怎么下载、怎么用 | `..\README.md`（英文 `..\README.en.md`） |
| CLI 开关、A0~A7 判据、原理、体积 | `.\DEVELOPER_GUIDE.md` |
| 界面每个文件是干什么的、怎么起开发服务器 | `.\DEVELOPER_GUIDE.md` §5 与 §12 |
| 跨会话续做要遵守什么、当前进度到哪 | 本地 `AGENTS.md`（**内部笔记，不在仓库里**） |
| 每次改完要跑哪些验证 | `.\DEVELOPER_GUIDE.md` §12.3 |
| 想把自己的 Mod 和别人**共存**（不互相覆盖） | `.\MOD_MERGE_PROTOCOL.md` |

## 本目录的文件

| 文件 | 讲什么 | 状态 |
|---|---|---|
| `DEVELOPER_GUIDE.md` | **开发者/参考文档全集**（原 `README.md` 全文）：CLI 使用与开关、安全机制、A0~A7 判据、原理、体积、GUI 各轮迭代、开发与调试指南、更多界面图集 | 2026-09-24 从仓库根目录移到此处；内容即当时的最新版 |
| `DEVELOPER_GUIDE.en.md` | 上面那份的**英文版** | 同上 |
| `RELEASE_NOTES_v1.2.0.md` | **v1.2.0 发布说明（中英双语）**：多 Mod 合并、合并完自动装进游戏、错误卡片、引导滚动与语言持久化、回滚按钮；可直接当 GitHub Release 正文用 | 2026-09-28；下载表里的体积/哈希由 `scripts\pack_release.ps1` 生成 |
| `RELEASE_NOTES_v1.1.0.md` | **v1.1.0 发布说明**（历史）：路线 B 的 2560×1440、预览图集与时间轴/预览块、缩略图修复、宽高比约束、多 Mod 共存协议 | 2026-09-26 发布时所用正文（历史记录；其中指向已归档评估文档的链接不再有效） |
| `2026-09-23_gui_design.md`（已清理） | GUI（G0）的**原始设计**：进程边界（FastAPI + PyWebView）、令牌守卫、SSE 日志通道、为什么 GUI 必须复用 `core.builder.Builder`、`gui/dist` 随包的决定 | 2026-09-28 由作者从仓库移除；设计意图仍有效，现以 `DEVELOPER_GUIDE.md` §10 为准 |
| `cleanup_plan_20260924.md`（已清理） | 2026-09-24 的**文件梳理清单**：待删（≈3.46 GB）、必须保留的三处（`tools-src\obj` / `fakegame` 沙箱 / venv）、执行脚本与验收顺序 | 2026-09-28 由作者从仓库移除；清单已按确认执行（`scripts\clean.ps1 -Apply -IncludeLogs`） |
| `MOD_MERGE_PROTOCOL.md` | **统一 Mod 合并协议（PoC）**：总索引 / 各 Mod manifest 字段、`da_edit` 行级操作与行号语义、`ui_text` 文件级合并、冲突判定规则（C1~C4）、M0~M6 判据、CLI 用法、真机安装、实测数据、已知限制 | 2026-09-27 新建；实现 = `core/merger.py` + `cli/merge_mods.py` + `scripts/merge_mods.{ps1}` + `scripts/install_merged.ps1`，回归 T30~T33 |
| `MOD_MERGE_PROTOCOL_REVIEW_XG.md` | **给 Xenon-XG 的 review 材料**（对外发的一份）：真实数据实测摘要、他现有 manifest 的逐字段体检、协议最小集、**待他拍板的 7 件事**、复现命令 | 2026-09-27 新建；协议全文见上一份 |
| `images/` | README 与开发文档里用到的截图 / 动图 / 猫图（截图已压成 JPEG） | 随仓库走；`logs/` 里的原始 PNG 不进 git |

> 早期的 CP 评估 / 设计文档（`2026-09-23_gui_design.md`、`cleanup_plan_20260924.md`、`CP35_*`、
> `CP36_*`、`CP37_*` 等）已于 2026-09-28 由作者从仓库清理，**不在仓库内**；它们记录的过程与结论
> 已经并入本目录的 `DEVELOPER_GUIDE.md`、根目录 `CHANGELOG.md` 与 `MOD_MERGE_PROTOCOL.md`，
> 所以仓库里的正文不再引用那些文件名（只在本表里留下"已清理"的痕迹）。

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
