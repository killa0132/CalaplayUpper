// ==========================================================================
// Tiny i18n layer.
//
//   * Two dictionaries, zh + en, one flat key space ("area.thing").
//   * `lang` is a ref, so any template that calls t() re-renders the moment it
//     changes -- no page reload, no event bus.
//   * First run picks the language from the system locale (zh* -> Chinese,
//     anything else -> English) and remembers the user's choice after that.
//
// Strings that come from the FROZEN core (build log lines, gate details, build
// errors) are NOT translated: they are emitted by core/builder.py and a
// translation table for them would rot the moment the pipeline adds a message.
// ==========================================================================
import { ref } from 'vue'
import { get as getPref, set as setPref } from './prefs.js'

const KEY = 'cala-lang'

export const LANGS = ['zh', 'en']

export const DICT = {
  zh: {
    'lang.name': '中文',
    'lang.switch': '切换语言',

    'app.connected': '已连接本地服务',
    'app.noToken': '缺少令牌',
    'app.preparing': '准备中…',
    'app.notStarted': '尚未开始',
    'app.guide': '引导',
    'app.guideTitle': '再看一遍新手引导',
    'app.join': '加入我们',
    'app.joinTitle': '加入我们喵',
    'app.themeDark': '暗色背景',
    'app.themeLight': '亮色背景',

    'inputs.title': '素材与游戏 / inputs',
    'inputs.paks': '游戏 Paks 目录（或游戏根目录）',
    'inputs.srcm': '素材根目录（里面有 bg / BGM / Sound / Ambient）',
    'inputs.browse': '浏览…',

    'run.start': '开始打包',
    'run.running': '打包中…',
    'run.cancel': '取消',
    'run.needPaths': '请先填游戏 Paks 目录与素材根目录。',
    'run.startFailed': '启动失败：',
    'run.reportFailed': '取报告失败：',
    'run.openFailed': '打开目录失败：',
    'run.rollbackFailed': '回滚失败：',
    'run.done': '[gui] 完成：',
    'run.failed': '[gui] 失败：',
    'run.dialogFailed': '打开目录对话框失败：',
    'run.dialogNoPath': '对话框没有返回路径：',

    'opts.title': '选项 / options',
    'opts.fit': '背景适配',
    'opts.fitCover': 'cover —— 填满裁边（默认）',
    'opts.fitContain': 'contain —— 完整留黑边',
    // the trigger shows the short form (the explanation lives in the menu) --
    // the left column is only 330 px wide at the minimum window size
    'opts.fitCoverShort': 'cover',
    'opts.fitContainShort': 'contain',
    'opts.dryRun': 'DryRun',
    'opts.dryRunHint': '只跑到 L4 出容器与判据，绝不碰游戏目录',
    'opts.combined': '-Combined',
    'opts.combinedHint': '在上一次 out_patch 成果之上累积',
    'opts.force': '-Force',
    'opts.forceHint': '越过限额（bg ≤ 59、音频 ≤ 10 min、PSNR ≥ 25 dB）',
    'opts.noAtlas': '-NoAtlas',
    'opts.noAtlasHint': '不做图集追加（回到旧行为：下拉缩略图更锐，但时间轴与右侧预览块不显示你的图）',
    'opts.adv': '进阶（ffmpeg / 工具目录）',
    'opts.advHint': '手动指定 ffmpeg 路径、自定义工具目录，以及更细的构建参数',
    'opts.ffmpegPh': '留空 = 自动探测',
    'opts.kitPh': '留空 = 自动找 kit/',

    'log.empty': '打包日志会实时出现在这里 —— 点「开始打包」开始。',
    'log.jump': '↓ 跳到最新',
    'log.split': '拖动可调整日志与判据两边的宽度',

    'gates.title': '判据 / gates',
    'gates.allPass': 'ALL PASS',
    'gates.failed': 'FAILED',
    'gates.deployed': '已部署',
    'gates.notDeployed': '未部署',
    'gates.none': '还没有结果。跑完一次就会显示 A0~A7 判据与部署状态。',
    'gates.daRows': 'DA 行数：',
    'gates.materials': '素材：',
    'gates.materialsUnit': ' 个',
    'gates.container': '容器：',
    'gates.seconds': '耗时：',
    'gates.openOut': '打开输出目录',
    'gates.rollback': '回滚（uninstall.ps1）',

    'prog.idle': '待机',
    'prog.packing': '正在打包',
    'prog.done': '打包完成',
    'prog.failed': '打包失败',

    'modal.okTitle': '转换成功喵',
    'modal.okDry': '容器与 A0~A7 判据都通过了（这次是 DryRun，没有写游戏目录）。',
    'modal.okDeployed': '已经装进游戏目录，A0~A7 全 PASS。可以进游戏看效果了喵。',
    'modal.failTitle': '洗大锅...出错了喵...',
    'modal.failSub': '这一轮没有产出可用的容器。下面是报错；要发给开发者就点「导出错误日志」。',
    'modal.export': '导出错误日志',
    'modal.exporting': '导出中…',
    'modal.exported': '已导出：',
    'modal.exportEmpty': '暂无日志可导出',
    'modal.exportCancelled': '已取消导出',
    'modal.exportFailed': '导出失败',
    'modal.exportFailedWhy': '导出失败：',
    'modal.yay': '好耶',
    'modal.close': '关闭',

    'ob.skip': '跳过引导',
    'ob.prev': '上一步',
    'ob.next': '下一步',
    'ob.start': '开始使用',
    'ob.welcomeKicker': '欢迎',
    'ob.welcomeTitle': '喵~ 欢迎来到打包工坊！',
    'ob.welcomeText': '两分钟就能把自己的<b>图片和声音</b>装进 CalaPlayer。<br>'
      + '这个工具只做一件事：把你给的东西打包成一份<b>只追加、不覆盖</b>的补丁，'
      + '随时可以一键回滚，原生资源一个字节都不会被动到。',
    'ob.pathKicker': '第 1 步 · 告诉它路怎么走',
    'ob.pathTitle': '两块路径，一次填好',
    'ob.pathText': '上面填<b>游戏目录</b>（游戏根目录 / Content / Paks 都可以，工具自己找），<br>'
      + '下面填<b>素材根目录</b> —— 里面放 <code>bg</code> / <code>BGM</code> / '
      + '<code>Sound</code> / <code>Ambient</code> 四个文件夹，缺哪个就跳过哪个。<br>'
      + '右边那个「浏览…」按钮会打开系统原生目录选择框。',
    'ob.dryKicker': '第 2 步 · 先试跑，再真装',
    'ob.dryTitle': 'DryRun 是你的安全带',
    'ob.dryText': '第一次请<b>保持勾选 DryRun</b>：它会把容器和 A0~A7 判据全跑一遍，'
      + '<b>绝不碰游戏目录</b>。<br>'
      + '确认判据全绿之后取消勾选再跑一次，才是真正安装。<br>'
      + '<b>-Combined</b> 用来在上一轮成果上继续累积（不会把上次的内容弄丢）。',
    'ob.forceKicker': '第 3 步 · 装不下的时候',
    'ob.forceTitle': '-Force 是越过限额的那把钥匙',
    'ob.forceText': '当素材超过默认限额（<b>bg &gt; 59 张</b> 或 <b>音频 &gt; 10 分钟</b>），'
      + '或者画质 <b>PSNR 低于 25 dB</b> 时，工具会主动停下并告诉你原因。<br>'
      + '这时勾上 <b>-Force</b> 才能继续打包。<br>'
      + '它不是"加速开关"，是"我知道我在干什么"的确认 —— 超限只是被拦，不是坏掉了。',
    'ob.advKicker': '第 4 步 · 想更细一点',
    'ob.advTitle': '进阶里藏着三个旋钮',
    'ob.advText': '展开<b>进阶</b>，可以：手动指定 <b>ffmpeg 路径</b>（自动探测找不到时）；'
      + '指定<b>自定义工具目录</b>（想换一套 kit 做实验）；'
      + '以及查看更详细的构建参数。<br>'
      + '平时不用动它，默认值就是最好走的那条路。',
    'ob.runKicker': '第 5 步 · 出发',
    'ob.runTitle': '点这里开始打包',
    'ob.runText': '底部的进度条会走 L0 → L5：<b>L0~L4 全在临时目录里干活</b>，'
      + '只有 L5 会写游戏目录。<br>'
      + '中途可以按「取消」，但它只在<b>阶段边界</b>生效；一进入 L5（部署）就不再中断，'
      + '保证要么装完、要么回滚，绝不留半成品。',
    'ob.splitKicker': '第 6 步 · 看清楚发生了什么',
    'ob.splitTitle': '左边看日志，右边看结论',
    'ob.splitText': '左边是<b>实时日志</b>（会自动跟着最新一行），右边是 <b>A0~A7 判据</b>。'
      + '中间的分隔条可以<b>拖动</b>，双击就回到左右对半。<br>'
      + '跑完会弹一个结果框：成功是「转换成功喵」，失败是「洗大锅...出错了喵...」，'
      + '失败那个框里有<b>导出错误日志</b>按钮。',
    'ob.joinKicker': '最后一步 · 别一个人玩',
    'ob.joinTitle': '右下角还有一个「加入我们」',
    'ob.joinText': '工具是死的，人是活的喵。<br>'
      + '右上角<b>「加入我们」</b>里有一张图和一段喵言喵语，还有 Discord 与 B 站的入口 —— '
      + '遇到问题、想提需求、或者只是想看看别人把游戏改成了什么样，都可以进来喵一声。',
    'ob.endKicker': '好了',
    'ob.endTitle': '好啦，去创造你的世界吧喵~',
    'ob.endText': '装完进游戏，打开 Create 编辑器，四个下拉的最末尾就是你的新条目。<br>'
      + '（编辑器里的<b>小缩略图</b>仍会显示原生那一格，这是 v1 明确接受的行为 —— '
      + '大预览和 PLAY 都是对的。）<br>'
      + '随时点右上角的 <b>? 引导</b> 可以再看一遍。',

    'join.title': '加入我们喵',
    'join.body': '喵——你能找到这里，说明你也在偷偷改造这个世界喵。<br>'
      + '有人负责把画塞进游戏，有人负责听一秒的爆音，还有人只负责在半夜问「这个能过审吗喵」。<br>'
      + '不打卡、不催更、不用带礼物，进来喵一声就好喵～',
    'join.discord': 'Discord 频道',
    'join.bili': 'B 站（待填）',
    'join.github': 'GitHub 仓库',
    'join.qq': 'QQ 群',
    'join.soon': '链接还没放上来喵',
    'join.close': '喵一声就走',
    'join.alt': '加入我们的插画',
    'join.starTitle': '给我一颗星星吧喵',
    'join.starBody': 'GitHub 上那颗 ⭐ 对我来说很重要喵 —— 它不是个数字，是"这东西真的有人在用"的证据。<br>'
      + '觉得有用就顺手点一下喵；觉得哪里不行，直接开 issue 骂我喵。',
    'join.starGo': '去点一颗星',
    'join.starLater': '下次一定喵',
    'join.starAlt': '求 star 的插画',
    'join.qqTitle': '来吧！到猫窝里就地复原吧！',
    'join.qqBody': '打包出问题？素材不认？还是只想找个人一起研究怎么把游戏拆开再装回去喵？<br>'
      + '群号已经躺进剪贴板了，进来直接粘贴就行喵～',
    'join.qqNumber': '群号',
    'join.qqCopy': '再复制一次',
    'join.qqCopied': '群号已复制喵',
    'join.copyFailed': '复制失败喵',
    'join.qqAlt': 'QQ 群二维码'
  },

  en: {
    'lang.name': 'English',
    'lang.switch': 'Switch language',

    'app.connected': 'local service connected',
    'app.noToken': 'no token',
    'app.preparing': 'preparing…',
    'app.notStarted': 'not started',
    'app.guide': 'Guide',
    'app.guideTitle': 'Show the first-run guide again',
    'app.join': 'Join us',
    'app.joinTitle': 'Join us, meow',
    'app.themeDark': 'Dark background',
    'app.themeLight': 'Light background',

    'inputs.title': 'materials & game / inputs',
    'inputs.paks': 'Game Paks folder (or the game root)',
    'inputs.srcm': 'Material root (holds bg / BGM / Sound / Ambient)',
    'inputs.browse': 'Browse…',

    'run.start': 'Start packing',
    'run.running': 'Packing…',
    'run.cancel': 'Cancel',
    'run.needPaths': 'Fill in the game Paks folder and the material root first.',
    'run.startFailed': 'Could not start: ',
    'run.reportFailed': 'Could not fetch the report: ',
    'run.openFailed': 'Could not open the folder: ',
    'run.rollbackFailed': 'Rollback failed: ',
    'run.done': '[gui] done: ',
    'run.failed': '[gui] failed: ',
    'run.dialogFailed': 'Could not open the folder dialog: ',
    'run.dialogNoPath': 'The dialog returned no path: ',

    'opts.title': 'options',
    'opts.fit': 'Background fit',
    'opts.fitCover': 'cover — fill and crop (default)',
    'opts.fitContain': 'contain — letterbox with a border',
    'opts.fitCoverShort': 'cover',
    'opts.fitContainShort': 'contain',
    'opts.dryRun': 'DryRun',
    'opts.dryRunHint': 'stop at L4: build the container and run every gate, never touch the game folder',
    'opts.combined': '-Combined',
    'opts.combinedHint': 'accumulate on top of the previous out_patch build',
    'opts.force': '-Force',
    'opts.forceHint': 'override the limits (bg ≤ 59, audio ≤ 10 min, PSNR ≥ 25 dB)',
    'opts.noAtlas': '-NoAtlas',
    'opts.noAtlasHint': 'skip the preview-atlas append (old behaviour: sharper dropdown thumbnail, but the timeline cell and the right preview block will not show your picture)',
    'opts.adv': 'Advanced (ffmpeg / kit folder)',
    'opts.advHint': 'set an explicit ffmpeg path, point at your own kit folder, and see the finer build switches',
    'opts.ffmpegPh': 'empty = auto-detect',
    'opts.kitPh': 'empty = find kit/ automatically',

    'log.empty': 'The live build log shows up here — press “Start packing” to begin.',
    'log.jump': '↓ Jump to latest',
    'log.split': 'Drag to resize the log and the gates panels',

    'gates.title': 'gates',
    'gates.allPass': 'ALL PASS',
    'gates.failed': 'FAILED',
    'gates.deployed': 'deployed',
    'gates.notDeployed': 'not deployed',
    'gates.none': 'No result yet. One run will fill in the A0~A7 gates and the deploy state.',
    'gates.daRows': 'DA rows: ',
    'gates.materials': 'materials: ',
    'gates.materialsUnit': '',
    'gates.container': 'container: ',
    'gates.seconds': 'took: ',
    'gates.openOut': 'Open output folder',
    'gates.rollback': 'Roll back (uninstall.ps1)',

    'prog.idle': 'idle',
    'prog.packing': 'packing',
    'prog.done': 'done',
    'prog.failed': 'failed',

    'modal.okTitle': 'Converted, meow!',
    'modal.okDry': 'The container and every A0~A7 gate passed (this was a DryRun, the game folder was untouched).',
    'modal.okDeployed': 'It is installed in the game folder and A0~A7 all passed. Go have a look, meow.',
    'modal.failTitle': 'Oh no... something broke, meow...',
    'modal.failSub': 'This run produced no usable container. The error is below; use “Export error log” to send it along.',
    'modal.export': 'Export error log',
    'modal.exporting': 'Exporting…',
    'modal.exported': 'Saved to ',
    'modal.exportEmpty': 'No log to export yet',
    'modal.exportCancelled': 'Export cancelled',
    'modal.exportFailed': 'Export failed',
    'modal.exportFailedWhy': 'Export failed: ',
    'modal.yay': 'Yay',
    'modal.close': 'Close',

    'ob.skip': 'Skip guide',
    'ob.prev': 'Back',
    'ob.next': 'Next',
    'ob.start': 'Start using it',
    'ob.welcomeKicker': 'Welcome',
    'ob.welcomeTitle': 'Meow~ welcome to the packing workshop!',
    'ob.welcomeText': 'Two minutes is enough to get your own <b>images and audio</b> into CalaPlayer.<br>'
      + 'The tool only does one thing: it packs what you give it into a <b>append-only, never-overwrite</b> '
      + 'patch that you can roll back with one click. Not a single byte of the original assets is touched.',
    'ob.pathKicker': 'Step 1 · show it the way',
    'ob.pathTitle': 'Two paths, filled in once',
    'ob.pathText': 'The top one is the <b>game folder</b> (game root, Content or Paks all work — the tool finds it),<br>'
      + 'the bottom one is the <b>material root</b> — put <code>bg</code> / <code>BGM</code> / '
      + '<code>Sound</code> / <code>Ambient</code> inside it; whichever is missing is simply skipped.<br>'
      + 'The “Browse…” button opens the native folder picker.',
    'ob.dryKicker': 'Step 2 · try first, install later',
    'ob.dryTitle': 'DryRun is your seat belt',
    'ob.dryText': 'Keep <b>DryRun ticked</b> the first time: it builds the container and runs every '
      + 'A0~A7 gate while <b>never touching the game folder</b>.<br>'
      + 'Once the gates are all green, untick it and run again to really install.<br>'
      + '<b>-Combined</b> keeps accumulating on top of the previous build instead of throwing it away.',
    'ob.forceKicker': 'Step 3 · when it does not fit',
    'ob.forceTitle': '-Force is the key past the limits',
    'ob.forceText': 'When the material exceeds the defaults (<b>bg &gt; 59</b> or <b>audio &gt; 10 min</b>), '
      + 'or the picture quality lands under <b>25 dB PSNR</b>, the tool stops and tells you why.<br>'
      + 'Tick <b>-Force</b> to go ahead anyway.<br>'
      + 'It is not a “go faster” switch, it is a “I know what I am doing” confirmation — being stopped is a limit, not a failure.',
    'ob.advKicker': 'Step 4 · want finer control',
    'ob.advTitle': 'Three knobs hide under “Advanced”',
    'ob.advText': 'Expand <b>Advanced</b> to set an explicit <b>ffmpeg path</b> (for when auto-detection fails), '
      + 'point at your own <b>kit folder</b> (if you want to experiment with another tool set), '
      + 'and read the finer build switches.<br>'
      + 'You normally never need it — the defaults are the well-trodden path.',
    'ob.runKicker': 'Step 5 · off we go',
    'ob.runTitle': 'Press here to start packing',
    'ob.runText': 'The bar at the bottom walks L0 → L5: <b>L0~L4 work entirely inside a scratch folder</b>, '
      + 'only L5 writes the game folder.<br>'
      + 'You can hit “Cancel” on the way, but it only lands on a <b>stage boundary</b>; once L5 (deploy) starts '
      + 'it is ignored so a run either finishes or rolls back — never a half-applied patch.',
    'ob.splitKicker': 'Step 6 · see what actually happened',
    'ob.splitTitle': 'Log on the left, verdict on the right',
    'ob.splitText': 'Left is the <b>live log</b> (it follows the newest line), right is the <b>A0~A7 gates</b>. '
      + 'The divider between them is <b>draggable</b>; double-click snaps it back to 50/50.<br>'
      + 'When a run ends you get a result dialog: “Converted, meow!” or “Oh no... something broke, meow...”, '
      + 'and the failure one carries an <b>Export error log</b> button.',
    'ob.joinKicker': 'Last step · do not play alone',
    'ob.joinTitle': 'There is also a “Join us” up there',
    'ob.joinText': 'Tools are cold, people are warm, meow.<br>'
      + 'Behind <b>“Join us”</b> there is a picture, some cat-speak and doors to Discord and Bilibili — '
      + 'drop in for problems, requests, or just to see what everyone else turned their game into.',
    'ob.endKicker': 'Done',
    'ob.endTitle': 'Alright — go build your world, meow~',
    'ob.endText': 'Install it, open the in-game Create editor, and your new entries are at the very bottom of all four dropdowns.<br>'
      + '(The tiny <b>thumbnail</b> in the editor still shows the original tile — that is the v1 behaviour we accepted; '
      + 'the large preview and PLAY are both correct.)<br>'
      + 'The <b>? Guide</b> button up top replays this any time.',

    'join.title': 'Join us, meow',
    'join.body': 'Mew — if you found this place, you are probably modding the world too, meow.<br>'
      + 'Some of us squeeze art into the game, some hunt a one-second audio glitch, and some just ask at 3 a.m. '
      + '“will this pass the vibe check, meow?”.<br>'
      + 'No check-ins, no deadlines, no gifts needed — just come say meow~',
    'join.discord': 'Discord server',
    'join.bili': 'Bilibili (TBD)',
    'join.github': 'GitHub repo',
    'join.qq': 'QQ group',
    'join.soon': 'That link is not up yet, meow',
    'join.close': 'Say meow and go',
    'join.alt': 'Join-us illustration',
    'join.starTitle': 'Leave me a star, meow',
    'join.starBody': 'That little ⭐ on GitHub matters a lot to me, meow — it is not a number, '
      + 'it is proof that somebody actually uses this.<br>'
      + 'If it helped you, one click is enough; if something is off, open an issue and yell at me, meow.',
    'join.starGo': 'Go leave a star',
    'join.starLater': 'Next time, meow',
    'join.starAlt': 'Star-begging illustration',
    'join.qqTitle': 'Come on! Get patched up back in the cat nest!',
    'join.qqBody': 'Something broke? Material not recognised? Or you just want company while taking a game '
      + 'apart and putting it back together, meow?<br>'
      + 'The group number is already on your clipboard — just paste it and come in, meow~',
    'join.qqNumber': 'Group No.',
    'join.qqCopy': 'Copy it again',
    'join.qqCopied': 'Group number copied, meow',
    'join.copyFailed': 'Copy failed, meow',
    'join.qqAlt': 'QQ group QR code'
  }
}

