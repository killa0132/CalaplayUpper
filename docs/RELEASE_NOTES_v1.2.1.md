# CalaPlayerSrcmBuilder **v1.2.1**

> 一站式素材打包工具：把图片/音乐丢进文件夹，一键生成可在 **CalaPlayer** 里使用的静态补丁。
> **只往补丁容器里追加，绝不替换任何原生条目**；打包/合并完**自动装进游戏**，随时一键回滚。
> **本版是修复版**：修掉两个真 bug（同一个输出目录连跑两次的 L2 失败、「导出错误日志」500），
> 并把"图集还剩几格空位"从写死的常数改成**运行时实测**（游戏更新后它自己跟着变）。

## 🔧 v1.2.1 修了什么

| | 说明 |
|---|---|
| 🐞 **同一个输出目录连跑两次打包不再失败** | 症状：第二轮（**没勾「仅累积」**）在 L2 报 `the atlas is byte identical to the original: nothing was embedded`。根因：非累积模式仍然拿**上一轮的图集**当基底，而那一格里已经是同一张 tile（素材没变）⇒ 写进去的字节与基底完全一样 ⇒ 撞上"图集内容必须变化"的守卫。现在：非累积模式一律从**游戏原生图集**重建；**逐字节相同的合法空操作**记一条 NOTE 放行（`-Combined` 幂等重跑同理） |
| 🐞 **「导出错误日志」不再 500** | 症状：失败弹窗里那颗按钮返回 `导出失败: Internal Server Error`。根因：过滤器用了传统 Win32 写法，pywebview 6 会**在平台层 try 之外**抛 `ValueError` ⇒ 变成纯文本 500（前端只能显示 `Internal Server Error`）。现在：过滤器改成它认的 `描述 (*.a;*.b)` 形式 + "选路径/写文件"整段兜底（**任何异常都给出明确文案，永不 500**）+ 新增 `dry=1` 让验收能覆盖这条"只有用户会走"的分支 |
| 📏 **背景上限改成"运行时实测"** | 工具现在读 `DA_Backgrounds` 每一行 `@30` 指向的预览 MI 的 `SpriteX/SpriteY`，得到游戏**真正占用**的格子，再算出"首个空闲格"和"上限"。本版游戏：占 0..166 共 **167 格** ⇒ 我们可用 **167 起、共 57 格**（旧文档里写的 59 是**上一版游戏**的值）。⚠️ 顺带更正一个坑：**别用"扫格子是否纯黑"数空位** —— cell 166 本身就是一张**纯黑的原生缩略图**，会被漏掉 |
| 🛡️ **判据加强** | 回归 **36 场景**（新增 **T35**：同一 `out_patch` 连跑两次、第二次不带「仅累积」必须成功 + 逐字节空操作必须放行；**T36**：把背景强行放进原生已占用的格子 ⇒ 必须被 `A9b` 拦下）。另外 `check_dist` 现在还会校验仓库里所有 `.ps1` 必须 **ASCII-only**（Windows PowerShell 5.1 会把无 BOM 的脚本按 ANSI 读，含中文的脚本会输出双重编码的文案 —— 本版顺手修掉了 GUI Kit 里 `README.txt` 的两行乱码） |
| 🔧 **顺手修掉的两个真问题** | ① **干净游戏目录**（还没装过任何补丁）上，回滚以前会报"备份目录里没有补丁容器三件套" ⇒ **装完就回不去**；现在语义 = 删掉我们装进去的那份、回到干净状态。② 「游戏在跑」的占用判据以前只看已装的 `_P`，干净目录下形同失效；现在**原生 `.ucas` 也探**（与 GUI 合并安装的口径一致） |

## 📥 下载

