# CalaPlayerSrcmBuilder GUI 改造方案（Vue 3 + FastAPI + PyWebView）

（2026-09-23 / 只读设计，**等你确认后再写代码**。CLI 版已跑通并通过 A0~A6 全部判据。）

> **状态：已实现（G0~G4 完成，G5 收口中）。** 方案按本文落地，三处拍板全部照办
> （`gui/dist` 随 Kit 分发 / 变体命名 `_gui_minimal_<date>`·`_gui_full_<date>`、
> exe 名 `CalaPlayerSrcmBuilderGUI.exe` / 做「取消打包」= 阶段边界取消）。
> 落地过程中抓到两个**只在打包成 exe 后才出现**的真 bug（源码模式全绿也会中招），
> 成因与修法见 `README.md` §10.5：① `--windowed` exe 没有 stdout 时 uvicorn
> 的日志 formatter 会 `AttributeError`，界面永远出不来；② 没有控制台时 .NET
> 工具用 ANSI 代码页写 stdout，`core/common.py` 却按 UTF-8 解码，非 ASCII
> 素材名会让 A7 直接判失败。两个都已修 + 已加回归（`tests/gui_exe_check.py`）。

---

## 0. 一句话

把已经验收过的 `core/` 打包管线**原封不动**留在原地，外面套一层
`FastAPI(本地回环) + Vue3(单页) + PyWebView(桌面壳)`；
GUI 与 CLI **调用同一个 `core.builder.Builder`**，因此 L0~L5、`-DryRun`、
自动回滚、`build.log` / `build_report.json`、`install.ps1` / `uninstall.ps1`
全部继承，不存在"两套逻辑"。

---

## 1. 现状（已完成的部分，GUI 直接复用）

```
core/
  common.py    Log(带 sink → 直接喂 SSE) / BuildError / run() / sha256
  config.py    srcm 目录识别、包路径、限额、命名清洗
  kit.py       retoc / da-patch / tex-inspect / ffmpeg 定位 + 封装
  bc1.py       BC1 编码器（已修 bug 版）+ cover/contain + PSNR/MAE/清晰度
  texture.py   cooked Texture2D 的 mip 链定位与同长替换
  wavutil.py   RIFF/WAVE 解析 + 合规判定
  da.py        DA_Backgrounds / DA_BGM / DA_Ambient / DA_Sounds **只追加**
  builder.py   L0..L5 编排 + 判据 + 报告      ← GUI 的唯一入口
cli/build_srcm.py   argparse 外壳（GUI 并存，不删）
main.py             PyInstaller 冻结入口
build_srcm.ps1 / build_kit.ps1
kit/                retoc / da-patch / tex-inspect / mappings / native
dist/CalaPlayerSrcmBuilder_minimal_20260923/   118.8 MB（无 ffmpeg）
dist/CalaPlayerSrcmBuilder_full_20260923/      323.1 MB（含 ffmpeg 204 MB）
```

**关键复用点**：`core.common.Log` 已经支持 `add_sink(fn)`。
GUI 只要 `log.add_sink(task.queue.put)` 就得到实时日志流 —— 不需要改动管线一行。

---

## 2. 目标目录结构

```
CalaplayUpper/
├─ core/                     ← 不动（CLI 与 GUI 共用）
├─ cli/build_srcm.py         ← 不动（命令行口子保留）
├─ main.py                   ← 不动（现在同时被 GUI 的 exe 复用）
├─ gui/
│  ├─ app.py                 FastAPI 应用（/api/*，SSE，静态托管）
│  ├─ desktop.py             PyWebView 壳（起服务 + 开窗 + 原生对话框）
│  ├─ tasks.py               任务注册表 + 线程 + 日志队列 + 取消标志
│  ├─ frontend/              Vue 3 + Vite 源码
│  │  ├─ index.html
│  │  ├─ vite.config.js      build.outDir = "../dist"
│  │  ├─ package.json
│  │  └─ src/
│  │     ├─ main.js
│  │     ├─ App.vue          布局：左表单 / 右日志
│  │     ├─ api.js           fetch + EventSource(SSE) 封装
│  │     ├─ components/
│  │     │  ├─ PathField.vue      输入框 + 「浏览…」按钮（调 /api/select_folder）
│  │     │  ├─ OptionPanel.vue    Fit 下拉 / DryRun·Combined·Force 勾选
│  │     │  ├─ RunBar.vue         大按钮 + 状态灯 + 进度阶段条
│  │     │  ├─ LogView.vue        实时日志（虚拟滚动 + 关键字高亮 + 自动滚底）
│  │     │  └─ ResultPanel.vue    A0~A6 判据表 + 部署/回滚结果 + 打开输出目录
│  │     └─ styles/
│  │        ├─ theme.css          变量（颜色/圆角/字体）
│  │        └─ uiverse/           从 Uiverse 抄来的纯 CSS 组件（原样引用）
│  └─ dist/                  ← vite 产物（被 PyInstaller 作为数据打进 exe）
├─ gui_main.py               GUI 版 PyInstaller 入口
└─ build_gui.ps1             前端构建 + 打包（生成第三个 Kit 变体）
```

