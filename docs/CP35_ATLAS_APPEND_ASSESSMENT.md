# CP-35 · 预览图集追加方案（只读评估报告）

> 状态：**只读评估，尚未动手改任何产品代码**。等你拍板。
> 日期：2026-09-26。作者 Discord 给的唯一静态解法 = 「往 `T_BackgroundPreviews` 末尾追加 250×141 小图，
> 并把 `MMI_BackgroundSelector` 实例上的 `SpriteX/SpriteY` 指过去」。
> 本报告把这句话拆成可验证的字节事实，并给出「能做 / 风险 / 分阶段 / 回滚」。
> 配图：[`images/cp35_atlas_free_space.png`](images/cp35_atlas_free_space.png)

---

## 0. 结论（先说三选一）

| 问题 | 结论 | 依据 |
|---|---|---|
| **图集末尾还有没有空位？** | **有，而且是连续的 476 px 高、4096 px 宽的纯黑空区**（第 11~13 行全空）。按「块对齐」放法能塞 **48 格** 250×141 | 解码 mip0 逐格测量，见 §2；配图红框 |
| **要不要重建整个 `.uexp` / `.ubulk`？** | **不用**。这张图集**没有 `.ubulk`**（13 级 mip 全部内联在 `.uexp`）；我们的改动是**等长像素替换**，`.uexp` 长度 / mip 数 / 尺寸 / 格式 / `uasset` 的 `SerialSize`、BulkDataMap **一个都不变**。要重做的只有**容器**（`retoc to-zen` 一次），已实测**逐级 sha256 无损** | §3、§4 实测 |
| **会破坏原有下拉预览图吗？** | **不会**。BC1 是 4×4 分块 ⇒ 我们的格子只覆盖 63×36 个块，**其余块逐字节原样复制**；165 个原生 MI 的「坐标 + 尺寸 + 图集」三件套完全不变 | §4.3；可写成断言，见 §6 A9 |
| **唯一还没证明的一环** | **当前 build 里"谁来把 SpriteX/SpriteY 写进那两个材质"** —— 两个材质的参数结构已经证明是「图集 + 坐标」接收端，但需要一次**只读**活进程探针确认游戏自己有没有写。这一环决定「本 build 就能修好」还是「要等作者下一版」 | §5（阶段 0） |

---

## 1. 怎么测的（可复现，全程只读）

> 真机目录 `D:\CalabiyanGalgameMaker` 只被**读取**，没有写入任何字节；
> 所有中间产物落在上游仓 `work/cp35_atlas/`。

```powershell
$kit  = 'D:\dsharnessProject\CalaplayUpper\kit'
$paks = 'D:\CalabiyanGalgameMaker\CalaPlayer\Content\Paks'
$out  = 'D:\dsharnessProject\CalabiyauGalMaker\work\cp35_atlas'

# 1) 头部/mip 台账（CUE4Parse）
& "$kit\tex-inspect\tex-inspect.exe" $paks "/Game/CalaPlayer/UI/EditorUI/Textures/T_BackgroundPreviews" `
    "$out\texdump" "$kit\mappings\CalaPlayer-UE5.7.usmap" > "$out\texinspect_full.txt"

# 2) 取原始 legacy 字节（注意要传整个 Paks 目录、-f 是子串匹配）
& "$kit\retoc\retoc.exe" to-legacy $paks "$out\legacy" --no-script-objects --no-shaders --version UE5_7 -f T_BackgroundPreviews

