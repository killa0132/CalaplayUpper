# 只读评估：时间轴条目 / 预览块 拿的是哪张图（CP-35 前置侦察）

> **⚠️ 2026-09-26 结论更新（先读这段）**
>
> 1. **§10 的"运行时修法"（R2 / `--refresh-backgrounds`）已被用户废弃**：真机实测**严重卡顿、
>    重开失效**，且游戏作者确认 `SetBrushFromMaterial` 不是预期路径（"看起来能用只是因为它把原定材质
>    整个替换掉了，但两种情况看起来都不对"）。开关已标 `[DEPRECATED]`，见
>    `docs/PROJECT_HANDOFF.md` §65.15（上游仓）。**本文件 §10 只作历史取证，不要再按它实现。**
> 2. **§11 之后的新路线 = 静态追加预览图集**：只读评估全文见
>    [`CP35_ATLAS_APPEND_ASSESSMENT.md`](CP35_ATLAS_APPEND_ASSESSMENT.md)（结论：图集末尾有连续空区、
>    改动是等长像素替换、容器重建实测无损、块对齐可保证原生 165 格逐字节不变）。
> 3. 本文件里 **§1~§9 的取证仍然有效**（DA 行结构、`@30` 是缩略图真源、三处取图通道、C1 定案
>    "游戏自己不做最后一跳"）。

> 只读侦察，**没有改动游戏目录任何文件、也没有改本工具任何行为**。
> 侦察对象：从原生容器解出的 `WBP_Editor` / `WBP_BackgroundPreview` / `WBP_TimelineSubslot` /
> `WBP_TimelineSlot` / `WBP_DetailsPanel` / `WBP_SubslotContent` / `WBP_TimelineTrackHeaderItem` /
> `WBP_DropdownButtonContent` / `S_BackgroundAssetData` / `S_BackgroundChange` / `S_Scenario` /
> `PDA_Backgrounds`，以及 CP-19 那份**运行时**控件树 dump（`logs/run_cp19/create_editor_layout.json`，
> 631 个控件 / 编辑器子树 407 个）。
> 方法与证据：`retoc to-legacy` 解包 → `da-patch probe` 读**名字表 + ImportMap**（这是离线能拿到
> "它到底调了哪些函数 / 引用了哪个资产"的唯一硬证据；Blueprint 字节码的连线图不在 uexp 里）。

---

## 1. 背景：用户实测现状

| 位置 | 期望 | v1.1.0 真机实测（用户） |
|---|---|---|
| 下拉条目的小预览（缩略图） | 我们的图 | ✅ **已变成自定义图** |
| 左侧 **Preview block**（预览块） | 我们的图 | ❌ 仍是原版 / 空白 / 默认图 |
| 底部 **Timeline entries**（时间轴条目） | 我们的图 | ❌ 仍是原版 / 空白 / 默认图 |

作者原话（Discord）：
> "You can go further and also implement background previews for **dropdown entries, timeline entries
> and preview block** if you create a material instance based on `MMI_BackgroundSelector` with these
> parameters. `SourceTexture` is the texture you're trying to use as background."

---

## 2. 已确证的事实（离线证据）

### 2.1 DA 的一行只有**一个**预览材质，就是 `@30`

`S_BackgroundAssetData`（`/Game/CalaPlayer/Blueprints/Structure/S_BackgroundAssetData`）的字段只有两个：

| 字段（真实名字带 UMG GUID 后缀） | 类型 | 对应 34 B 行里的位置 |
|---|---|---|
| `Background_4_3439A4B8422F8124A7F1C587FA1EEA1D` | **SoftObjectProperty → `Texture2D`** | `+10` 包名 / `+18` 资源名 / `+26` 空子串 |
| `Preview_5_9CE26F0D45C2B697FDDA87ABCFBE5499` | **ObjectProperty → `MaterialInstanceConstant`** | **`@30`** |

⇒ 一行里没有第二个预览材质；「下拉缩略图 / 预览块 / 时间轴条目」要想显示同一张图，最终只能来自
这两个值（我们两个都写了：软路径 = 我们的贴图，`@30` = 我们的 `MI_<名字>`）。

### 2.2 原生数据有一条我们没满足的**命名不变式**

只读统计原生 `DA_Backgrounds`（165 行，`u32@8` 行数、34 B 定长）：

```
row 0   key=20240116-161610          pkg=/Game/CalaPlayer/Backgrounds/20240116-161610  asset=20240116-161610  @30=-2
row 1   key=Evni_BP2_Background       pkg=.../Evni_BP2_Background                     asset=Evni_BP2_Background
row 2   key=T_Evni_Background_01_A    pkg=.../T_Evni_Background_01_A                  asset=T_Evni_Background_01_A
key == asset name : 165 / 165
```

