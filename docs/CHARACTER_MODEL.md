# 添加角色模型 / Add a character skin

> 给 CalaPlayer 游戏加一套**新的角色皮肤**：把导出的皮肤素材（贴图 PNG，或整个
> `...\Characters\<角色>\<皮肤>` 文件夹）做成游戏里"添加角色 → 皮肤列表"能直接
> 创建的新皮肤。
>
> GUI 第三个模式「添加角色模型」；CLI 入口 `cli/import_character.py`。
> 本版实测：`Aika` + `S051` 素材 → 新皮肤 `S052`，游戏内创建成功、渲染正常
> （2026-10-11，含 6 张贴图重编码 / 18 个材质 / 10 个 DA 槽位 / 双容器部署）。

---

## 1. 用户怎么用

### GUI

1. 左侧切到 **添加角色模型**。
2. **游戏 Paks 目录**：游戏根目录或它的 `Content\Paks` 都行（与另外两个模式同一套发现逻辑）。
3. **素材目录**：一套导出的皮肤文件夹，例如
   `E:\Calabiyau\Export\PaperMan\SkinAssets\Characters\Aika\S051`
   （有 `Mesh3D\` 子目录时优先用它里面的 PNG）。
4. **角色**：点「读取角色列表」会**只读地**提取一次 `DA_Characters`，
   把游戏里的 20 个实装角色列出来（`Aika（S001 / S002 / S051）` 这样带上已有皮肤）。
   留空 = 从素材路径自动识别。
5. **新皮肤 ID**：形如 `S052`（S + 3 位数字）。留空 = 自动挑一个没被占用的号。
   右边那个框是**源皮肤**（从哪套已有皮肤克隆，默认 `S001`）。
6. 点 **开始导入**。默认会**直接装进游戏**（两个容器各有备份）；想只构建不安装就勾上
   「仅构建不安装」。进度条走 `C0..C6`，日志 / 判据 / 结果面板与其它模式共用。
7. 重启游戏 → 剧情编辑器 → 角色 → 添加角色 → 选角色 → 皮肤列表里就能看到新皮肤。
8. 不满意：结果面板右下角 **回滚**（把 `_P` 与 `_P2` 都还原到安装前）。

### CLI

```powershell
python cli\import_character.py -Paks "D:\...\CalaPlayer" `
    -Skin "E:\...\Characters\Aika\S051" -SkinId S052 [-Character Aika] [-Source S001] `
    [-Out <输出目录>] [-Kit <工具目录>] [-DryRun] [-KeepWork] [-Log <日志>] [-Quiet]
