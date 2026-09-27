# 统一 Mod 合并协议（Mod Merge Protocol）· PoC v1

> 适用仓库：`CalaplayUpper`（CalaPlayerSrcmBuilder）· 实现：`core/merger.py` · CLI：`cli/merge_mods.py` + `scripts/merge_mods.ps1`
> 目标：让**多个互不相干的 Mod 共存**——合并成一个 `_P` 补丁容器，而不是互相覆盖。
> 本文是给 Mod 作者（含 Xenon-XG）对齐用的事实源：字段定义、行号语义、冲突规则、判据全部写在这里。

---

## 0. 一句话模型

```
mods/  ──(总索引 manifest.json)──►  每个 Mod 自己的 manifest.json
                                      ├─ kind=da_edit  → 数据表「行级」新增/修改/删除
                                      └─ kind=ui_text  → 整份 legacy 资产「文件级」替换
                                                    ↓
                              core/merger.py 逐 Mod 套到「原生基底」上
                                                    ↓
                       一个 CalaPlayer-Windows_P.{pak,ucas,utoc} + merge_report.json
```

合并器**只读** `-Base`（干净的游戏 Paks 目录），**只写** `-Out`；它从不安装、从不碰游戏目录。
安装仍然走 `install.ps1`（或手动复制三个文件）。

---

## 1. 目录结构（真实场景）

```
<ModsRoot>/                        ← -Mods 指向这里
├── manifest.json                  ← 总索引（只做索引，不内联内容）
├── CalaplayUpper_src/             ← 背景包（有自己的子文件夹）
│   ├── manifest.json
│   ├── DA_Backgrounds.uasset      ← 数据表「行源」，通常放在 Mod 根目录
│   ├── DA_Backgrounds.uexp
│   ├── DA_BGM.uasset / .uexp
│   └── CalaPlayer/Content/...     ← 该 Mod 引用的资产，**保留完整相对路径**
└── mods/                          ← 汉化包（Xenon-XG：文件直接放自己 folder 根下）
    ├── manifest.json              ← 他自己的声明（索引里写作 mods/manifest.json）
    └── CalaPlayer/Content/CalaPlayer/UI/...  ← 40 个 legacy 资产，同样保留路径
```

**铁律：路径不能拍平。** `file` 条目必须是「legacy 相对路径」（含 `Content` 段），
例如 `CalaPlayer/Content/CalaPlayer/UI/Widgets/WBP_MainMenu.uasset`。
`retoc to-zen` 靠目录结构还原包 id（`/Game/...`），拍平就会变成错误的包路径。

---

## 2. 总索引 `manifest.json`