**165/165 都满足 `map key == 贴图对象名`，且包路径恒为 `/Game/CalaPlayer/Backgrounds/<名字>`。**
而我们的新行**故意不满足**：`key` 是给玩家看的显示名（可中文、可被 `names.json` 覆盖），
`obj` 是 ASCII 清洗名。例：`夜景 测试.png` → `key='夜景 测试'`，`obj='User_BG_02'`。

### 2.3 三个通道各自的取图路径（按名字表 + ImportMap 反推）

| 控件 | 关键名字 / Import（证据） | 取图方式 |
|---|---|---|
| `WBP_BackgroundPreview`（预览块本体，布局里出现 2 次：编辑器主面板 + 详情面板） | `PreviewMaterial`(ObjectProperty)、`SetImage`、`SetDynamicMaterial`、`SetPlaceholder`、`SpriteX`、`SpriteY`、`WidgetSize`、`GetDynamicMaterial`、`K2_GetScalarParameterValue`；imports 有 `MMI_BackgroundPreview`（父材质）、`SPR_UI_RoomInsidePC_custom_FrameEmpty`（占位图）、`MaterialInstanceConstant` | 它自己**不找图**：渲染别人塞进来的 `PreviewMaterial`，然后 `GetDynamicMaterial()` 取 MID，读 `SpriteX/SpriteY` 标量算尺寸 |
| `WBP_DetailsPanel`（详情面板；布局里有 `WBP_BackgroundPreview` + `Image_Preview`） | **`BackgroundsData` / `BackgroundsData_Value`**、**`BackgroundNamesPreviews` / `BackgroundNamesPreviews_Value`**、`BackgroundsPath`（字面量 `"/Game/CalaPlayer/Backgrounds/"`）、`SetImage`、`SetBrushFromMaterial`、`Map_Find`、`Map_GetKeyValueByIndex`、`Map_Keys`；imports 有 `DA_Backgrounds` 包、`MaterialInstanceConstant`、`Texture2D`、`Concat_StrStr`、`Conv_NameToString` | **它是喂图的人**：遍历背景表建两张表（名字→材质 / 名字→资源），再按"当前步骤的背景名"取材质塞给预览块与时间轴。**既能拿到 MI，也存在"用名字拼路径"的代码路径** |
| `WBP_TimelineTrackHeaderItem`（时间轴左侧轨道头） | `BackgroundDynamicMaterial`、`BackgroundImage`、`SetBrushFromMaterial`、`GetDynamicMaterial`、`SetVectorParameterValue`、`SetBackgroundColor` | 直接用**材质**设 brush（没有 `SetBrushFromTexture`） |
| `WBP_TimelineSubslot`（时间轴条目本体） | `BackgroundMap`、`BackgroundData`、`BackgroundChange_...`、`Map_Find`、`CallFunc_Map_Find_Value`、`GetSubslotContent`；imports 有 `DA_Backgrounds` 包 + `PDA_Backgrounds_C DA_Backgrounds`、`BlueprintMapLibrary` | `Map_Find(DA_Backgrounds.BackgroundMap, <步骤里的背景名>)` → 取到值结构体 → 交给内容控件 |
| `WBP_SubslotContent`（条目内容） | `BackgroundMaterial`、`GetDynamicMaterial`、`K2_GetScalarParameterValue`、`SetScalarParameterValue`、`SetWidthOverride` | 与预览块同一套：拿 `BackgroundMaterial` 做 MID + 读标量 |
| `WBP_DropdownButtonContent`（下拉按钮内容） | 只有 `SetText` / `SetValues` / `TextBlock` / `isPlaceholder`（**没有任何 Image / 材质**） | 下拉按钮**只显示文字**；小预览是旁边那个 `WBP_BackgroundPreview` |

**两条硬结论**：
1. **没有任何控件调用 `SetBrushFromTexture`**（全仓 32 个 WBP 里 0 命中）——所有背景图都走
   **材质 / 动态材质实例（MID）**，这与作者的说法一致。
2. **没有任何控件引用 `MMI_BackgroundSelector`**（0 命中）；`WBP_BackgroundPreview` 引用的父材质是
   `MMI_BackgroundPreview`。⇒ 真正被渲染的永远是"某个 `MaterialInstanceConstant` 实例"，
   而背景表里的实例就是 **`@30`**（我们已经挂上去了）。

---

## 3. 两个候选根因（都能解释"下拉好了、预览块/时间轴没好"）