```

Exit code：`0` 成功；`3` 失败（看日志）；`2` 参数错。

---

## 2. 产物与部署

| 产物 | 内容 | 说明 |
|---|---|---|
| `<输出目录>\p2\CalaPlayer-Windows_P2.*` | 新皮肤的**全部资产**（网格/材质/贴图） | 新路径的新包，必须由带**完整头部的独立容器**承载（to-zen 生成，游戏挂载时经 `LogFilePackageStore` 合并注册包名） |
| `<输出目录>\p\CalaPlayer-Windows_P.*` | **只替换了 `DA_Characters` chunk** 的补丁容器 | 现有 `_P` 用 `unpack-raw`/`pack-raw` **字节级**换掉 DA chunk（其余 48 个 chunk 一个字节都不动，实测往返零损耗） |
| `<输出目录>\work\` | 提取树 / 构建产物 / 打包输入 | 勾 KeepWork 保留；部署成功后默认清掉 |
| `<输出目录>\p\install_backup_<时间戳>\` | 安装前 `_P` 的备份（含 `BACKUP.txt`） | 回滚用 |
| `<输出目录>\p2\install_backup_<时间戳>\` | 安装前 `_P2` 的备份 | 回滚用 |

* 游戏里**只认一个 `_P`**：如果用户之前已经装过别的补丁（背景/音频/剧情编辑器），
  本次不会覆盖它 —— C5 是"在原容器上加一个 DA chunk"，其余原样。
* `_P2` 同理：已存在 `_P2`（例如以前的 S102/S002/S051）时，它里面的资产会**先并入**
  打包目录、再叠加新皮肤，最后一起重新出包（实测 88+31→119 chunk 全量保留）。

---

## 3. 六阶段流水线（`core/character.py`）

```
C0 环境     kit + 游戏发现 + 磁盘/占用检查 + 清理旧的 work/产物（install_backup_* 保留）
C1 基线提取  retoc to-legacy（只取「该角色目录 + 旧 _P2 涉及目录 + DA_Characters」）
C2 计划     素材 PNG ↔ 源皮肤贴图（归一化匹配）→ 选中材质 → 要构建的贴图 → DA 槽位表
C3 资产构建 贴图（ubulk 重编码 + 格式声明核对）→ 材质 → 网格（全部"纯同长字节替换"）
C4 DA 注册  da-patch addname（新增名称）→ 克隆源皮肤条目 → 改写引用 → 插入 + count+1
C5 打包     _P2 = to-zen（旧资产 + 新皮肤）；_P = unpack-raw → 换 DA chunk → pack-raw
C6 部署     core.deploy.install ×2（备份 → 写入 → 读回 → 失败自动还原）；两步都失败时整体回滚
```

### 3.1 素材匹配（C2）

素材文件名归一化后与源皮肤资产名比较（去皮肤记号、去分隔符、转小写）：

| 素材 PNG | 归一化 | 匹配的源贴图 |
|---|---|---|
| `T_Aika_Body_1_S051_D.png` | `taikabody1d` | `T_Aika_body_1_D` |
| `T_Aika_body2_Mask1_051.png` | `taikabody2mask1` | `T_Aika_body2_Mask1` |
| `T_HuiXing_Body_D_S102.png` | `thuixingbodyd` | `T_HuiXing_Body_D_S101`（源皮肤 S101） |

匹配不上的 PNG 只记一条日志（跳过），不影响其余导入。

### 3.2 选中哪些材质（数据驱动）

**选中 = 引用了"被替换贴图"的材质**，再把它们引用的**全部贴图**一起构建
（有素材的换新像素，没有的原样复制）—— 从根上杜绝断链：

```
被替换的 6 张贴图（素材提供）
   └─ 引用它们的 18 个材质（Body1 组 6 + Body2 组 8 + Sign/Skin 4）
         └─ 它们引用的 6 张贴图全部构建（不多不少）
