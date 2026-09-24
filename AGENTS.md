<!-- 本文件是 CalaplayUpper 工程的"开工规则 + 当前状态"，用于跨会话续做。

     稳定内容 = 开工规则 / 授权边界 / 已验证原语 / 工具链 / 坑表。
     本轮细节看 docs/ 与 build.log。 -->

# CalaplayUpper（CalaPlayerSrcmBuilder）

> 上游工程 = `D:\dsharnessProject\CalabiyauGalMaker`（CP-32 为止的逆向取证与历史交付件）。
> **游戏本体 `D:\CalabiyanGalgameMaker\CalaPlayer` 一律只读**；改写只允许发生在
> `Content\Paks\CalaPlayer-Windows_P.{pak,ucas,utoc}` 这一个同名补丁容器上。

## 当前阶段：CP-33（M1~M4 真机验收 + GUI 六轮：G0~G5 → UI/UX → 分隔条/引导 → 中英双语/LineSidebar/社区 → SquishSwitch/乱码解码/GlideSelect/社区四入口 → **引导只弹一次/社区栏改版/下拉穿透/左栏定宽**）

### GUI 第六轮（2026-09-24，全部有断言、可复跑）

* **新手引导"只在首次打开时自动弹出"以前是坏的**，根因不是 localStorage 的写法，而是
  **页面没有稳定 origin**：页面从 `http://127.0.0.1:<每次启动随机的端口>/` 加载，而 WebView2 的
  `localStorage` **按 origin（含端口）分桶** ⇒ 每次启动都是空桶，`cala-onboarded` /
  `cala-lang` / `cala-theme` / `cala-split` 全部悄悄回默认值、引导**每次必弹**。
  ⇒ 新增 **`gui/prefs.py` + `GET/POST /api/prefs`**（白名单键 / 值 ≤64 字符 / tmp+`os.replace`
  原子写；落在 `%LOCALAPPDATA%\CalaPlayerSrcmBuilder\prefs.json`）+ 前端 **`src/prefs.js`**
  （`main.js` 在 mount **之前** await 一次，之后同步读 —— 主题和语言必须落在第一帧上；
  localStorage 仍同步写一份，供 `vite` dev origin 与浏览器调试）。
  **判据**：开窗前 `prefs.clear(['cala-onboarded'])` 造真·首次运行 ⇒ 引导必须**自己弹**
  （不靠 `restart(0)`，页面里报 `auto=True`）→ 走完读 `GET /api/prefs` 必须
  `cala-onboarded=1` → 最后**真 `location.reload()`**（＝下一次启动）⇒ 新页面
  `guide=False, auto=False, stored=True`；跑完把用户原 prefs 写回（与剪贴板同规矩）。
* **引导卡片本身**：加 `max-height: calc(100vh-28px)` + 纵向滚动（内容再长也读得全）；
  按钮栏 `flex-wrap: nowrap` + 按钮 `flex:none/white-space:nowrap` + 圆点缩到 6px/5px 间距，
  卡片 392→**436px** ⇒ "跳过引导 / 9 圆点 / 上一步 / 下一步"**一行放得下**（判据 `rows=1`、
  `overflow=0px`）；聚光框在目标滚不进视口时**退化成可见交集**（而不是画到屏幕外），
  且只滚**真正可滚动**的祖先（`overflow:hidden` 的右栏被 `scrollIntoView` 滚一下会永久偏位）。
* **社区弹窗**：GitHub 图标换成用户给的 **Octicon `mark-github`** 原始 path（断言 path 前缀，
  不是"有个图标"）；四入口改成**一个 2×2 Grid 且四按钮等宽**（原来是 flex-wrap，QQ 被挤到
  单独一行）；悬浮**不再卡出滚动条** —— 9 颗星星是绝对定位子元素，会把祖先的 scrollable
  overflow 撑大，现在半径收到 13~28px + 弹窗 `overflow-x: hidden`，判据直接比
  `scrollWidth/clientWidth` 与 `scrollHeight/clientHeight`（悬浮前后都必须相等）。
* **「背景适配」下拉点到 DryRun（z-index / 事件穿透）**：根因是**栈上下文** —— 菜单原在选项
  卡片内部，卡片有 `backdrop-filter`（自成栈上下文）、每行又带 `z-index`，于是菜单**画在下一行
  后面**。修法：`<Teleport to="body">` + `position: fixed` + `place()` 实时摆位（滚动/缩放重摆、
  外部点击要认这个"不再是子节点"的菜单）。
  ⚠️ **teleport 的连带坑**：`--gs-*` CSS 变量原先只挂在 `.uv-gs` 根上，弹出层搬到 body 后
  **不再继承** ⇒ 行高/pill 高度变 `auto` ⇒ "pill 滑到第 N 行"和"点在第 N 行"用两套尺寸，
  点到上一行。现在变量同时挂根与弹出层。判据用 **`document.elementFromPoint(选项行中心)`**
  问浏览器到底把谁画在那里（必须是那一行的 `.uv-gs-opt`），并断言 `position=fixed`/父节点 `BODY`；
  组件内留 `window.__calaGsTrace` 面包屑（open/down/up/pick/close）。
* **「浏览…」按钮被挤扁** ⇒ 文件夹 SVG + 文案、`flex:none; white-space:nowrap`；
  **`ScrambleText` 的 `white-space: pre-wrap` 会盖掉继承来的 nowrap**，故给该组件加了
  `nowrap` 开关（选项行标题也用它）。
* **左栏加载后收缩 11px** ⇒ 左栏加 **`scrollbar-gutter: stable`**（`clamp(330px,30%,460px)` 不动）。
  判据：往左栏塞 1400px 临时元素逼出滚动条，断言**前 / 溢出后 / 移除后** `#card-inputs`
  宽度三者一致。这条 11px 曾让「背景适配」折成两行 ⇒ 选项行改成**标题 nowrap + 右侧控件先让位**，
  并加"既没折行也没被省略号截断"的断言（`scrollWidth <= clientWidth+1`）。
* **右栏在大小窗口下都"不适配"（第六轮追加修复）**：右栏内容只占左边一段、并且在栏内居中，
  宽度不随窗口增长（1446 px 时分割条仍只有 717 px，本该 976 px）。根因是 `App.vue` 里给
  **页头按钮组**写的 `.right { display:flex; align-items:center; flex-wrap:wrap }`
  **同时命中了工作区右列** `<section class="col right">` ⇒ 那一列被加了 `align-items:center`
  （子元素不再拉伸，SplitPane 变成 shrink-to-fit 并居中）+ `flex-wrap:wrap`。
  修法：页头那组改名 `.bar-right`。判据（`--selftest-shell` 四档窗口各测一遍）：
  `splitW == rightW`、`paneAL == 右栏左边`、`paneA == paneB`、判据卡右缘 ≤ 栏右缘、
  `chips/taskid 右缘 == 栏右缘`、**大窗口面板宽度必须比标准窗口大 ≥20px**，
  以及最小窗口下选项标签 `trunc=0/5`。顺带把「背景适配」收起态改成显示短值
  （`cover` / `contain`），否则最小窗口（左栏 330px）里行标题会被挤成省略号。
  截图新增 `gui_shot_layout_min.png`。