**H1（命名不一致导致按名查找/拼路径失败）**
引擎在这两个通道里是**按名字**取图（`Map_Find(<步骤里的背景名>)`，或 `BackgroundsPath + 名字` 拼
`/Game/CalaPlayer/Backgrounds/<名字>` 再加载）。原生 165/165 满足 `key == 对象名`，所以拼出来一定能命中；
我们的行 `key != 对象名`：
* 若走 `Map_Find(key)` → 能找到（我们写进去了）；
* 若走"名字拼路径"或步骤里存的是**资源名**而不是 key → 找不到 → 预览块保持上一次的材质（看起来是**原版**）
  或占位图（**空白/默认**）。

**H2（不是 bug：这两个位置显示的是"当前步骤的背景"）**
`WBP_TimelineSubslot` 读的是 `S_BackgroundChange.BackgroundChange`（步骤里选的背景名），
详情面板的预览块显示的是**当前步骤**的背景。若测试场景的步骤仍旧指着原生背景，
显示原版就是**正确行为**；只有"把某个步骤的背景选成我们的新条目"之后仍不对，才算 bug。

两个假设的判别方法都不贵：

| # | 判别动作 | 结果解读 |
|---|---|---|
| **D1（30 秒，用户做）** | 在 Create 编辑器里把**当前步骤**的背景下拉选成我们的新条目，看左侧预览块 + 底部时间轴那一条 | 变对了 ⇒ **H2**（无需改代码，只是显示语义）；仍不对 ⇒ **H1** 或更深 |
| **D2（只读，我可跑）** | 游戏在跑时用 CP-30 的语义适配器读：`WBP_DetailsPanel.BackgroundsData / BackgroundNamesPreviews` 的**实际键**、`WBP_BackgroundPreview.PreviewMaterial`、`WBP_TimelineTrackHeaderItem.BackgroundDynamicMaterial` | 直接看到"引擎手里到底是哪个 MI"；键里有没有我们的行、材质是不是我们的 `MI_*` |
| **D3（5 分钟，用户做）** | 用**纯 ASCII 文件名**（如 `mybg.png`，无空格/中文 ⇒ `key == 对象名`）重新打包安装 | 预览块/时间轴变对 ⇒ **坐实 H1** |

---

## 4. 实现方案（按判别结果分叉）

### 方案 A —— 若 H1 成立：让 `key == 贴图对象名`（**不需要动 ImportMap**）

* 改动：`core/config.py` 的命名规则把 **DA 的 map key 改成与对象名同源的 ASCII 名**
  （`names.json` / 文件名的中文只用于我们 GUI 的展示与日志，不再写进 DA key）。
* 代价：游戏内下拉会显示清洗后的名字（如 `User_BG_01`）而不是中文原名。
  若想保留中文可读性，只能二选一或走方案 C。
* 风险：**低**。只影响我们新行的三个 FName 槽（第 2.1 节里 `+0/+10/+18`），仍然是"只追加"；
  既有 165 行、ImportMap、`@30` 全都不动。
* 新判据：A7 增加 `key == 对象名`（并在回归里放一个中文名 fixture 断言它被清洗成同源名）。

### 方案 B —— 若 H2 成立：**不改代码**

* 结论写成文档：预览块/时间轴显示的是"该步骤的背景"，把步骤背景选成新条目即可；
  若用户希望"下拉一选就三处同时变"，那属于游戏本体行为，静态补丁无法改。

### 方案 C —— 若两条都不成立（引擎手里拿的是别的东西）

* 走**运行时**：Launcher 侧语义适配器在编辑器打开时，按名字找到这三类控件、直接把 brush/MID 设成
  我们的 `MI_<名字>`（CP-30 已经有"按名字从类链找 UFunction + 调 `SetImage`/`SetBrushFromMaterial`"
  的能力）。代价：**必须每次启动注入**，与静态 `_P` 补丁是两条线。
* 静态备选（**要动 ImportMap**，中等风险）：给 `DA_Backgrounds` 末尾的**两个空列表**
  （`Backgrounds` / `Previews`，运行时 dump 里 count=0）追加元素 + 在 ImportMap 末尾追加对象 import。
  ⚠️ 这需要新的数组布局手术与新的门（数组长度、元素 FPackageIndex、末尾追加证明），
  **只有在 D2 证明引擎确实读这两个列表时才值得做**。

---

## 5. 风险评估汇总

| 方案 | 动 ImportMap？ | 动游戏原生物？ | 真机崩溃风险 | 工作量 | 判据 |
|---|---|---|---|---|---|
| A（key 同源命名） | ❌ 不需要 | ❌ 不 | 低（只改我们新行的三个 FName） | 0.5 天 | A7 加 `key==obj`；回归 26 场景 |
| B（不改代码） | ❌ | ❌ | 无 | 0 | 用户按 D1 复验 |
| C-静态（补两个空列表） | ✅ 需要（追加 import + 数组元素） | ❌ | **中**（数组布局/长度是新的手术面） | 1~2 天 | 新门 A9 + chunk 台账 |
| C-运行时（注入） | ❌ | ❌ | 低（不写游戏数据） | 2~3 天（复用 CP-30 适配器） | 离屏判据 + 真机肉眼 |