| 文件 | 体积 | SHA256（前 16 位） | 说明 |
|---|---|---|---|
| `CalaPlayerSrcmBuilder_GUI_minimal_v1.2.1.zip` | 81.5 MB | `2E7DF22C2794EA7C` | **桌面 GUI · 精简版**（不含 FFmpeg，推荐先下这个） |
| `CalaPlayerSrcmBuilder_GUI_full_v1.2.1.zip` | 159.8 MB | `CC1EB92C8BEDAE9F` | 桌面 GUI · 完全体（自带 FFmpeg：MP3/FLAC 开箱即用）※ 超过 GitHub 单文件 100 MB 限制，走网盘 |
| `CalaPlayerSrcmBuilder_CLI_minimal_v1.2.1.zip` | 65.3 MB | `4EFB52BD9B3F8C44` | 命令行 · 精简版 |
| `CalaPlayerSrcmBuilder_CLI_full_v1.2.1.zip` | 143.6 MB | `DBCDF46886341DAB` | 命令行 · 完全体 ※ 同上，走网盘 |

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
* **背景上限 = 预览图集实测的空闲格数**（本版游戏 **57**）；超过要 `-Force`，且超出的背景缩略图不会显示。
  游戏更新后这个数由工具自己在打包时重新测量。
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
  （**原生格**在 mip0 像素改动 = 0；原生格集合是**运行时实测**的）、预览材质是原生形态；
  图像类会打印 `QUALITY: PSNR / MAE / 清晰度比`。
* 合并器有 **M0~M6** 判据（输入自检 → 冲突检查 → 干净基底 → 行级合并（每次追加都做只追加证明）→
  文件合入（legacy 相对路径**绝不拍平**）→ 打包 + **容器读回**（行数/新行的 key·pkg·obj/`@30` 未移动/每个 Mod
  `.uexp` 逐字节一致）→ 只追加不重排）。