* 本轮验收：源码 `SHELL UI SELFTEST: OK`；21 场景 **21/21（197.8 s）**；`G1 RESULT: OK`；
  GUI Kit **98.1 / 302.4 MB**（exe 41.0 MB）；`G4 RESULT: OK`（**70 项全 PASS / 0 FAIL**，
  含 13 项本轮新增）；`check_dist` 4 Kit OK。截图新增 `gui_shot_second.png`（第二次启动不弹引导）、
  `gui_shot_join_hover.png`（四宫格 + 无滚动条）、`gui_shot_layout_min.png`（最小窗口布局）。
  禁改清单五文件一字节未改。

### GUI 第五轮（2026-09-24，全部有断言、可复跑）

* **中/EN 切换件换成 ReactBits Squish Switch**（`components/SquishSwitch.vue`）：真弹簧积分器
  （非 CSS transition）+ **速度驱动形变**（沿行进方向拉伸、垂直压扁），悬停膨胀，拖过 4px slop
  可拖拽切换；中/EN 两字在轨道两端，旋钮压在激活的那个下面。
  自检**真实按下**（它在 pointerup 提交，合成 `.click()` 无效）后每 45ms 采样 17 次：
  断言 `|scaleX−1|>0.02` 且 `minSy<0.999`（真拉伸+真压扁）、末态停在另一端、语言真换了。
* **切换语言的"乱码解码"一次性波纹**（`components/ScrambleText.vue`）：上游是**鼠标邻近**触发，
  用户明确不要 ⇒ 改成"按下切换件时播放一次"的解码波，每字符按**与点击点的距离**依次落定
  （点击扩散），只播一次、之后悬浮不再触发；噪声字形**按脚本选**（CJK→汉字、拉丁→字母）
  以免整行重排；覆盖 23 个文本节点。
  **判据必须在页面内部采样时间序列**（跨进程 `evaluate_js` 往返比波纹本身还慢，从 Python 读
  永远只看到落定结果）：SCRAMBLE_RUN_JS 触发+60ms×14 采样，断言有采样 `running>0` 且 `#run`
  既非中文也非英文、末采样必须是落定英文；SCRAMBLE_HOVER_JS 派发 5 次 pointermove 后采样
  必须 `running` 恒 0。
  ⚠️ **这条判据当场抓到真 bug**：组件里用了 `nextTick` 却忘了 import ⇒ 异步 watcher 抛
  ReferenceError 被 Vue 吞掉 ⇒ **文字瞬间切换、波纹从未运行**，而"切换后文案正确"式断言全绿。
* **背景适配下拉换成 ReactBits Glide Select**（`components/GlideSelect.vue`）：弹出层里单个
  pill 元素在行间 `translateY(row*step)` **滑行** + pop 进出 + 指针划选 + 键盘 + 空间不足翻转 +
  标签 blur-swap。自检：真实按下开 → pill 在 row0 → pointerover 到 row1 → **位移 ≥20px** →
  划选 → 值变 contain、标签跟着变、菜单关闭。
* **「加入我们」四个入口**：GitHub（图标外 9 颗**满天飞**星星 `gh-fly`；点击 → 打开
  `https://github.com/killa0132/CalaplayUpper` **并**蹦出 `star.png` 求 star 弹窗，**上下结构**）
  + QQ（点击 → **先复制群号 `1054243070` 到剪贴板**，再弹 `joinQQ.png` + 群号 +
  「来吧！到猫窝里就地复原吧！」）。剪贴板走后端 `GET /api/copy`（WebView2 的
  `navigator.clipboard` 需安全上下文+手势，缺一个就**静默失败**＝死按钮）；`dry=1` 只校验。
  自检**真实写入 + Win32 `GetClipboardData` 读回比对**，且**先存用户原剪贴板内容、测完写回**。
  `/api/open_url` 白名单加 GitHub。
* **修掉一个真 UI 缺陷**：引导卡片的入场原本是 keyframe（`fill-mode: both`），
  **WebView2 合成器恢复时会重启关键帧动画** ⇒ 卡片会瞬间掉回 `opacity:0`（截图里抓到
  op=0.0489）⇒ 改成**过渡 + `.ready` 类**（过渡只在值变化时跑，重启不会回到起始态）。
* 本轮验收：源码 `SHELL UI SELFTEST: OK`；21 场景 **21/21（191.3 s）**；`G1 RESULT: OK`；
  GUI Kit **98.1 / 302.4 MB**；`G4 RESULT: OK`（**55 项全 PASS / 0 FAIL**）；`check_dist` 4 Kit OK。
  截图新增 `gui_shot_{scramble,squish,glide,star,qq}.png`。禁改清单五文件一字节未改。

### GUI 第四轮（2026-09-24，全部有断言、可复跑）

* **全界面中英双语**：`gui/frontend/src/i18n.js`（扁平 key + 两本字典，`lang` 是 Vue `ref`，
  切换即时重渲染整页）。首启判定 = `localStorage` → 否则系统语言（`zh*` 中文、其他英文），
  在 `main.js` **首帧前**执行（不闪错语言）。右上角 **中 / EN** 分段开关，
  自动化等价物 `window.__cala.setLang('en')`。引导/两个结果弹窗/社区弹窗全双语；
  「暂无日志可导出 / 已取消导出」改由**页面**按后端机器可读的 `reason` 选词。
  **来自冻结 core 的字符串不翻译**（构建日志、判据明细、构建报错）——给它们配翻译表会随管线腐烂。
  ⚠️ 用户以为 `README.md` 已是中英双语，**实际是纯中文**（他记成交付件里的英文 `README.txt`）；
  本轮补了 `README.en.md`（同结构、覆盖全部功能），两份顶部互链。
* **引导补两步 → 共 9 步**：新增 `-Force`（超限/PSNR 门槛才需要勾，是确认不是加速）与
  「进阶」（ffmpeg 路径 / 自定义工具目录 / 更细参数），目标 `#opt-force` / `#opt-adv`；
  切目标前先 `scrollIntoView`（左栏会滚动，否则聚光落在屏幕外）。
* **选项栏换成 ReactBits Line Sidebar**（`components/LineSidebar.vue`）：机制原样移植——
  单个 `rAF` + 与帧率无关的指数平滑推进每行 `--effect`，`translateX` 朝光标滑动、
  `color-mix()` 混向金青强调色、marker 线缩放跟随。ON 的行/展开的进阶/适配行**钉在满效果**。
  中心点用 `getBoundingClientRect` 量（原版 `offsetTop` 只在 nav 是 offsetParent 时等价）。
  自检用合成 `pointermove` 戳某行，断言光标下行 `eff>0.75` 且平移 ≥6px、隔两行 `<0.25` 且 `<3px`、
  两者 **computed color 不同**。