---

## 6. 第一轮判别（D1 / D3）的结果：两个假设都被否

用户 2026-09-25 实测：**D1（把当前步骤背景手动选成我们的新条目）与 D3（纯 ASCII 文件名重打）都没有
任何变化**。
* ⇒ **H1（名字/路径不匹配）不成立**（D3 已经让 `key == 对象名`，若引擎按名字找/拼路径就该好了）。
* ⇒ **H2（只是"没选到"）不成立**（D1 就是显式选中）。
* ⇒ 用户的判断成立：**这几处 UI 根本没有去读我们新增的材质**。
* 一并可以确认：`WBP_DropdownButtonContent` 里**没有任何 Image/材质**（它只管文字），
  用户看到的"下拉缩略图"是 `WBP_BackgroundPreview`（编辑器主面板那一份），它已经好了 ⇒
  预览块这类控件**本身能显示我们的图**，问题只在"谁来喂它、什么时候喂"。

⇒ 于是转入第二轮**字段级**侦察（第 7 节）。

## 7. 第二轮侦察（字段级，2026-09-25 晚）—— D1/D3 都失败之后的转向

**用户实测反馈**：D1（手动把当前步骤背景选成我们的新条目）与 D3（纯 ASCII 文件名重打）**都无变化**
⇒ **H1（名字不匹配）与 H2（步骤没选中）双双被否**。于是本轮不再猜"名字"，而是直接问：
**这几个控件在 Blueprint 层面到底访问了 `S_BackgroundAssetData` 的哪一个字段？**
（Blueprint 访问结构体字段会把**字段全名**写进该资产的名字表 —— 这是离线可得的硬证据。）

### 7.1 字段级真值表（`da-patch probe` 读名字表）

| 控件 | 引用 `Preview_5_9CE26…`（= `@30` 的 MI 字段） | 引用 `Background_4_3439…`（软路径贴图字段） | 其它确证 |
|---|---|---|---|
| `WBP_TimelineSubslot` | ✅ **是** | ❌ | `BackgroundMap`（按名字查表） |
| `WBP_Editor` | ✅ **是** | ❌ | `BackgroundNamesPreviews`、`SetBackgroundPreviews`、`Map_GetKeyValueByIndex`、`SetImage` |
| `WBP_MainMenu` / `WBP_MenuScenarioEntry` | ❌ | ✅ **是**（软路径） | `BackgroundMap`、`BackgroundsData` ← **主菜单这条链路才读软路径** |
| `WBP_DetailsPanel` | ❌ | ❌ | `BackgroundsData`、`BackgroundNamesPreviews`、`BackgroundsPath="/Game/CalaPlayer/Backgrounds/"`、`Map_GetKeyValueByIndex`、`SetImage`、`SetBrushFromMaterial` |
| `WBP_TimelineTrackHeaderItem` | ❌ | ❌ | **完全不碰 DA**：只有 `SetBrushFromMaterial`、`BackgroundDynamicMaterial`、`BackgroundImage`、`SetTrack`/`SetCharacterTrack`/`SetBackgroundColor` |
| `WBP_SubslotContent` | ❌ | ❌ | `BackgroundMaterial`、`GetDynamicMaterial`、`SpriteX`/`SpriteY`（与预览块同一套尺寸逻辑） |
| `WBP_BackgroundPreview` | ❌ | ❌ | 只渲染被塞进来的 `PreviewMaterial`；自身 `SetImage`/`SetDynamicMaterial`/`SpriteX`/`SpriteY` |

**⇒ 回答"它有没有可能读软路径而不是 MI"：时间轴/预览块侧不是。** 真正读软路径的是**主菜单**
（`WBP_MainMenu`/`WBP_MenuScenarioEntry`），也就是我们一开始就成功的那条（章节卡片背景）。

### 7.2 重大发现：`BackgroundMap` 是**生成出来的**，而且生成它的两个数组是**空的**

`PDA_Backgrounds`（= `DA_Backgrounds` 的 Blueprint 类）名字表里有：

```
GenerateMap / Map_Clear / Array_Clear / Array_Get / Array_Length / Add_IntInt / Less_IntInt
Conv_SoftObjectReferenceToObject / Conv_StringToName / GetDisplayName
K2Node_MakeStruct_S_BackgroundAssetData / K2Node_DynamicCast_AsTexture_2D
Backgrounds / Previews / BackgroundMap / BackgroundMap_Value / Preview_5_9… / Background_4_3439…
```