# 3) 逐格测量 + 出图
& 'D:\dsharnessProject\CalaplayUpper\python\Scripts\python.exe' work\cp35_atlas\probe_atlas.py
& 'D:\dsharnessProject\CalaplayUpper\python\Scripts\python.exe' work\cp35_atlas\probe_grid.py
```

**证据索引**（都在 `work/cp35_atlas/`）：

| 文件 | 内容 |
|---|---|
| `texinspect_full.txt` | 图集头部 + 13 级 mip 的 size/sha256/head（注意：PowerShell `>` 重定向写成 UTF-16LE，脚本里已按 BOM 解码） |
| `legacy/.../T_BackgroundPreviews.{uasset,uexp}` | 原生图集原始字节（uasset 1,351 B / uexp 5,592,759 B） |
| `atlas_report.json` | 13 级 mip 的偏移、逐级 sha256 校验、帧间空隙、占用图 |
| `atlas_grid.json` | 224 格的 `bbox_rel` / 内容占比 / 空闲格清单 |
| `atlas_mip0.png`、`atlas_mip0_thumb.png` | 解码回来的图集（含 1-bit alpha 正确解码） |
| `verify_dump.txt` / `verify_mut_dump.txt` | 容器重建后与「改 1 字节」后的读回台账 |

---

## 2. 图集的真实事实

### 2.1 资产层（CUE4Parse 读回）

| 字段 | 值 |
|---|---|
| 包路径 | `/Game/CalaPlayer/UI/EditorUI/Textures/T_BackgroundPreviews` |
| 尺寸 / 格式 | **4096 × 2048**，**PF_DXT1（BC1）** |
| mip 数 | **13**（`FirstMipToSerialize=0`，`NumMipsInTail=0`，`ExtData=0`） |
| 存储 | 每级 `BULKDATA_SingleUse \| BULKDATA_ForceInlinePayload`，**全部内联**；`retoc to-legacy` 只吐出 `.uasset` + `.uexp`，**没有 `.ubulk`** |
| 其它 | `LODGroup=TEXTUREGROUP_UI`、`Filter=TF_Nearest`、`sRGB=True`、`AddressX/Y=TA_Clamp`、`CompressionSettings=TC_Default` |
| 尺寸 | `.uexp` = 5,592,759 B，13 级负载合计 = **5,592,424 B** |

### 2.2 字节帧格式（逐字节核实）

```
[ 头部 111 B ][ BulkDataMap 索引 0 (4 B) ]
  for i = 0..11:  payload_i  [SizeX_i SizeY_i SizeZ_i  index_(i+1)]
                  payload_12 [1 1 1  0]
                  [8 B 零][PACKAGE_FILE_TAG c1 83 2a 9e]