网格引用的材质里「被选中的 9 个」切到新皮肤目录；面部/头发/眼睛等保持源皮肤。
```

### 3.3 纯同长字节替换（C3 的铁律）

皮肤 ID 是 4 字符（`S001`→`S052`），所有改名都只做**等长替换**：

* 网格 `aika-s001` → `aika-s052`（自身名/路径 + 被切材质的路径）；
* 材质/贴图：目录段与资产名逐引用替换（**不做目录段全局替换** —— 骨架/物理/面部材质
  这些"故意保留"的引用会被误伤；需要保留、又恰好含 `S001` 记号的引用用**等长占位符**
  遮住，替换完再还原）；
* 每个文件收尾双重校验：**残留检查**（应替换的串一个不许剩）+ **长度不变**。
* 绝不新增 import / 改表结构 —— 那是网格"能加载、无报错、渲染空白"的根因（教训 12.1）。

### 3.4 贴图（C3）

* 只替换 `.ubulk` 里的**前几级大 mip**（2048→128，5 级），小 mip 内联在 `.uexp` 里保持原样；
* 编码格式必须与**声明**一致：`PF_DXT1`→DXT1、`PF_DXT5`→DXT5、`PF_BC5`→BC5；
  源是 `PF_BC7` 而素材要替换时，**自动做声明修复**（uexp 内联 `PF_BC7`→`PF_DXT5`
  +uasset `SerialSize` +1，与《皮肤贴图正确显示_修复记录》阶段①的修复同一条路）；
* 新 ubulk 与源 ubulk **精确同尺寸**（mip 链从源 ubulk 长度反推，逐级校验）；
* 权威元数据（尺寸/格式/mip 数）来自 `tex-inspect`（从游戏容器直接读）。

### 3.5 DA 条目（C4，`core/char_da.py`）

条目字节布局（实测）：

```
[Key FName 8B][00 07][PkgName FName 8B][AssetName FName 8B][SubPathLen u32]
[Outlines 数 u32][Outlines 数 × (Pkg FName 8B + Asset FName 8B + u32)][Portrait i32]
条目长度 = 38 + 20 × n
```

* 定位用"**皮肤键锚定 + 链式校验**"：枚举 `S\d{3}` 名称的 8 字节命中，
  要求 `count@k-4` 合理且从 `k` 起能严格解析出 count 个连续条目；
* **角色键的判据**：键后面紧跟 `00 07`（角色条目 value 的 struct 头）——
  没有它，Morphs map 里的表情名（Anger/Angry…）会被当成角色（GUI 角色下拉踩过）；
* 新条目 = **克隆源皮肤条目** → 改 key / pkg / asset + 需替换的 Outlines 槽位 →
  插到源条目之后 → `count+1` → `uasset` 的 `SerialSize` 同步 +条目长度；
* 新名字先用 `da-patch addname` 只追加进名称表（旧索引不动，`core/da.py` 的
  append-only 证明复用）。

---

## 4. 边界与注意事项

* **皮肤 ID 必须 4 字符**（`S` + 3 位数字）：同长替换是这套配方的硬约束；
  想用更长的号需要"变长改名 + 名称索引重写"，本版直接拒绝并提示。
* **素材必须包含 `.ubulk` 级的贴图替换**：这套配方只处理外置 mip 的贴图；
  完全新画网格（换形状）不在本版范围（游戏内皮肤本来就复用网格几何）。
* 立绘（`Portrait`）默认**沿用源皮肤**：皮肤下拉里显示的还是源皮肤的立绘。
  想给新皮肤画独立立绘需要额外构建 `MMI_CharacterPortrait_0NN` 资产，本版不做。
* 安装前必须**关掉游戏**（容器被占用时工具会在碰任何文件之前拒绝并给中文提示）。
* 卸载/回滚：结果面板的「回滚」按钮，或手动
  `Copy-Item <输出>\p\install_backup_*\<...> 回去`（两份 `BACKUP.txt` 里有照抄命令）。
* 素材与游戏目录建议纯英文路径（与其它模式同一条注意事项）。

---

## 5. 关键文件

| 文件 | 职责 |
|---|---|
| `core/character.py` | 六阶段引擎（`CharacterBuilder` / `CharCtx`） |
| `core/char_da.py` | `DA_Characters` 解析 + 皮肤条目插入（纯 Python 字节手术） |
| `core/char_kit.py` | retoc 扩展包装（多过滤器 to-legacy / unpack-raw / pack-raw / verify） |
| `core/bcn.py` | BC3(DXT5) / BC4 / BC5 编码器 + ubulk 生成（BC1 复用 `core/bc1.py`） |
| `cli/import_character.py` | 命令行入口 |
| `gui/chars.py` | 角色清单发现 + 开始前校验（GUI 侧，宽容） |
| `gui/tasks.py` | `start_character` / `_run_character`（与 CLI 同一条管线） |
| `gui/app.py` | `GET /api/characters`、`POST /api/character`、`POST /api/character/rollback` |

`core/builder.py`、`core/merger.py` 等既有引擎文件**一个字节都没改**；
`core/deploy.py` 的 `install/rollback` 直接复用（`base` 参数本来就支持 `_P2`）。