即：**`GenerateMap()`** 会先 `Map_Clear` + `Array_Clear`，再遍历两个**平行数组**
（`Backgrounds` = 软引用贴图、`Previews` = 材质实例），对每个元素 `GetDisplayName` 取名字（**这就是
"原生 165/165 key == 贴图对象名"的由来**）、`DynamicCast<Texture2D>`、`MakeStruct_S_BackgroundAssetData`
→ `Map_Add` 重建 `BackgroundMap`。

再看**运行时实测**（CP-19 dump）：`DA_Backgrounds` 的 `Backgrounds` **count=0**、`Previews` **count=0**，
而 `BackgroundMap` 有 165 行。且**全量资产里只有 `PDA_Backgrounds` 自己引用 `GenerateMap`**（32 个 WBP +
PDA 二进制 grep）⇒ **它是编辑器侧的工具函数，运行时不会被调用**。

**结论**：所谓"游戏启动时一次性缓存 165 个背景"的那份 cache，**确实是存在的**（就是那两个数组），
**但它在出货资产里是空的**；运行期大家读的是**已经生成好的 `BackgroundMap`**（我们的补丁就是往它追加，
所以下拉条目 ✔）。⇒ **时间轴/预览块不可能"因为数组里没有我们的条目"而失败**（数组里谁都没有）；
它们要么只认 map（那我们该生效），要么走**另一份在运行时构造的映射**（`WBP_Editor` /
`WBP_DetailsPanel` 各自的 `BackgroundNamesPreviews` / `BackgroundsData`，用 `Map_GetKeyValueByIndex`
遍历 map 建起来）——**这份映射的构造时机和数据源，名字表看不出来，必须上运行时只读探针。**

### 7.3 剩下的两个候选（离线已到极限）

* **C1「构造一次、再也不刷新」**：`WBP_Editor`/`WBP_DetailsPanel` 在某个早期时刻（构造 / 第一次打开
  Create）用 `SetBackgroundPreviews` 把"名字→预览材质"建好；之后选择背景只更新下拉自己的缩略图，
  不再回头刷新预览块与时间轴。（能解释"下拉好了、另外两处不动"，也能解释 D1/D3 无变化。）
* **C2「我们追加的那一行被漏掉」**：构造映射时用了某种按**索引/数量**或**按原生 MI 列表**的写法
  （例如只遍历 map 的前 165 项，或只认 `MI_BackgroundPreview_0xx` 命名），我们 append 的第 166 行被跳过。

两个候选的修法完全不同，所以**下一步必须是运行时只读探针**（第 8 节），不能靠猜。

---

## 8. 只读运行时探针方案（Phase 1，不改任何东西）

**工具链已就绪**（都在上游工程 `D:\dsharnessProject\CalabiyauGalMaker`）：
`tools\jmap\jmap_dumper.exe`（9.5 MB，能对**活进程**做反射 dump，**含 CDO 与属性值** —— CP-19 的
控件树/文本/`Previews` 样本就是它出的）+ `tools\jmap\q_*.py` 查询脚本 + `launcher\calaplayer_launcher.py`
（现成的"启动 → 进 Create → dump → 建语义目录"流程）+ `tools\runtime-probe\ue_semantic.js`（按名字解析
UFunction、按引擎属性表造调用帧）。

**步骤**（约 5~10 分钟，全程只读）：
1. 启动游戏 → 主菜单 → **Create 编辑器**（`launcher` 的 enter-create 流程，CP-19 已验证）。
2. `tools\jmap\jmap_dumper.exe --pid <游戏 pid> --engine-version 5.7 --all logs\run_cp35\editor.jmap`
3. 从 dump 里读这 6 组对象/属性（全部是"读"，不写）：
   | 对象 | 读什么 | 判据 |
   |---|---|---|
   | `DA_Backgrounds` | `BackgroundMap` 条数 + 我们的 key 在不在；`Backgrounds`/`Previews` 条数 | 我们的行在不在 map |
   | `WBP_Editor_C` | `BackgroundNamesPreviews` 条数/键；`Previews` | 映射里有没有我们的键（**C2 判据**） |
   | `WBP_DetailsPanel_C` | `BackgroundsData` / `BackgroundNamesPreviews` 条数/键 | 同上 |
   | `WBP_BackgroundPreview_C` ×2 | **`PreviewMaterial`** 指向谁（我们的 `MI_*` / 原生 / None） | 预览块到底渲染什么 |
   | `WBP_TimelineTrackHeaderItem_C` | `BackgroundDynamicMaterial`、`BackgroundImage` 的 brush | 轨道头材质来源 |
   | `WBP_TimelineSubslot_C` / `WBP_SubslotContent_C` | `BackgroundMaterial` | 时间轴条目材质来源 |
