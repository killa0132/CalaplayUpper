# 统一 Mod 合并协议 · 给 Xenon-XG 的 review 材料（PoC v1）

> 来自 **killa0132**（`CalaplayUpper` / CalaPlayerSrcmBuilder 作者）· 2026-09-27
> 协议全文：`docs/MOD_MERGE_PROTOCOL.md`（本文是**给你 review 的精简版 + 待你拍板清单**）
> 一句话：让你的汉化包和我的背景包**同时生效于同一个 `_P`**，而不是谁覆盖谁。

---

## 0. 先说结论：我们是拿**你仓库的真实数据**跑通的

不是纸上方案。我们 clone 了 `Xenon-XG/CalaPlayer_Translations`，**原样**使用你的 `mods/manifest.json` 与 `mods/CalaPlayer/Content/**`
40 个文件，和我的背景包（`da_edit`）合并成一个 `_P` 容器：

| 实测项 | 结果 |
|---|---|
| 合并结果 | `RESULT: OK`，判据 M0~M6 全 PASS |
| 你的部分 | 20 个包全部合入；**每个 `.uexp` 从容器读回后逐字节一致**（0 缺失、0 差异） |
| 我的部分 | `DA_Backgrounds 165→167`、`DA_BGM 100→101`（我的 2 张背景 + 1 条 BGM） |
| 容器台账 | 5 个全新包（我的贴图/MI/音频）+ **23 个有意 override**（你 20 个包 + 图集 + 2 张 DA 表），与预期完全一致 |
| 只追加证明 | DA 名字表 490→498、ImportMap 333→337，**每一条老索引原位不变** |
| 耗时 | 一次合并 ≈ 8 s |
| 真机 | **已装机并实测通过**：背景下拉出现我的 `grid_a`/`grid_b`（缩略图/预览块/时间轴三处都对）、BGM 出现 `merge_theme`、**界面是简体中文** = 两个 Mod 真的共存了 |

**你不需要改任何东西**——你现在的 `mods/manifest.json` 与目录结构就是合规的。

---

## 1. 你的 manifest 逐字段体检（我们的处理方式）

| 你的字段 | 我们的处理 | 备注 |
|---|---|---|
| `name: "XG_Translations"` | 用作 Mod 名（索引里也用它） | 重复名会报错 |
| `folder: "mods"` | **作为你的文件根目录**（`files` 相对它解析） | 与"manifest 所在目录"一致时最省心 |
| `kind: "ui_text"` | 走**文件级**合并（不做行级检查） | 另一类 `da_edit` 走数据表行级 |
| `version` / `author` | 只进合并报告 | |
| `note` | 只进报告（日志里会打印一句） | 你的说明写得挺清楚 👍 |
| `targets: {}` | 空对象 = 不声明行级操作 | `ui_text` 里必须为空 |
| `packages[].path` / `edits` | **目前只统计进报告**（`ftext/strprop/bytecode` 计数） | 见下面问题 ⑤：要不要把它用起来 |
| `files[40]` | **逐个按原相对路径合入统一目录**（绝不拍平） | 这是协议里最重要的字段，见 §2 |
| `container_base: "CalaPlayer-Windows"` | **暂未使用** | 见问题 ④ |
| `engine: "UE5_7"` | **暂未使用**（合并器固定按 `UE5_7` 调 retoc） | 同上 |

---

## 2. 协议最小集（你只需记住这 5 条）

1. **目录结构**：你的文件保持现在的样子——`<你的 folder>/CalaPlayer/Content/...`。**路径不许拍平**，
   因为 `retoc to-zen` 就是靠这个目录结构还原包 id（`/Game/...`）。
2. **总索引**：合并工具这一侧有一个 `mods/manifest.json` 索引，形如
   `{"mods":[{"name":"CalaplayUpper","manifest":"CalaplayUpper_src/manifest.json"},
             {"name":"XG_Translations","manifest":"mods/manifest.json"}]}`
   —— **你更新自己的 manifest 后，索引不用改**，合并器每次都读最新的。
3. **`files` 是所有类型都必须带的字段**（没有额外资产就写 `[]`）。它承担三件事：
   **声明改动范围**（没写进去的文件不会进容器）、**冲突检测**（两个 Mod 撞同一路径 → 报错零打包）、
   **保留完整相对路径**。你的 `files` 现在就完全合规。
4. **冲突**：只有 4 种会让我们报错——① 两个 Mod 改**同一张数据表的同一行**；② 同一 Mod 重复声明同一行；
   ③ 两个 Mod 提供**同一个文件路径**；④ 有人声明 `deleted_rows` 时另一个 Mod 也在改那张表。
   除此之外都直接合入（你的 20 个包 vs 我的背景包 = 零冲突）。
5. **不改原生**：合并器只读游戏原生容器，产物只有一个新 `_P`；安装/回滚有脚本（写前备份、写后读回、失败自动还原）。