```json
{
  "mods": [
    { "name": "CalaplayUpper", "manifest": "CalaplayUpper_src/manifest.json" },
    { "name": "XG_Translations", "manifest": "mods/manifest.json" }
  ]
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `mods[].name` | 是 | 显示名；重复即报错。也必须与 Mod 自己 manifest 里的 `name` 一致 |
| `mods[].manifest` | 是 | **相对 `-Mods` 的路径**，不能绝对路径、不能 `..` 逃逸 |

* 索引只做索引：Xenon-XG 更新自己的 `manifest.json` 后，**总入口不用改**。
* 列表顺序 = 合并顺序（对结果无影响，见 §4 行号语义）。GUI 勾选 Mod 时用 `selected_mods` 传名字子集。

---

## 3. 各 Mod 自己的 manifest

### 3.1 公共字段

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `name` | 是 | string | Mod 名（与索引里的 `name` 一致） |
| `folder` | 推荐 | string | 相对 `-Mods` 的**所属文件夹**；缺省 = manifest 所在目录。**该 Mod 的所有文件都相对它解析** |
| `kind` | 是 | `da_edit` \| `ui_text` | 见下 |
| `version` / `author` | 否 | string | 只进报告 |
| `targets` | `da_edit` 必填 | object | 行级操作，见 §3.2 |
| **`files`** | **是（所有类型都必须带）** | string[] | 该 Mod 贡献的 legacy 资产（**不含**目标 DA 表；目标表是「行源」而不是文件）。没有额外资产就写 `[]`。作用见 §3.4 |
| `note` | 否 | string | 只进报告 |

### 3.2 类型 A：`kind = "da_edit"`（数据表行级改动）

```json
{
  "name": "CalaplayUpper",
  "folder": "CalaplayUpper_src",
  "version": "1.1.0",
  "author": "killa0132",
  "kind": "da_edit",
  "targets": {
    "DA_Backgrounds": { "appended_rows": [165, 166] },
    "DA_BGM":         { "appended_rows": [100] }
  },
  "files": ["CalaPlayer/Content/CalaPlayer/Backgrounds/grid_a.uasset", "..."]
}
```

* `targets` 的键只能是这四张表：`DA_Backgrounds` / `DA_BGM` / `DA_Ambient` / `DA_Sounds`。
* 每张表支持三种操作（**可同时出现**）：

| 操作 | 含义 | 行号语义 |
|---|---|---|
| `appended_rows` | 新增行 | 在该 Mod **自己的表**里的行号；必须 **≥ 原生行数**（否则报错，因为那一行本来就有） |
| `modified_rows` | 改写已有的原生行 | 指向**原生表**的行号（`< 原生行数`） |
| `deleted_rows` | 删除原生行 | 指向**原生表**的行号；**独占**该表（见 §5） |

* Mod 必须**自带**它 `targets` 到的那些 `<TABLE>.uasset/.uexp`（合并器按文件名在该 Mod 的 folder 内递归查找，同名多份会报错）。
  这一对就是「**行源**」：它就是单 Mod 打包管线产出的那张表（= 原生表 + 本 Mod 自己追加的行）。
* **目标的 DA 表永远不会被当成普通文件整体拷贝**，而是由合并器从**原生基底**重建、再逐行拼接（原因见 §4）。
* `kind=da_edit` **也要带 `files`**：背景包同时贡献贴图/MI/图集，就在里面逐个列出来；确实没有额外资产（例如只改音频表）就写 `"files": []`。

### 3.3 类型 B：`kind = "ui_text"`（整份资产替换）

```json
{
  "name": "XG_Translations",
  "folder": "mods",
  "version": "1.1",
  "author": "Xenon-XG",
  "kind": "ui_text",
  "targets": {},
  "packages": [
    { "path": "/Game/CalaPlayer/UI/Widgets/WBP_MainMenu",
      "edits": { "ftext": 9, "strprop": 0, "bytecode": 15 } }
  ],
  "files": [
    "CalaPlayer/Content/CalaPlayer/UI/Widgets/WBP_MainMenu.uasset",
    "CalaPlayer/Content/CalaPlayer/UI/Widgets/WBP_MainMenu.uexp"
  ]
}
```

* `files` 必填（含 `[]`）：逐个按**原相对路径**合入统一目录。
* `packages` 只是**元信息**（报告里统计各包改了多少条文本/字节码）；**不做行级冲突检查**。
* `kind=ui_text` 不允许在 `targets` 里声明行操作（会报错）。
* 汉化这类 Mod 的资产通常覆盖原生同名包（= 有意 override），合并器会把它计入台账（§7）。

### 3.4 `files` 字段的三个作用（所有类型统一）

`files` 不是可选的备注，它是协议里**唯一的「改动范围声明」**，同时承担三件事：

1. **声明改动范围** —— 合并器只处理 `files` + 目标 DA 表；没写进来的文件不会被合并、也不会被带进容器。
   因此**漏写 = 资产不在容器里**（合并器会照实报告「N 个文件合入」，而不是替你猜）。
2. **冲突检测** —— 两个 Mod 的 `files` 归一化（大小写不敏感）后相撞 ⇒ **直接报错、零打包**（规则 C3）。
   这是「两个 Mod 都想提供同一个包」唯一的发现途径，绝不静默二选一。
3. **保留完整相对路径** —— 每条都必须是含 `Content` 段的 legacy 相对路径（例如
   `CalaPlayer/Content/CalaPlayer/UI/Widgets/WBP_MainMenu.uasset`），合并时**原样保留、绝不拍平**：
   `retoc to-zen` 就是靠这个目录结构还原包 id（`/Game/...`）的。路径不对 ⇒ 包路径就错。

> 目标 DA 表（`DA_Backgrounds` / `DA_BGM` / `DA_Ambient` / `DA_Sounds`）**不要写进 `files`**：
> 它们由 `targets` 走行级合并。即使写了，合并器也只会提示一句「按行合并、不整体拷贝」。

---

## 4. 行号语义（最重要的一节）

单 Mod 管线的产物是「**原生表 + 追加行**」，所以：

1. 合并器**永远从原生表重建**（`-Base` 里的干净容器 → `retoc to-legacy -f DA_`），
   不会在「已经被追加过的表」上再 `addname`/`bgref`。
   （在已追加的表上重序列化会让 uexp 多出一整行而行数不变 ⇒ 单 Mod 管线里那个 `-Combined` bug 就是它。）
2. 每个 Mod 的行被**按语义搬运**：读出行里的 `key`（下拉显示名）、`pkg`（软路径包）、`obj`（对象名）、`@30`（预览材质硬引用），
   再用 `da-patch addname` / `bgref` / 字节级行手术写进**合并后的表**。因此：
   * FName 索引会**重新分配**（名字表只增不改），Mod 之间不会互相踩名字；
   * `@30` 指向**原生** MI 时索引原样保留（名字/import 表只追加，老索引不变）；
   * `@30` 指向**该 Mod 自己新建**的 MI 时，用 `da-patch bgref` 在合并表的 ImportMap 末尾重新追加 2 条 import 并取得新索引。
3. 因此行号只在「同一张表、同一行」这个粒度上冲突（§5），**与 Mod 顺序无关**。

---

## 5. 冲突判定规则

合并前先做全量冲突检查，**任何冲突 = 立刻报错、一个字节都不打包**。

| # | 冲突 | 判定 | 报错样式 |
|---|---|---|---|
| C1 | **同一张表的同一行被两个 Mod 声明** | 任意操作组合（新增/修改/删除）只要落在同一个 `(表, 行号)` | `DA_Backgrounds 第 10 行: ModA 与 ModB 同时声明 (ModA=modified_rows, ModB=modified_rows)` |
| C2 | 同一个 Mod 内部重复声明同一行 | 同一 `(表, 行号)` 出现在两个操作里 | `DA_Backgrounds 第 10 行: 同一个 Mod ModA 重复声明 (...)` |
| C3 | **两个 Mod 提供同一个文件路径** | `files` 归一化（大小写不敏感）后相撞 | `文件 CalaPlayer/Content/.../WBP_MainMenu.uasset: ModB 与 ModD 都想提供` |
| C4 | **`deleted_rows` 与别的 Mod 共用一张表** | 删行会让后面所有行号平移，破坏别人的行号语义 | `DA_Backgrounds: ModA 声明了 deleted_rows，而 ModB 也在改这张表（删行会让后面所有行号平移）` |

**不构成冲突**（直接合入）：两张表的不同行；`ui_text` 的 `packages` 之间（不做行级检查）；
不同 Mod 的**不同**文件路径；一个 Mod 新增 + 另一个 Mod 修改不同行。

---

## 6. 合并流水线（CLI 输出的 M0~M6 判据）

| 门 | 名字 | 判据（失败即中止，不产出容器） |
|---|---|---|
| **M0** | 输入自检 | 索引与每个 Mod 的 manifest 可解析；`kind` 合法；`folder` 存在；声明的 `files` 都在；`targets` 的表/操作合法；目标表自带的 DA 对存在 |
| **M1** | 冲突检查 | C1~C4 全空 |
| **M2** | 干净基底 | 从 `-Base`（**排除已装的 `_P`**）抽出 4 张原生表，打印原生行数 |
| **M3** | 行级合并 | 每张表最终行数 = 原生 + Σ新增 − Σ删除；每次追加都用 `assert_append_only` 证明「只有行数域 + 追加行变了」 |
| **M4** | 文件合入 | 所有 Mod 文件按原相对路径落进统一 legacy 目录；路径无丢失、无拍平 |
| **M5** | 打包 + 读回 | `retoc to-zen` 出 `_P`；**读回容器**核对：DA 行数、每个新增/修改行的 key/pkg/obj、`@30` 未移动、每个 Mod 文件的 `.uexp` 逐字节一致；chunk 台账（新包 vs 有意 override）数量符合预期 |
| **M6** | 只追加不重排 | 对每个合并后的表做语义转储比对：**原生名字表/ImportMap 的每一条老索引都原位不变** |

---

## 7. 输出

```
<Out>/
├── CalaPlayer-Windows_P.pak / .ucas / .utoc     ← 合并后的补丁容器
├── merge_report.json                            ← 机读报告
└── merge.log                                    ← 全量日志（每条外部命令逐字记录）
```

`merge_report.json` 关键字段：

| 字段 | 含义 |
|---|---|
| `ok` / `error` | 成功与否 / 失败原因（含门号） |
| `selected` | 本次合并的 Mod 名（顺序 = 索引顺序） |
| `mods[]` | 每个 Mod 的 `name/kind/version/author/folder/rows/files` |
| `conflicts[]` | 冲突明文列表（C1~C4） |
| `tables{}` | 每张表 `native / final / appended / modified / deleted` |
| `files[]` | 合入的 legacy 相对路径清单 |
| `gates{}` | M0~M6 的 `ok` + `detail`（人类可读的真值） |
| `ledger` | chunk 台账：`new`（全新包，原生 0 命中）/ `override`（有意覆盖）/ `expected_override` / `override_of[]` |
| `container.files{}` | 三件套的 `bytes` / `sha256` / `sha16` |
| `container.content_sha256` | **内容指纹**（见 §8） |

> ⚠️ `retoc to-zen` 的**容器字节不是确定的**：同一输入两次打包，`.ucas/.utoc` 哈希会不同（体积相同、内容读回逐字节一致，已实测）。
> 所以**不要用容器哈希当"同一份产物"的判据**，用 `content_sha256`（对"读回容器的每个文件 sha256"再哈希，实测同输入稳定）。

---

## 8. 命令行

```powershell
# 直接调用（源码方式）
python cli\merge_mods.py -Mods <mods 目录> -Base <干净的游戏 Paks 目录> -Out <输出目录>

