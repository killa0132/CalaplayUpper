# CalaPlayerSrcmBuilder **v1.2.0**

> 一站式素材打包工具：把图片/音乐丢进文件夹，一键生成可在 **CalaPlayer** 里使用的静态补丁。
> **只往补丁容器里追加，绝不替换任何原生条目**；打包/合并完**自动装进游戏**，随时一键回滚。
> 本版重点：**打包与「多 Mod 合并」变成一条流水线** —— 你打出来的包本身就是一个 Mod，能和别人的 Mod 合并成同一个补丁容器。

## ✨ v1.2.0 有什么新东西

| | 说明 |
|---|---|
| 🤝 **多 Mod 共存（GUI 里就能做）** | 左侧卡片顶部多了一个 **「多 Mod 合并」** 小 Tab（默认仍是「单包打包」，界面不变）：选一个文件夹，工具会**自动嗅探**里面所有带 `manifest.json` 的 Mod 并列出（可勾选/移除），**自动生成总索引**；也可以填多个目录（`;` 分隔）或对话框多选。点「开始合并」→ 得到一个**同时包含所有 Mod** 的补丁容器，而不是互相覆盖。协议规定**冲突即报错、零产出**（并写明是谁和谁冲突） |
| 📦 **打包即 Mod（`-ExportSrc`）** | 单包打包勾上 `-ExportSrc`，输出目录里会多出一份 `mod_src\<名字>_src\`（`manifest.json` + 本次涉及的全部资产，**保留完整相对路径**），**可以直接丢进「多 Mod 合并」**和别人的 Mod 一起合并。想合并两份自产 Mod 时用 `-SrcName` 换个名字（否则同名/同路径会按协议判冲突） |
| 🚀 **合并完成自动装进游戏** | 点完「开始合并」就走完整流水线：合并出容器 → **备份**当前补丁到 `<输出目录>\install_backup_<时间戳>\`（含 `BACKUP.txt` 账本）→ 写入游戏 `Content\Paks` → **逐文件读回 sha256** → 任一步不符**自动还原**。成功后弹窗直接写「**已安装到游戏，重启生效**」。想只出容器不安装，勾选项里的 **「仅产出不安装」**（默认关闭，等效单包的 `-DryRun`）。**没有**另加"安装到游戏"按钮 —— 和单包一样，点一次就够 |
| ↩️ **「回滚」按钮两个模式都有** | 判据面板右下角：**真的装进游戏了才亮**（单包 = 本次部署过；合并 = 有安装记录），没装就**置灰**并说明原因；点一下回到安装前（单包走输出目录里的 `uninstall.ps1`，合并走 `install_backup_<时间戳>` 里的备份），回滚成功后按钮再次置灰 |
| 🚨 **打包/合并前的错误卡片** | 点按钮前先做检查（路径没填、路径不存在、输出目录的上级不存在、勾选的 Mod 不在目录里……），一次列出**全部**问题：一张大卡片 + 逐条 ❌ + 「知道了」，**不会启动任务**、也不会 3 秒后抛一个看不懂的失败。**单包与合并用的是同一张卡片** |
| 🧭 **引导与语言记忆** | 新手引导高亮会**自动把元素滚进视口**，退出时**恢复你原来的滚动位置**；引导只看一次（存 `%LOCALAPPDATA%\CalaPlayerSrcmBuilder\prefs.json`，想再看点右上角「引导」）。语言第一次按**系统语言**来（中文系统 = 中文，其它 = English），手动切换后记住，重启沿用 |
| 🎨 **界面细节** | 合并模式下的「协议规定，不可关闭」改成**金色加粗 + 感叹号徽章**（一眼看出是硬规定，不是开关）；修掉开始按钮在最小窗口（960×620）下可能溢出表单列的问题；底部进度条的黑色外框上下收窄 **22.5%**（里面的文字、`chongci.gif`、进度条本体尺寸不变） |
| ✅ **判据加强** | 回归 **34 场景**（新增 **T34**：合并产物 → 沙箱安装（备份+读回）→ **逐字节回滚**）；GUI 侧 API 验收与冻结 exe 验收 **80+ 项**，其中新增：`-ExportSrc` 结构体检、把导出的 `mod_src` **直接喂回合并器**（M0~M6 全 PASS）、**合并自动安装 + 两个模式的「回滚」按钮都能点并真的回滚**（沙箱逐字节还原）、合并前检查卡片、金色硬性规定、按钮与进度条几何、引导滚动还原、语言嗅探与持久化 |

## 📥 下载

| 文件 | 体积 | SHA256（前 16 位） | 说明 |
|---|---|---|---|
| `CalaPlayerSrcmBuilder_GUI_minimal_v1.2.0.zip` | 81.5 MB | `45972379576FC2C4` | **桌面 GUI · 精简版**（不含 FFmpeg，推荐先下这个） |
| `CalaPlayerSrcmBuilder_GUI_full_v1.2.0.zip` | 159.8 MB | `A435E61407D5BA56` | 桌面 GUI · 完全体（自带 FFmpeg：MP3/FLAC 开箱即用）※ 超过 GitHub 单文件 100 MB 限制，走网盘 |
| `CalaPlayerSrcmBuilder_CLI_minimal_v1.2.0.zip` | 65.3 MB | `53F0F4E2A103F5CC` | 命令行 · 精简版 |
| `CalaPlayerSrcmBuilder_CLI_full_v1.2.0.zip` | 143.5 MB | `2EB545B3E6E35593` | 命令行 · 完全体 ※ 同上，走网盘 |

解压后**双击 `CalaPlayerSrcmBuilderGUI.exe`** 即可，不需要安装 Python 或 .NET。
（命令行版解压后跑 `build_srcm.ps1`。）

## 🚀 三步用起来

1. 建一个素材夹，里面放 `bg\`、`BGM\`、`Sound\`、`Ambient\` 四个子目录（大小写不敏感，缺哪个跳过哪个）；
2. 打开 GUI → 选「游戏 Paks 目录」和「素材根目录」→ 点「开始打包」（默认是 `DryRun`：**只出容器不装**，
   想直接装进游戏就把 `DryRun` 关掉）；
3. 想和别人的 Mod 一起用时，切到「**多 Mod 合并**」：选 Mod 根目录（会自动嗅探）→ 勾选要参与的 Mod →
   点「开始合并」→ **它自己装好**，重启游戏即可。

回滚：判据面板右下角的「**回滚**」按钮（单包=回到安装前，合并=还原 `install_backup_*` 里的旧容器）。

## 🧭 已知边界（请先读）

* **时间轴单元格**与编辑器右侧的**「Background」预览块**：**v1.1.0 起会显示你新增的背景**（静态实现）。
* **下拉列表里的小缩略图锐度会轻微降低（约 30%）**：游戏原生渲染路径决定的（该缩略图只从图集里那一格采样，
  GPU 的 mip 选择落在两级的混合上），**肉眼无感**；`-NoAtlas` 可回到旧行为。
* **背景上限 = 59**（预览图集的空闲格数）；超过要 `-Force`，且超出的背景缩略图不会显示。
* **同一个游戏目录只能有一个补丁容器**（同名容器互斥）—— 这正是要"合并"的原因；两个 Mod 改同一张表的同一行、
  或提供同一个文件路径，合并器会**明确报错并零产出**。
* **预览图集是"单点资源"**：两个**背景类** Mod 同时改 `T_BackgroundPreviews` 会撞文件冲突。
  「格子协商」（各写自己的格、由合并器统一分配）**列入后续开发**，本版不做。这条**不是汉化包作者（Xenon-XG）的待办**。
* **单包模式默认仍是 `DryRun`（只打包不安装）**；**合并模式默认自动安装**，调试时可勾「仅产出不安装」。
* **安装前必须先关掉游戏**（`.ucas` 被占用会导致安装失败；工具会在碰任何文件之前拒绝并给中文提示）。
* Windows 可能提示「未知发布者」：exe 未签名，点「更多信息 → 仍要运行」即可。
* 路径建议用**纯英文**；你需要先拥有 **CalaPlayer 游戏本体**。

## 🔬 质量与安全（怎么证明它没坏）

* 每次打包都跑 **A0~A10** 判据：三个壳（贴图/音频/MI）写回逐字节保真、容器里能读回每个新资产、
  音频解回 WAV 与源逐字节一致、chunk id 台账（新包 0 命中 + 4 张 DA 与图集这 5 个"故意覆盖"）、
  四张数据表的新行 FName 可解析、缩略图通道指向我们自己的材质、图集差异块 ⊆ 我方格子
  （原生 165 格在 mip0 像素改动 = 0）、预览材质是原生形态；图像类会打印 `QUALITY: PSNR / MAE / 清晰度比`。
* 合并器有 **M0~M6** 判据（输入自检 → 冲突检查 → 干净基底 → 行级合并（每次追加都做只追加证明）→
  文件合入（legacy 相对路径**绝不拍平**）→ 打包 + **容器读回**（行数/新行的 key·pkg·obj/`@30` 未移动/每个 Mod
  `.uexp` 逐字节一致）→ 只追加不重排）。
* **34 场景回归全绿**；GUI 侧另有 API 验收与冻结 exe 验收（80+ 项）。
* **安装同样有账可查**：写前把已装容器**移动**到 `install_backup_<时间戳>\real_P\`（不是删除）、写后逐文件读回
  哈希、失败自动还原；原生容器与 `Scenarios.sav` 在安装前后做哈希快照，**一个字节都不许变**，
  账本写在同目录的 `BACKUP.txt` 里。

---

**完整改动记录**：[`CHANGELOG.md`](https://github.com/killa0132/CalaplayUpper/blob/main/CHANGELOG.md) ·
**开发文档**：[`docs/DEVELOPER_GUIDE.md`](https://github.com/killa0132/CalaplayUpper/blob/main/docs/DEVELOPER_GUIDE.md) ·
**多 Mod 合并协议**：[`docs/MOD_MERGE_PROTOCOL.md`](https://github.com/killa0132/CalaplayUpper/blob/main/docs/MOD_MERGE_PROTOCOL.md)

---
---

# CalaPlayerSrcmBuilder **v1.2.0** (English)

> One-stop material packer: drop your images/music into a folder, press a button, and get a static patch that
> **CalaPlayer** can load. Everything is **appended to a patch container — native entries are never replaced** —
> and a build/merge now **installs itself into the game**, with one-click rollback.

## ✨ What's new in v1.2.0

| | |
|---|---|
| 🤝 **Several mods can coexist (from the GUI)** | A small **“Multi-mod merge”** tab sits at the top of the left card (the default is still “Single pack”, unchanged). Pick a folder and the tool **sniffs every Mod inside it** (any `manifest.json`), lists them with tick boxes, and **generates the index for you**; several folders work too (`;`-separated or multi-select in the dialog). Press *Start merging* and you get **one** patch container that contains **all** of them instead of them overwriting each other. The protocol refuses conflicts loudly and produces nothing, naming both sides |
| 📦 **A build is a mod (`-ExportSrc`)** | Tick `-ExportSrc` while packing and the output folder also gets `mod_src\<name>_src\` (`manifest.json` + every asset with its **full relative path**), ready to be fed straight into *Multi-mod merge*. Use `-SrcName` when you plan to merge two of your own builds (same name / same file paths would be a protocol conflict) |
| 🚀 **Merging installs itself** | Pressing *Start merging* now runs the whole pipeline: merge → **back up** the current patch into `<output>\install_backup_<timestamp>\` (with a `BACKUP.txt` ledger) → write into the game's `Content\Paks` → **read every file back by sha256** → **restore automatically** on any mismatch. The dialog then says “**installed into the game, restart to see it**”. Tick *Produce only (no install)* (off by default, same as `-DryRun` for a single build) to skip the install. There is **no** extra “install” button — one press does it, exactly like a single build |
| ↩️ **Roll back in both modes** | The button in the gates panel lights up **only when something was really installed** (single build = it deployed; merge = an install record exists), is **greyed out** otherwise with a reason, and one click puts the previous container back (`uninstall.ps1` for a single build, `install_backup_<timestamp>` for a merge). After a successful rollback it greys out again |
| 🚨 **A pre-flight card instead of a mystery failure** | Before anything starts, the inputs are checked (empty path, path that does not exist, missing parent folder, a ticked mod that is not there …) and **all** problems are listed at once in one big card with ❌ lines and a “Got it” button — no task is started. **Both modes use the same card** |
| 🧭 **Guide and language memory** | The first-run guide **scrolls its highlight into view** and **restores your scroll position** when it closes; it only appears once (stored in `%LOCALAPPDATA%\CalaPlayerSrcmBuilder\prefs.json`; the “?” button shows it again on demand). The language starts from your **system language** (Chinese system → Chinese, anything else → English) and a manual switch is remembered across restarts |
| 🎨 **UI polish** | The protocol's “cannot be switched off” rule is now **gold + bold with an exclamation badge**; the start button can no longer overflow the form column in a 960×620 window; the progress bar's dark frame is **22.5 % shorter** (its caption, `chongci.gif` and rail keep their size) |
| ✅ **More gates** | Regression is now **34 scenarios** (new **T34**: merged container → install into a sandbox (backup + read-back) → **byte-exact rollback**); the GUI side has **80+** API/frozen-exe checks, including: the `-ExportSrc` manifest structure, **feeding that `mod_src` straight back into the merger** (M0~M6 all pass), **merge → auto-install and both rollback buttons being clickable and really rolling back** (byte-exact restore), the pre-flight card, the gold rule badge, button/progress geometry, guide scroll restore, and language sniffing/persistence |

## 📥 Download

| File | Size | SHA256 (first 16) | Notes |
|---|---|---|---|
| `CalaPlayerSrcmBuilder_GUI_minimal_v1.2.0.zip` | 81.5 MB | `45972379576FC2C4` | **Desktop GUI · minimal** (no FFmpeg — start here) |
| `CalaPlayerSrcmBuilder_GUI_full_v1.2.0.zip` | 159.8 MB | `A435E61407D5BA56` | Desktop GUI · full (bundles FFmpeg: MP3/FLAC work out of the box) — over GitHub's 100 MB per-file limit, hosted on a netdisk |
| `CalaPlayerSrcmBuilder_CLI_minimal_v1.2.0.zip` | 65.3 MB | `53F0F4E2A103F5CC` | Command line · minimal |
| `CalaPlayerSrcmBuilder_CLI_full_v1.2.0.zip` | 143.5 MB | `2EB545B3E6E35593` | Command line · full — netdisk as well |

Unzip and **double-click `CalaPlayerSrcmBuilderGUI.exe`**. No Python or .NET installation required.

## 🚀 Three steps

1. Create a material folder with `bg\`, `BGM\`, `Sound\`, `Ambient\` inside (case-insensitive, missing ones are skipped);
2. Open the GUI → pick the *Game Paks folder* and the *Material root* → press **Start packing**
   (it defaults to `DryRun` = **build only, no install**; turn `DryRun` off to install right away);
3. To combine with someone else's mod, switch to **Multi-mod merge**: pick the Mods root (it sniffs the mods),
   tick the ones you want, press **Start merging** — it installs itself; restart the game.

Roll back with the **Roll back** button in the gates panel.

## 🧭 Known limitations (please read)

* The **timeline cell** and the editor's right-hand **“Background” preview block** do show a background you added
  (since v1.1.0, implemented statically).
* The **dropdown thumbnail is ~30 % softer**: that is the game's own rendering path (the thumbnail samples a single
  atlas cell and the GPU's mip selection lands on a blend of two levels). **Not perceptible to the eye**;
  `-NoAtlas` restores the old behaviour.
* **Background limit = 59** (free cells in the preview atlas); `-Force` goes beyond it, but those thumbnails will not show.
* **Only one patch container can live in the game folder** (same-named containers are mutually exclusive) — that is
  exactly why merging exists. Two mods touching the same table row, or providing the same file path, make the merger
  fail loudly and produce nothing.
* **The preview atlas is a single-point resource**: two *background* mods patching `T_BackgroundPreviews` collide
  (file conflict). “Cell negotiation” is on the roadmap, **not** part of this release — and **not** something the
  translation-pack author (Xenon-XG) has to deal with.
* **Single-pack mode still defaults to `DryRun`** (build only); **merge mode installs by default** (tick
  *Produce only* for debugging).
* **Close the game before installing** (a locked `.ucas` makes the install fail; the tool refuses before touching
  anything and says so in Chinese).
* Windows may warn about an unknown publisher (the exe is unsigned) → “More info” → “Run anyway”.
* Prefer **ASCII-only paths**. You need to own **CalaPlayer** itself.

## 🔬 Quality and safety

* Every build runs gates **A0~A10**: byte-faithful write-back of the three shells (texture / audio / MI), every new
  asset readable back from the container, audio decoded back to WAV byte-identical to the source, a chunk-id ledger
  (0 collisions for brand-new packages + the 5 deliberate overrides), new DA rows resolvable by FName, the thumbnail
  channel pointing at our own material, atlas diff blocks ⊆ our cells (native 165 cells: **0** changed pixels in mip0),
  native MI shape; images also print `QUALITY: PSNR / MAE / sharpness ratio`.
* The merger has gates **M0~M6** (input check → conflict check → clean base → row-level merge with an append-only
  proof per row → file merge (**relative paths are never flattened**) → pack + **read back** (row counts, new rows'
  key/pkg/obj, `@30` unchanged, every mod `.uexp` byte-identical) → append-only verification).
* **34-scenario regression, all green**; plus the GUI's API and frozen-exe checks (80+).
* **Installs are auditable**: the previously installed container is *moved* (never deleted) into
  `install_backup_<timestamp>\real_P\`, every written file is read back by hash, a mismatch restores automatically,
  and the native containers plus `Scenarios.sav` are hash-snapshotted before/after — **not a single byte may change**.
  The ledger lives in `BACKUP.txt` next to the backup.

---

**Full changelog**: [`CHANGELOG.md`](https://github.com/killa0132/CalaplayUpper/blob/main/CHANGELOG.md) ·
**Developer guide**: [`docs/DEVELOPER_GUIDE.md`](https://github.com/killa0132/CalaplayUpper/blob/main/docs/DEVELOPER_GUIDE.md) ·
**Mod merge protocol**: [`docs/MOD_MERGE_PROTOCOL.md`](https://github.com/killa0132/CalaplayUpper/blob/main/docs/MOD_MERGE_PROTOCOL.md)