4. 三选一落锤：**(a)** 映射里没有我们的键 → C2；**(b)** 有键但材质是原生/None → 绑定/映射构造问题；
   **(c)** 材质是我们的但没上 brush → 纯刷新问题。

**需要用户点头**：这一步要**拉起游戏**（会占用前台约 2 分钟，启动期偶发崩溃已有机上重试逻辑）。
用户也可以自己做 20 秒的对照实验先缩小范围：**在编辑器里选一个「原生」背景，看左侧预览块会不会变**
——若原生也不变，就说明这条 UI **本来就不响应选择**（C1 类），"我们的行没被读"这个说法要修正。

---

## 9. 修复方案（按探针结果分支）

| 结果 | 最干净的修法 | 动 ImportMap？ | 风险 |
|---|---|---|---|
| **(a)** 映射里没有我们的行 | **静态 S1**：向 `DA_Backgrounds` 的两个平行数组 `Backgrounds`（我们的贴图软引用）与 `Previews`（我们的 MI）**成对追加**，让引擎自己的"数组 → map/预览"链路认得我们（`GenerateMap` 是引擎自己写的，格式天然合法）。数组是对象引用 ⇒ 需要 **ImportMap 追加 + 数组元素手术 + 新门（长度/成对性/元素索引）** | ✅ **需要**（用户已明令先不动，故只列为方案） | 中（新手术面） |
| **(a) 的运行时替身** | 进 Create 后调用一次 `PDA_Backgrounds::GenerateMap()`（引擎自己重建 map）—— **前提仍是 `Backgrounds`/`Previews` 里有我们的条目**，所以它不能替代 S1，只是 S1 的收尾 | ❌ | 低 |
| **(b)/(c)** 材质没被绑上/没刷新 | **运行时 R2**：进 Create 后按名字找到 `WBP_BackgroundPreview_C`(×2) / `WBP_TimelineTrackHeaderItem_C` / `WBP_SubslotContent_C`，对它们调 `SetImage(我们的MI)` / `SetBrushFromMaterial(我们的MI 或 MID)`；MID 用 `KismetMaterialLibrary::CreateDynamicMaterialInstance`。原语齐备：`set_image_brush.js` 已验证"从 PNG 造 Texture2D + `UImage::SetBrushFromTexture`"，`ue_semantic.js` 已能按名字解析 UFunction 并按**引擎属性表**造调用帧 | ❌ | 低（不写游戏数据） |
| **C1 确认（原生也不刷新）** | 静态层**无法修**（要改的是游戏逻辑）；只能 R2 运行时接管，或接受现状 | — | — |

**如果 R2 落地**，形态建议：把探针脚本 + 注入动作做成 Launcher 的一个 action（复用 CP-30 的
`ue_semantic.js`），**只在静态补丁存在新背景时**对这几类控件做一次刷新；静态 `_P` 补丁本身不写游戏数据。

---

## 10. 第三轮：只读活进程探针的实测结果（2026-09-25 晚，**已定案**）