# 包装脚本（ASCII-only，供命令行/后续 GUI 调用）
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\merge_mods.ps1 `
    -Mods D:\mods -Base "D:\CalabiyanGalgameMaker\CalaPlayer\Content\Paks" `
    -Out D:\merged -Select CalaplayUpper XG_Translations -KeepWork
```

| 参数 | 说明 |
|---|---|
| `-Mods` | 总索引所在目录 |
| `-Base` | **干净**的游戏 Paks 目录（只读；里面已装的 `_P.*` 会被自动忽略） |
| `-Out` | 输出目录（容器 + 报告 + 日志） |
| `-Select` | 只合并列出的 Mod（缺省 = 全部）；名字大小写不敏感 |
| `-Kit` | 工具目录覆盖（retoc / da-patch / mappings） |
| `-KeepWork` | 保留合并中间目录（`<Out>\merge_work`）供排查 |
| `-Quiet` / `-Log` | 静音 / 指定日志文件 |

退出码：`0` 合并成功、`2` 参数错、`3` 合并失败（冲突或判据不过）。

**给 GUI 用的接口**（PoC 已封装好，GUI 直接复用，不要另写管线）：

```python
from core.merger import merge_mods

rep = merge_mods(mods_dir, base_paks, out_dir, selected_mods=None)   # -> MergeReport
if not rep.ok:
    for line in rep.conflicts:   # 勾选冲突能直接展示给用户
        print(line)