export const lang = ref('zh')

//: The language switch fires a one-shot "decode" wave (see ScrambleText.vue).
//: `scrambleTick` is what the text components watch, and `scrambleOrigin` is the
//: click position the ripple spreads from -- this is what replaces ReactBits'
//: pointer-proximity trigger, which we deliberately do NOT want.
export const scrambleTick = ref(0)
export const scrambleOrigin = ref({ x: 0, y: 0 })

export function detectLang() {
  // the durable copy (prefs.json) wins, then localStorage, then the system locale
  const saved = getPref(KEY)
  if (saved === 'zh' || saved === 'en') return saved
  const n = String((navigator.language || navigator.userLanguage || 'en')).toLowerCase()
  return n.startsWith('zh') ? 'zh' : 'en'
}

export function applyLang(l) {
  const v = LANGS.indexOf(l) >= 0 ? l : 'zh'
  lang.value = v
  document.documentElement.setAttribute('lang', v === 'zh' ? 'zh-CN' : 'en')
  document.documentElement.setAttribute('data-lang', v)
  return v
}

//: `origin` = the viewport position of the click that caused the switch; the
//: ripple starts there.  `applyLang` (first paint) intentionally does NOT bump
//: the tick, so a cold start shows the text already settled.
export function setLang(l, origin) {
  const v = applyLang(l)
  setPref(KEY, v)                    // remembered across launches (prefs.json)
  if (origin && typeof origin.x === 'number' && typeof origin.y === 'number') {
    scrambleOrigin.value = { x: origin.x, y: origin.y }
  }
  scrambleTick.value += 1
  return v
}

export function toggleLang() {
  return setLang(lang.value === 'zh' ? 'en' : 'zh')
}

//: t('key', a, b) -- {0} {1} are replaced by the extra arguments
export function t(key, ...args) {
  const d = DICT[lang.value] || DICT.zh
  let s = d[key]
  if (s === undefined) s = DICT.zh[key]
  if (s === undefined) return key
  if (args.length) {
    s = s.replace(/\{(\d+)\}/g, (m, i) => (args[Number(i)] === undefined ? m : String(args[Number(i)])))
  }
  return s
}
