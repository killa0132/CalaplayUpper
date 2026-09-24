# CalaplayUpper 文件梳理清单（2026-09-24，**已于当日按用户确认执行完毕**）

> **执行记录**：`scripts\clean.ps1 -Apply -IncludeLogs` → 释放 **3,541.7 MB（3.46 GB）**，
> 退出码 0。`logs\` 只留本轮证据（`g7_*` + 四张 `gui_shot_*.png`），历史证据 22 个文件
> 归档到 `logs\archive\`。用户另外确认：**只写 `docs\README.md` 索引，不搬根目录的
> `bg_*.jpg`**。执行后复验：21 场景回归、源码 GUI 自检、`gui_api_check`、`check_dist` 全绿
> （见 §4）。

> 结论先行：可以安全释放 **≈ 3.46 GB**，只删「可再生 / 无人引用」的东西；
> 有 3 处看着像垃圾但**必须保留**（见 §3），删了会踩坑。
> 执行脚本：`scripts\clean.ps1`（**默认只打印清单，加 `-Apply` 才真删**）。

---

## 0. 判断原则（每条候选都按这个过一遍）

1. **可再生** ⇒ 删（构建中间产物、自动生成的测试素材、字节码缓存）。
2. **有引用** ⇒ 先查引用再决定：`grep` 整个工程（含 `.ps1` / `.py` / `.md`），
   只在注释或历史日志里出现的引用不算"在用"。
3. **不确定** ⇒ 保留或归档，**绝不删**。删错的代价远大于多留几 MB。
4. **交付件只留"当前版本"**：同一交付物只保留最新日期那一份。

---

## 1. 待删除（可释放 ≈ 3.46 GB，`scripts\clean.ps1` 实测数字）

| # | 路径 | 大小 | 为什么可删 | 核查方式 |
|---|---|---|---|---|
| 1 | `_probe\` | **944.1 MB** | CP-32/33 逆向阶段的一次性取证产物（含一份 900 MB 原生容器副本、老 tex-inspect 发布件、各种 `an1/perf_trim/...` 试验目录） | 全工程 grep `_probe`：只命中 `core\builder.py::_probe_names`（同名不同物，是个方法名）和两个已废弃的 `logs\*_probe.py`；**没有任何脚本读它** |
| 2 | `tests\mat\` | **1884.7 MB** | 回归测试**自动生成**的素材（注释原文就是"跑完即弃"）。`regression.py:151` 每次开跑都会重建 `mat\demo` 等 8 个场景目录 | `regression.py` 里 `MAT = tests\mat`、`make_png/make_wav` 都写在这里；`tests\mat\demo` 由 `-T1/T2/T15/T16` 每次重建 |
| 3 | `build_out\` | **145.7 MB** | PyInstaller 的 `work/` 与 `dist/` 临时目录（`.toc/.pyz/.pkg/xref.html`）。两个 build 脚本每次都会 `Remove-Item` 后重建 | `build_kit.ps1:9`、`build_gui.ps1:14` 都指向它；`regression.py:83` 只是把 `build_out\dist\*.exe` 当**备用**候选（`dist\` 里没有才用），删掉不影响 |
| 4 | `dist\CalaPlayerSrcmBuilder_gui_minimal_20260923\`<br>`dist\CalaPlayerSrcmBuilder_gui_full_20260923\` | **394.1 MB** | 被 `_20260924` 那一对取代的旧 GUI Kit（exe 是加图标/新界面之前的版本） | `gui_exe_check.py::find_exe` 取 `sorted(os.listdir(dist), reverse=True)` 的第一个 ⇒ 永远拿最新的 `_20260924` |
| 5 | `tests\build.log` (29.9 KB)<br>`tests\build.report.json` (11.8 KB)<br>`tests\mat\build.log` / `build.report.json`<br>`tests\_real_before.txt` | **≈ 45 KB** | 手工在 `tests\` 下直接跑 exe 时，`core` 的兜底把日志写到了 CWD；`_real_before.txt` 是某次手工探测的残留 | grep `_real_before`：`regression.py` 里只有局部变量 `real_before`，**不读这个文件** |
| 6 | `tools-src\{da-patch,tex-inspect}\bin\` | **172.1 MB** | `dotnet publish` 的输出目录；真正被 Kit 使用的是 `kit\` 里的拷贝，重新发布随时可再生成 | 见 §3.3：**只删 `bin`，`obj` 必须留** |
| 7 | `cli\__pycache__` `core\__pycache__` `gui\__pycache__` `tests\__pycache__` | ≈ 0.2 MB | Python 字节码缓存 | — |
| 8 | `logs\` 里的**一次性调试脚本**：`a7_gui_probe.py` `dump_dialog.py` `enc_probe.py` `run_frozen_probe.py`，以及已废弃/空文件（`g4_*.txt` 里 0 字节的那几个、`g4_frozen_full.txt`、`g4_headless.txt`、`g4_selftest.txt`、`a7_*_out/err.txt`、`enc_*.txt`、`nowin_probe.txt`、`g4_probe*`） | ≈ 0.1 MB | 它们是排查过程中的临时脚本与中间输出，结论已经进了 `README.md` / `docs/` / 记忆库 | 逐个确认没有任何脚本 import/调用它们 |
| 9 | `logs\` 里上一轮及更早的日志 `g4_*` `g5_*` `g6_*`（保留 `g6_shot_*` 可选） | ≈ 0.6 MB | 结论已写进 README 第 10 章；保留最新一轮 `g7_*` 作为当前证据 | 建议**归档**到 `logs\archive\` 而不是删（见 §4） |

---

## 2. 待新增 / 待移动

| 动作 | 内容 | 理由 |
|---|---|---|
| 新增 `scripts\`（**已建好，dry-run 已验证**） | `clean.ps1`（本清单的可执行版，默认 dry-run）、`check_dist.ps1`（校验每个交付 Kit 的文件清单，防止多余文件混进去） | 用户要求"同类工具脚本归到同一个子目录下"；目前维护用脚本散在 `logs\` 里 |
| 新建 `assets\`（**待确认**） | 工程根的 `bg_light.jpg` / `bg_dark.jpg`（4.3 MB）搬过去，同时改 `build_gui.ps1` 里读它们的两行 | 根目录应该只剩脚本与文档；这两张是**素材**不是脚本 |
| 归档（**待确认**） | `logs\g4_*` `g5_*` `g6_*` → `logs\archive\` | 保留历史证据但让 `logs\` 一眼看到"当前这一轮" |
| 文档 | `docs\README.md` 索引（列出每份文档讲什么、对应哪一轮） | 让后来者一眼看懂 |

> ⚠️ 两个 `.ps1` 一律 **ASCII-only**：Windows PowerShell 5.1 读**没有 BOM** 的 `.ps1` 时按
> ANSI（本机 GBK）解析，中文注释会直接把脚本解析崩掉（本轮真踩了，这也是
> `build_*.ps1` 头部都写着 "ASCII only" 的原因）。中文说明放 `docs\`。

> `dist\` 的整洁由 `scripts\check_dist.ps1` 保证：GUI Kit 只允许
> `CalaPlayerSrcmBuilderGUI.exe` + `README.txt` + `kit\**`；CLI Kit 只允许
> `CalaPlayerSrcmBuilder.exe` + `README.txt` + `kit\**`；出现别的文件就报错并列出。

---

## 3. 看着像垃圾、但**必须保留**的（重点，别误删）

### 3.1 `tools-src\{da-patch,tex-inspect}\obj\`（≈ 163 MB）—— 留！
`obj\project.assets.json` 是 `dotnet publish --no-restore` 的输入。README 第 6 节明确要求
**必须带 `--no-restore`**：两个 csproj 里 UAssetAPI 写的是 `Version="*"`，一旦 restore 就会
浮到新版本，而 A0/A1 判据只对 **UAssetAPI 1.1.0 / CUE4Parse 1.2.2.202609** 验过。
删掉 `obj` ⇒ 下次重新发布前必须先 restore ⇒ 有把判据基准换掉的风险。
**只删 `bin`（172 MB 的 publish 输出），`obj` 保留。**

### 3.2 `tests\fakegame\`（971 MB）—— 留！
它是回归与 GUI 自检的**沙箱游戏目录**：5 个原生容器是指向真机的**硬链接**（几乎不额外占盘），
外加已装 `_P` 三件套的副本。回归每次开跑都会打印"沙箱是否与真机逐字节一致"，
`DRIFTED` 就意味着结论未必代表真机。删了就必须重新对齐 + 重新造，风险大于收益。

### 3.3 其它保留项

| 路径 | 大小 | 为什么留 |
|---|---|---|
| `python\`（venv） | 118 MB | `build_kit.ps1` / `build_gui.ps1` 硬编码 `python\Scripts\python.exe`；PyInstaller / fastapi / pywebview / pillow 全在这里 |
| `kit\` | 57.1 MB | 自包含工具（retoc / da-patch / tex-inspect / usmap / native）；两个 build 脚本从这里**拷贝** |
| `dist\CalaPlayerSrcmBuilder_{minimal,full}_20260923\` | 369.6 MB | **当前**的 CLI 交付件 |
| `dist\CalaPlayerSrcmBuilder_gui_*_20260924\` | 396.4 MB | **当前**的 GUI 交付件（本轮会重打，同名覆盖） |
| `tests\srcm_demo` `srcm_more` `srcm_badimg` `srcm_mp3only` | 5.4 MB | 手做验收素材，README 与排查都用得到 |
| `gui\frontend\node_modules\` | 36.5 MB | `npm.cmd run build` / `run dev` 需要；没有它 vite 起不来 |
| 根的 `bg_light.jpg` / `bg_dark.jpg` | 4.3 MB | `build_gui.ps1` 从根目录读（若采纳 §2 的移动则改到 `assets\`） |

---

## 4. 执行后的验收（缺一不可）

```powershell
scripts\clean.ps1 -Apply                 # 1) 只删 §1 清单
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\run_regression.ps1   # 2) 21 场景全绿
python gui\desktop.py --selftest --selftest-ui --selftest-shell                  # 3) GUI 源码自检
python tests\gui_api_check.py            # 4) 接口层 G1
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_gui.ps1              # 5) 重打
python tests\gui_exe_check.py            # 6) 冻结 exe G4
scripts\check_dist.ps1                   # 7) 交付件清单干净
```

**顺序说明**：`tests\mat` 必须**最后**删（`gui_exe_check.py` 需要 `tests\mat\demo`；
第 2 步的回归会把它重建回来）。

---

## 5. 一句话小结

* 删：一次性取证产物 `_probe`（944 MB）、自动生成的 `tests\mat`（1885 MB）、PyInstaller
  中间目录 `build_out`（146 MB）、被取代的旧 GUI Kit（394 MB）、`dotnet` 的 `bin`（172 MB）、
  散落的运行残留与字节码缓存 ⇒ **≈ 3.46 GB**（`scripts\clean.ps1` dry-run 实测）。
* 留：`tools-src\obj`（钉住 UAssetAPI 1.1.0 的 restore 图）、`fakegame` 沙箱、
  venv、`kit`、当前交付件。
* 加：`scripts\`（清理与交付件校验）、`assets\`、`logs\archive\`。