```

---

## 9. 实测（PoC 真实数据，2026-09-27）

真实数据：**背景包（`da_edit`）+ Xenon-XG 汉化包（`ui_text`）**。

| 项 | 实测 |
|---|---|
| 结果 | `RESULT: OK`，M0~M6 全 PASS |
| `DA_Backgrounds` | **165 → 167**（+2 新增，来自背景包） |
| `DA_BGM` | **100 → 101**（+1 新增） |
| 合入文件 | **54**（52 个来自两个 Mod + 2 张 DA 表） |
| chunk 台账 | **5 个全新包**（2 张背景贴图 + 2 个预览 MI + 1 条音频）、**23 个有意 override**（21 个汉化资产 + 图集 + 2 张 DA 表），与预期一致 |
| 读回判据 | 新增行 key/pkg/obj 全部对上；`@30` 未移动；**26 个 Mod `.uexp` 逐字节一致** |
| 只追加证明 | 名字表 490→498、ImportMap 333→337，**每一条老索引原位不变** |
| 内容指纹 | `1751e401e54fa61d97d90f4ce7d04a32…`（两次独立打包一致） |
| 容器 | `_P.ucas` 12,769,910 B（同输入的 `.ucas` 哈希两次不同、内容一致） |

冲突用例（回归 T31/T32）：两个 Mod 都声明 `DA_Backgrounds` 第 10 行 ⇒ **rc=3、零打包**；
两个 Mod 都提供 `WBP_MainMenu.uasset` ⇒ **rc=3、零打包**。

回归：`tests\regression.py` 新增 **T30**（无冲突能合并）/ **T31**（行冲突）/ **T32**（文件冲突）/ **T33**（缺 `files` 被拒），用模拟数据，不依赖任何外部 Mod 仓库。

---

## 10. 已知限制 / 注意事项

1. **预览图集是「单点资源」（已知限制，给未来的背景类开发者）**：`T_BackgroundPreviews` 是**同路径 override**，
   两个背景类 Mod 同时修改它 ⇒ 触发 **C3 文件冲突**（合并器如实报错，不会静默二选一）。
   ⚠️ **这不是 Xenon-XG 的待办**（汉化包不碰图集）；这条限制是留给**将来其他背景类 Mod 作者**的明确交代：
   在「格子协商」落地之前，**同一时间只能有一个背景类 Mod 占用图集**。
   「格子协商」（各 Mod 只写自己的格子、由合并器统一分配 `cell_index` 并合并像素）**列入后续开发计划**，不在本次 PoC 范围内。
2. **只支持这四张数据表**（`DA_Backgrounds` / `DA_BGM` / `DA_Ambient` / `DA_Sounds`）。别的表要加，得在 `core/merger.py::TABLE_SPECS` 里补 stride/偏移。
3. **`deleted_rows` 是独占操作**：它会平移后续行号，所以同一个表不允许第二个 Mod 参与（C4）。
4. **`scriptobjects.bin` 不放**（2026-09-27 与 Xenon-XG 确认）：实测 `retoc to-zen` 会忽略它——Xenon-XG 自己那份**已上机可用**的补丁容器也只有 `ExportBundleData + ContainerHeader`。蓝图字节码编辑不需要它。
   即使某个 Mod 的 `files` 里仍然声明了 `scriptobjects.bin`，合并器也会**显式跳过并记一条 NOTE**（不会报错，也绝不会进容器）——回归 **T30** 就是拿一个"老式"manifest 断言这条。
5. **不安装**：合并器只产出容器。安装/卸载见 §10.1（真机安装脚本 `scripts\install_merged.ps1`：写前备份、写后读回、失败自动还原、一键回滚）。
6. **不碰 GUI / 单 Mod 管线**：`core/builder.py`、`build_srcm.ps1` 一行未改；`core/merger.py` 独立成模块，只复用既有的 `Kit.to_zen` / `da-patch` 原语。
7. **容器哈希不确定**（§7 末尾）：比对产物请用 `content_sha256` 或逐文件读回。
8. 一次合并的耗时（真实数据）≈ **8 s**（含两轮读回与台账探测），中间目录峰值约 200 MB（=`-Base` 硬链接 + 合并后的 legacy 树，不含整包解包）。

### 10.1 把合并产物装进游戏（真机）

合并容器和单 Mod 产物**完全同构**（同名 `_P` 三件套），所以安装方式一样，但项目规矩是「写前备份、写后读回、失败自动还原」：

```powershell
# 干跑：只打印将要做的每一步 + 当前/新容器哈希（不碰游戏目录）
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_merged.ps1 `
    -Src "D:\...\work\merge_poc\out_merged" -Paks "D:\CalabiyanGalgameMaker\CalaPlayer\Content\Paks"

# 真装（需要 -Apply）：
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_merged.ps1 `
    -Src "D:\...\out_merged" -Paks "D:\CalabiyanGalgameMaker\CalaPlayer\Content\Paks" -Apply