```

实测（`atlas_report.json`）：

* mip0 负载位于 **offset 115**，其 sha256 与 `tex-inspect` 报的 `6741372026AD7AF1` 一致；
* 每级之后固定 **16 B** = `SizeX, SizeY, SizeZ` + **下一级的索引**（例：mip0 后 = `4096, 2048, 1, index=1`）；
* 13 段空隙逐段打印、逐段吻合；尾部 28 B = `1,1,1, index=0` + 8 B 零 + `c1832a9e`；
* 13 级 mip 的 size 全对（4194304 → 1048576 → … → 8 → 8 → 8）。

> 结论：**每级 mip 的帧格式与背景壳完全相同**（同样的「payload + 16 B 记录」、同样的尾部 tag），
> 但**头部长度是按资产变的，不能当常量**：
>
> | | 头部 | mip0 偏移 | `@2` | `@50` | `PF_DXT1` FString |
> |---|---|---|---|---|---|
> | 背景壳 1920×1080 | **110 B** | 114 | SizeX,SizeY 对 | = `len-62` | @86 |
> | 图集 4096×2048 | **111 B** | **115** | 不是尺寸对（真尺寸对在 `@6`） | = **0** | @91 |
>
> ⇒ 现有 `core/texture.py` 的 `HEADER_LEN = 110` 是**壳专用**的（`compose`/`roundtrip_check`/`parse_header` 都用它）；
> 拿它套图集会被同尺寸回环门**正确地拒绝**（这正是此前 `work/cp35_routeb_check.py` 报"壳 PASS / 图集 FAIL"的真因，
> 不是"图集没有那 16 B 记录"）。实现图集路线时要把头部长度**按资产实测**
> （`locate_mips` 本来就用 tex-inspect 的 mip0 head 定位，把 `HEADER_LEN` 换成实测值即可）。

### 2.3 格子几何（解码 mip0 后逐格量）

* 图集背景色 = **纯黑 (0,0,0)**，不透明（没有任何块使用 1-bit alpha）。
* 逐格 `bbox_rel`（相对格子原点）实测 = **`[0, 0, 249, 140]`**，即 **250 × 141**，原点 = `(列*252, 行*143)`。
* 网格：**16 列 × 14 行 = 224 格**，其中 **165 格被占用**，**59 格全黑**。
* 占用图（`1`=有内容）：

```
r0..r9  1111111111111111   (10 行 × 16 = 160)
r10     1111100000000000   (5 格)
r11     0000000000000000
r12     0000000000000000
r13     0000000000000000
```

* 有内容像素的 y 范围 = **0 … 1571**；**y ≥ 1572 全部是纯黑**。

### 2.4 原生 MI 的坐标约定（实测 11 个）

`da-patch miprobe` 打在从**原生容器**导出的 `MI_BackgroundPreview_*` 上：

| MI | SpriteX | SpriteY | 其它 4 个标量 | SourceTexture |
|---|---|---|---|---|
| `_000` | 0 | 0 | `250 / 141 / 4096 / 2048` | `T_BackgroundPreviews` |
| `_001` | 252 | 0 | 同上 | 同上 |
| `_015` | 3780 (=15×252) | 0 | 同上 | 同上 |
| `_016` | 0 | 143 | 同上 | 同上 |
| `_017` | 252 | 143 | 同上 | 同上 |
| `_159` | 3780 | 1287 (=9×143) | 同上 | 同上 |
| `_160` | 0 | 1430 (=10×143) | 同上 | 同上 |
| `_164` | 1008 (=4×252) | 1430 | 同上 | 同上 |

⇒ **`SpriteX/SpriteY` 就是图集里的像素原点**，`SpriteWidth/Height = 250/141`，`TextureWidth/Height = 4096/2048`。
`MI_000..MI_164` 正好一一对应 §2.3 的 165 个占用格（前 10 行 160 格 + 第 11 行 5 格）。
本报告后面所有坐标都按这套约定写。

### 2.5 两个「问题控件」的材质：本来就是图集接收端

`da-patch probe` 读名字表（cooked 材质里参数名会留在名字表中）：

| 材质 | 直接引用的贴图 | 声明的参数 |
|---|---|---|
| `MM_BackgroundPreviewBase`（右侧 Background 预览块的父材质） | **`T_BackgroundPreviews`** | `SourceTexture, SpriteX, SpriteY, SpriteWidth, SpriteHeight, TextureWidth, TextureHeight` |
| `MM_SubslotContentBase`（时间轴单元格的父材质） | **`T_BackgroundPreviews`** | 同上 7 个 |
| `MM_DropdownImageItem`（下拉条目） | `DefaultTexture` + `T_EditorPanels` | 同上 7 个 |

⇒ **这两个控件从设计上就是「图集 + 坐标」的接收端**，作者说的那条路在架构上成立。
`MMI_BackgroundSelector` 这个实例把 `SpriteWidth/Height=250/141`、`TextureWidth/Height=4096/2048`、
`SourceTexture=T_BackgroundPreviews` 全部**硬编码**好了（实测），所以**只有 `SpriteX/SpriteY` 是"每项不同"的量**。

---

## 3. 风险：要不要重建 `.uexp` / `.ubulk`？

**不用。** 逐条回答：

1. **没有 `.ubulk`** —— 13 级 mip 全部内联，`retoc to-legacy` 只产出 `.uasset` + `.uexp`。
2. **不需要改结构** —— 我们不动尺寸、不动格式、不动 mip 数、不动 `FirstMipToSerialize`，
   所以：`.uexp` 长度不变、`uasset` 里的 `SerialSize` 不变、13 条 BulkDataMap 记录与"表前计数"不变。
   **唯一变化的字节 = 我们那 63×36 个 BC1 块**。这是比"改长度 + 补三处耦合字段"（画质路线 B 踩过的两个假绿坑）**低一档的风险**。
3. **需要重做的只有容器**（我们每打一次补丁本来就要做）：`retoc to-zen`。已实测无损（见 §4.1）。
4. **不会破坏原生下拉预览**：见 §4.3。

---

## 4. 实测的三个关键实验

### 4.1 容器重建无损：原样过一遍管线，13 级 sha256 全等

把**未改动**的图集 legacy 树 `retoc to-zen` 成一个 `_P` 容器，再连同原生容器一起喂回 CUE4Parse：

```
原生        : 6741372026AD7AF1 18CD8D9AF3139FD5 89123DC67C0DB646 D062AEE988503C88
               A867795F7F1E533F 50103539426AC749 2DE99BCDF87C81FB ... 33173B705BC60E35
