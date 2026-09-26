> **这是开发者 / 参考文档。** 内容 = 原仓库根目录的 README.md 全文（2026-09-24 因首页改版移到 docs/）。
> 面向使用者、下载与快速上手请回到 **[README](../README.md)** ｜ **[English](../README.en.md)**。
>
> 本文包含：CLI 开关与 30 秒上手、安全机制、A0~A8 判据、原理、体积、GUI 各轮迭代、开发与调试指南。
> 跨会话的开工规则与当前状态在 AGENTS.md。

---

# CalaplayUpper

**中文** | [English](DEVELOPER_GUIDE.en.md)

一站式 **CalaPlayer 静态 `_P` 补丁生成器**（`CalaPlayerSrcmBuilder`）。

把你自己的图片 / 音频丢进一个 `srcm` 文件夹，一条命令产出可以直接覆盖安装的
`CalaPlayer-Windows_P.{pak,ucas,utoc}`，**不污染任何原生资源**，并且随时一键回滚。

> 本目录是从 `D:\dsharnessProject\CalabiyauGalMaker`（CP-32）拆出来的独立工程：
> 那边保留逆向取证与历史交付件，这边只做"傻瓜化打包工具"。

---

## 0. 下载（不用自己编译）

去 **[Releases](https://github.com/killa0132/CalaplayUpper/releases)** 下最新一版：

| 版本 | 什么时候选它 |
|---|---|
| **完全体 Full**<br>`CalaPlayerSrcmBuilder_gui_full_<日期>.zip` | **推荐**。**自带 FFmpeg，开箱即用**，支持 MP3 自动转码（后台转成 PCM 再进游戏） |
| **精简版 Minimal**<br>`CalaPlayerSrcmBuilder_gui_minimal_<日期>.zip` | 体积小很多（不含那 204 MB 的 ffmpeg）。**需要你电脑上已经装好 FFmpeg** 才能处理 MP3，否则只能用 WAV |

两个 zip 里都是 `CalaPlayerSrcmBuilderGUI.exe` + `kit\`（自包含工具链，**免装 .NET / Python**）。
解压 → 双击 exe 就能用。CLI 版（`CalaPlayerSrcmBuilder.exe` + `build_srcm.ps1`）也在同一个
Release 里，脚本党自取。

### 界面一览（点开看大图）

| 主界面：左边填素材，右边实时日志 + A0~A8 判据 | 第一次打开会有 9 步新手引导 |
|---|---|
| [<img src="images/ui-layout.jpg" width="430">](images/ui-layout.jpg) | [<img src="images/guide.jpg" width="430">](images/guide.jpg) |

进度条跑起来是这样（`chongci.gif` 当推进头部）：

<img src="images/chongci.gif" width="430">

| 跑完：成功弹窗 | 出问题：失败弹窗 + 一键导出错误日志 |
|---|---|
| [<img src="images/modal-ok.jpg" width="430">](images/modal-ok.jpg) | [<img src="images/modal-fail.jpg" width="430">](images/modal-fail.jpg) |

---

## 1. 30 秒上手

```powershell
# 1) 准备素材（目录名大小写不敏感；缺哪个就跳过哪个）
#    srcm\bg        图片  (png/jpg/bmp/webp/tga/tif/gif)
#    srcm\BGM       音乐
#    srcm\Sound     音效
#    srcm\Ambient   环境音
#    srcm\names.json  可选：{ "bg/city.jpg": "城市夜景" }

# 2) 跑
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_srcm.ps1 `
    -Paks "D:\CalabiyanGalgameMaker\CalaPlayer" `
    -Srcm "D:\srcm"

# 3) 产物在 <srcm 的上级>\out_patch\
#    CalaPlayer-Windows_P.{pak,ucas,utoc}   install.ps1  uninstall.ps1  README.md
#    verify\  _prev_container\  build.log  build_report.json
```

`-Paks` 可以只给游戏根目录（`...\CalaPlayer`）、UE 工程根、`Content` 或 `Paks` 目录本身，
工具自己找 `Content\Paks`。**代码里没有任何硬编码路径。**

### 开关

| 开关 | 含义 |
|---|---|
| `-Fit cover`（默认） | 等比放大填满目标画布（v1.1.0 起 2560×1440）再居中裁边（二次元图裁边比留黑边好看） |
| `-Fit contain` | 等比缩到能放下，四周补 `(18,18,22)` 黑边，一个像素都不重采样 |
| `-DryRun` | 只跑 L0~L4（出容器 + 全判据），**绝不碰游戏目录** |
| `-Combined` | 在上一次 `out_patch` 成果之上**累积**（不是每次从原生表重建）。累积状态就是 `out_patch\work\manifest.json` 加同目录的 legacy 树；**失败的运行不会把它吃掉**，且没有历史时会明确告诉你 `nothing to carry` |
| `-Force` | 越过限额（bg ≤ 59 张、音频总时长 ≤ 10 min、PSNR ≥ 25 dB） |
| `-Ffmpeg <exe>` | 手动指定 ffmpeg |
| `-Kit <dir>` | 手动指定工具目录 |

---

## 2. 安全机制（"不得污染游戏目录"）

| 措施 | 实现 |
|---|---|
| 构建与部署分离 | L1~L4 只写 `<srcm 上级>\out_patch\`；**只有 L5 写游戏目录** |
| 写前备份 | L5 先把已装的 `_P` **移动**到 `out_patch\_prev_container\`，这就是回滚素材 |
| 写后立刻读回 | 用 tex-inspect 直接从**真实游戏目录**读：音频 `--audio-out` 逐字节等于源；背景每级 mip 哈希等于我们造的值；四张 DA 行数等于期望 |
| 失败自动还原 | 上述任一项失败 → 自动删掉新容器 + 还原 `_prev_container`，退出码非 0 |
| 原生资源 | 5 个原生容器的 sha256 在 L0 记录、在报告里复核；**永不写入** |
| 只追加 | 四张 DA 表格逐字节证明"只多了行 + 只动了 count 字段"，原生行一个字节不动 |
| 游戏占用 | L0 只读探测到已装的 `_P` 被锁（**游戏还在跑**）→ 日志警告；真要写时在碰任何文件之前就带中文提示拒绝；回滚时只删"哈希等于我们自己产物的"文件，绝不误删 |

> ⚠️ 安装前请**先关闭游戏**。游戏在运行时 `.ucas` 被占用，工具会明确告诉你 `close the game first` 并保持游戏目录原样。

---

## 3. 判据（A0~A10，全部带落盘证据）

| 门 | 内容 |
|---|---|
| A0 | UAssetAPI 写回保真：三个壳资产（贴图壳 / 音频壳 / **预览 MI 壳**）的 uasset/uexp 逐字节一致 |
| A1 | CUE4Parse 能从**容器里**读出每个新资产，类型 = `USoundWave` |
| A2 | `bStreaming=True` / `AudioFormat="PCM"` / `NumChunks=1` / 内联负载长度 == WAV 长度 |
| A3 | cooked `USoundWave` 的 `NumChannels/SampleRate/Duration/TotalSamples` 与 WAV 一致 |
| A4 | `tex-inspect --audio-out` 从容器解回来的 WAV 与规范化后的 WAV **逐字节一致** |
| A5 | chunk id 台账：新包（贴图 + **预览 MI**）在原生容器 **0 命中**；与原生重合的只允许是故意覆盖的（4 张 DA **+ 预览图集**，数目等于预期） |
| A6 | 把交付容器**再解一遍**：四张 DA 行数正确 + 每个新资产（贴图 / 音频 / **MI**）uexp 逐字节一致 |
| A7 | 从容器里取出四张 DA，把每条新行的 **key / 包名 / 资源名** 三个 FName 索引解析回字符串，逐个比对"我打算写进去的显示名与软路径"（**非 ASCII 显示名就是靠这道门保住的**；A6 只看行数和资产字节） |
| A8 | **缩略图通道**（CP-34/CP-37）：容器里读回每条新背景行的 `@30`，必须解析成 `MaterialInstanceConstant` 且名字 = 我们的 `MI_<name>`；再用 `da-patch miprobe` 证明那个 MI 的 `SourceTexture` 指向预期贴图（图集形态下 = `T_BackgroundPreviews`）。`-NoThumb` 时显式 `skipped` |
| A9 | **图集像素**（CP-37）：从交付容器读回图集，与基线（原生 / 上一轮）**逐 BC1 块**比对 ⇒ 差异块集合必须 ⊆ 我方格子覆盖的块集合；再用 CUE4Parse 独立读回 4096×2048 / `PF_DXT1` / 13 级、且**逐级 sha256 与我们所写一致** |
| A9b | **原生缩略图不受影响**（CP-37）：逐级解码两版图集，统计**原生 165 格采样矩形内**的差异像素与最大通道差 —— **mip0 必须为 0**；mips ≥ 1 打印数字（P1 策略下 ≤1 块宽的接缝） |
| A10 | **原生形态**（CP-37）：容器里读回我方 MI：`SourceTexture` 解析出对象名 == `T_BackgroundPreviews`，且 6 个标量 == `格子X/格子Y/250/141/4096/2048`（与游戏自带 MI 逐字段同形）。`-NoAtlas` 时显式 `skipped` |

图像额外带 `QUALITY: PSNR=… MAE=… 清晰度比=…` 一行（低于 25 dB 直接报错，`-Force` 才放行），
并在 `out_patch\verify\` 落 `*_preview.png` 供肉眼比对。

### 3.1 背景缩略图 = 每个新背景一个独立 MI（CP-34）

一条 `DA_Backgrounds` 行有**两条互不相干的引用通道**：

```
BackgroundMap 的 34 字节条目
├─ +0   FName Key               显示名
├─ +10  FSoftObjectPath 软路径  → /Game/CalaPlayer/Backgrounds/<名>   【大预览 + PLAY】读这里
└─ +30  FPackageIndex 硬引用     → 一个预览 MI（UMaterialInstanceConstant）
                                   └─ SourceTexture → 要显示的贴图     【下拉缩略图 + 侧边小预览】读这里
```

v1 让新行的 `@30` **原样继承克隆源**（= 某个原生 `MI_BackgroundPreview_NNN`，它指着共享图集
`T_BackgroundPreviews` 的一格）⇒ 缩略图永远是原生那一格。CP-34 起：

* **克隆源不硬编码**：L0 读 `DA_Backgrounds` 第 0 行的 `@30` → 在 DA 自己的 ImportMap 里解析出 MI
  对象名与包路径 → 只解出那一个包（`retoc to-legacy -f` 是**子串**匹配，不能整目录拷）。
* `da-patch mimk` 克隆它：**内部身份三处一起改**（`FolderName` + 名字表包路径 + export
  ObjectName），在**它自己的 ImportMap 末尾**追加 `Package` + `Texture2D` 两条 import，
  把 `TextureParameterValues` 重指到我们的贴图，写 `SpriteX/Y=0`、
  `SpriteWidth/Height=TextureWidth/Height=` **目标画布尺寸**（v1.1.0 起 = 2560×1440，见 §3.3；
  游戏自带的 MI 只有这 6 个标量，**没有作者截图里的
  `isSelected`** —— 缺席的参数会被点名报出来，不硬塞）。
* `da-patch bgref` 在 **DA 的 ImportMap 末尾**追加 `Package` + `MaterialInstanceConstant` 两条
  import，python 把它返回的 `FPackageIndex` 写进**这一行**的 `@30`（每行不同）。
* **只追加不重排**由 `assert_name_import_append_only()` 证明：比较 `probe`（名字表）与
  `imports`（ImportMap）的**语义转储** —— 老名字/老 import 的索引与内容必须逐条不变，只在末尾长出来。
  ⚠️ **不能拿字节 diff 当判据**：UAssetAPI 会把整个 uasset 重新序列化。
* 万一真机出事，`-NoThumb`（CLI / `build_srcm.ps1` / GUI `no_thumb`）回到 v1 行为：
  不造 MI、`@30` 继承克隆源、A8 `skipped`。

### 3.2 宽高比约束（防变形，CP-34）

游戏用**固定 sprite**采样背景（`MMI_BackgroundSelector` 把 `SpriteWidth/Height`
烘死），社区实测：非宽屏素材进游戏会被**拉伸**。所以 L0 扫描阶段就按宽高比分流：

| 形状 | 默认（`-Fit cover`） | `-Fit contain` |
|---|---|---|
| 宽 > 高（含 1233×725、3440×1440 等非 16:9 宽屏） | 放行，日志给 `WARN: 非 16:9 图片 …` | 放行，居中补 `(18,18,22)` 黑边 |
| 正方形（`\|w-h\| ≤ max(2, 2%·h)`） | **拒绝**（中文提示） | 强制 contain，放行 |
| 竖屏（w < h） | **拒绝**（中文提示） | 强制 contain，放行 |

打不开的图**不在 L0 报错**（留给 L1 的 `cannot decode image`，判据不变）。`-Fit contain` 的
几何正确性由回归 T5 在 build 自己写出的 `verify/b_preview.png` 上**量**出来（中线首末像素 =
黑边色、左右黑边等宽 ±2 px、中间确实有画面），不是"日志里出现了 borders"。

### 3.3 背景目标画布与 `uexp` 整块重建（路线 B，v1.1.0）

**目标画布 = `config.TARGET_W/TARGET_H`（2560×1440），格式仍是 `PF_DXT1`。** 2560×1440 的源图
**不再缩放**（实测 PSNR 35.54 → **36.75 dB**、41.13 → **41.71 dB**），更小的图按 cover/contain
适配到该画布；`MI_<名字>` 的 6 个精灵标量由这两个常量派生，**自动同步**。

cooked `Texture2D` 的尺寸是写在自包含 `.uexp` 里的，所以换尺寸必须**整块重建**（不是补丁式改几个
字节）。实测布局（`T_Evni_Background_01_O`，1920×1080，1,383,410 B）：

```
[header 110 B] [mip0][16 B] [mip1][16 B] ... [mip10][16 B] [8 B 零][PACKAGE_FILE_TAG]
```

| 位置 | 含义 |
|---|---|
| `@0` | `FStripDataFlags`（`04 05`） |
| `@2` / `@6` | `SizeX` / `SizeY` ← 改 |
| `@10` | 16 B 键：**语义未确认**（8 种 MD5/SHA1 候选全部不匹配）⇒ **原样保留** |
| `@50` | `DataSize` = `len(uexp) - 62` ← 改 |
| `@74` / `@78` | `SizeX` / `SizeY` 第二处 ← 改 |
| `@82` | `SizeZ` = 1 |
| `@86` | `PF_DXT1` 的 FString（换格式才动） |
| `@102` | `MipCount` ← 改（2560×1440 ⇒ **12**） |
| 每级 mip 的 16 B 记录 | `u32 SizeX, u32 SizeY, u32 SizeZ(=1), u32 (i+1)`，**最后一级记 0** |

尺寸链用**移位**规则 `max(1, W>>i)`（壳的第 4 级是 **120×67**、第 6 级 **30×16**，不是 ceil 半宽），
每级负载 = `ceil(X/4)·ceil(Y/4)·8` B。2560×1440 ⇒ 负载合计 2,457,960 B，重建后 uexp = **2,458,274 B**。

**每级 mip 的真实结构**（这一点曾把我误导很久，按 CUE4Parse 的读法才是对的）：

```
FTexture2DMipMap = [FByteBulkData][int32 SizeX][int32 SizeY][int32 SizeZ]
FByteBulkData(inline, legacy) = [u32 BulkDataMap 索引][payload]
```

⇒ 文件里看到的是"**payload 后面跟 16 B**"，其实是 **该 mip 的 3 个 dim** + **下一个 mip 的 4 B 索引**；
最后一级后面那 4 B（值为 0）是尾部的哨兵。索引值 = `BulkDataMap` 里的下标（0,1,2,…），
**不是** i+1（早先的误读）。逐字节回环门把这个结构钉死了。

**uasset 侧有三个尺寸耦合字段，必须一起改**：

| 字段 | 说明 |
|---|---|
| `SerialSize`（8 B） | `= len(uexp) - 4`，该模式在 uasset 里**唯一命中** |
| `BulkDataMap` 记录表 | `retoc to-legacy` 把 Zen 的 bulk 表搬到了 uasset 尾部：每条 **44 B** = `u64 SerialOffset, i64 CookedIndex(-1), u64 SerialSize, u32 ElementCount(=size), 2×u32 pad, u32 Flags(0x48 = SingleUse\|ForceInlinePayload), u32 pad`，**每级 mip 一条** |
| 记录表**前面的计数**（u32，位于 `start-8`） | 表里有多少条记录 |

⚠️ **最坑的一处**：只改记录表、不改计数，CUE4Parse 会读成"11 条正确 + 第 12 条垃圾" ——
`BulkDataFlags` 变成 `PayloadAtEndOfFile|SerializeCompressed`、`byte[0]`、`SizeY/SizeZ=0`，
而**所有字节级判据（A0/A6 的哈希与字节比对）依然全绿**（因为文件确实是我们写的那些字节）。
所以 A6 现在额外做一件事：**用 CUE4Parse 把重建后的贴图读回来**，要求
`2560x1440 / PF_DXT1 / 12 级 / 每级 sha256 == 编码器输出`（这条判据是在 `-DryRun` 阶段就能拦住的）。

复现用的只读工具：`work/cp35_uexp_layout.py`（解 header）、`work/cp35_uexp_walk.py`（走结构）、
`work/cp35_hash_guess.py`（试 `@10` 是不是载荷哈希）、上游 `work/cp35_routeb_check.py`（回环门）。

---

### 3.4 预览图集：把我们的缩略图放进游戏自己的格子（CP-37，当前形态）

**为什么需要它**：`@30` 那个 MI 是**三个消费者共用**的唯一通道（只读活进程实测，2026-09-26）：

| 显示的三个地方 | 谁在建材质 | 它从 `@30` 拿到什么 |
|---|---|---|
| 下拉选择器里的缩略图（chip） | 游戏建一个 **MID，父对象就是 `@30` 那个 MI** | **整份材质**（`SourceTexture` + 7 个标量） |
| 编辑器右侧 Background 预览块 | 游戏建 MID，父 = `MMI_BackgroundPreview` | **只有 `SpriteX/SpriteY`** |
| 底部时间轴单元格 | 游戏建 MID，父 = `MMI_SubslotContentBackground`（每次选择新建） | **只有 `SpriteX/SpriteY/0`** |

后两处的材质**自己不传贴图**（`TextureParameterValues` 为空，父材质默认 = 图集）
⇒ 静态补丁下它们**只能显示图集里的某一格**，而"显示哪一格"完全由 `@30` 的两个坐标决定；
chip 作为那个 MI 的 MID，也跟着换成图集格子。所以：

* **格子位置 = 游戏自己的网格**：`列 = i % 16`、`行 = ⌊i / 16⌋`、坐标 `= (列×252, 行×143)`，
  格子 `250×141`、步长 `252×143`（2 px 间隔）。游戏自带 165 格（第 0~9 行整行 + 第 10 行前 5 格）
  ⇒ 我们可用 **序号 165..223 共 59 格**（`MAX_BG = 59` 就是这个数）。
* **MI 形态改成原生形态**：`SourceTexture` 保持壳自己的图集（`mimk` 传 `- -` ⇒ **不追加任何
  import**），只写 `SpriteX/SpriteY`（语义上就两个 float）+ `250/141/4096/2048`。
* **像素是等长原地替换**：只改图集 `.uexp` 里"我方格子覆盖的 BC1 块"，**uasset 一个字节都不动**
  （所以不需要路线 B 那套 `SerialSize` / `Zen BulkDataMap` 手术）。图集定位用**文件长度方程 +
  每级 16 B 记录链自证**（不依赖 `HEADER_LEN`，因此"上一轮的图集"也能当基线 ⇒ `-Combined` 可行）。
* **P1 共块策略**（用户拍板）：mip0 里我方格子的块边界正好落在 2 px 间隔上 ⇒
  **原生 165 格的 mip0 逐字节不变（A9b 断言 0）**；mips ≥ 1 坐标不再 4 对齐，序号 165..175 /
  176..180 这 16 格会与原生邻居共 1 块宽 ⇒ 那些块用"原始解码像素 + 我方矩形内像素"重组再编码，
  代价 = 邻格边缘 ≤1 像素的重编码误差（实测最大通道差 42，A9b 每次构建报数）。
* **chip 不会因此变糊**：chip 的实测显示尺寸 = **146×82**（真机 NCC 实测；设计值 163×92，
  `WBP_CharacterListItem.Spacer_94.Size`），图集格子 250×141 比它还大 2.9 倍面积。
  ⚠️ **但 2026-09-26 真机 A12 测出来 chip 变软约 30%**（Laplacian 1715 → 1196、
  `PSNR(before,after)=26.4 dB`）：格子只有 250 texel 宽而 chip 显示 146 px ⇒ 足迹 1.7 texel/px
  ⇒ **GPU 取 LOD≈0.5，渲染的是 mip0(250) 与 mip1(125) 各半的混合**；2K 路径的足迹是 17.5 texel/px
  ⇒ LOD≈4.1 ⇒ 主要由 mip4(160 ≈ 1:1) 出图。⇒ 结论要写成"**内容相同、观感略软**"，
  这条是"面积够大 ≠ 不掉画质"的实例（三重线性的分数 LOD 会偏向更粗的 mip）。
* `-NoAtlas` = 回到 CP-36 的整图形态（`SourceTexture` = 我们的 2K 贴图，chip 吃 2K，
  另两处显示图集第 0 格）；`-NoThumb` = v1（不造 MI）。

## 4. 原理（为什么这样做）

* **容器**：往 `Content\Paks` 放同名补丁容器 `CalaPlayer-Windows_P.{pak,ucas,utoc}`
  （mount point `../../../`，只需要 ExportBundleData + ContainerHeader，**不要 scriptobjects.bin**）。
  同名容器互斥，所以 `install.ps1` / `uninstall.ps1` 必须成对。
* **背景**：克隆原生 1920×1080 `PF_DXT1` 壳 → `da-patch namerepl` **同时**改
  `FolderName` + 名字表包路径 + export ObjectName（只改文件名会被容器注册成旧包 id）
  → 用自研（已修 bug）BC1 编码器编码到**目标画布**（v1.1.0 起 2560×1440 / 12 级）
  → **整块重建 `.uexp`** 并修 uasset 的 `SerialSize`（见 §3.3）。
* **音频**：克隆最小 BINKA 壳 → 保持**流式**路径 + `AudioFormat` 换成 `"PCM"`
  + **单 chunk 内联**，负载 = **整个 RIFF/WAVE 文件原封不动**；
  再修 legacy uasset 尾部 Zen `BulkDataMap` 的 `SerialSize`（不修的话引擎按陈旧长度读负载）。
  引擎证据：运行期格式名表有 `PCM`，`PcmAudioInfoHybrid` 断言 `wFormatTag==1` 并
  调 `FWaveModInfo::ReadWaveInfo` 解析 RIFF。
* **MP3**：**运行期没有 MP3 解码器**（exe 里的 MP3 字符串属于 Media/Electra 插件与编辑器导入器），
  所以一律先转成 PCM WAV（`-ar 48000 -ac 2 -c:a pcm_s16le`）。
* **DA 追加**：背景表每行 34 B（`+30` 是**硬引用**指向该行预览材质 —— v1 原样继承克隆源，
  CP-34 起指向我们自己造的 `MI_<name>`，见 §3.1；**永远不要**把"看起来等于 `-(行号+2)`"当成
  不变式去重算，那会让引擎 `HandleBadImportIndex()` Fatal）；
  音频三表每行 28 B，走 `da-patch sndmap`（反射调用 `TMap.Add`）。

---

## 5. 项目结构（每个目录是干什么的）

```
core/            打包管线 —— 唯一的"引擎"。L0~L5 编排、A0~A8 判据、DA 只追加、
                 BC1 编码、WAV 规范化、kit/ffmpeg 探测、日志与报告。
                 ⛔ 不可改：改这里就是改工具本身的行为。
cli/             命令行入口（argparse 一层薄壳，只做参数解析后调用 core）。
                 ⛔ 不可改。
main.py          PyInstaller 冻结入口（CLI 版）。            ⛔ 不可改

gui/             界面层（纯壳，不含任何打包逻辑）：
  tasks.py         任务注册表 + 工作线程 + CancelableLog（靠 Log.add_sink 把
                   core 的日志喂给 SSE，而不是另写一套管线）
  app.py           FastAPI 全部 /api/*（令牌守卫 / SSE / 原生对话框 / 导出日志 /
                   外链白名单 / 剪贴板 / **prefs**）
  prefs.py         需要跨启动记住的几个设置（引导已看过 / 语言 / 主题 / 分隔条比例）。
                   写进 %LOCALAPPDATA%\CalaPlayerSrcmBuilder\prefs.json —— 页面每次启动
                   都换随机端口，localStorage 的 origin 跟着变，存不住。
  desktop.py       PyWebView 桌面壳 + --selftest 全套自检 + 截图取证
  no_window.py     给每个子进程补 CREATE_NO_WINDOW（进程内 patch，不动 core）
  frontend/        Vue 3 源码（见下面的"改哪个文件"）
  dist/            vite 产物，随 Kit 分发（没有 Node 的机器也能跑）
  ✅ 这一层可以随便改。
gui_main.py      PyInstaller 冻结入口（GUI 版 → CalaPlayerSrcmBuilderGUI.exe）。

kit/             self-contained 工具集：retoc / da-patch / tex-inspect /
                 mappings(usmap) / native(oo2core, zlib-ng)。build_*.ps1 是**拷贝**它，
                 所以改过 tools-src 之后必须重跑构建脚本。
tools-src/       da-patch 与 tex-inspect 的 C# 源码（可用 dotnet publish 重新发布）
python/          项目私有 venv（numpy / pillow / pyinstaller / pywebview / fastapi）
tests/           回归与沙箱：
  regression.py      29 场景 CLI 回归（出厂 exe + fakegame 沙箱 + 真机目录守护）
  run_regression.ps1 包装脚本
  gui_api_check.py   GUI 接口端到端（G1）
  gui_exe_check.py   冻结 GUI exe 的三项检查（G4）
  fakegame/          沙箱游戏目录（5 个原生容器硬链接 + 已装 _P 的副本）
  mat/               回归自动生成的素材（跑完即弃，删掉后重跑回归即可重建）
  srcm_*/            手做的演示素材
logs/            每次自检/回归的日志与截图（证据；**不进 git**，README 用的图已复制到
                 images/）
docs/            设计与说明（含每轮评估报告与清理清单）
  images/          README 里那些界面截图 / 动图 / 猫图（裁剪压缩过的副本）
dist/            交付件（两个 CLI Kit + 两个 GUI Kit）。**不进 git** —— 它们走 Release 附件
build_srcm.ps1   CLI 包装脚本（同 cli/，不可改）
build_kit.ps1    产出两个 CLI Kit
build_gui.ps1    产出两个 GUI Kit（同步界面素材 → vite build → PyInstaller）
scripts/         维护脚本：clean.ps1（文件梳理，默认 dry-run）、check_dist.ps1（交付件清单校验）
bg_light.jpg     亮色主题背景（构建时同步进 gui/frontend/public/；工程根也留一份原始件）
bg_dark.jpg      暗色主题背景（同上）
.vscode/         编辑器推荐配置（插件 / 设置 / 调试配置）
.gitignore       哪些不进仓库、以及为什么（生成物 / 大文件 / 别人的二进制 / 游戏数据）
AGENTS.md        跨会话开工规则 + 当前状态 + 踩坑表（给 AI 协作用）
README.en.md     英文版 README（顶部与中文版互链）
```

> **仓库里没有的东西**（都在 `.gitignore` 里）：`python/`（venv）、`gui/frontend/node_modules/`、
> `gui/dist/` 与 `build_out/`（构建产物）、`dist/` 与 `kit/`（交付件与自包含工具链，走 Release）、
> `tests/mat/` 与 `tests/fakegame/`（回归素材；**fakegame 是指向真机的硬链接，含游戏自身数据，
> 绝不外发**）、`logs/`（自检日志与截图）。也就是说：**clone 下来的是源码，不是可直接运行的成品**——
> 要能跑就跑 §6 的构建，或者直接下 Release。

### 5.1 改界面时改哪个文件

| 想改什么 | 文件 |
|---|---|
| 页面骨架、左右栏、日志/判据的分隔、主题开关、测试钩子 | `gui/frontend/src/App.vue` |
| 路径输入框与「浏览…」 | `gui/frontend/src/components/PathField.vue` |
| 选项（Fit / DryRun / Combined / Force / 进阶） | `gui/frontend/src/components/OptionsPanel.vue` |
| 选项列表本体（ReactBits Line Sidebar 的 Vue 移植） | `gui/frontend/src/components/LineSidebar.vue` |
| 中/EN 切换件（ReactBits Squish Switch 的 Vue 移植） | `gui/frontend/src/components/SquishSwitch.vue` |
| 「背景适配」下拉（ReactBits Glide Select 的 Vue 移植） | `gui/frontend/src/components/GlideSelect.vue` |
| 切换语言时的乱码解码波纹 | `gui/frontend/src/components/ScrambleText.vue` |
| 实时日志面板 | `gui/frontend/src/components/LogView.vue` |
| A0~A8 判据面板（含 BorderGlow 光晕） | `gui/frontend/src/components/ResultPanel.vue` |
| 可拖拽分隔条 | `gui/frontend/src/components/SplitPane.vue` |
| 底部进度条 | `gui/frontend/src/components/ProgressBar.vue` |
| 成功/失败弹窗 | `gui/frontend/src/components/StatusModal.vue` |
| 「加入我们」社区弹窗 | `gui/frontend/src/components/CommunityModal.vue` |
| 新手引导 | `gui/frontend/src/components/Onboarding.vue` |
| **全部界面文案（中英两套）** | `gui/frontend/src/i18n.js` |
| 跨启动记住的设置（引导/语言/主题/分隔条） | `gui/frontend/src/prefs.js` + `gui/prefs.py` |
| 主题变量（亮/暗两套颜色） | `gui/frontend/src/styles/theme.css` |
| Uiverse 风格组件（按钮/卡片/输入框/表格/滚动条） | `gui/frontend/src/styles/uiverse/basic.css` |
| 进度条 / 弹窗 / 光晕 / 引导 的样式 | `styles/uiverse/{progress,modal,border-glow,onboarding}.css` |
| 后端接口 | `gui/app.py`；任务线程与取消 | `gui/tasks.py` |
| 桌面壳、自检断言、截图 | `gui/desktop.py` |
| 界面素材（png/gif/ico） | 放到 `gui/frontend/public/`（`gui/dist/` 也可当投递口，构建脚本会搬过来） |

> ⚠️ `gui/dist/` 是 vite 的产物目录，**每次 build 都会被清空**。要长期保存的素材请放
> `gui/frontend/public/`；直接丢进 `gui/dist/` 的素材由 `build_gui.ps1` 第一步搬进 `public/`。


## 6. 重新构建

```powershell
# 重建两个 Kit（exe + kit + README）
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_kit.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_gui.ps1    # GUI 那两个变体

# 重新 self-contained 发布自建工具（改了 tools-src 里的 C# 才需要）
#   必须带 --no-restore：csproj 里 UAssetAPI 是 Version="*"，一 restore 就会浮到新版本，
#   而 A0/A1 判据只对 1.1.0 验过。两个工具都要打，打完后 build_kit/build_gui 里
#   的 kit 是**拷贝**，所以必须重跑这两个脚本才会带上新 exe。
#   dotnet publish tools-src\da-patch\da-patch.csproj -c Release -r win-x64 `
#       --self-contained true --no-restore -p:PublishSingleFile=true `
#       -p:EnableCompressionInSingleFile=true -p:PublishTrimmed=true -p:TrimMode=partial `
#       -p:PublishReadyToRun=true -o kit\da-patch
#   dotnet publish tools-src\tex-inspect\tex-inspect.csproj -c Release -r win-x64 `
#       --self-contained true --no-restore -p:PublishSingleFile=true `
#       -p:EnableCompressionInSingleFile=true -p:PublishTrimmed=true -p:TrimMode=partial `
#       -o kit\tex-inspect
#   发布产物里会有 .pdb，删掉再打包（不然会随 Kit 发出去）。
```

## 7. 体积（2026-09-24，GUI 第六轮重打后）

| 件 | 大小 | 说明 |
|---|---|---|
| `CalaPlayerSrcmBuilder.exe` | **25.6 MB** | PyInstaller onefile（Python + numpy + pillow） |
| `CalaPlayerSrcmBuilderGUI.exe` | **41.0 MB** | PyInstaller onefile --windowed（+ pywebview / fastapi / uvicorn / gui/dist） |
| `kit\da-patch\da-patch.exe` | **27.0 MB** | self-contained 单文件，**trim + ReadyToRun** |
| `kit\tex-inspect\tex-inspect.exe` | **19.2 MB** | self-contained 单文件，**trim only** |
| `kit\retoc` + `native` + `mappings` | 10.9 MB | retoc / oo2core / zlib-ng / usmap |
| **极简版 CLI Kit 合计** | **82.6 MB** | 无 ffmpeg（14 文件：exe + README + `build_srcm.ps1` + `KIT_VARIANT.txt` + kit\） |
| **全量版 CLI Kit 合计** | **287.0 MB** | 另含 `kit\ffmpeg\ffmpeg.exe`（204 MB） |
| **极简版 GUI Kit 合计** | **98.1 MB** | 12 文件（exe + README + 同一个 kit） |
| **全量版 GUI Kit 合计** | **302.4 MB** | 13 文件 |

交付件清单由 `scripts\check_dist.ps1` 守着（哪个 Kit 该有哪几个文件写死在里面）。

瘦身的两个反直觉结论（都已实测 + 回归验证）：
- `PublishTrimmed=true, TrimMode=partial` 能让 `tex-inspect` 41.6 → 20.1 MB，但每次调用 **+147 ms**（JIT 变多）；
  它每次只被调 5~10 次，这笔代价可以接受。
- 对**被频繁调用**的 `da-patch`（一次 50 张背景的运行会调 200+ 次），纯 trim 会让每次 +229 ms（≈ 多 60 s）；
  加上 `PublishReadyToRun=true` 后变成 28.3 MB **且比不瘦身还快**（372 → 301 ms/次）——**R2R 把 trim 的 JIT 代价吃掉了还倒赚**。
  ⇒ 所以两个工具的瘦身策略**故意不同**。

## 8. 真实规模开销（实测，2026-09-23）

把"满额"素材跑一遍：**50 张背景 + 600 s（10 min）音频**，素材本身 100.8 MB：

| 项目 | 实测 |
|---|---|
| 耗时 | **145 s** |
| 交付容器 | `ucas` **170.1 MB**（58 个包 / 59 chunks；`.pak` 347 B、`.utoc` ~3 KB） |
| 峰值临时磁盘 | **约 1.5 GB**（都在 `<srcm 上级>\out_patch\`，原生容器是硬链接不占空间） |
| DA 行数 | `DA_Backgrounds` 165→**215**、`DA_BGM` 100→**102**、`DA_Ambient` 19→**20**、`DA_Sounds` 111→**112** |
| 画质 | 50 张 BC1 的 PSNR **41.5 ~ 43.1 dB** |
| 判据 | A0~A7 全 PASS（未部署，`-DryRun`） |

复跑：`python tests\regression.py --stress`（不在默认套件里，因为它要跑 2.5 分钟）。

> 建一次这样的补丁，请确保 `<srcm 上级>` 所在盘有 **≥ 2 GB** 空闲；容器换成"50 张图"这类大素材时体积大致按 1.4 MB/张 增长，音频按 11.5 MB/分钟（立体声）增长。

## 9. 回归测试（改任何东西之后都要跑）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\run_regression.ps1
#   → 26 个场景，约 4 分钟，全部走"出厂 exe + 沙箱游戏目录 + 真游戏目录守护"
#   --only T1 T6                 只跑指定场景
#   --list                       列出场景
#   --exe <exe>                  换被测 exe（例如全量版）
#   --kit <dir>                  换工具集（例如实验版瘦身工具）
#   --stress                     只跑满额规模测试（50 张图 + 10 min 音频，见 6-c）
```

| 场景 | 断言 |
|---|---|
| T1 全量 dry-run | A0~A8 全 PASS、`deployed=false` |
| T2 部署 + 读回 + 回滚 | 部署的容器哈希 == 构建产物；`uninstall.ps1` 后沙箱回到部署前 |
| T3 只有背景 / T4 只有音频 | 另一类判据显示 `skipped`，不假通过 |
| T5 `-Fit contain`（90×160 竖图） | 在 build 自己写出的 `verify\b_preview.png` 上量几何：中线首末像素 = 黑边色、左右黑边等宽 ±2px、中间确实有画面（实测 `328\|328 px bars`） |
| T6 坏图 / T12 空素材夹 | 非 0 退出 + 指定报错文案 |
| T7 MP3 但无 ffmpeg | 非 0 退出 + ffmpeg 中文指引 |
| T8 超 bg 限额 / T10 PSNR 门 | 非 0 退出（限额 / 画质各自命中） |
| T9 / T11 `-Force` | 越过限额与画质门 |
| T13 `-Combined` | `carried_materials` 非空（累积生效） |
| T14 容器被占用（= 游戏在跑） | 非 0 退出 + "close the game first"，**沙箱一个字节未动** |
| T15 全程没有 ffmpeg | 只用合规 WAV 也能跑完并全门 PASS（= 极简版 Kit 的承诺） |
| T16 全量版自带 ffmpeg | 即使显式禁用 PATH 探测，也回落到 Kit 内的 `kit\ffmpeg\ffmpeg.exe` |
| T17 `-Kit <dir>` | 手动指定的工具目录确实被使用 |
| T18 / T19 | 有 ffmpeg 时 MP3 **确实被转码**；`-Ffmpeg <path>` 指定路径也生效 |
| T20 `-Combined` 但没有历史 | 明确提示 `nothing to carry`，容器只装本次 srcm |
| T21 一次失败的 `-Combined` 之后 | 上一轮的累积状态**没被吃掉**，下一次 `-Combined` 仍能带上 |
| T22 1233×725（宽但不 16:9） | 打包成功，日志出现 `非 16:9 图片` 警告 |
| T23 1024×1024 正方形 | 非 0 退出 + 中文提示 `请自行裁剪或加黑边转换为 16:9` |
| T24 90×160 竖图 + 默认 cover | 同上（**`-Fit contain` 才是逃逸口**） |
| T25 缩略图通道 | 报告里每个 bg 都有 `mi_obj/mi_pkg/mi_ref/mi_tex_ref/mi_scalars`，A8 PASS |
| T26 `-NoThumb` | 不造 MI、`mi_ref` 为空、A8 显式 `skipped`（v1 行为） |
| 全程 | 原生 5 容器哈希不变；**真实游戏目录**不被改动 |

> T16/T17 是条件场景：极简 Kit 里没有 ffmpeg，所以它们会被 `SKIP`。要覆盖它们就显式补跑
> （`--kit <full kit>\kit` 跑 T17、`--exe <full kit>\CalaPlayerSrcmBuilder.exe` 跑 T15/T16）。

> 另外做过一次**对着真实游戏目录的只读 dry-run**（`-Paks D:\CalabiyanGalgameMaker\CalaPlayer -DryRun`）：
> 13.5 s、A0~A7 全 PASS、真实目录 8 个文件哈希**逐个未变**（含已装的 audio3 `_P`）——
> 证明"把 858 MB 的 `ucas` 硬链接进 work 目录"不会写穿原件。
>
> 回归开跑时还会打印一行 **sandbox 是否与真实游戏目录逐字节一致**（8 个容器文件）；
> 不一致会提示 `DRIFTED`，因为这时的结论未必代表真机（本轮就是靠它发现沙箱的 `_P`
> 被早先一次手工安装测试改过、已不是真机的镜像）。

为让限额与画质门可以用小素材测到，脚本支持三个**测试用**环境变量
（正常使用不要设）：`CALA_MAX_BG`、`CALA_MAX_AUDIO_SECONDS`、`CALA_MIN_PSNR`；
另有 `CALA_NO_FFMPEG=1` 用来模拟"本机没装 ffmpeg"。

## 10. 桌面界面（GUI，Vue 3 + FastAPI + PyWebView）

```powershell
python gui\desktop.py                 # 打开窗口
python gui\desktop.py --headless      # 只起本地 HTTP API（会打印带一次性令牌的 URL）
python gui\desktop.py --selftest      # 自检：开窗 -> 页面加载 -> 页面调到后端 -> 退出码
```

* 后端 = 本机 `127.0.0.1` 上的 FastAPI，**只监听回环**，且每次运行生成一次性令牌
  （`?t=` 或 `X-Cala-Token` 头）；没有令牌的 `/api/*` 一律 **403**。
* 界面 = Vue 3 单页（G2）由 `gui/dist` 托管；桌面壳 = PyWebView（WebView2）。
  `gui/dist` 会随 Kit 一起分发（已拍板），所以没装 Node 的机器也能直接跑。
* **打包逻辑与命令行版完全相同** —— GUI 调用的就是同一个 `core.builder.Builder`，
  因此 A0~A7 判据、部署、一键回滚、`build.log` / `build_report.json` 一套到底；
  `core/`、`cli/`、`main.py`、两个 `build_*.ps1` 一个字节都没改。
* 「回滚」按钮 = 调交付目录里现成的 `uninstall.ps1`，**GUI 里没有任何新的回滚逻辑**。
* 「取消打包」在 L0~L4 的日志边界生效；**一进入 L5（部署）就自动忽略取消**，
  保证部署要么完成、要么回滚，绝不留半成品。

接口：`GET /api/health` · `POST /api/start` · `GET /api/logs/{id}`（SSE 实时日志 + 阶段事件）·
`GET /api/report/{id}` · `POST /api/cancel/{id}` · `GET /api/select_folder` ·
`GET /api/open_folder` · `POST /api/uninstall`。同一时刻只允许一个构建在跑（否则 409）。

验证（G1，一条命令）：

```powershell
python tests\gui_api_check.py
#   令牌 403 / 走 HTTP 跑一次 dry-run 并看实时日志 / 与 CLI 的判据逐项一致 /
#   真部署 + /api/uninstall 回滚到部署前 / 取消真的停得下来 / 真机目录不动
```

### 10.1 主题与背景（两张图交叉淡入）

* 工程根目录放两张图：`bg_light.jpg`（亮色）/ `bg_dark.jpg`（暗色），
  构建时复制到 `gui/frontend/public/`，最终进 `gui/dist`。
* 两张图各自做一层**全屏固定背景**（`cover` + `center` + `no-repeat` + `fixed`），
  靠 `opacity` 过渡**交叉淡入淡出**（620 ms），所以切换是"化"过去而不是硬切。
* 右上角的小开关（Uiverse 风格的滑动药丸 + 太阳/月亮交叉淡入）在两者之间切换，
  选择记在 `localStorage`，并在首屏渲染前应用，避免闪一下错的主题。
* **亮色主题不加黑色蒙版**（按你的要求），改用强对比的深色文字 + 半透明白卡片；
  暗色主题才加一层半透明暗幕（`rgba(5,7,12,.6)`）压住背景。
* 所有 CSS 都读同一组主题变量，因此"改一处颜色、两套主题同时跟着变"。

### 10.2 前端构建与自检

```powershell
cd gui\frontend
npm.cmd install          # 首次
npm.cmd run build        # 产出到 gui/dist（FastAPI 直接托管，PyInstaller 也会带上）

# 回到工程根目录后，一条命令验证整个界面：
python gui\desktop.py --selftest --selftest-ui
#   -> 窗口加载 / Vue 已挂载 / 页面读到了 /api/health / 令牌守卫 /
#      亮暗两层背景确实分别指向 bg_light.jpg 与 bg_dark.jpg 且随主题互换 /
#      **从页面里填表并点「开始打包」，等它跑完并断言 A0~A7 全 PASS**
```

页面还刻意暴露了一个自动化钩子（自检与批量脚本都用它，无头也能驱动）：

```js
window.__cala.setParams({ paks: '...', srcm: '...', dryRun: true })
window.__cala.run()
window.__cala.state()      // { running, ok, deployed, gates, da_counts, ... }
window.__cala.toggleTheme()
```

### 10.3 桌面壳：原生目录对话框与窗口尺寸

* 「浏览…」走 `/api/select_folder` → pywebview 的原生文件夹对话框（Vista IFileDialog）。
  它会**从输入框里现有的路径打开**（不是有效目录时退回用户主目录）。
* 对话框失败会**明确报错到界面上**，不会静默什么都不发生 —— 这点很关键：
  pywebview 6 把模块级的 `FOLDER_DIALOG` 常量改成了**弃用的函数**，
  直接把它当参数传进去会让 `create_file_dialog` 走进 `except` 把异常吞掉、
  立刻返回 `None`，**和"用户点了取消"长得一模一样**（本步就抓到这个真 bug）。
  现在统一用 `webview.FileDialog.FOLDER`，并且把 pywebview 的日志抓出来 —— 有异常就 500。
* 窗口最小 `960×620`，在这个尺寸下**仍然保持左右两栏**（左 400 px），日志区高度 ≥ 360 px；
  单栏回退只在更窄的浏览器窗口里出现。

### 10.4 桌面壳自检（G3）

```powershell
python gui\desktop.py --selftest --selftest-shell
#   -> 布局在 1226x783 / 946x583（最小）/ 1226x783 三档都保持两栏且日志区够高；
#      打开原生文件夹对话框：**按窗口类 #32770 精确确认它真的出现了**，
#      再 WM_CLOSE 关掉，并断言这次调用确实阻塞过（>=1.5s）
```

### 10.5 交付 exe 的自检（G4）与两个「只在打包后才出现」的真 bug

```powershell
python tests\gui_exe_check.py            # 默认测 dist 里最新的 GUI Kit
python tests\gui_exe_check.py --keep-log # 失败时把 exe 的完整日志留在 logs/
```

三项检查，按用户实际会遇到的顺序：

1. **双击**：用 `ShellExecuteW` 启动（**这正是资源管理器双击的行为**：不传任何
   std 句柄），要求出现真正属于该 exe 的顶层窗口、会应答 `WM_NULL`、
   **且绝不弹 PyInstaller 的 "Unhandled exception in script" 模态框**。
2. **无控制台启动**：同样的双击方式启动 `--headless --selftest`，要求 HTTP API 起得来
   （这是下面 bug ① 的回归用例 —— 用 `subprocess` 启动会**继承有效句柄，恰好把这个 bug 藏起来**）。
3. **冻结自检**：`--selftest --selftest-ui --selftest-shell --log-file`，断言退出码 0、
   Vue 真的挂载、原生对话框真的出现、**从页面驱动的构建 A0~A7 全 PASS**。

两个 bug（都只有打包成 exe 之后才暴露，源码模式全绿也照样中招）：

* **① `sys.stdout is None` 把 uvicorn 打死。** `--windowed` 的 exe 由资源管理器双击时
  **没有** stdout/stderr，`uvicorn` 的日志 formatter 会调 `sys.stdout.isatty()` →
  `AttributeError` → `Unable to configure formatter 'default'` → uvicorn 根本起不来，
  界面永远不出现，只剩一个模态崩溃框。修法：`gui/app.py` 的
  `ensure_std_streams()`（给缺失的流装一个 `isatty()==False` 的哑流），
  在 `start_server_thread()` / `run_server()` 以及桌面壳 `main()` 开头各调一次。
* **② 没有控制台时 .NET 用 ANSI 代码页写 stdout。** `core/common.py` 一直按 **UTF-8**
  解码子进程输出，但 `da-patch` / `tex-inspect` 没有显式指定输出编码：
  **有控制台时 .NET 写 UTF-8，没有控制台时退回 ANSI（本机 GBK）**。
  于是 `自定义名`（GBK `D7 D4 B6 A8 D2 E5 C3 FB`）被当成 UTF-8 解出 `\ufffd\u0536\ufffd…`，
  A7 判据直接把构建判失败 —— 而 CLI 版（控制台程序、有控制台）和源码模式都是绿的，
  所以这个 bug 只在**双击 GUI exe + 非 ASCII 素材名**时出现。修法：两个工具开头
  `ForceUtf8Stdio()`（`Console.OutputEncoding` + 用 UTF-8 `StreamWriter` 接管标准流）。
  同一个修法也保护了「CLI 被无控制台的宿主（计划任务 / 服务 / `CREATE_NO_WINDOW`）拉起」的场景。

用户素材名含中日文时，② 属于**必修**：不修就是 GUI 一装就失败。

### 10.6 UI/UX 改造轮（布局 / 黑框 / Uiverse / 进度条 / 弹窗）

用户看完真机画面后提的六件事，全部落地并被自检锁住：

1. **布局与自适应（bug 级）**
   * 整个外壳 = flex 列（header / 工作区 / 进度条），工作区 = `grid`，左栏
     `clamp(330px, 30%, 460px)`、右栏 `minmax(0,1fr)`；窗口从 946×583 拉到 1446×903
     时日志区高度 293 → 613 px（自检断言"窗口变高日志必须变高"）。
   * 日志面板**自己滚**（`overflow-y:auto` + 主题化滚动条）并在贴底时自动跟随。
     这里修掉一个真 bug：跑完后**判据面板长高会把日志挤出底部视野**（原来只在"新增行"
     时跟随）⇒ 加 `ResizeObserver`，盒子尺寸变化也重新贴底。自检断言
     `scrollHeight > clientHeight` 且 `atBottom=True`。
2. **子进程黑框**：`gui/no_window.py` 在进程内 patch `subprocess.Popen.__init__`，
   给每个子进程补 `CREATE_NO_WINDOW`（**core/common.py 一个字节没动**）。
   验证不是"设置了标志就算"：自检在**无控制台**的 exe 里 `AttachConsole(child)` 问
   **子进程自己**有没有控制台窗口 ⇒ 打补丁时 `0`，把补丁摘掉（阳性对照）时拿到真实
   HWND ⇒ 判据非空洞。真实构建里 37 个子进程全部走的是补丁后的路径。
3. **Uiverse 视觉**：主题开关和标签包进**实心带阴影的 chip**（原来直接压在照片上，
   字看不清）；INPUTS / OPTIONS / 判据卡片换成带 **hover 渐变环 + 抬升**的卡片
   （`.uv-card-glow`，金→青，和进度条同一套色）；日志与左栏用主题化滚动条。
4. **底部进度条**：`ProgressBar.vue`，`--p` 由阶段推进（L0→L5）+ 结束补满；
   头部就是 `chongci.gif` 本体，配色直接取自 GIF 调色板（**奶金 `#F7E78D` / 青 `#7DD7E4`**），
   所以动图看起来像"长在"进度条上；跑动时有流光 + 头部轻微起伏。
5. **成功 / 失败模态框**：`success.png` + 「转换成功喵」 / `cry.png` + 「洗大锅...出错了喵...」，
   Uiverse 风格的模糊背景 + 缩放淡入淡出。**只有失败弹窗有「⬇ 导出错误日志」**。
   点背景可以关掉，但**只认真实点击**（`isTrusted`）——否则宿主消息泵里的合成点击会让
   结果框自己消失（本轮真踩到，靠模态框内的面包屑 trace 才定位）。
6. **导出错误日志**：`POST /api/export_log/{id}` → 走和 `/api/select_folder` 同一套
   pywebview 原生对话框（`FileDialog.SAVE`）保存 `<task>.log`，内容 = 头部信息 +
   SSE 全量日志 + 磁盘上的 `build.log` / `build_report.json`；**没有日志时返回
   `{"ok":false,"message":"暂无日志可导出"}` 而不是报错**。测试用 `?path=` 直写以便断言。
7. **应用图标**：`gui/dist/T_UI.png` → 构建时生成多尺寸 `T_UI.ico`（`System.Drawing.Icon`
   不认 PNG），既做 PyWebView 窗口图标（`webview.start(icon=...)`）也做 exe 图标
   （`--icon`，日志里能看到 `Copying icon to EXE`）。

自检还多做了两件"看得见"的事：`--selftest-ui` 会**截两张图**（成功/失败弹窗各一张，
`logs/gui_shot_ok.png` / `gui_shot_fail.png`，截图前会把自己的窗口提到前台），
以及把每个断言写进 `desktop.py` 的 `bad()` 列表 —— 冻结 exe 的自检现在是
**UI 层的回归**，`tests/gui_exe_check.py` 逐条复核。

另外两处"交付件不能长垃圾"的收口：GUI 进程启动时把工作目录切到
`%LOCALAPPDATA%\CalaPlayerSrcmBuilder`（双击时 CWD 就是 exe 所在目录，而 srcm
选错时 core 的兜底会把 `build.log` 写进 CWD ⇒ 现在 exe 旁边不会再莫名多出文件；
kit / ffmpeg 探测都是 exe / `_MEIPASS` 路径，与 CWD 无关），`build_gui.ps1` 收尾会清掉
误入 kit 的 `build.log` / `build_report.json` / `.pdb`，`tests/gui_exe_check.py` 则断言
"自检跑完交付目录**不许多出文件**"。

体积：GUI 极简版 **96.2 MB**、全量版 **300.6 MB**（exe 39.2 MB，含图标与新界面）。

### 10.7 GUI 第三轮（分隔条 / 新手引导 / 卡片动效 / 更大的进度条）

1. **日志与判据改成左右并排，中间是可拖拽分隔条**
   * 右栏从"上下堆叠"改成 `SplitPane`：左边实时日志、右边 A0~A7 判据，
     默认**左右对半**，拖动分隔条自由调整，**双击回到 50/50**，方向键微调。
     位置记在 `localStorage`（`cala-split`），下次打开还是你放的位置。
   * 判据面板内部**自己滚动**（`overflow-y:auto` + 主题化滚动条）：条目多的时候
     表头和底部按钮固定、中间滚动，不再被内容撑出窗口。
   * 两边高度都随窗口自适应（纯 flex，没有硬编码像素高度）；窗口从 946×583 拉到
     1446×903 时日志高度 366 → 686 px。
   * 自检不是"看到分隔条就算"：它**派发真实的 pointerdown/move/up** 拖动分隔条，
     断言 pane A 真的变宽（358 → 505 px），再断言复位后回到左右对半。

2. **新手引导（首次启动的分步蒙版）**
   * 六步：`hello.png` 欢迎 → 四步 `guide.png`（选目录 / DryRun 安全带 / 开始打包 /
     日志与判据）→ `end.png` 收尾。
   * 蒙版不是"盖一层黑"，而是**聚光灯**：一个跟随目标元素的方框用
     `box-shadow: 0 0 0 9999px` 把四周压暗，所以每一步的说明都**指着**它讲的那个控件
     （`#card-inputs` / `#card-options` / `#run` / `#split`），并且会跟着窗口缩放重算位置。
   * 右上角常驻 **`? 引导`** 按钮可以随时重看；`跳过引导` / `Esc` 直接结束；
     看过一次记在 `localStorage`（`cala-onboarded`），之后不再自动弹。
   * 自检会**走完六步**并断言：第 1 步是 `hello.png` 且不聚光、中间四步都是 `guide.png`、
     最后一步是 `end.png`、聚光方框与目标元素的矩形**逐坐标吻合（±3px）**、
     **卡片真的可见**（`visibility`/`opacity`/尺寸 > 0/整块在视口内）、
     结束之后真的关掉并记住了选择。
   * ⚠️ 最后那条"真的可见"是补上去的：这个组件最初踩了 `<script setup>` 模板 ref 的坑
     （模板里写 `ref="card"`、变量叫 `cardRef` ⇒ ref 永远是 `null`），`layout()` 直接
     `return`，于是卡片一直停在 `(0,0)` + `visibility:hidden` —— **六步里只看得见聚光，
     卡片从不出现，而旧断言（"DOM 里有 `.uv-ob-art` 且图片解码成功"）全绿**。
     是截图先看出不对，才补上几何/可见性断言。UI 判据别停在"元素存在"。

3. **卡片动效**
   * `选项 / OPTIONS` 卡片：一条金→青的**彗星沿边框循环**（`@property` 驱动锥形渐变角度），
     构建中会加速；hover 抬升。
   * `判据 / GATES` 面板：**ReactBits 的 BorderGlow**（[组件页](https://www.reactbits.dev/components/border-glow)）
     —— 光晕**跟着指针**沿边框走（`--gx/--gy` + 掩膜只留 1.6px 的边），有结果时常亮、
     ALL PASS 时是金青呼吸光。ReactBits 那份是 React + framer-motion 实现，本项目没有 React，
     所以用**纯 CSS 复刻同一个视觉**，不引入新依赖。

4. **进度条上的 `chongci.gif` 放大到 2 倍**
   * 头部 34 → **68 px**，轨道 12 → 20 px，整条高度 46 → 80 px，比例一起放大所以不显突兀；
     配色仍直接取自 GIF 调色板（奶金 `#F7E78D` / 青 `#7DD7E4`）。
   * 自检断言头部实测宽度 **≥ 68 px**（不是"我写了 68 就算"）。
   * （第四轮把**轨道改回 12 px**、头部保持放大，并加了一条**居中判据**，见 §10.8。）

5. **四张截图取证**：`logs/gui_shot_guide.png`（引导）、`gui_shot_layout.png`（跑完的完整界面）、
   `gui_shot_ok.png`（成功弹窗）、`gui_shot_fail.png`（失败弹窗 + 导出按钮）。
   抓图走 **`PrintWindow(hwnd, memDC, PW_RENDERFULLCONTENT)`**：让**窗口自己渲染**
   到自己的一块内存 DC 上，所以别人的窗口盖不住；拿不到帧或整幅单色才回退
   `ImageGrab` + 临时置顶。返回值会带 `[printwindow]` / `[screengrab]` 标记，肉眼能看出
   这张图是怎么来的（此前一路 `SetForegroundWindow` / 置顶都输给一个自己反复抬升的
   窗口，连续三张都拍到用户的聊天窗）。

### 10.8 GUI 第四轮（中英双语 / 引导补全 / Line Sidebar / 社区弹窗）

1. **整个界面双语（zh + en）**
   * 所有文案集中在 `gui/frontend/src/i18n.js`（一套扁平 key + 两本字典）。`lang` 就是一个
     Vue `ref`，所以切换是**即时重渲染整页**——不刷新、不走事件总线。
   * 首次启动的判定顺序：`localStorage`（用户显式选过）→ 否则看系统语言（`zh*` 中文、
     其他英文）。这一步在 `main.js` 里**首帧渲染之前**做掉，所以不会闪一下错语言。
   * 右上角是 **中 / EN** 分段开关；自动化等价物是 `window.__cala.setLang('en')`。
   * 新手引导、两个结果弹窗、社区弹窗全部有中英两版；「暂无日志可导出 / 已取消导出」这类
     提示改成由**页面**根据后端返回的机器可读 `reason` 选词，所以也跟着语言走。
   * **来自冻结 core 的字符串不翻译**（构建日志、判据明细、构建报错）：它们是
     `core/builder.py` 吐出来的，给它们配翻译表只会随着管线加消息而腐烂。
   * 自检会读一组固定文案（运行按钮/取消/加入我们/引导/三个卡片标题/三个选项提示/日志空态），
     切到英文后断言**每一项都变了**且英文里不含 CJK，再切回中文断言中文文案复原。

2. **引导补两步**（把每个控件都覆盖到）：
   * **-Force**：「当素材超过默认限额（bg > 59 张 或 音频 > 10 分钟）或画质 PSNR 低于 25 dB 时，
     需要勾选 -Force 才能继续打包」——它是"我知道我在干什么"的确认，不是加速开关。
   * **进阶**：「这里可以手动指定 ffmpeg 路径、自定义工具目录，以及查看更详细的构建参数」。

3. **选项栏换成 ReactBits 的 [Line Sidebar](https://www.reactbits.dev/components/line-sidebar)**
   * 用 Vue 移植，**机制原样保留**：一个 `rAF` 循环用与帧率无关的指数平滑推进每行的
     `--effect`（0..1），所有派生属性都读这同一个值——`translateX` 让行**朝光标方向滑动**、
     `color-mix()` 把文字颜色混向金青强调色、左侧 marker 线的缩放跟着一起走。因为只有一个
     共享值，所以不会出现 CSS transition 各走各的错位感。
   * 开关是 ON 的行、展开中的「进阶」行、以及永远有值的适配行会被**钉在满效果**，所以
     "哪些是启用状态"一眼可读。
   * 邻近曲线默认用 ReactBits 的 `smooth` 衰减；中心点用 `getBoundingClientRect` 量
     （不必关心 offsetParent 是谁——原版用 `offsetTop`，只有 nav 本身是 offsetParent 时才等价）。
   * 自检用**合成 `pointermove`** 把指针"戳"到某一行上，等缓动收敛后断言：光标下那行
     `--effect > 0.75` 且**至少平移 6 px**，隔两行的那行 `< 0.25` 且位移 `< 3 px`，两者的
     **computed color 必须不同**（证明颜色渐变真的跟着光标走）。不是"组件挂上了"式的判据。

4. **「加入我们」社区弹窗**
   * 右上角 `🐾 加入我们` 打开一个模态框：`gui/dist/joinus.png` + 一段卡拉比丘味的**喵言喵语**
     + 两个按钮。
   * **Discord** → `https://discord.com/invite/BGeYfMBwaw/login`；**B 站**今天是占位符（`#`），
     点了会说「链接还没放上来喵」，而不是什么都不发生。
   * 链接走 `GET /api/open_url`：WebView2 里 `<a target="_blank">` 可能被宿主直接吞掉，
     那看起来就是个死按钮，所以改由后端交给 `webbrowser.open`。该接口只接受一份**短白名单**
     （Discord 邀请链接与 bilibili.com），绝不会变成"本地能打开任意东西"的原语；
     `dry=1` 只做校验不真开（自检用它——自检不该弹浏览器）。
   * 开关动画与结果弹窗同一套 Uiverse 机制（背景淡入 + 弹性缩放），金青光环 + 右上角 ✕。
   * 自检断言：能打开、真的显示 `joinus.png`（解码成功且宽 > 120 px）、两个按钮指向正确、
     标题保留喵味、入场动画存在、B 站占位符有话说、`closeJoin()` 能关掉。

5. **英文 README**：`README.en.md`（与本文同结构、覆盖全部功能）。两份文件顶部互相链接，
   GitHub 上的国际访客能直接落到英文版。

### 10.9 GUI 第五轮（Squish Switch / 乱码解码 / Glide Select / 社区扩四入口）

1. **中/EN 切换件换成 ReactBits 的 [Squish Switch](https://www.reactbits.dev/micro/squish-switch)**
   * `SquishSwitch.vue` 保留了原版机制：旋钮由**真弹簧积分器**驱动（不是 CSS transition），
     并且**用弹簧的速度**驱动形变 —— 沿行进方向拉伸、垂直方向压扁，这就是"squish"；
     悬停微微膨胀，按下后超过 4px slop 还能拖着切换。中/EN 两个字留在轨道两端，
     旋钮滑到哪边就压在哪个字下面。
   * 自检按**真实按下**（pointerdown + pointerup，它在 pointerup 上切换，合成 `.click()`
     不会触发），然后**每 45ms 采样 17 次**旋钮的 transform：断言 `|scaleX−1| > 0.02`
     且 `minSy < 0.999`（真的拉伸并压扁过，不是"能动就算"），末态停在另一端、语言真的换了。

2. **切换语言时的"乱码解码"波纹**
   * ReactBits 原版 [Scrambled Text](https://www.reactbits.dev/text-animations/scrambled-text)
     是**鼠标邻近触发**的；用户明确要求**不要**这样。`ScrambleText.vue` 因此改成：
     **按下切换按钮时一次性播放**的"解码波" —— 每个字符先显示噪声，再按它与**点击点**的
     距离依次落定（即"点击扩散"），播完就结束；之后鼠标怎么滑过都不再触发，只有下一次
     切换语言才再播一次。
   * 噪声字形**按脚本选**（CJK→随机汉字、拉丁→随机字母），这样每个字符的宽度基本不变，
     整行不会因为乱码而重排。目前覆盖 23 个文本节点（三个卡片标题、路径标签与「浏览…」、
     五个选项的标题与说明、开始打包/取消、日志空态、进度条文案、右上角两个按钮与主题标签）。
   * 自检**在页面内部**每 60ms 采样一次时间序列（跨进程 `evaluate_js` 的往返比波纹本身还慢，
     从 Python 读永远只能看到落定后的结果）：断言序列里至少一个采样 `running > 0` 且
     `#run` 显示的既不是中文也不是英文、序列末尾必须是落定的英文；随后派发 5 次 pointermove
     的采样里 `running` 必须**一直是 0**（证明不被悬浮触发）。
   * ⚠️ 这条判据当场抓到一个真 bug：组件里用了 `nextTick` 却**忘了 import**，异步 watcher
     抛出的 ReferenceError 被 Vue 吞掉 → 文字**瞬间切换、波纹从未运行** ——
     而"切换后文案正确"这类断言依然全绿。**只有时间序列能看见它。**

3. **「背景适配」下拉换成 ReactBits 的 [Glide Select](https://www.reactbits.dev/micro/glide-select)**
   * `GlideSelect.vue`：弹出层里只有一个「pill」元素，在行之间**滑行**
     （`translateY(行号 × 步高)`），配 pop 缩放进出、指针划选、方向键/Home/End/typeahead、
     空间不足时上下翻转、选中值变化时标签有一次 blur-swap。
   * 自检：真实按下打开 → pill 在第 0 行 → `pointerover` 到第 1 行 → **pill 位移 ≥ 20px** →
     划选 → 值变 `contain`、触发按钮上的标签跟着变、菜单关闭。

4. **「加入我们」扩到四个入口**
   * **GitHub**：图标外面套一圈**满天飞的星星**（9 颗，各自方向/节奏/延迟不同，CSS 无限动画
     `gh-fly`）；点击 → 打开 `https://github.com/killa0132/CalaplayUpper`，**并且**蹦出
     `star.png` 的"求 star"弹窗（**上下结构**：图在上、喵言喵语在下，两个按钮
     「去点一颗星 / 下次一定喵」）。
   * **QQ**：点击 → **先把群号 `1054243070` 复制到剪贴板**，再弹出 `joinQQ.png` + 群号 +
     「来吧！到猫窝里就地复原吧！」文案 + 「再复制一次」按钮。
   * 剪贴板走后端 `GET /api/copy`：WebView2 里 `navigator.clipboard` 需要安全上下文 **且**
     要有用户手势，缺一个就**静默失败** —— 那又是个死按钮。该接口只接受 ≤256 字符的文本，
     `dry=1` 只校验不写。自检**真实写入并用 Win32 `GetClipboardData` 读回比对**，
     而且**先读出用户原有剪贴板内容、测完再写回去**（不打扰用户桌上正在用的东西）。
   * `GET /api/open_url` 白名单加入 GitHub 仓库地址（Discord / bilibili 之外）。
   * 三个弹窗（hub / star / QQ）共用同一套 Uiverse 进出场动画，都是淡入 + 弹性缩放。

5. **截图证据**新增 `gui_shot_{scramble,squish,glide,star,qq}.png`。

### 10.10 GUI 第六轮（引导只弹一次 / 社区栏改版 / 下拉穿透 / 左栏定宽 / 右栏填满）

1. **新手引导"只在首次打开时自动弹出" —— 这条以前是坏的，根因不在 localStorage 的写法，
   而在页面根本没有稳定的 origin。**
   * 页面是从 `http://127.0.0.1:<每次启动随机分配的端口>/` 加载的（端口随机是为了别的本机
     程序猜不到它），而 WebView2 的 `localStorage` **按 origin（含端口）分桶** ⇒
     每次启动都是全新空桶：`cala-onboarded`、`cala-lang`、`cala-theme`、`cala-split`
     全都悄悄退回默认值，引导**每次都弹**。
   * 现在这些值走 `%LOCALAPPDATA%\CalaPlayerSrcmBuilder\prefs.json`（新增 `gui/prefs.py` +
     `GET/POST /api/prefs`，只接受白名单键、值 ≤64 字符、原子写 tmp+`os.replace`）。
     前端 `src/prefs.js` 在 `main.js` 里 **mount 之前**拉一次，之后所有读取都是同步的
     （主题与语言必须落在**第一帧**上）；`localStorage` 仍然同步写一份，供 `npm run dev`
     与浏览器调试用。
   * 自检把这件事**证明到位**：开窗前先 `prefs.clear(['cala-onboarded'])` 造出真正的"首次运行"⇒
     引导必须**自己弹出来**（不是靠 `restart(0)`）；走完后读 `GET /api/prefs` 必须看到
     `cala-onboarded=1`；最后**真的 `location.reload()`**（这就是"下一次启动"）⇒
     新页面里 `guide=False, auto=False`。跑完把用户原来的 prefs 原样写回（和剪贴板同一条规矩）。
   * 引导卡片本身也修了三处：卡片加 `max-height` + 纵向滚动（再长也读得全）、
     按钮栏 `flex-wrap: nowrap` + 按钮 `flex:none; white-space:nowrap`（"跳过引导 / 九个小圆点 /
     上一步 / 下一步"**一行放得下**，不再折行挤压；卡片同时从 392 → 436px 宽）、
     聚光框在目标滚不进视口时**退化为"可见部分"**而不是画在屏幕外（并只滚动真正可滚动的祖先，
     绝不 `scrollIntoView` 到 `overflow:hidden` 的右栏）。

2. **社区弹窗改版**
   * GitHub 图标换成用户给的 **Octicon `mark-github`** 原始 path（自检断言 path 前缀
     `M10.226 17.284c-2.965-.36-5.054`，而不是"有个图标"）。
   * 四个入口（Discord / B站 / GitHub / QQ）改成**一个 2×2 Grid**，四个按钮同宽；
     以前是 flex-wrap，QQ 被挤到单独一行。
   * **悬浮不再卡出滚动条**：那 9 颗"满天飞"的星星是绝对定位子元素，会把祖先的
     *scrollable overflow* 撑大 —— 这正是滚动条出现的原因。现在飞行半径收到 13~28px、
     弹窗加 `overflow-x: hidden`，自检直接读 `scrollWidth/clientWidth` 与
     `scrollHeight/clientHeight`，**悬浮前后都必须相等**。

3. **「背景适配」下拉点到别的东西 —— z-index / 事件穿透**
   * 根因是**栈上下文**：下拉原本渲染在选项卡片内部，而卡片有 `backdrop-filter`
     （自成栈上下文）、每一行又带 `z-index`，于是菜单被**画在下一行（DryRun）后面**，
     点击自然落到 DryRun 上。修法是把弹出层 `<Teleport to="body">` + `position: fixed`
     （`place()` 按触发按钮的实时位置摆位，滚动/缩放时重新摆位，外部点击判定也要认这个
     "已经不是子节点"的菜单）。
   * ⚠️ 顺带抓到一个**只有 teleport 才会暴露**的坑：`--gs-*` 这些 CSS 变量原来只写在
     `.uv-gs` 根上，弹出层搬到 `<body>` 后**不再继承** ⇒ 行高、pill 高度全变成 `auto`，
     "pill 滑到第 N 行"和"鼠标点在第 N 行"用到的是两套尺寸 ⇒ 点到的是上一行。
     现在变量同时挂在根与弹出层上。
   * 判据不能再是"菜单打开了吗"：自检用 `document.elementFromPoint(选项行中心)` 问
     **浏览器到底把哪个元素画在那里**，断言拿到的是第 1 行（contain）而不是别的行；
     再断言 `position=fixed`、父节点是 `BODY`。另外组件里留了
     `window.__calaGsTrace` 面包屑（open/down/up/pick/close），"关了菜单但没选上"
     这种状态一眼就能定因。

4. **「浏览…」按钮被挤扁 & 左栏加载后收缩**
   * 浏览按钮原来是弹性 flex 项，路径一长就被压成一条 —— 现在换成"文件夹 SVG + 文案"、
     `flex: none; white-space: nowrap`，标签也不再换行（`ScrambleText` 新增 `nowrap`，
     因为它的 `white-space: pre-wrap` 会盖掉继承来的 nowrap）。
   * 左栏宽度按用户要求固定：`grid-template-columns: clamp(330px, 30%, 460px)` 不动，
     左栏加 **`scrollbar-gutter: stable`** —— 以前内容长到出滚动条时，卡片会突然少 11px
     （"加载后自己收缩一点"）。自检往左栏塞一个 1400px 高的临时元素逼出滚动条，
     断言**前 / 溢出后 / 移除后** `#card-inputs` 的宽度三者完全一致。
   * 那条 11px 曾经让「背景适配」标签折成两行，所以顺带把选项行改成
     **标题 nowrap + 右侧控件先让位**，并加了"标签既没折行也没被省略号截断"的断言
     （`scrollWidth <= clientWidth`）。

5. **截图证据**新增 `gui_shot_second.png`（第二次启动：引导不再自动弹），
   `gui_shot_join_hover.png`（GitHub 悬浮态：四宫格 + 无滚动条），
   `gui_shot_layout_min.png`（最小窗口下的整体布局）。

6. **小窗口 / 大窗口下右侧布局不适配 —— 一个 CSS 类名撞车**
   * 现象：右栏内容**只占左边一部分、且在栏内居中**，判据卡片被挤成几十像素；
     窗口越大右栏越空（1446 px 时分割条仍只有 717 px，本该 976 px）。
   * 根因：`App.vue` 里给**页头右侧按钮组**写的 `.right { display:flex; align-items:center;
     flex-wrap:wrap }`，同时命中了**工作区右列** `<section class="col right">`
     —— 于是那一列被加了 `align-items:center`（子元素不再拉伸 ⇒ SplitPane 变成
     shrink-to-fit 并居中）和 `flex-wrap:wrap`。**和第五轮 `.uv-ss-face.left` 撞
     `document.querySelector('.left')` 是同一类错误**：一个通用类名被两处共用。
   * 修法：页头那组改名为 `.bar-right`（模板 + 样式各一处）。改完小/中/大三档都是
     `split 宽 == 右栏宽`、第一个面板紧贴栏左边、两面板等宽、chips 行与任务号铺到栏右缘。
   * 顺带：`「背景适配」` 下拉的**收起态只显示短值**（`cover` / `contain`，完整说明在展开的
     菜单里）—— 原来的 198 px 长标签在最小窗口（左栏 330 px）里会把行标题挤成省略号。
   * 新判据（全部在 `--selftest-shell` 里，四档窗口各测一遍）：`splitW == rightW`、
     `paneAL == 右栏左边`、`paneA == paneB`、`判据卡右缘 ≤ 栏右缘`、
     `chips/taskid 右缘 == 栏右缘`、**大窗口的面板宽度必须比标准窗口大 20px 以上**（"真的会随窗口适配"），
     以及最小窗口下 `选项行标签既不折行也不被截断`（`trunc=0/5`）。

## 11. 已知边界（明确接受 / 待修）

* ⚠️ **时间轴单元格 + 编辑器右侧 Background 预览块不显示新增背景**（2026-09-26 定案）。
  原因是**游戏原生蓝图不响应**这两个位置——**连游戏自带的背景也不显示在上面**（只读活进程探针 C1 定案）。
  不受影响：下拉缩略图（CP-34 已修好）、主菜单章节封面、游戏画面里的背景本体。
  运行时补救方案（R2）已废弃（严重卡顿 + 重启失效 + 作者确认原语不对），
  现行路线 = **静态追加预览图集 `T_BackgroundPreviews`**，只读评估见
  [`CP35_ATLAS_APPEND_ASSESSMENT.md`](CP35_ATLAS_APPEND_ASSESSMENT.md)。
* ⚠️ **`-Combined` 目前在"再加一张背景"时不可用**（2026-09-26 实测，**待修**）：
  `-Combined` 会把上一轮**已经追加过行**的 `DA_Backgrounds` 当基线，而 `da-patch bgref`/`addname`
  走 UAssetAPI 重新序列化整包，在这个基线上会让 **uexp 多出 34 B（一整行）而行计数不变**
  ⇒ L3 的 trailer 门直接拒绝（`DA_Backgrounds trailer check failed`）。
  **失败是安全的**（碰任何文件前就停、游戏目录零写入、上一轮累积状态自动还原），但功能不可用。
  实测对照：原生 DA(165 行) 上两者都 **+0 B**；已追加 DA(166 行) 上两者都 **+34 B**。
  29 场景没抓到，是因为唯一覆盖 `-Combined` 的 T13 第二次跑用的是**只有音频**的夹具
  （`srcm="extra"` 只有 `Ambient\extra.wav`）⇒ `DA_Backgrounds` 那一支 `rows=[]`、从不调 `bgref`。
  绕行（已验证）：换一个**新的 out_patch** 做全新构建，srcm 里把上一轮素材按**同名文件**再放一遍。
  建议修法（架构级，先出方案再动手）：`-Combined` 时 DA 基线改用**原生 DA**，
  carried 行 + 新行统一走字节级 `append_bg_rows`。
  **2026-09-26 用户拍板：先记账、不修**，等图集路线定了再一起处理。
* **背景数量上限：拍板取 48（尚未实现，代码里现在仍是 50）** —— 2026-09-26 为图集追加方案的
  块对齐硬上限（48 格）预留：将来默认上限取 48，只有显式 `-Force` 才允许突破到 50，
  并且要**警告缩略图可能不显示**。改这一条要连 `core/config.py` 的上限与回归里的上限用例一起改。
* PCM 不压缩：48 kHz 立体声 ≈ 11.5 MB/分钟，单声道 ≈ 5.8 MB/分钟。
* 不含 OGG/Vorbis 压缩路线（引擎有 `VorbisAudioDecoder`，属后续可探索项）。
* 不含"替换原生条目"（只追加）。

---

## 12. 开发与调试指南

### 12.1 两个进程，先起后端

界面分两半：**页面**（Vue；可以是 vite 的 dev server，也可以是打包好的 `gui/dist`）和
**后端**（FastAPI；真正干活的还是 `core/`）。开发时两个一起跑：

```powershell
# 终端 1 —— 后端（--dev 固定用 8756，正好给 vite 做代理；并打开 WebView2 DevTools）
python gui_main.py --dev

#   ……或者不要窗口，只留 HTTP API（推荐：直接用浏览器调前端）
python gui_main.py --headless
#   它会打印 http://127.0.0.1:<端口>/?t=<一次性令牌>；没有令牌的 /api/* 一律 403

# 终端 2 —— 前端 dev server（热更新）
cd gui\frontend
npm.cmd install        # 首次
npm.cmd run dev        # http://127.0.0.1:5173
```

* `--dev` 的后端端口固定在 **8756**（`gui/desktop.py::DEV_PORT`），`vite.config.js` 把
  `/api` 代理到它，所以页面不需要 CORS、也不用知道真实端口。想换：
  `$env:CALA_API='http://127.0.0.1:9000'` 之后再 `npm.cmd run dev`。
* 用**浏览器**调试（而不是内嵌窗口）时：跑 `python gui_main.py --headless`，把它打印的
  `?t=<令牌>` 接到 `http://127.0.0.1:5173/` 后面再打开 —— 令牌不匹配就连不上后端。
* 本机 `npm.ps1` 被 PowerShell 执行策略拦，**一律用 `npm.cmd`**。
* 出正式产物：`npm.cmd run build`（落 `gui/dist`，FastAPI 直接托管、PyInstaller 也会带上）。

### 12.2 打开 DevTools

| 场景 | 做法 |
|---|---|
| 内嵌窗口（pywebview / WebView2） | `python gui_main.py --dev`（即 `webview.start(debug=True)`），窗口里按 **F12** 或 **Ctrl+Shift+I**，右键也有"检查" |
| 浏览器 | F12 |
| 后端日志 | 后端那个终端就是；再加 `--log-file x.txt` 会同时落一份 UTF-8 副本（无控制台的 exe 只能靠它） |

页面里有一个**刻意公开**的自动化钩子（自检与批量脚本都用它，无头也能驱动）：

```js
window.__cala.setParams({ paks:'D:\\CalabiyanGalgameMaker\\CalaPlayer', srcm:'D:\\srcm', dryRun:true })
window.__cala.run()               // 走一遍打包（和点按钮完全同一条路径）
window.__cala.state()             // { running, ok, deployed, gates, da_counts, split, guide, ... }
window.__cala.cancel()            // 阶段边界取消
window.__cala.toggleTheme()
window.__cala.setSplit(35)        // 分隔条位置（%）
window.__cala.onboard.state()     // 新手引导：state/next/prev/skip/restart(from)
window.__calaErrors               // 页面里所有未捕获错误（排查"组件静默消失"必备）
window.__calaModalTrace           // 结果弹窗的开/关面包屑（排查"弹窗自己没了"）
```

### 12.3 改完代码之后的验收顺序

```powershell
# 0) 只要动了 .py，先确认语法。PyInstaller 对有语法错误的入口**不会失败**，
#    它只会跳过依赖、打印 "Build complete"，然后给你一个明显变小的坏 exe。
python -m py_compile gui\desktop.py

# 1) 源码自检：Vue 挂载 / 双主题 / 新手引导走完六步 / 布局与分隔条拖动 /
#    原生文件夹对话框 / 从页面驱动一次真构建（A0~A7 必须全 PASS）
python gui\desktop.py --selftest --selftest-ui --selftest-shell

# 2) 接口层（G1）：令牌 403 / SSE / 与 CLI 判据逐项一致 / 真部署 + 回滚 / 取消
python tests\gui_api_check.py

# 3) CLI 29 场景回归（约 4 分钟，出厂 exe + fakegame 沙箱 + 真机目录守护）
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\run_regression.ps1

# 4) 重打交付件 + 验冻结 exe（G4：双击 / 无控制台启动 / 冻结自检）
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_gui.ps1
python tests\gui_exe_check.py --keep-log
```

* **改了 `tools-src/` 里的 C#** 还要重新 self-contained 发布（命令见第 6 节），
  然后**必须重跑 `build_kit.ps1` 与 `build_gui.ps1`** —— 那两个脚本是把 `kit\` **拷**进 `dist\` 的。
* 界面素材（png/gif）放 `gui/frontend/public/`；也可以直接丢进 `gui/dist/`，
  `build_gui.ps1` 第一步会把它搬进 `public/`（vite 每次 build 都会清空 `gui/dist/`）。
* 自检会在 `logs/` 下留证据：`gui_shot_guide.png`（新手引导）、`gui_shot_layout.png`（跑完的
  完整界面）、`gui_shot_ok.png`（成功弹窗）、`gui_shot_fail.png`（失败弹窗 + 导出按钮）。
  抓图用 **`PrintWindow` + `PW_RENDERFULLCONTENT`**（窗口自己渲染，别人的窗口盖不住），
  回退才是 `ImageGrab`；返回值带 `[printwindow]` / `[screengrab]` 标记。
* `python tests\gui_exe_check.py` 还能 `--only 1|2|3` 单独跑某一项；它跑完会断言
  "交付目录里不许因为自检多出任何文件"。

### 12.4 VSCode 插件与配置

仓库里已经放好 `.vscode/`（可以直接用）：

| 文件 | 内容 |
|---|---|
| `.vscode/extensions.json` | 推荐插件：**Vue - Official (Volar)**、**Python + Pylance**、**PowerShell**、**C# Dev Kit**（改 `tools-src/`）、**EditorConfig** |
| `.vscode/settings.json` | 解释器指向 `python\Scripts\python.exe`；隐藏 `python/` / `build_out/` / `__pycache__` / `tests/mat` / `tests/fakegame` 这些噪声目录；UTF-8 + LF |
| `.vscode/launch.json` | 四个调试配置：GUI 后端 `--dev`、GUI 源码自检、CLI dry-run、当前文件 |

其它顺手建议：
* 终端一律用 **PowerShell**，但记住本机 `pwsh` 的坑：`>` 重定向会写 UTF-16、
  控制台是 GBK（所以工程里所有日志文件调用都显式用 `-Encoding UTF8`）。
* 调试"页面里点不动/弹窗自己没了"这类问题时，先看 `window.__calaErrors` 和
  `window.__calaModalTrace` —— 这两样是专门为此埋的。
* 调 UI 时开着 `npm.cmd run dev`，改 `.vue` 存盘即刷新；改完记得 `--selftest` 过一遍，
  因为**很多坑只在冻结 exe / 无控制台时才出现**。

---

## 13. 更多界面 + 整活

「加入我们」是四个入口：Discord / B站 / **GitHub**（点开仓库的同时蹦一个求 star 的弹窗）/
**QQ 群**（点一下群号就直接进剪贴板）。

| 社区弹窗（四入口 2×2 宫格） | 鼠标停在 GitHub 上：图标外一圈星星满天飞 |
|---|---|
| [<img src="images/community.jpg" width="430">](images/community.jpg) | [<img src="images/community-hover.jpg" width="430">](images/community-hover.jpg) |

| 求 star（上下结构：图在上，喵言喵语在下） | QQ 群：点一下就把群号抄到剪贴板 |
|---|---|
| [<img src="images/star.jpg" width="430">](images/star.jpg) | [<img src="images/qq.jpg" width="430">](images/qq.jpg) |

英文界面、最小窗口、以及几处动效的抓帧：

| English UI | 最小窗口（960×620）也不塌 |
|---|---|
| [<img src="images/ui-en.jpg" width="430">](images/ui-en.jpg) | [<img src="images/ui-layout-min.jpg" width="430">](images/ui-layout-min.jpg) |

| 「背景适配」下拉（Glide Select） | 选项栏（Line Sidebar：光标靠近就滑动变色） |
|---|---|
| [<img src="images/dropdown.jpg" width="430">](images/dropdown.jpg) | [<img src="images/line-sidebar.jpg" width="430">](images/line-sidebar.jpg) |

| 切语言时的「乱码解码」波纹 | 中/EN 切换件（Squish Switch，真弹簧 + 形变） |
|---|---|
| [<img src="images/scramble.jpg" width="430">](images/scramble.jpg) | [<img src="images/squish.jpg" width="430">](images/squish.jpg) |

界面里的几只猫（`gui/frontend/public/` 里的原图，也随 Release 一起发）：

| <img src="images/T_UI.png" width="150"> | <img src="images/hello.png" width="150"> | <img src="images/guide.png" width="150"> | <img src="images/end.png" width="150"> |
|---|---|---|---|
| 图标 `T_UI.png` | 引导·欢迎 `hello.png` | 引导·步骤 `guide.png` | 引导·结束 `end.png` |
| <img src="images/joinus.png" width="150"> | <img src="images/star.png" width="150"> | <img src="images/joinQQ.png" width="150"> | <img src="images/cry.png" width="150"> |
| 社区弹窗 `joinus.png` | 求 star `star.png` | QQ 群 `joinQQ.png` | 失败 `cry.png` |

> 想改成自己的猫？把图片塞进 `gui/frontend/public/`（文件名对上）再重跑 `build_gui.ps1` 就行。