> 用户授权后跑了活进程探针（`tools\jmap\jmap_dumper.exe --pid <pid> --engine-version 5.7 --stats --all`），
> 目标游戏 = 真机 `D:\CalabiyanGalgameMaker`，**装着用户 D3 那版 `_P`（`bg_dark`）**。
> 过程证据：`D:\dsharnessProject\CalabiyauGalMaker\logs\run_cp35\live\`（三份 ~110 MB 的 dump + 截图 + 事件流）。
> **只读成立**：探针前后游戏 `_P` 三件套与 `Scenarios.sav` 的 sha256 **完全一致**（`before_hashes.txt` / `after_hashes.txt`）。

### 10.1 读到的真值（全部是"引擎手里实际拿着的对象"）

| 对象 | 属性 | 实测值 |
|---|---|---|
| `DA_Backgrounds`（live 实例） | `BackgroundMap` | **166 行**，最后一行 `bg_dark → /Game/.../MI_bg_dark` ✔ |
| 同上 | `Backgrounds` / `Previews` | **0 / 0**（与出货资产一致，确实没人填） |
| `WBP_Editor_C`（live） | `BackgroundNamesPreviews` | **166 条**，含 `bg_dark → MI_bg_dark` ✔ |
| `WBP_DetailsPanel`（live） | `BackgroundNamesPreviews` | **166 条**，含我们的行 ✔ |
| 同上 | **`BackgroundsData`** | **0 条**（空） |
| 同上 | `BackgroundChange` | **`bg_dark`**（当前就是我们的行） |
| `BP_TimelineSlotObject_C_2147482266`（`WBP_Editor.SelectedTimelineObject`，= 当前步骤） | `TimelineStep.BackgroundChanges.BackgroundChange` | **`bg_dark`** |
| `WBP_BackgroundPreview_C` ×2（预览块） | `PreviewMaterial` | `MID_MMI_BackgroundPreview_*`，**Parent = `MMI_BackgroundPreview`**，`ScalarParameterValues`/`TextureParameterValues` **全空** ⇒ 渲染的是 `MM_BackgroundPreviewBase` 的默认图（用户说的"原版"） |
| `WBP_TimelineTrackHeaderItem_C` ×4（轨道头） | `BackgroundDynamicMaterial` | **全部 `null`** |
| `WBP_SubslotContent_C`（live） | `BackgroundMaterial` | `MMI_SubslotContentBackground`（**设计期默认**） |
| `MI_bg_dark` | `Parent` / `SourceTexture` / 标量 | `MMI_BackgroundSelector` / **`/Game/CalaPlayer/Backgrounds/bg_dark`** / 6 个标量齐全 ⇒ **我们的 MI 完全正常** |
| 每个背景行的下拉条目（`WBP_CharacterListItem_C_*`，**恰好 166 个**） | `Button_22.Brush.ResourceObject` | 该行 `Preview` MI 建出来的 **MID**：原生 `MID_MI_BackgroundPreview_051_64` ↔ 我们 `MID_MI_bg_dark_178`，**结构完全同构** |

### 10.2 三选一定案

* **C2（我们 append 的第 166 行被跳过）——彻底否证**：`BackgroundMap`（166）、
  `WBP_Editor.BackgroundNamesPreviews`（166）、`WBP_DetailsPanel.BackgroundNamesPreviews`（166）**三处都含我们的行**；
  并且 166 个下拉条目里我们那条**和原生逐项同构**（MID 数量、挂载位置、命名规律全部一致）。
  用户看到的"下拉缩略图正常"正是这条链路。
* **"绑定/命名问题"——否证**：当前步骤背景名**就是 `bg_dark`**（两处真值），说明游戏自己的代码**已经能按名字
  取到我们的行**；我们的 MI 也能正常加载、能被 `CreateDynamicMaterialInstance` 消费。
* **C1（接收端不会被执行最后一跳）——成立**：
  `WBP_BackgroundPreview.PreviewMaterial` 停在**设计期默认材质**（`MMI_BackgroundPreview`→`MM_BackgroundPreviewBase`），
  4 个轨道头 `BackgroundDynamicMaterial = null`，`WBP_SubslotContent` 停在设计期默认；
  而且 `WBP_DetailsPanel.BackgroundsData` **是空的** ⇒ 那一跳需要的输入本身没人填。
  ⇒ **D1（选我们这条）与 D3（纯 ASCII 重打）都"无变化"，是因为这条 UI 本来就不响应选择**，与我们的新增行无关。

### 10.3 现场验证（把"修法"从推测变成真机证据）

在同一个活进程里做了 A/B/A（**只调 UFunction、不写盘、不动资产**，游戏重启即复原）：

| 动作 | 结果 |
|---|---|
| 调 `WBP_BackgroundPreview_C:SetPlaceholder()`（BP） | **0 视觉变化** ⇒ 游戏自己的 BP 入口**从外部调用是空操作** |
| 调 `WBP_BackgroundPreview_C:SetImage(<MI>)`（BP） | **0 视觉变化**（只让 MID 的标量数组由空变有 ⇒ 内部走到了 `SetDynamicMaterial`，但 brush 没换） |
| 调**原生** `UImage::SetBrushFromMaterial(<MI_bg_dark>)`（`/Script/UMG.Image:SetBrushFromMaterial`，UFunction `0x7ff4c3bc6fb0`） | **86,790 像素变化**：左侧预览块 + 右侧 Background 预览块**同时显示出用户的 `bg_dark` 图**（见 `docs/cp35_live/01_before_editor_preview_default.png` vs `02_after_push_our_MI.png`） |
| 再把 brush 设回 `MMI_BackgroundPreview` | 86,787 像素变化 ⇒ 完全对称，可逆 |
| 调**游戏自己的** `WBP_DetailsPanel_C:SetBackgroundEditor(<当前步骤对象>)`（该步骤背景就是 `bg_dark`） | **18 像素变化（= 3D 背景动画噪声）** ⇒ **游戏自己的"步骤选中 → 填预览"这一跳确实没干活**，与我们的行无关 |

### 10.4 结论与修法（给用户）

1. **静态 `_P` 这一层已经没有可改的地方了**：数据、名字、MI、ImportMap 全部正确且被引擎认到。
   缺的是**游戏自己的 UI 最后一跳**（它连对原生背景也不执行）。
2. **能修的路只有 R2（运行时）**，而且**已验证可行**：
   进入 Create 后（以及每次切换背景后），对每个 live `WBP_BackgroundPreview_C` 的 `Image_Preview`
   调**原生** `UImage::SetBrushFromMaterial(<该背景的 Preview MI>)`；
   绝不要调 `WBP_BackgroundPreview_C:SetImage/SetPlaceholder`（实测空操作）。
   时间轴侧对应的是 `WBP_TimelineSubslot_C:SetBackgroundContent(S_BackgroundChange)`（12 B 结构：FName+bool）
   与 `WBP_SubslotContent_C:SetBackgroundContent(<MI>, ThroughBlack)`（8+1 B），仍是**待验证**的下一步。
3. 副作用记录：R2 直接压 MIC 时，块的 brush 没有经过游戏自己的 `SetDynamicMaterial` 尺寸逻辑，
   画面能出图但取景/缩放由 `MI_bg_dark` 的 `SpriteX/Y/Width/Height` 决定；若要"和原生一样正"，R2 里
   应在压 brush 之后继续把该控件的 `WidgetSize`/`Sprite*` 标量按控件尺寸写一遍（已在探针里验证
   `SetDynamicMaterial` 会把标量数组填起来，可作为收尾步骤）。
4. **下一步的用户动作**：他原先准备的"切回原生背景看预览块变不变"20 秒对照实验，按本节证据
   **预期结论是"原生也不变"**；无论哪一边，结论都指向 R2（不是我们的行）。

---

## 11. 后记：用户否掉 v2 之后的定案与 R2 v3（2026-09-25 深夜）

第 10 节的三条猜测，有两条**被用户自己的 run 推翻/修正**，这里如实记下（细节见上游
`docs/PROJECT_HANDOFF.md` §65.11–65.14）：

| 第 10 节的说法 | 后来定案 |
|---|---|
| "对每个 live `WBP_BackgroundPreview_C` 的 `Image_Preview` 调 SetBrushFromMaterial" | ❌ **错了**：编辑器里有**两个**同类的 `WBP_BackgroundPreview_C`，分属两个系统 —— 左列 **`Preview`＝章节封面**（宿主 `WBP_Editor`）、右面板 **`Background`＝每步背景**（宿主 `WBP_DetailsPanel`）。用户判词："**左右两侧预览块不是一个系统**…**绝对禁止触碰左侧预览块**"。R2 v3 只推右侧那一个，且靶点取自 panel 的字段 + `ClassPrivate` + `Outer.Outer==panel` 三重校验，**类枚举已删除**。 |
| "时间轴侧对应的是 `WBP_TimelineSubslot_C:SetBackgroundContent(...)`" | ❌ **从进程外是空操作**：用户那次 run 里它被调了 12 次、选中项变了 11 次，而 `WBP_SubslotContent.BackgroundMaterial` **12 次都是同一个地址**。真正的单元格是 `WBP_SubslotContent_C` 里的 **`Border_32`（`UBorder`）**，它的 `Brush.ResourceObject` 是 `MID_MMI_SubslotContentBackground`（靠 `SpriteX/SpriteY` 采样共享图集）——**补丁新增的背景在图集里没有格子**，所以图集路线永远出不了图 ⇒ v3 改成：先调游戏自己的 `WBP_SubslotContent_C:SetBackgroundContent(<MIC>, ThroughBlack)`，再用**原生 `/Script/UMG.Border:SetBrushFromMaterial`** 把该行材质压进 `Border_32`。 |
| "R2 直接压 MIC 时取景可能不正，要补写 `WidgetSize`/`Sprite*`" | 仍成立（未改），v3 保持原样：压的是下拉条目自己的 MID，取景由该 MI 的六标量决定。 |

**R2 v3 与它的验收状态**：代码全部完成（只推右侧、时间轴推给**当前选中步骤**的单元格、心跳+观察窗、
`_r2_verdict` 判据、推送前后各抓一张截图）；第一次真机跑（`logs/launcher_run_20260925_231941/`）落在
**空章节**上（`BackgroundChange=0:0`、`list_items=0`、`selected_step=0x0`，截图显示
"Select Background..." / "Select timeline slot to start editing"），因此**证明不了"跟随"**——
需要用户在 Create 里打开自己的章节、点一下时间轴 Background 单元格并切背景，命令与判读方式见
上游 §65.12。