重建后读回  : 6741372026AD7AF1 18CD8D9AF3139FD5 89123DC67C0DB646 D062AEE988503C88
               A867795F7F1E533F 50103539426AC749 2DE99BCDF87C81FB ... 33173B705BC60E35
```

**13/13 完全一致**（`work/cp35_atlas/verify_dump.txt`）。
⇒ 「重建容器」这一步对图集是**无损**的，不会因为重新 cook 而改变任何一个像素。

容器体积：**`_P.ucas` = 5,593,631 B**（图集单独一个补丁的代价 ≈ 5.6 MB）。

### 4.2 覆盖确实生效：改 1 字节 ⇒ 读回只有 mip0 变

在同一棵 legacy 树上，把 mip0 负载的**最后一个字节**翻转（`0xAA → 0x55`，仍在纯黑空区），重新 `to-zen` + 读回：

```
mip0  : 6741372026AD7AF1 -> F07CBD273F3FB67A   ← 变了（我们的覆盖赢）
mip1  : 18CD8D9AF3139FD5 -> 18CD8D9AF3139FD5   ← 不变
mip2  : 89123DC67C0DB646 -> 89123DC67C0DB646   ← 不变
```

⇒ **`_P` 容器对原生 `T_BackgroundPreviews` 的覆盖是真实生效的**，而且读回是忠实的。
（这条实验很重要：没有它，4.1 的"全等"无法区分「覆盖生效」和「根本没覆盖、读到的还是原生」。）

### 4.3 为什么"原生下拉预览图绝对不受影响"是**可证明**的

BC1 以 **4×4 像素为块**。我们选定**块对齐**的追加布局：

* 横向步长 **256**（=64 块），格子宽 250 ⇒ 每格恰好占 **63 块**，格与格之间留 **1 整块**（4 px）永不被碰；
* 纵向步长 **144**（=36 块），格子高 141 ⇒ 每格恰好占 **36 块**；
* 起点 **y = 1600**（=400 块，8 的倍数）；本图集原生内容到 y=1571 为止。

于是每一级 mip 里我们触碰的块**全部落在该级 mip 的纯黑空区**（mip3 最坏情况下仍从 mip0 坐标 1600 起，> 1571）。

⇒ 补丁后的 `.uexp` 与原生 `.uexp` 相比：**差异块集合 ⊆ 我们那 48 格的块集合**。
这是一条可以写成断言的硬判据（§6 的 A9），而"原生 165 个格子的像素"在任何 mip 上都**逐字节不变**。

---

## 5. 分阶段方案（只追加、不重排）

### 阶段 0 —— 只读 go/no-go：当前 build 到底谁写 `SpriteX/SpriteY`？

**状态：2026-09-26 用户已授权，探针已实现并开跑**（`launcher/calaplayer_launcher.py --probe-bg-writers`
＋ `tools/runtime-probe/ue_reflect.js` 的新 action `probe_brush_writers`）。该 action 里**一个 `invoke`
都没有**（不调 UFunction、不写属性、不写盘），只读对象指针与它们的类；观察器复用 R2 的"选择变化"
检测（轮询 `WBP_DetailsPanel.BackgroundChange` / `WBP_Editor.SelectedTimelineObject`），但触发的是
**只读探针**而不是推送（`refresh_action: 'probe_brush_writers'`）。

已知（本报告 §2.5）：两个材质声明了这 7 个参数、并直接引用图集。
**待回答**：选中一个步骤时，游戏有没有把该背景的坐标写进这两个材质的动态实例。

只读判据（探针每次采样都输出这三行）：

| 观察点 | 读什么 | 判读 |
|---|---|---|
| 右侧背景预览块 | `WBP_DetailsPanel.WBP_BackgroundPreview` → `Image_Preview` → `Brush.ResourceObject` 的**地址与类** | 出现 `MID`（MaterialInstanceDynamic）且地址随选中变化 ⇒ 游戏自己会建动态实例 ⇒ **本 build 静态就能修好**；恒定是同一个 `MIC` ⇒ 没人写它 ⇒ 等作者下一版 |
| 时间轴单元格 | 选中步骤那个 `WBP_SubslotContent.BackgroundMaterial` 的**地址与类** | 同上 |
| 参照物 | 同 key 的**下拉条目**自己那份材质（`WBP_CharacterListItem.ButtonImage`，游戏自己建的） | 前两者的地址若等于它 ⇒ 说明真的"传过去了" |

> 只读自证：流程前后对 `Content\Paks` 与 `Scenarios.sav` 做哈希比对（与之前每一轮同规矩）；
> 全程唯一一次 UFunction 调用是**点 CREATE 标签进编辑器**（与用户自己点一样，是导航不是改状态）。

### 阶段 1 —— 实现（等你确认后动手）

1. **取图集副本**：构建时从**装机目录的原生容器**里 `retoc to-legacy -f T_BackgroundPreviews`（和 `TEX_SHELL` 一样"就地发现"，不把 559 万字节塞进仓库）。
2. **追加格子**：`(x, y) = (256·c, 1600 + 144·r)`，`c∈[0,16)`，`r∈[0,3)` ⇒ **48 格**。
   每格：把源图缩到 250×141（cover，与现行 `-Fit` 语义一致）→ BC1 编码 → 写进**那 63×36 个块**。
3. **同步 mip 链**：对 k=1..12，用同一矩形在 mip_k 坐标下的覆盖块替换；因为带子在每级 mip 的纯黑区，原生像素仍不被触碰。
4. **我方 MI**：克隆原生 `MI_BackgroundPreview_000` 壳 → 改内部身份三处（沿用 `da-patch namerepl` 规格）→
   **`SourceTexture` 保持指向图集**（原生壳的 ImportMap 里本来就有这条 import，**不需要 `bgref` 追加 import**）→
   6 个标量写成 `(格子X, 格子Y, 250, 141, 4096, 2048)`。
   > 比现行 `mimk` **更简单**：现行要把 `SourceTexture` 重指到我们自己的贴图，这条路不用。
5. **DA 行 `@30`** 仍指向该 MI（现有 `bgref` 逻辑不变）。
6. **同一容器**：图集覆盖必须和 DA/MI 放进**同一个 `_P`**（同名容器互斥）。
   加 `-NoAtlas` 诊断开关，回到现行"整图 MI"形态（与 `-NoThumb` 同一风格）。
7. **容量上限（已拍板 2026-09-26）**：块对齐的硬上限 **48 格/次** ⇒ **背景数量上限直接取 48**；
   只有显式加 `-Force` 才允许突破到 50，并且要**警告缩略图可能不显示**。
   （"第 49/50 张回退成现行整图形态"这个方案被否掉——不值得为它增加逻辑复杂度。）

### 阶段 2 —— 真机小步验证（沿用现有 L5 流程）

先只装 1 张新背景 → 进 Create 看三处：**下拉缩略图**（应显示我们的图，且与原生条目同构）、
**右侧 Background 预览块**、**时间轴单元格**；再逐步加满。装前备份、装后读回、失败自动还原、一键回滚。

---

## 6. 判据（建议新增 A9 / A10）

| 门 | 判据 | 为什么必须有 |
|---|---|---|
| **A9** | 从**构建出的容器**里读回图集：`4096×2048 / PF_DXT1 / 13 级`，且**逐级 sha256 == 原生**；再把两个 `.uexp` 按 BC1 块比对，断言 **差异块集合 ⊆ 我们那 48 格的块集合** | "下拉预览不受影响"从"我以为"变成"机器证明" |
| **A9b** | 我们格子解码回来 → 与源图 250×141 缩放版比 `QUALITY: PSNR`（复用现有画质门，< 25 dB 失败） | 缩略图也得有画质判据 |
| **A10** | `miprobe` 我方 MI：`SourceTexture == T_BackgroundPreviews` 且 6 标量 == `(x, y, 250, 141, 4096, 2048)` | 防"坐标写错 ⇒ 显示别人的格子" |
| 真机 | 原生条目区域**分区像素差 = 0**（下拉截图 before/after，复用 `work/cp35_region_diff.py`） | 肉眼+数字双证 |

---

## 7. 回滚方案（四层，全部现成）

1. **`uninstall.ps1`**：删掉我们的 `_P` 三件套并还原安装前的备份 ⇒ 回到**安装前状态**（现有机制，本方案不改它）。
2. **`-NoAtlas`**：重新打一个**不含图集覆盖**的补丁 ⇒ 回到现行形态（可选，不需要回滚安装）。
3. **原生图集从未被写过**：它一直躺在 `CalaPlayer-Windows.{utoc,ucas}` 里，我们只是在 `_P` 里放了一份**副本 + 追加格**。
4. **L5 失败自动还原**：沿用现有"碰任何文件之前硬拒绝 + 失败自动还原"的部署流程。

---

## 8. 诚实边界（这份报告**没有**证明的东西）

1. **"追加格子 + 指向它"就能让那两个控件显示我们的图** —— 这一条**还没被证明**，卡在 §5 阶段 0 的那一问。
   本报告证明的是：**图集侧的路是通的、无破坏的、可回滚的**（必要条件的全部）。
2. 我**没有**改动任何产品代码、没有改任何产品判据、没有写游戏目录。
3. 我方格子的**外观会变**：下拉缩略图从"整图缩放"变成"250×141 格子"（与原生条目完全同构，
   比例 250/141 = 1.773 vs 16:9 的 1.778，差 0.3%）。**165 个原生条目的外观逐字节不变**。
   主菜单章节封面走的是 `Background` 软路径 ⇒ 不受影响（已有此前取证）。
4. `MI_<名字>` 的 `SourceTexture` 会从"我们自己的整图"改成"图集"。
   **如果**将来某个界面把行里的 `Preview` MI 当"整图"用，那里会显示成小格子 —— 目前已知的取图通道里没有这种用法。

---

## 9. 拍板记录

| # | 事项 | 结论（2026-09-26 用户拍板） |
|---|---|---|
| 1 | 阶段 0 只读探针 | **已授权**，探针已实现并开跑（`--probe-bg-writers`）；结果出来再定"图集拼接这条路走不走" |
| 2 | 容量上限 | **取 48 作为硬上限**；只有显式 `-Force` 才允许突破到 50，并**警告缩略图可能不显示**。"第 49/50 张回退现行形态"被否掉（不值得增加逻辑复杂度） |
| 3 | `-NoAtlas` 诊断开关 | 待实现时一并做（沿用 `-NoThumb` 的风格） |
| 4 | 是否做成独立可选容器 | 待实现时再定（技术受限：同名 `_P` 互斥；倾向先放进同一个 `_P`，用 `-NoAtlas` 控制） |
| 5 | `-Combined` 的 DA bug | **先记账、不修**（用户认可"DA 基线改用原生 DA + 统一走字节级 `append_bg_rows`"的修法，但等图集路线定了再一起处理） |

---

## 10. 只读探针结果（2026-09-26，7 次真实选择，共 57 个样本）

**一句话：右侧 Background 预览块 —— 游戏自己在写 `SpriteX/SpriteY`，而且写的就是图集格子坐标；时间轴单元格的 `BackgroundMaterial` 字段没人写（它渲染用的 `UBorder.Background` brush 待补测）。**

证据（`logs/launcher_run_20260926_154500/events_probe_bg_*.json`）：

| 选中行的 key | 预览块 brush 地址 | 它的两个标量（步长 36 B 解出） |
|---|---|---|
| （空编辑器基线） | MID `0x1e5c72d2a70` | 标量计数 **0** |
| `9d3f0` | **同一个 MID** | **252.0 / 0.0** |
| `1d373b` | **同一个 MID** | **0.0 / 0.0** |
| `b17ca` | **同一个 MID** | **1260.0 / 1287.0** |

* 预览块的 MID **7 次选择地址全程不变**（与空编辑器时同一个对象），**但它的标量跟着选中变**；同一 key 重复选中时数值完全复现 ⇒ 完全由选中驱动。
* `252 = 1×252`、`1260 = 5×252`、`1287 = 9×143` ⇒ **就是原生图集的格子坐标**（列×252、行×143）。
* 参照物：同 key 的**下拉条目**那份材质每次都是**不同的 MID 地址** ⇒ 说明"跟着选中变"这个读数本身是灵验的（不是读错对象）。
* 只读自证：探针前后真机 `_P`（`59EE5D384B588407` / `97719BFFCE07F198`）与 `Scenarios.sav`（`F8E4AA78258CC51E`）哈希未变。

### 10.1 这条结果**改变**了放置方案

⚠️ **2026-09-26 第二轮探针（钉时间轴）后的修订——本节的机制推断被更强的证据修正**：
游戏读的其实是**该行 `@30` 那个 MI 里的 `SpriteX/SpriteY`**，不是"按序号现算"：

| 选中的行 | 预览块/单元格拿到 | 我们 `MI_<名字>` 里写的 | 按序号算会得到 |
|---|---|---|---|
| `a00f4`（原生） | 1008 / 1430 | — | 4×252 / 10×143 ✅ 一致 |
| `1d3653`（我们的） | **0 / 0** | **0 / 0** | (1260,1430) ❌ |
| `1d36d1`（我们的） | **0 / 0** | **0 / 0** | (1512,1430) ❌ |
| `1d377a`（我们的） | **0 / 0** | **0 / 0** | (1764,1430) ❌ |

下面的公式仍然成立，但它描述的是**原生 MI 静态值的生成方式**（原生 165 个 `MI_BackgroundPreview_NNN` 逐个吻合），**不是运行时算法**：

```
列 = i % 16      行 = ⌊i / 16⌋      SpriteX = 列 × 252      SpriteY = 行 × 143
```

**修订后的方案（同时满足两种解释）**：把我们的缩略图放在**游戏自己的格子**上（序号 165、166、… 依次，坐标按上面的公式），**并且**把这同一组坐标写进我们的 `MI_<名字>`。这样无论游戏是"读我们的 MI"还是"按序号现算"，都对得上。

⇒ 我们追加的行序号 ≥ 165：**第 165 行 = 列5/行10 = (1260, 1430)** —— 正好是 §2.3 测出的"纯黑空区"的**第一格**。这也解释了用户看到的现象：选中我们的背景时控件得到 **(0,0)**（因为我们 MI 里写的是 0/0）⇒ 显示图集第 0 格，**所以"图不换"**。

**容量**：空闲格 = 序号 165..223 = **59 格**（224 − 165，正好等于 §2.3 测出的空闲格数）。用户 2026-09-26 拍板**用满 59**（不再保守留 11 格）。
**字节级影响**：第 165 格 (1260, 1430) 的 x 是 4 的倍数（1260/4 = 315 ✓），y 不是（1430/4 = 357.5）⇒ 只有第 10 行那 11 格的**顶部边界块行**与上一行的 **2px 间隔**共用；重新编码只会动到**背景/间隔**像素，原生预览矩形仍然逐像素不变（A9 判据照旧可用，只是"允许变化的块集合"要按**游戏格子**重新算）。

**修订版完整设计**见 [`CP36_ATLAS_APPEND_DESIGN.md`](CP36_ATLAS_APPEND_DESIGN.md)（含 59 格的逐格坐标表、分阶段实现、A9/A9b/A10/A11 判据、四层回滚）。

### 10.2 时间轴那一半：**已经钉死（2026-09-26 第二轮探针）**

`WBP_SubslotContent.BackgroundMaterial`（@1048）在 7 次选择里**一直是同一个 MIC**（1 个标量 = 0）⇒ **没人写这个字段，它不是渲染路径**。
真正渲染走的是 **`Border_32`（`UBorder`）的 `Background` brush**（jmap 实测 `/Script/UMG.Border`：`Background @528`、`FSlateBrush.ResourceObject @56`），第二轮补测结果：

| 选中的行 | 单元格 Border 的 brush 材质 | 它的 3 个标量 |
|---|---|---|
| `a00f4`（原生） | MID，地址 **A** | **1008 / 1430 / 0** |
| `1d3653`（我们的） | MID，地址 **B**（≠A） | **0 / 0 / 0** |
| `1d36d1`（我们的） | MID，地址 **C**（≠A,B） | **0 / 0 / 0** |
| `1d377a`（我们的） | MID，地址 **D**（≠A,B,C） | **0 / 0 / 0** |

⇒ **游戏每次选择都给单元格新建一个 MID**（地址每次都变），把该行 `@30` MI 的 `SpriteX/SpriteY` 写进去，第三个标量恒 0（对应 `S_BackgroundChange.SwitchThroughBlack`）。
**两个控件都"有人写"** ⇒ 图集路线的 go/no-go 是 **可以走**，且**不需要等作者下一版**。