```

* 脚本会先把**当前已装**的 `_P` 三件套**移动**到 `-Backup`（默认 `<Src>\..\install_backup_<时间戳>\real_P\`），
  并写 `BACKUP.txt`（含新旧哈希、原生容器与 `Scenarios.sav` 的哈希快照）。
* **同名容器互斥**：装合并容器 = 取代当前那个 `_P`（旧的背景/音频 Mod 会随之消失，这是容器机制决定的）。
* **一键回滚**：`-Rollback` 把备份里的三件套放回、删掉新装的三个文件；
  脚本自身在「读回哈希不一致 / 原生容器或存档被改动」时也会**自动还原**。
* 游戏在跑时会**在碰任何文件之前**拒绝（`_P` 被独占）。

> **GUI「Mod 管理器」标签页**：按用户拍板**暂不做**——等真机验收通过与 Xenon-XG 对齐完成后再讨论。
> 接口已经备好：`core.merger.merge_mods(mods_dir, base_paks, out_dir, selected_mods)` + `MergeReport.conflicts`。

---

## 11. 给 Mod 作者的对齐清单（Checklist）

要让自己做的 Mod 能被合并，只需要：

- [ ] 有一个 `<你的 folder>/manifest.json`，含 `name` / `folder` / `kind` / **`files`** / `version` / `author`。
- [ ] **`files` 一定要写**（没有额外资产就写 `[]`）：它是你的「改动范围声明」，也是冲突检测与「路径不拍平」的依据（§3.4）。
- [ ] `kind=da_edit`：`targets` 里逐表写清 `appended_rows`（**行号 = 你自己表里的行号，且 ≥ 原生行数**），并随包带上对应的 `<TABLE>.uasset/.uexp`。
- [ ] `kind=ui_text`：`files` 里写全你改过的资产，**路径必须含 `Content` 段、保持 legacy 目录结构**。
- [ ] 不要和别人的行号/文件路径相撞（撞了合并器会明确告诉你是谁撞了）。
- [ ] 想被单独勾选/排除，无需改任何东西：合并器支持按名字选择（`-Select` / `selected_mods`）。