* **36 场景回归全绿**；GUI 侧另有 API 验收与冻结 exe 验收（80+ 项，含"导出日志 dry 分支不再 500"）。
* **安装同样有账可查**：写前把已装容器**移动**到 `install_backup_<时间戳>\real_P\`（不是删除）、写后逐文件读回
  哈希、失败自动还原；原生容器与 `Scenarios.sav` 在安装前后做哈希快照，**一个字节都不许变**，
  账本写在同目录的 `BACKUP.txt` 里。

---

**完整改动记录**：[`CHANGELOG.md`](https://github.com/killa0132/CalaplayUpper/blob/main/CHANGELOG.md) ·
**开发文档**：[`docs/DEVELOPER_GUIDE.md`](https://github.com/killa0132/CalaplayUpper/blob/main/docs/DEVELOPER_GUIDE.md) ·
**多 Mod 合并协议**：[`docs/MOD_MERGE_PROTOCOL.md`](https://github.com/killa0132/CalaplayUpper/blob/main/docs/MOD_MERGE_PROTOCOL.md)

---
---

# CalaPlayerSrcmBuilder **v1.2.1** (English)

> One-stop material packer: drop your images/music into a folder, press a button, and get a static patch that
> **CalaPlayer** can load. Everything is **appended to a patch container — native entries are never replaced** —
> and a build/merge now **installs itself into the game**, with one-click rollback.
> **This is a fix release**: two real bugs are gone (an L2 failure when packing twice into the same output folder,
> and “Export error log” returning 500), and the free preview-atlas cells are now **measured at build time**
> instead of being a hard-coded number (it follows the game automatically).

## 🔧 What v1.2.1 fixes

| | |
|---|---|
| 🐞 **Packing twice into the same output folder no longer fails** | Symptom: the *second* run (without *accumulate*) died at L2 with `the atlas is byte identical to the original: nothing was embedded`. Cause: a non-accumulating run still used the **previous build's atlas** as its base, and that cell already held the very same tile (same material) ⇒ the write was byte-identical to the base ⇒ it tripped the “the atlas must change” guard. Now: a non-accumulating run always rebuilds from the **game's own atlas**, and a **legitimately byte-identical rewrite** is accepted (logged as a no-op) — same for an idempotent `-Combined` re-run |
| 🐞 **“Export error log” no longer returns 500** | Symptom: the button in the failure dialog answered `导出失败: Internal Server Error`. Cause: the file-dialog filters used the legacy Win32 form, which pywebview 6 rejects **outside its platform try block** ⇒ `ValueError` escaped as a plain-text 500 (the page could only show `Internal Server Error`). Now: the filters use the form pywebview accepts, the whole “pick a path / write the file” block is wrapped (**every failure returns a clear message — never a 500**), and a new `dry=1` lets the acceptance suite cover that user-only branch |
| 📏 **The background limit is measured at build time** | The tool reads `DA_Backgrounds` row by row (`@30` → the preview MI's `SpriteX/SpriteY`) to learn which atlas cells the game really occupies, then derives the **first free cell** and the **cap**. This game build occupies **0..166 (167 cells)** ⇒ we may use **167 onward, 57 cells** (the “59” in older docs was the *previous* game build). ⚠️ It also corrects a trap: **do not count free cells by “is the cell pure black”** — cell 166 *is* a pure-black native thumbnail |
| 🛡️ **More gates** | Regression is now **36 scenarios** (new **T35**: packing twice into the same out_patch must succeed + a byte-identical no-op must be accepted; **T36**: forcing a background into a native-occupied cell must be caught by `A9b`). `check_dist` now also verifies that every `.ps1` in the repo is **ASCII-only** (Windows PowerShell 5.1 reads a BOM-less script as ANSI, so a script containing non-ASCII text emits double-encoded text — v1.2.1 also fixes two garbled lines in the GUI kit's `README.txt`) |
| 🔧 **Two related real bugs fixed** | ① On a **clean game folder** (no patch installed yet), rollback used to fail with “the backup has no container trio” ⇒ **you could not get back**; it now means “delete what we installed, back to clean”. ② The “game is running” probe only looked at an installed `_P`, which is useless on a clean folder; the **native `.ucas` is probed too** (matching the GUI's merge installer) |

## 📥 Download

| File | Size | SHA256 (first 16) | Notes |
|---|---|---|---|
| `CalaPlayerSrcmBuilder_GUI_minimal_v1.2.1.zip` | 81.5 MB | `2E7DF22C2794EA7C` | **Desktop GUI · minimal** (no FFmpeg — start here) |
| `CalaPlayerSrcmBuilder_GUI_full_v1.2.1.zip` | 159.8 MB | `CC1EB92C8BEDAE9F` | Desktop GUI · full (bundles FFmpeg: MP3/FLAC work out of the box) — over GitHub's 100 MB per-file limit, hosted on a netdisk |
| `CalaPlayerSrcmBuilder_CLI_minimal_v1.2.1.zip` | 65.3 MB | `4EFB52BD9B3F8C44` | Command line · minimal |
| `CalaPlayerSrcmBuilder_CLI_full_v1.2.1.zip` | 143.6 MB | `DBCDF46886341DAB` | Command line · full — netdisk as well |

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
* **Background limit = the preview atlas' measured free cells** (this game build: **57**); `-Force` goes beyond it,
  but those thumbnails will not show. The tool re-measures it on every build, so a game update follows automatically.
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
  channel pointing at our own material, atlas diff blocks ⊆ our cells (native cells: **0** changed pixels in mip0 —
  and the native cell set is **measured at run time**), native MI shape; images also print
  `QUALITY: PSNR / MAE / sharpness ratio`.
* The merger has gates **M0~M6** (input check → conflict check → clean base → row-level merge with an append-only
  proof per row → file merge (**relative paths are never flattened**) → pack + **read back** (row counts, new rows'
  key/pkg/obj, `@30` unchanged, every mod `.uexp` byte-identical) → append-only verification).
* **36-scenario regression, all green**; plus the GUI's API and frozen-exe checks (80+, including “the export-log dry
  branch can no longer 500”).
* **Installs are auditable**: the previously installed container is *moved* (never deleted) into
  `install_backup_<timestamp>\real_P\`, every written file is read back by hash, a mismatch restores automatically,
  and the native containers plus `Scenarios.sav` are hash-snapshotted before/after — **not a single byte may change**.
  The ledger lives in `BACKUP.txt` next to the backup.

---

**Full changelog**: [`CHANGELOG.md`](https://github.com/killa0132/CalaplayUpper/blob/main/CHANGELOG.md) ·
**Developer guide**: [`docs/DEVELOPER_GUIDE.md`](https://github.com/killa0132/CalaplayUpper/blob/main/docs/DEVELOPER_GUIDE.md) ·
**Mod merge protocol**: [`docs/MOD_MERGE_PROTOCOL.md`](https://github.com/killa0132/CalaplayUpper/blob/main/docs/MOD_MERGE_PROTOCOL.md)