---

## 3. 请你看完回复的 7 件事

| # | 事项 | 我的建议 | 你的意见 |
|---|---|---|---|
| ① | `files` 必填（含 `[]`） | 保持必填，语义明确、冲突可检测 | |
| ② | **`scriptobjects.bin` 不用再带** ✅ **已确认（XG，2026-09-27）** | 实测 `retoc to-zen` **忽略**它；你那份已上机可用的 `patch/` 容器里也只有 `ExportBundleData + ContainerHeader` ⇒ 你 `tools/rebuild.ps1` 里 `Copy-Item scriptobjects.bin` 那两步（第 35 行）**可以删掉**，流程更短。我们这侧的合并器也会**显式跳过**它（即使 manifest 里还写着） | |
| ③ | 总索引由谁维护 | 由**合并工具侧**维护（你什么都不用改）；将来 GUI 里就是"勾选卡片" | |
| ④ | 你的 `container_base` / `engine` 字段 | 目前忽略；如果你希望协议里保留（比如将来支持别的容器名/引擎版本），我们就写进协议**并做校验** | |
| ⑤ | 你的 `packages[].edits` 计数 | 目前只进报告。要不要升级成"**重叠声明**"——比如两个 Mod 都改同一个 `WBP_MainMenu` 时提前警告（现在这种情况会被 ③ 文件路径冲突挡住，但同包不同编辑的合并能力还没做） | |
| ⑥ | 预览图集（`T_BackgroundPreviews`） | **跟你的汉化无关**，只是告知：它是"单点资源"，两个**背景类** Mod 同时改会撞文件冲突；"格子协商"（各写自己的格子）在我们的后续计划里 | |
| ⑦ | 版本/字段扩展 | 你想加的字段（例如 `homepage`、`changelog`、`min_game_version`）告诉我们，写进协议即可；未知字段我们**忽略而不报错**（向前兼容） | |

---

## 4. 你可以自己复现（两条命令）

```powershell
# 合并（-Mods 指向含总索引的目录，-Base 指向干净的游戏 Paks）
python cli\merge_mods.py -Mods <mods目录> -Base "<游戏>\CalaPlayer\Content\Paks" -Out <输出目录>
# 或包装脚本 + 只合并指定的 Mod
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\merge_mods.ps1 `
    -Mods <mods目录> -Base "<游戏>\CalaPlayer\Content\Paks" -Out <输出目录> -Select XG_Translations
```

* 输出：`<输出目录>\CalaPlayer-Windows_P.{pak,ucas,utoc}` + `merge_report.json` + `merge.log`。
* 退出码：`0` 成功、`2` 参数错、`3` 失败（冲突或判据不过，**不会产出半个容器**）。
* 冲突时的报错长这样（会点名两个 Mod 与具体行/路径）：
  - `DA_Backgrounds 第 10 行: ModA 与 ModB 同时声明 (ModA=modified_rows, ModB=modified_rows)`
  - `文件 CalaPlayer/Content/CalaPlayer/UI/Widgets/WBP_MainMenu.uasset: ModB 与 ModD 都想提供`
* 安装到游戏（可选，写前备份/写后读回/失败自动还原/一键回滚）：
  `scripts\install_merged.ps1 -Src <输出目录> -Paks "<游戏>\CalaPlayer\Content\Paks" -Apply`

---

## 5. 我们这边的后续计划（你确认协议之后再动）

1. **GUI「Mod 管理器」标签页**：读 `mods/manifest.json`，把每个 Mod 渲染成可勾选卡片，冲突当场展示，点一下合并打包（复用同一个 `core/merger.py`）。
2. **图集「格子协商」**：让多个背景类 Mod 各自只写自己的格子、由合并器统一分配并合并像素。
3. 如果你愿意，把合并器接进你的 `tools/rebuild.ps1`：你只管维护 `translations.json` 和 `manifest.json`，合并/打包一步完成。

---

## 附：合并报告里的关键字段（你排查问题时看这些）

| 字段 | 含义 |
|---|---|
| `ok` / `error` | 成功与否 / 失败原因（带门号） |
| `mods[]` | 参与了哪些 Mod、各自贡献多少行/文件 |
| `conflicts[]` | 冲突明文 |
| `tables{}` | 每张表 `native / final / appended / modified / deleted` |
| `files[]` | 合入的完整相对路径清单 |
| `gates{}` | M0~M6 判据的 `ok` + 人类可读明细 |
| `ledger` | `new`（全新包）/ `override`（有意覆盖）与预期数量 |
| `container.files{}` | 三件套的 `sha256` / 字节数 |
| `container.content_sha256` | **内容指纹**（同输入两次打包内容一致；容器哈希本身不是确定的，别拿它当"同一份产物"的判据） |