---

## 3. 后端接口契约（FastAPI）

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/` | 托管 `gui/dist/index.html`（生产模式；开发模式走 Vite） |
| `POST` | `/api/start` | body：`{paks, srcm, fit, dry_run, combined, force, ffmpeg, kit}` → `{task_id}` |
| `GET` | `/api/logs/{task_id}` | **SSE** 实时推送日志行 |
| `GET` | `/api/report/{task_id}` | 结束后返回 `build_report.json` 的对象 |
| `POST` | `/api/cancel/{task_id}` | 请求取消（阶段边界生效） |
| `GET` | `/api/select_folder?kind=paks\|srcm` | 系统原生目录对话框，返回绝对路径 |
| `GET` | `/api/open_folder?what=out\|log` | 资源管理器打开 `out_patch` / `build.log` 所在目录 |
| `POST` | `/api/uninstall` | 调用交付目录里的 `uninstall.ps1`（一键回滚），返回读取的 stdout |
| `GET` | `/api/health` | 给 PyWebView 轮询"服务起来了没" |

### 3.1 SSE 载荷

```
data: {"line": "...", "stage": "L3", "ts": 1758...}     ← 每行日志
event: stage                                            ← 阶段切换（进度条用）
data: {"stage":"L2","state":"start"|"done","seconds":3.2}

event: done                                             ← 收尾，只发一次
data: {"ok": true, "report": {...}, "output": "D:\\...\\out_patch"}
```

前端用原生 `EventSource`（SSE 天生适合"只向下推"的场景，比 WebSocket 少一套心跳/重连逻辑）。

### 3.2 任务与线程模型

```
POST /api/start
   └─ tasks.create(params)             （主线程/uvicorn 线程）
        ├─ task = Task(id, queue=Queue(), cancel=Event())
        ├─ threading.Thread(target=run_build, args=(task,)).start()
        └─ return {task_id}

run_build(task):
   log = Log(path=<srcm parent>/build.log, echo=False)
   log.add_sink(task.push)                    ← 就是 GUI 实时日志的全部秘密
   b = Builder(Ctx(**params), log)
   try:    rep = b.run();  ok = True
   except BuildError as e: rep = b.report(False, str(e)); ok = False
   finally: task.push_done(ok, rep)
```

* uvicorn 跑在 **daemon 线程**，`127.0.0.1` + **随机空闲端口**（`socket.bind(0)` 探一个），
  避免和别的服务撞端口；
* PyWebView 必须在主线程（Windows 上 WebView2 的消息循环要求），
  所以 `desktop.py` 的顺序是：先起 uvicorn 线程 → 再 `webview.start()`；
* 启动时 `main.py` 生成一个随机 `token`，写进加载的 URL（`?t=...`），
  FastAPI 中间件校验 —— 防止本机其它程序乱调 `/api/start`（**只监听 127.0.0.1 + token 双重保险**）。

### 3.3 原生目录对话框

`pywebview` 的 `window.create_file_dialog(webview.FOLDER_DIALOG)` 由 Python 侧调用，
`desktop.py` 把 window 对象注册进 `app.py` 的一个模块级变量；
没有窗口（纯浏览器调试）时 `/api/select_folder` 返回 501，前端自动隐藏「浏览…」按钮。

---

## 4. 前端（Vue 3 + Vite）

* **技术栈**：Vue 3 (`<script setup>`) + Vite 5，**不引 UI 库**（你要求用 Uiverse 的纯 HTML/CSS 组件）。
* **自定义 CSS 无缝引入**：Vite 原生支持
  `import './styles/uiverse/glass-button.css'`（全局）或
  `<style scoped>@import './styles/uiverse/glass-button.css';</style>`（组件内）。
  Uiverse 拿到的组件是"HTML 片段 + 一段 CSS"，落地方式：
  1. CSS 存成 `styles/uiverse/<name>.css`（原样，不改类名避免冲突 → 外层再包一个 `.uv-scope` 前缀）；
  2. 组件的 `<template>` 照抄 HTML，把 `<button class="...">` 换成 `<button class="... uv-scope">`。
  *（如果不方便加前缀，也可以让 Vite 用 CSS Modules：`import s from './x.module.css'`，代价是要改类名引用。）*
* **界面元素**（你点名的全部）：游戏 Paks 路径输入框、srcm 路径输入框、Fit 下拉（cover/contain）、
  DryRun / Combined / Force 三个勾选、大按钮「开始打包」、右侧实时日志区（等宽字体 + 自动滚底 + `QUALITY:`/`GATE`/`AUDIO:` 高亮）。
* **状态机**：`idle → running → done|failed`，running 时禁用表单并提供「取消」。
* **开发模式**：`vite dev`（5173）→ `vite.config.js` 里 `server.proxy['/api'] = 'http://127.0.0.1:<port>'`，
  PyWebView 加载 `http://127.0.0.1:5173`；生产模式 PyWebView 加载 `http://127.0.0.1:<uvicorn port>/`
  （**不用 `file://`**，避免 `fetch`/`EventSource` 的跨源与 CORS 麻烦）。