* **进度条**：轨道**改回 12px**、GIF 头部保持 **68px**，并加**居中判据**——
  实测 `railCY=headCY=barCY=729`（自检断言 |head−rail| ≤ 2px、|head−bar| ≤ 3px）。
* **「加入我们」社区弹窗**（`components/CommunityModal.vue`）：`joinus.png` + 喵言喵语 +
  Discord（真链）+ B 站（占位符，点了会说「链接还没放上来喵」）。外链走
  `GET /api/open_url`（**WebView2 里 `target="_blank"` 可能被宿主吞掉 = 死按钮**），
  只接受短白名单（Discord 邀请 + bilibili.com），`dry=1` 只校验不弹浏览器（自检用）。
* 截图新增 `gui_shot_en.png` / `gui_shot_ls.png` / `gui_shot_join.png`；
  自检断言同步扩到 i18n（11 项文案必须都变 + 英文无 CJK + 切回复原）、9 步引导（steps≥9、
  masked≥7、两个新目标在列）、LineSidebar、社区弹窗、open_url 白名单、进度条居中。
* 本轮验收：源码 `SHELL UI SELFTEST: OK`；`tests\regression.py` **21/21 0 失败（189.1 s）**；
  `tests\gui_api_check.py` → `G1 RESULT: OK`；`build_gui.ps1` → GUI minimal **96.6 MB / 12 文件**、
  full **300.9 MB / 13 文件**；`tests\gui_exe_check.py` → **43 项全 PASS / 0 FAIL，`G4 RESULT: OK`**；
  `scripts\check_dist.ps1` → 4 Kit 全 OK。`core/`、`cli/`、`main.py`、`build_srcm.ps1`、
  `build_kit.ps1` 一字节未改。
* 交付件：`README.en.md`（全量英文文档，与 `README.md` 顶部互链）；
  `gui/app.py` 新增 `GET /api/open_url`（外链白名单 + `dry=1`）。

### GUI 第三轮（2026-09-24，全部有断言、可复跑）

* **日志与判据左右并排 + 可拖拽分隔条**：`components/SplitPane.vue`（新）。
  右栏不再上下堆叠：左日志、右 A0~A7，默认 **50/50**，拖动调整、双击回中、
  方向键微调，位置记 `localStorage('cala-split')`。
  判据面板改成"表头/按钮固定 + 中间滚动"（`ResultPanel.vue` 的 `.res-body`），
  条目多时不再被撑出窗口。**自检派发真实 pointerdown/move/up 拖分隔条**，
  断言 pane A 358 → 505 px、复位后回到 50/50（不能只断言"分隔条存在"）。
* **新手引导**：`components/Onboarding.vue` + `styles/uiverse/onboarding.css`（新）。
  六步 `hello.png` → `guide.png`×4 → `end.png`；蒙版是**聚光灯**（目标方框上
  `box-shadow: 0 0 0 9999px` 压暗四周，随窗口缩放重算），指 `#card-inputs` /
  `#card-options` / `#run` / `#split`；`? 引导` 按钮可重看；`cala-onboarded` 记一次。
  自检走完六步并断言：第 1 步 hello 且不聚光、中间四步 guide、末步 end、
  **聚光方框与目标矩形逐坐标吻合（±3px）**、结束即关闭且已记住。
* **卡片动效**：`OPTIONS` 卡片加**锥形渐变彗星沿边框循环**（`@property --uv-a`，
  构建中加速）；判据面板加 **ReactBits BorderGlow**（指针跟随的边框光晕，
  `--gx/--gy` + 掩膜只留 1.6px 边）。ReactBits 那份是 React + framer-motion，
  本项目用**纯 CSS 复刻同一视觉**，不引依赖。
* **进度条 GIF 放大 2 倍**：头部 34 → **68 px**、轨道 12 → 20 px、整条 46 → 80 px。
  自检断言**实测宽度 ≥ 68 px**，不是"我写了 68"。
* **截图取证改成抗遮挡**：`_grab()` 先 `PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)`
  （窗口自己渲染，别人的窗口盖不住），拿不到或整幅单色才回退 `ImageGrab` + topmost。
  返回值带 `[printwindow]` / `[screengrab]` 标记。新增 `logs/gui_shot_layout.png`
  （跑完的完整界面，无弹窗遮挡）。
* **开发文档**：README §5 项目结构（含"改哪个文件"表 + `core/`/`cli/` 禁改清单）、
  §12 开发与调试指南（`--dev` 模式、DevTools、验收顺序、VSCode 插件与配置）；
  新增 `.vscode/{extensions,settings,launch}.json`；`gui/desktop.py --dev`
  （固定 8756 端口 + `vite.config.js` 代理 `/api` + `webview.start(debug=True)`）。
* **文件梳理（待用户确认后才执行）**：`docs/cleanup_plan_20260924.md` +
  `scripts/clean.ps1`（默认 dry-run，`-Apply` 才删；实测可释放 **3.46 GB**）+
  `scripts/check_dist.ps1`（交付 Kit 文件清单校验）。
* 本轮验收：源码 `SHELL UI SELFTEST: OK`；`tests/regression.py` **21/21 0 失败（200 s）**；
  `tests/gui_api_check.py` → `G1 RESULT: OK`；`build_gui.ps1` → exe 39.2 MB、
  GUI minimal **96.2 MB / 12 文件**、full **300.6 MB / 13 文件**；
  `tests/gui_exe_check.py` → `G4 RESULT: OK`。**`core/`、`cli/`、`main.py`、
  `build_srcm.ps1`、`build_kit.ps1` 一字节未改。**

### 已完成（有判据，可复跑）

* **M1** 背景：`srcm\bg\*` → cover/contain 适配 1920×1080 → 自研 BC1 11 级 mip →
  克隆原生壳 + `da-patch namerepl` 改内部身份 → 独立 `UTexture2D` 包
  → `DA_Backgrounds` 只追加（34 B/行，`@30` 原样继承）。
* **M2** 音频：`srcm\{BGM,Sound,Ambient}\*` → WAV 头自检，不合规才调 ffmpeg
  （`-ar 48000 -ac 2 -c:a pcm_s16le`）→ `da-patch sndmk` 造 PCM 流式 SoundWave
  → 修 Zen `BulkDataMap.SerialSize` → `DA_BGM`/`DA_Ambient`/`DA_Sounds` 只追加（28 B/行）。
* **M3** 合并容器 + L5 部署 + 自动回滚 + `build.log` / `build_report.json` + `-DryRun`
  + `-Combined` 累积 + `install.ps1` / `uninstall.ps1` / `README.md`。
* **M4** 双 Kit（**2026-09-23 第三轮瘦身；GUI 轮重打后为 82.6 / 287.0 MB**）：`dist\CalaPlayerSrcmBuilder_minimal_20260923\`
  **82.6 MB**（无 ffmpeg）、`dist\CalaPlayerSrcmBuilder_full_20260923\` **287.0 MB**（含 ffmpeg）；
  自建工具已是 **self-contained 单文件**（da-patch 28.3 MB = trim+R2R、tex-inspect 20.1 MB = trim-only），
  目标机器**不需要 .NET、不需要 Python**。原 118.8 / 323.1 MB。
* 实测：L0~L4 约 14 s（2 图 + 4 音频）；A0~A7 全 PASS；
  沙箱游戏目录上的部署 → `uninstall.ps1` 回滚 → 再次 `install.ps1` 哈希完全复原；
  故障注入（坏图 / 缺 ffmpeg 的 MP3）均在 L1 停住且**未碰游戏目录**。
* **回归套件 `tests\regression.py`：21 个场景全 PASS（约 3 min）**，走**出厂 exe** +
  沙箱游戏目录 + **真实游戏目录守护**（跑前跑后比对 `_P` 三件套哈希）。
  覆盖：全量 dry-run、部署+读回+回滚、只有背景/只有音频（另一类判据 skipped）、
  `-Fit contain` 黑边、坏图、空素材夹、MP3 无 ffmpeg 中文提示、bg 限额、PSNR 门、
  `-Force` 越过限额与画质门、`-Combined` 累积、T14 容器被占用（游戏在跑）被拒且沙箱零改动、
  T15 全程无 ffmpeg（极简版承诺）、T16 全量版用自带 ffmpeg、T17 `-Kit` 覆盖生效、
  T18 有 ffmpeg 时 MP3 确实转码、T19 `-Ffmpeg <path>` 生效、
  **T20 `-Combined` 但无历史会明确提示 `nothing to carry`、T21 一次失败的 `-Combined` 不会吃掉上一轮累积状态**。
  开关：`--exe`、`--kit`、`--only`、`--list`、`--real-game`、**`--stress`**（只跑满额规模：
  50 图 + 600 s 音频）。
* **满额规模实测（`--stress`）**：耗时 **145 s**、容器 `ucas` **170.1 MB**、峰值临时磁盘
  **约 1.5 GB**（都在 `out_patch`）、`DA_Backgrounds` 165→215、50 张图 PSNR 41.5~43.1 dB、
  A0~A7 全 PASS。⇒ 用户跑满额素材前，确保 `<srcm 上级>` 盘有 ≥2 GB 空闲。
* **对真实游戏目录的只读 dry-run 已验过**：13.5 s、A0~A7 全 PASS、真实目录 8 个文件哈希逐个未变
  ⇒ "把 858 MB 的 `ucas` 硬链接进 work"不会写穿原件。
* 状态一致性（2026-09-23 第六轮）：`-Combined` 的累积状态 = `out_patch\work\manifest.json` + 同目录 legacy 树；运行结束时**只有当本轮真的产出了 manifest 才清掉上一轮状态**，否则把上一轮状态还原回 `work\`（否则一次失败会让累积成果凭空消失）。
* **真机验收（2026-09-23 21:16，用户自己跑）**：四个下拉（bg/BGM/Ambient/Sound）末尾都有新条目、大预览/PLAY 正常、音频出声 —— **用户回报 PASS**；他那轮 A0~A7 全 PASS、17.56 s、8 包/9 chunks。真实游戏目录现在装的就是他那个容器（`_P.ucas 4E42212B3137CEA8`）。
* **GUI G0（完成）**：`gui/` 骨架（tasks.py / app.py / desktop.py / dist 占位页）+ gui_main.py；依赖 fastapi 0.141.1 / uvicorn 0.53.0 / pywebview 6.2.1 + pythonnet 3.1.0 + WebView2 153.0.4234.48。自检 `python gui\desktop.py --selftest` -> `G0 SELFTEST: WINDOW OK`（真窗口打开 + 页面从 FastAPI 加载 + 页面自己带令牌 fetch 到 `/api/health`；无令牌 403）。
* **GUI G1（完成）**：`python tests\gui_api_check.py` -> `G1 RESULT: OK`（18 项）：令牌 403、走 HTTP 跑 dry-run 并收到实时日志与 L0~L5 阶段事件、**与 CLI 的判据逐项一致（门/DA 行数/素材清单）**、真部署后 `POST /api/uninstall` 回滚到部署前、取消能在 L5 之前停下、真机目录不动。**取消的实现不改 core**：`CancelableLog(Log)` 覆写 `__call__/raw`，记完日志再查取消并抛 `BuildCanceled`，`stage=="L5"` 时永久关闭检查。
* **GUI G2（完成）**：`gui/frontend/`（Vue 3 + Vite）→ `gui/dist`；界面 = 左表单（Paks / Srcm / Fit / DryRun·Combined·Force / 进阶 ffmpeg·Kit）+ 右实时日志（QUALITY/GATE/AUDIO/ERR 高亮、自动滚底、跳最新）+ A0~A7 判据面板 + 部署状态 + 「打开输出目录」「回滚」。**主题**：`bg_light.jpg`/`bg_dark.jpg` 两层全屏背景交叉淡入（620 ms），右上角 Uiverse 风格滑动开关切换并记 localStorage；亮色**不加暗幕**、用强对比深色字，暗色才加暗幕。Uiverse 组件是我按它的风格手写并存于 `src/styles/uiverse/*.css`，统一 `.uv-scope` 前缀隔离。
  证据：`python gui\desktop.py --selftest --selftest-ui` → `G2 SELFTEST: OK`（窗口加载 / Vue 挂载 / 页面读到 `/api/health` / 令牌守卫 / 亮暗两层确实分别指向 `bg_light.jpg` 与 `bg_dark.jpg` 且随主题互换 / **从页面里填表点「开始打包」，跑完 198 行日志且 A0~A7 全 True**）。页面暴露 `window.__cala.{setParams,run,cancel,state,toggleTheme}` 供自动化驱动。前端构建：`cd gui\frontend && npm.cmd install && npm.cmd run build`。
* **GUI G3（完成）**：桌面壳 + 原生目录对话框实测。**抓到一个真 bug**：pywebview 6 把模块级 `FOLDER_DIALOG` 常量改成了**弃用的函数**，`create_file_dialog(webview.FOLDER_DIALOG)` 会让它走进 `except` 吞掉异常并立刻返回 `None` ⇒ 点「浏览…」什么都不发生，且**与"用户取消"无法区分**（静默失败）。修法：用 `webview.FileDialog.FOLDER`；并给它一个**真实起始目录**（pywebview 自己的兜底是 `os.environ['HOMEPATH']`，在 Windows 上**没有盘符**，例如 `\Users\me`，会让对话框立刻返回）；再把 pywebview 的日志抓出来，有异常就 500 而不是假取消。**日志器名字是 `pywebview` 不是 `webview`**。另有自检脚本自身的坑：`_send_escape` 忘了初始等待 ⇒ ESC 在 t≈0 就发出去，把"没弹出"和"弹出后被立刻关掉"混为一谈；改成**按窗口类 `#32770` 精确定位对话框窗口**再 `WM_CLOSE`，这样还多一条硬证据。
  证据：`python gui\desktop.py --selftest --selftest-shell` → `SHELL SELFTEST: OK`（布局三档都两栏、左 400px、日志 360~560px；`dialog window: appeared=True after=0.46s`；`folder dialog: ok=True path=None after=1.79s`）。
  界面侧同步：对话框从输入框现有路径打开；失败会把原因显示在界面上（不再静默）。
* 安全加固（2026-09-23 第二轮）：L0 只读探测已装 `_P` 是否被锁（游戏在跑）→ 警告；
  L5 在**碰任何文件之前**硬拒绝并给中文提示；回滚只删"哈希等于我们自己产物"的文件。

* **GUI G4（完成）**：`build_gui.ps1` 打两个变体 —— `dist\CalaPlayerSrcmBuilder_gui_minimal_20260923\`
  **94.9 MB / 12 文件**、`dist\CalaPlayerSrcmBuilder_gui_full_20260923\` **299.2 MB / 13 文件**，
  exe 名 `CalaPlayerSrcmBuilderGUI.exe`（37.8 MB），`gui/dist` 随包（已拍板）。
  验证 `python tests\gui_exe_check.py` → `G4 RESULT: OK`，三项检查：
  ① **双击**（用 `ShellExecuteW` 复刻资源管理器：不传 std 句柄）出真窗口 + 会应答 `WM_NULL` +
  **绝不弹 PyInstaller 模态崩溃框**；② **无控制台启动** `--headless`（uvicorn 必须在
  `sys.stdout is None` 下也能配好日志）；③ 冻结 exe 的 `--selftest --selftest-ui --selftest-shell`
  （rc=0、`ui driven ok=True`、**A0~A7 全 True**、原生对话框 `appeared=True after=0.46s`）。
  **本轮抓到两个"只在打包后出现"的真 bug，源码模式全绿也照样中招**（成因/修法见 README §10.5）：
  ① `--windowed` exe 由资源管理器双击时 `sys.stdout/stderr is None`，`uvicorn` 的日志 formatter
  调 `sys.stdout.isatty()` → `AttributeError` → `Unable to configure formatter 'default'`
  ⇒ **uvicorn 根本起不来，界面永远不出现**，只剩一个模态崩溃框（用 `subprocess` 启动会继承
  有效句柄，恰好把它藏住 —— 第一版双击检查就是这么被骗过去的）。
  修：`gui/app.py::ensure_std_streams()`（给缺失的流装 `isatty()==False` 的哑流），
  在 `start_server_thread()/run_server()` 和桌面壳 `main()` 开头各调一次。
  ② **没有控制台时 .NET 用 ANSI 代码页写 stdout**（有控制台写 UTF-8），而 `core/common.py`
  一直按 UTF-8 解码 ⇒ `自定义名`（GBK `D7 D4 B6 A8 D2 E5 C3 FB`）被解成 `\ufffd\u0536\ufffd…`，
  **A7 直接把构建判失败**。修：`tools-src/{da-patch,tex-inspect}/Program.cs` 开头
  `ForceUtf8Stdio()`（`Console.OutputEncoding` + UTF-8 `StreamWriter` 接管标准流），
  重新 `dotnet publish`（**带 `--no-restore`**，否则 `Version="*"` 会浮到新 UAssetAPI）→
  重跑 `build_kit.ps1` + `build_gui.ps1`。**这个修法同时保护了"CLI 被无控制台宿主
  （计划任务/服务/`CREATE_NO_WINDOW`）拉起"的场景。**
* **GUI G5（完成，回归收口）**：出厂 CLI exe **21 场景 0 失败（197 s）**（T16/T17 两个条件场景
  另用全量 Kit 补跑：`--kit <full kit>` 跑 T17、`--exe <full exe>` 跑 T15/T16，均 PASS）；
  `tests\gui_api_check.py` → `G1 RESULT: OK`（18 项，**API 与 CLI 判据逐项一致**）；
  源码模式 `python gui\desktop.py --selftest --selftest-ui --selftest-shell` → `SHELL UI SELFTEST: OK`；
  `tests\gui_exe_check.py` → `G4 RESULT: OK`。真实游戏目录 `_P.ucas 4E42212B3137CEA8` 全程未变。
  重打包后体积：CLI minimal **82.6 MB** / full **287.0 MB**（CLI exe 24.7→25.6 MB，PyInstaller 重打）；
  GUI minimal **94.9 MB** / full **299.2 MB**。

### 未做 / 待用户拍板

1. **等用户确认 `docs/cleanup_plan_20260924.md`**（≈3.46 GB，`scripts\clean.ps1 -Apply` 执行；
   `tests\mat` 必须最后删，`gui_exe_check.py` 需要它，回归会重建）。
2. **GUI 画面等用户再看一次**（若他给 Uiverse / ReactBits 具体条目，就用 `.uv-scope` 包上替换）。
3. 背景缩略图修正（新建 `MI_BackgroundPreview_User_BG_0X` + ImportMap 末尾追加 import）——
   v1 明确**不做**（用户拍板：接受缩略图不对，绝不为缩略图引入崩溃风险）。
4. 真机验收：用户需把 `out_patch` 装进**真实**游戏目录试听/试看（目前只跑过沙箱 fakegame）。
5. OGG/Vorbis 压缩音频路线（体积降到 PCM 的 ~1/10）——后续可探索，v1 不做。

## 开工规则（沿用上游工程，且已被本项目实测验证）

1. **分析与执行要快**：根因确定 + 既有机制上的增量 ⇒ 一轮交齐「结论 + 方案 + 产物」；
   **新建工具 / 架构级**（如 GUI 改造）⇒ **先出只读设计方案**等拍板，不先写代码。
2. **高风险改动分阶段**：新内容一律**独立成新包**、只改游戏目录里的 `_P` 容器、
   写前备份、写后立刻从真实目录读回验证、失败自动还原。
3. **判据不放松**：图像必须打 `QUALITY: PSNR=… MAE=… 清晰度比=…`；音频必须
   `--audio-out` 逐字节一致；容器必须做 chunk id 台账（新包 0 命中）。
4. **失败也要收口**：报清楚是哪个阶段、哪个对象、哪个命令、返回码与 stderr 尾部，
   不接受笼统 FAIL。
5. **绝不**：手搓 BINKA；写 `Binaries\Win64`；改任何原生容器/资产；
   把观察到相关性当不变式去"维护"（`DA_Backgrounds` 的 `@30` 就是这么崩的）。

## 已验证原语与硬事实（不要重新试错）

| 事实 | 数值 / 结论 |
|---|---|
| 补丁容器名 | `<Game>-Windows_P.{pak,ucas,utoc}`，mount `../../../`，无 scriptobjects.bin |
| 背景壳 | `/Game/CalaPlayer/Backgrounds/T_Evni_Background_01_O`，uexp **1,383,410 B**，11 级 mip |
| 纹理 uexp 布局 | 头部 **110 B**（`@50`=DataSize，`@90`=`PF_DXT1`，`@102`=MipCount）；mip0 紧跟头部；**mip1..10 每级前 16 B**；尾部 28 B |
| 纹理 mip 尺寸 | 1036800 / 259200 / 65280 / 16320 / 4080 / 1080 / 256 / 64 / 16 / 8 / 8 |
| 音频壳 | `/Game/CalaPlayer/SFX/Ambient/LS_BP3_Rain__SFX_`，uasset 859 / uexp 150 / ubulk 351086 |
| 音频 uexp 布局 | 属性 `NumChannels@0x06` `SampleRate@0x0A` `Duration@0x0E(f32)` `TotalSamples@0x12(f32)`；`len(uexp) = 82 + 负载` |
| Zen BulkDataMap | 4 字节 = 表索引；legacy uasset 尾部按 `[SerialOffset=0x46][CookedIndex=-1][SerialSize=28]` 三元组唯一定位 `SerialSize` |
| DA_Backgrounds | uexp = `[12 B 头][N×34 B][12 B trailer]`，行数在 `u32@8`，原生 **165** 行 |
| 音频三表 | uexp = `[10 B 头][N×28 B][12 B trailer]`，行数在 `u32@6`，原生 **100 / 19 / 111** 行 |
| 12 B trailer | `ff ff ff ff 00 00 00 00 c1 83 2a 9e` |
| `da-patch addname` | `AddNameReference` **会去重**（同名重复调用返回原 index、产物字节一致）；**支持非 ASCII** |
| **无控制台的编码陷阱** | `da-patch`/`tex-inspect` 是 .NET：**有控制台时 stdout 写 UTF-8，没有控制台时退到 ANSI 代码页（本机 GBK）**。`core/common.py` 永远按 UTF-8 解 → 无控制台宿主（`--windowed` exe / 计划任务 / 服务）里非 ASCII 名字会变成 `\ufffd` 并让 A7 失败。两个工具已加 `ForceUtf8Stdio()` 修掉；**改工具后必须重跑 `build_kit.ps1` + `build_gui.ps1`**（Kit 是拷贝，不重打包就还是旧的 exe）。 |
| **打包后才出现的启动坑** | `--windowed` PyInstaller exe 由**资源管理器双击**时 `sys.stdout/stderr is None`（用 `subprocess` 启动会继承有效句柄，**看起来一切正常**）。任何在启动期调 `.isatty()` 的库都会炸 —— uvicorn 的日志 formatter 就是；表现是模态 `Unhandled exception in script` 框 + 界面永不出现。`gui/app.py::ensure_std_streams()` 修掉。**验证必须用 `ShellExecuteW`**（= 双击），不能用 `subprocess`。 |
| **子进程黑框（无控制台宿主）** | 没有控制台的 GUI 进程 spawn 任何 console 子程序，Windows 都会给它一个新控制台窗口（一次 50 图构建会调 da-patch 200+ 次）。`gui/no_window.py` patch `Popen.__init__` 加 `CREATE_NO_WINDOW`（`subprocess.run/call/check_output` 全部经过它）。**验证方法别用窗口枚举**：本机 Windows 11 的控制台由 Windows Terminal 承载，`ConsoleWindowClass` 一个都数不到（阳性对照当场证明这个方法是瞎的）；正确做法 = `AttachConsole(child_pid)` 后 `GetConsoleWindow()`（`kernel32`，不是 `user32`），**判据必须有阳性对照**（摘掉补丁时该拿到非 0 HWND）。 |
| **`say()` 里的 `print()` 会杀进程** | 控制台/重定向 stdout 在本机是 GBK，任何 GBK 编不出的字符（如 U+FFFD）会让 `print` 抛 `UnicodeEncodeError`，而 `say()` 是每个阶段的日志出口 ⇒ 直接崩。`say()` 的 print 现在 try/except 兜住；**读别人写出的日志文件也要先试 UTF-8、可疑时回退 ANSI**（`tests/gui_exe_check.py::_decode`），并且检查脚本自己要 `sys.stdout.reconfigure(encoding='utf-8')`。 |
| **结果弹窗"自己消失"** | 模态框点背景关闭（`@click.self`）会**被宿主消息泵里的合成点击触发**（pywebview 等 JS 返回时会 pump Windows 消息）⇒ 弹窗闪一下就没了、自动化判据随机失败。修法：只认真实点击（`e.isTrusted`），并在组件里留一条 `window.__calaModalTrace` 面包屑（没有它根本查不出是谁关的）。**测试断言要取"第一次看见"而不是"稳定 3 秒后仍在"**：这个窗口就开在用户桌面上，用户随手一点是合法行为。 |
| **截图被别的窗口盖住（追不到头）** | `ImageGrab` 抄的是合成后的屏幕。`SetForegroundWindow` 会被前台锁拒；先 topmost 再取消也**输给一个自己反复抬升的窗口**（本轮连续三张都拍到用户的 QQ）。正解 = `PrintWindow(hwnd, memDC, **2**)`（`PW_RENDERFULLCONTENT`，专为 DirectComposition 窗口加的）让**窗口自己渲染**，再 `GetDIBits` 取像素；失败/整幅单色才回退 ImageGrab。判据是返回值里的 `[printwindow]` / `[screengrab]` 标记。**通用教训：要"看到某个窗口的内容"，就别去争 z 序，直接问那个窗口要它自己的像素。** |
| **WebView2 会重启 CSS 关键帧动画** | 入场动画写成 `animation: xxx .36s ... both` 时，**合成器恢复（窗口被置顶/还原、抢焦点）会把关键帧动画从头播一遍** ⇒ 元素瞬间掉回起始态。本轮引导卡片因此出现 `opacity:0.048`（截图里卡片"消失了一下"，自动化采样偶发失败）。修法：入场/退场改成 **transition + 一个 `.ready` 类**（过渡只在值真变化时跑，重启不会回到起始态），只需要"挂载在起始态、下一帧翻到终态"这一个空档。 |
| **跨进程 `evaluate_js` 比动画还慢** | 想判定"这段动画真的播过"，**不要在 Python 侧 sleep 后再读**：`evaluate_js` 的往返（+ 主线程消息泵）经常比动画本身还长，读到的永远是终态。正解 = **把触发和采样放在同一次 JS 调用里**（`setTimeout(snap, k*60)` 采一串样本存到 `window.__calaXxx`，之后一次性取回）。本轮乱码波纹、squish 弹簧峰值、分隔条拖动都是这么测的；用 sleep 的写法最初把"波纹从未运行"误判成"读晚了"。 |
| **Vue 里忘 import 会被静默吞掉** | `ScrambleText.vue` 用了 `nextTick` 却忘了 import：异步 watcher 里抛的 `ReferenceError` 被 Vue 的错误处理吃掉，**界面表现完全正常**（文案照样切换），只有动画从未运行 —— 因此"切换后文案正确"这类断言全绿。**新增组件时先核一遍用到的 Vue API 是否都在 import 里**（编译器不会替你查），并且给"动画/过渡"单独写时间序列判据。 |
| **组件内部别用 `.left` / `.right` 这类通用类名** | `SquishSwitch` 的两个标签用了 `.uv-ss-face.left`，于是 `document.querySelector('.left')` 命中的是它、不是 `.grid > .col.left`，布局探针里左栏宽度突然变成 28px。**同类错误第二轮**：`App.vue` 给页头按钮组写的 `.right` 规则也命中了工作区右列（`<section class="col right">`），把 `align-items:center` + `flex-wrap:wrap` 带了进去 ⇒ 右列里的 SplitPane 变成 shrink-to-fit 且居中、宽度不随窗口增长（小窗口"右侧不适配"就是这个）。**规矩：一个类名只归一个元素用**（页头那组现在叫 `.bar-right`）；探针选择器也尽量写成语义化的后代选择器（`.grid > .col.left`）。 |
| **flex 的 `align-items:center` 会让子元素不再拉伸** | 这正是上面那个 bug 的机制层：一列（`flex-direction:column`）只要被加了 `align-items:center`，子元素就退化成 shrink-to-fit，"填满整栏"的假设全部失效 —— 而**居中 + 溢出**还会变成左右各溢出一半（`justify-content:center` 同理）。判断"某元素是否填满父容器"时，不要只看它的内容，直接断言 `子宽 == 父宽`。 |
| **WebView2 里 `target="_blank"` / `navigator.clipboard` 都可能是死按钮** | 往社区链接（Discord / GitHub / B 站）点下去，宿主完全可以把 new-window 请求吞掉；`navigator.clipboard.writeText` 在 WebView2 里要安全上下文 **且**要有用户手势，缺一个就**静默失败**。两者表现都和"按钮坏了"一模一样。改法：外链交给后端 `GET /api/open_url` → `webbrowser.open`（**只接受一份短白名单**，否则这就是"本地能打开任意东西"的原语）；剪贴板交给 `GET /api/copy`（后端 Win32 写）。都加 `dry=1` 只校验不真做，好让自检能测而不弹浏览器/不动用户剪贴板；剪贴板自检还要**先存用户原有内容、测完写回**。**通用做法：凡是"点了没反应"的外部动作，先怀疑被宿主吞了，再给它一条可判定的替代路径。** |

| **Vue 函数式模板 ref 会累积** | `:ref="setItem"` 这种函数式 ref 在每次重渲染都被调用一遍；我原来写成 `if(el) list.push(el)` 会在几轮更新后让同一个元素进列表多次。这个组件里的 ref 只用来量几何，所以最省事最稳的做法是**别收 ref，直接 `ul.children` 查 DOM**。 |
| **`.ps1` 里不能写中文（无 BOM 时）** | Windows PowerShell 5.1 读**没有 BOM** 的 `.ps1` 是按 ANSI（本机 GBK）解析的：UTF-8 中文字节会被当乱码，**直接把脚本解析崩掉**（`Unexpected token`）。所以 `build_*.ps1` 头部都写着 "ASCII only"，`scripts\*.ps1` 也遵守（中文说明放 `docs\`）。另一种做法是写 UTF-8 BOM，但很容易被后续编辑抹掉 ⇒ 统一 ASCII。 |
| **`kill` 别名压过同名函数** | PowerShell 的**命令解析顺序是 别名 > 函数 > cmdlet**：我写了个 `function Kill($rel,$why)`，调用时命中的却是内建别名 `kill`（= `Stop-Process`），报 `Cannot convert "_probe" to System.Diagnostics.Process`。**自定义函数别用内建别名同名**（`kill`/`ls`/`cd`/`rm`/`mv`…）。 |
| **测试脚本删日志要先杀进程** | `gui_exe_check.py` 第 3 项在"删 exe 的 `--log-file`"时踩到 `WinError 32 另一个程序正在使用此文件`：Windows 上句柄要等进程真的退出才释放，而它先删文件再杀进程（**顺序反了**），时序一变就崩。修法：**先 `taskkill` 再删**，且删除带重试。判据脚本自己的健壮性和被测代码一样重要。 |
| **vite build 会清空 `gui/dist`** | `vite.config.js` 里 `emptyOutDir: true`，所以**丢进 `gui/dist` 的素材会被下一次 build 抹掉**。素材要么放 `gui/frontend/public/`，要么让 `build_gui.ps1` 第一步把它从 `gui/dist` 搬进 `public/`（新增 hello/guide/end 三张就加进了那个数组）。 |
| **自动跟随日志不能只听"新行"** | 跑完后判据面板长高会把日志挤出底部视野，用户以为日志"卡住了"。`LogView.vue` 用 `ResizeObserver`：贴底状态下盒子尺寸变化也要重新贴底。截图取证时先把窗口 `SetForegroundWindow` 提到前台，否则 `ImageGrab` 抓到的是盖在上面的别人窗口（本轮第一次就抓到了用户的 VS Code）。 |
| **`localStorage` 在"每次换端口"的页面里等于没有** | 页面从 `http://127.0.0.1:<随机端口>/` 加载（端口随机是为了别的本机程序猜不到），而 WebView2 的 `localStorage` **按 origin（scheme+host+**port**）分桶** ⇒ 每次启动都是空桶。表现是"引导每次打开都弹""语言/主题/分隔条记不住"，而代码看起来完全正确。**要跨启动记东西就得落在文件里**（本轮 = `gui/prefs.py` + `/api/prefs` + `%LOCALAPPDATA%`），并**在 mount 之前**拉一次让首帧就能用；localStorage 只当 dev/浏览器回退。 | 
| **`<Teleport>` 出去的节点不再继承祖先的 CSS 自定义属性** | `GlideSelect` 的 `--gs-*` 都写在 `.uv-gs` 根上，弹出层 teleport 到 `<body>` 后拿不到 ⇒ `height: var(--gs-row)` 变成 `auto`，行高与 JS 算的步高不一致（"pill 滑到第 N 行"与"点在第 N 行"对不上，点到上一行）。**teleport 的组件要把变量补挂在被传送的节点上**；判据用 `document.elementFromPoint(坐标)` 直接问"这里画的是谁"。 |
| **组件自己写死的 `white-space` 会盖掉继承** | `ScrambleText` 内部是 `white-space: pre-wrap`（乱码字形不能重排行），于是外层 `.lab b { white-space: nowrap }` **完全无效**、标签照旧折行。**改"不折行"之前先确认没有子组件自己声明了 white-space**（本轮给该组件加了 `nowrap` 开关）；另外 nowrap 之后要**顺手断言没被省略号截断**（`scrollWidth <= clientWidth+1`），否则只是把"折行"换成"截断"。 |
| **`scrollIntoView` 会滚 `overflow:hidden` 的祖先** | `overflow:hidden` 的元素**可以被程序滚动**（只是没有滚动条）。引导的聚光为了把目标拉进视口而 `scrollIntoView`，若目标在 `overflow:hidden` 的右栏里，右栏会被永久推偏。修法：自己找**真正可滚动**的祖先（`overflow-y` ∈ auto/scroll **且** `scrollHeight > clientHeight`）再改它的 `scrollTop`。 |
| **`_ensure_working_dir()` 之后 `sys.argv[0]` 不能再是相对路径** | pywebview 的 `base_uri()` 是 `load_html()` 的**默认参数**（＝import 时求值），它取 `os.path.realpath(sys.argv[0])` 的目录。`desktop.py` 会 `chdir` 到 `%LOCALAPPDATA%`，所以用 `python gui\desktop.py` 启动时它算成 `...\CalaPlayerSrcmBuilder\gui`（不存在）⇒ `ValueError: Path ... does not exist`，窗口根本建不起来。修法：`main()` 一进门就 `sys.argv[0] = os.path.abspath(sys.argv[0])`（命令行自检/开发都用得上）。 |
| **判"鼠标邻近"类动效时，真鼠标会来抢** | LineSidebar 的 `--effect` 由 `pointermove` 决定，而**用户真实的鼠标只要在这段时间里划过窗口**，就会按真实坐标重设目标（离开还会 `pointerleave` 清零）⇒ 0.9s 后再读可能读到 0，被误判成"动效坏了"。修法：**读数前再补一次同坐标 poke，短延时后立刻采样**（仍然在测同一个机制，只是不再测用户的手）。 | 

| 引擎路径 | `tex-inspect` 既能吃 `/Game/...` 也能吃 `CalaPlayer/Content/...`；`retoc to-legacy -f` 是**子串**匹配（`-f DA_BGM` 会带上 `PDA_BGMs`，必须白名单拷贝） |
| GATES 里的一处笔误 | 上游 `dist/pak_patch_audio3_20260923/verify/GATES.txt` 把 BGM/Ambient 的 chunk id 标反了：实测 `/Game/CalaPlayer/BGM/User_BGM_01` → `ae10268c1830921d`，`/Game/CalaPlayer/SFX/Ambient/User_Ambient_01` → `cc398fbed1b71bb4`（容器本身正确，仅标注错误） |

## 环境

* Python：`python\Scripts\python.exe`（venv，numpy 2.5.3 / pillow 12.3.0 / pyinstaller 6.22.3）
* 工具：`kit\retoc\retoc.exe`（cwd 需含 `oo2core_9_win64.dll`）、
  `kit\da-patch\da-patch.exe`、`kit\tex-inspect\tex-inspect.exe`（+ `native\`）、
  `kit\mappings\CalaPlayer-UE5.7.usmap`
* 本机 `pwsh` 是 **Windows PowerShell 5.1 语义**；`>` 写 UTF-16；控制台 GBK；
  **变量名大小写不敏感**（本轮又踩一次：`$DA` 与 `$da` 互相覆盖）。
* ffmpeg：`C:\Program Files\ffmpeg\bin\ffmpeg.exe`（**不硬编码**，走探测 + `-Ffmpeg`）。
* `Select-Object -First N` 会**提前关掉管道**杀掉还在跑的原生进程 → 跑工具时用 `-Last N`。

## 下一步第一条命令

```powershell
# 全量回归（改任何东西之后都要跑；21 场景 / 约 200 s / 走出厂 exe）
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\run_regression.ps1

# GUI 三条（API / 桌面壳 / 出厂 exe）
python tests\gui_api_check.py
python gui\desktop.py --selftest --selftest-ui --selftest-shell --log-file logs\self.txt
python tests\gui_exe_check.py --keep-log

# 界面自检还会截图，肉眼复核用：
#   logs\gui_shot_guide.png（新手引导，9 步）/ gui_shot_layout.png（跑完的界面）/
#   gui_shot_ok.png / gui_shot_fail.png（成功/失败弹窗）/ gui_shot_en.png（英文界面）/
#   gui_shot_ls.png（Line Sidebar 动效）/ gui_shot_join.png（社区 hub）/
#   gui_shot_scramble.png（乱码解码中）/ gui_shot_squish.png（旋钮行进中）/
#   gui_shot_glide.png（Glide Select 打开）/ gui_shot_star.png / gui_shot_qq.png /
#   gui_shot_second.png（第二次启动：引导不再自动弹）/ gui_shot_join_hover.png（社区四宫格悬浮）/
#   gui_shot_layout_min.png（最小窗口 960x620 下的整体布局）

# 交付件清单校验（防止多余文件混进 dist）
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_dist.ps1

# 开发模式（改界面用）：后端固定 8756 + vite 代理 /api + WebView2 DevTools
python gui_main.py --dev          # 另开一个终端：cd gui\frontend; npm.cmd run dev

# 重新打包（改了 gui/ 或 tools-src/ 里的 C# 之后）
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_kit.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_gui.ps1

# 打一次真机补丁（先 dry-run）
& .\dist\CalaPlayerSrcmBuilder_minimal_20260923\CalaPlayerSrcmBuilder.exe `
    -Paks .\tests\fakegame -Srcm .\tests\mat\demo -DryRun
```

## 测试钩子（只为回归服务，正常使用不要设）

| 环境变量 | 作用 |
|---|---|
| `CALA_MAX_BG` | 覆盖 bg 张数上限（默认 50），用 3 张小图即可测 `-Force` |
| `CALA_MAX_AUDIO_SECONDS` | 覆盖音频总时长上限（默认 600 s） |
| `CALA_MIN_PSNR` | 覆盖画质门（默认 25 dB），设 99 即可测到该门被触发 |
| `CALA_NO_FFMPEG=1` | 假装本机没装 ffmpeg，用来测中文提示路径 |
| `CALA_KIT` / `CALA_FFMPEG` | 覆盖工具/ffmpeg 路径 |

`out_patch/work/manifest.json` 是**唯一**跨轮次状态（`-Combined` 靠它知道上一轮有哪些素材），
与 work 树同生共死；不要手工删改。