---

## 5. 打包（第三个 Kit 变体）

```
build_gui.ps1
  1) cd gui/frontend && npm.cmd install && npm.cmd run build     → gui/dist
  2) python -m PyInstaller --onefile --windowed ^
        --add-data "gui\dist;gui\dist" ^
        --name CalaPlayerSrcmBuilderGUI ^
        --paths . ^
        gui_main.py
  3) 复制 kit/ 与 ffmpeg（可选）→
       dist/CalaPlayerSrcmBuilderGUI_gui_<date>/      （-minimal 变体）
       dist/CalaPlayerSrcmBuilderGUI_full_<date>/     （含 ffmpeg）
```

* `--windowed` 会吞掉 stdout → 必须靠 `build.log` 与 UI 内的日志区，这点已经在 CLI 里做好了。
* 冻结后的路径：`gui/dist` 从 `sys._MEIPASS` 读（`kit.app_root()` 已经处理 frozen 分支）；
  `kit/` 仍然**放在 exe 旁边**（自包含的前提，不能被塞进单文件）。
* 本机注意：`npm.ps1` 被执行策略拦住，脚本里统一用 **`npm.cmd`** 或 `node <npm-cli.js>`。

---

## 6. 风险 / 边界（请重点看这一节）

| 风险 | 处理 |
|---|---|
| GUI 引入的**回归**影响 CLI | GUI 只新增 `gui/` 与 `gui_main.py`；`core/`、`cli/`、两个 `build_*.ps1` 一个字节都不改（设计如此：`Builder` 是纯 Python 类，无全局状态） |
| 打包后体积再涨 ~30 MB | PyWebView 依赖 pythonnet/WebView2 → 预计 GUI 版比 CLI 版大；**CLI 版继续保留**，两条路并行 |
| 前端构建依赖 Node | 本机 Node v22.18 已就绪；`gui/dist` 的产物会**进仓库**，没装 Node 的机器也能直接跑（只有改前端才需要 Node） |
| SSE 断线 | 前端 `EventSource` 自带重连；后端任务继续跑，重连后从**当前缓冲**继续（任务里保留最近 500 行） |
| 长任务窗口卡死 | 打包线程与 uvicorn 线程分离；UI 只读日志，不会阻塞 |
| `-DryRun` 语义 | GUI 里未勾选 DryRun 才写游戏目录；勾选后与 CLI 完全一致（L0~L4 + 报告） |
| 回滚 | GUI 的「回滚」按钮=调用交付目录现成的 `uninstall.ps1`，**不新增**回滚逻辑 |

---

## 7. 落地顺序（确认后执行）

| 步 | 内容 | 完成判据 |
|---|---|---|
| G0 | 建 `gui/` 骨架 + `pip install fastapi uvicorn pywebview` | `python gui/desktop.py` 能开出空白窗口 |
| G1 | `tasks.py` + `app.py`（`/api/start`、SSE、`/api/report`） | 用 `curl`/浏览器能跑通一次 dry-run 并看到实时日志 |
| G2 | Vue 前端（表单 + 日志 + 判据面板 + Uiverse 皮肤） | 浏览器里完整跑一次，与 CLI 的 `build_report.json` 逐字段一致 |
| G3 | PyWebView 壳（含 `/api/select_folder`） | 双击 exe → 选路径 → 打包 → 显示 A0~A6 + 部署结果 |
| G4 | `build_gui.ps1` + 双变体打包 + 手册 | 干净机器（无 Python/Node/.NET）双击可用 |
| G5 | 回归：CLI 版再跑一遍 `-DryRun` 与真机部署/回滚 | 与 G2 前的输出、判据完全一致 |

---

## 8. 需要你点头的 3 件事

1. **前端要不要进仓库**：`gui/dist`（构建产物，约 200 KB）是否一并提交/随 Kit 分发？
   （推荐：要。这样没装 Node 也能打包。）
2. **GUI 的第三个 Kit 变体命名**：`CalaPlayerSrcmBuilder_gui_minimal_<date>` /
   `..._gui_full_<date>`，还是你直接叫 `CalaPlayerSrcmBuilderGUI.exe` 单文件？
3. **要不要「取消打包」按钮**：阶段边界取消（安全、实现简单）；
   还是不做（更省事，长任务约 15 s~2 min，基本不需要）。
