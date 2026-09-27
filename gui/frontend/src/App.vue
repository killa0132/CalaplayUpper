<template>
  <div class="scrim"></div>

  <div class="uv-scope app">
    <header class="bar">
      <div class="brand">
        <img class="brand-art" :src="BRAND" alt="">
        <h1>CalaPlayerSrcmBuilder</h1>
        <span class="uv-pill" id="backend">v{{ version }}</span>
        <span class="uv-pill" :class="api.hasToken ? 'on' : 'fail'">
          {{ api.hasToken ? t('app.connected') : t('app.noToken') }}
        </span>
        <span v-if="running" class="uv-pill now">
          <span class="uv-spin"></span> {{ stage || t('app.preparing') }}
        </span>
      </div>
      <!-- `.bar-right`, NOT `.right`: the work area's second column is
           `<section class="col right">`, and a bare `.right` rule in this file
           leaks into it (align-items:center + flex-wrap:wrap), which made the
           split pane shrink-to-fit and float in the middle of the column
           instead of filling it.  Same trap as the old `.left` one. -->
      <div class="bar-right">
        <button id="join" class="uv-btn uv-btn-help" type="button" :title="t('app.joinTitle')"
                @click="joinOpen = true">
          <span class="paw">🐾</span> <ScrambleText :text="t('app.join')" />
        </button>
        <button id="help" class="uv-btn uv-btn-help" type="button" :title="t('app.guideTitle')"
                @click="openGuide">
          <span class="q">?</span> <ScrambleText :text="t('app.guide')" />
        </button>
        <!-- ReactBits Squish Switch drives the language; the press position is
             remembered so the text-decode ripple can spread from it -->
        <span id="lang" class="uv-chip uv-lang-wrap" :data-lang="lang"
              @pointerdown.capture="rememberLangOrigin">
          <SquishSwitch id="lang-switch" :checked="lang === 'en'" off-label="中" on-label="EN"
                        :width="66" :height="30" :thumb-width="28" :speed="55"
                        aria-label="language" @change="onLangChange" />
        </span>
        <div class="uv-chip" id="theme-toggle-wrap">
          <span class="cap"><ScrambleText :text="theme === 'dark' ? t('app.themeDark') : t('app.themeLight')" /></span>
          <ThemeToggle :theme="theme" @toggle="toggleTheme" />
        </div>
      </div>
    </header>

    <main class="grid">
      <section class="col left uv-scroll">
        <div class="uv-card uv-card-glow uv-card-pad" id="card-inputs">
          <h3 class="uv-card-title"><ScrambleText :text="t('inputs.title')" /></h3>

          <!-- CP-38: two work modes share this one card (no global tabs).
               `single` = the original one-package build, pixel-identical;
               `merge`  = several mods -> one _P via core/merger.py. -->
          <div class="modes" id="mode-tabs" role="tablist">
            <button id="mode-single" class="uv-btn uv-btn-sm" type="button" role="tab"
                    :class="{ 'uv-btn-primary': mode === 'single' }"
                    :aria-selected="mode === 'single'"
                    @click="setMode('single')"><ScrambleText :text="t('inputs.modeSingle')" /></button>
            <button id="mode-merge" class="uv-btn uv-btn-sm" type="button" role="tab"
                    :class="{ 'uv-btn-primary': mode === 'merge' }"
                    :aria-selected="mode === 'merge'"
                    @click="setMode('merge')"><ScrambleText :text="t('inputs.modeMerge')" /></button>
          </div>

          <template v-if="mode === 'single'">
            <PathField id="paks" v-model="form.paks" :label="t('inputs.paks')"
                       placeholder="D:\CalabiyanGalgameMaker\CalaPlayer" kind="paks"
                       @error="notice = $event" />
            <div style="height:10px"></div>
            <PathField id="srcm" v-model="form.srcm" :label="t('inputs.srcm')"
                       placeholder="D:\mytest" kind="srcm" @error="notice = $event" />
          </template>

          <template v-else>
            <!-- the merge still needs the CLEAN base + somewhere to write -->
            <PathField id="paks-merge" v-model="form.paks" :label="t('inputs.paksBase')"
                       placeholder="D:\CalabiyanGalgameMaker\CalaPlayer\Content\Paks"
                       kind="paks" @error="notice = $event" />
            <div style="height:10px"></div>
            <div class="uv-field-row">
              <label class="uv-label" for="mods"><ScrambleText :text="t('inputs.mods')" /></label>
              <div class="uv-field-line">
                <input id="mods" class="uv-field mono" type="text" spellcheck="false"
                       placeholder="D:\mods" :value="form.mods"
                       @input="onModsInput($event.target.value)"
                       @change="loadMods()">
                <button id="pick-mods" class="uv-btn uv-btn-sm uv-btn-ghost mods-pick" type="button"
                        @click="pickMods"><ScrambleText :text="t('inputs.modsPick')" nowrap /></button>
              </div>
            </div>
            <div style="height:10px"></div>
            <PathField id="out-merge" v-model="form.out" :label="t('inputs.outDir')"
                       placeholder="D:\merged" kind="out" @error="notice = $event" />

            <div class="mods-list" id="mods-list">
              <div class="uv-label"><ScrambleText :text="t('inputs.modsList')" /></div>
              <div v-if="!modRows.length" class="mods-empty" id="mods-empty">
                <ScrambleText :text="modsNote || t('inputs.modsNone')" />
              </div>
              <div v-for="(m, i) in modRows" :key="m.name + '#' + i" class="mod-row"
                   :id="'mod-' + i" :class="{ off: !m.on }">
                <input class="mod-check" type="checkbox" :checked="m.on"
                       :aria-label="m.name" @change="toggleMod(i, $event.target.checked)">
                <span class="mod-name" :title="m.name + ' · ' + m.manifest">{{ m.name }}</span>
                <span class="uv-pill">{{ m.kind || '?' }}</span>
                <button class="uv-btn uv-btn-sm uv-btn-ghost mod-x" type="button"
                        :title="t('inputs.modRemove')" @click="removeMod(i)">✕</button>
              </div>
            </div>
          </template>
        </div>

        <OptionsPanel id="card-options" :class="{ busy: running }" :mode="mode"
                      v-model:fit="form.fit" v-model:dry-run="form.dryRun"
                      v-model:combined="form.combined" v-model:force="form.force"
                      v-model:noAtlas="form.noAtlas" v-model:exportSrc="form.exportSrc"
                      v-model:mergeDryRun="form.mergeDryRun"
                      v-model:ffmpeg="form.ffmpeg" v-model:kit="form.kit" />

        <div class="runbar">
          <button id="run" class="uv-btn uv-btn-primary uv-btn-lg grow" type="button"
                  :disabled="running || !api.hasToken" @click="run">
            <span v-if="running" class="uv-spin"></span>
            <ScrambleText :text="runLabel" /></button>
          <button id="cancel" class="uv-btn uv-btn-lg shrink" type="button"
                  :disabled="!running" @click="cancel"><ScrambleText :text="t('run.cancel')" /></button>
        </div>
        <div v-if="notice" class="notice">{{ notice }}</div>
      </section>

      <section class="col right">
        <div class="chips">
          <span v-for="s in STAGES" :key="s" class="uv-pill"
                :class="stageClass(s)">{{ s }}</span>
          <span class="growspace"></span>
          <span class="uv-pill" id="taskid">{{ taskId || t('app.notStarted') }}</span>
        </div>

        <!-- log on the left, the A0~A7 verdict on the right; the divider in the
             middle is draggable (double-click = back to 50/50) -->
        <SplitPane v-model:ratio="splitRatio" store-key="cala-split" id="split"
                   :label="t('log.split')">
          <template #a><LogView :lines="lines" /></template>
          <template #b>
            <ResultPanel :rep="report" :mode="mode" :rollback-text="rollbackText"
                         @open-out="openOut" @rollback="rollback" />
          </template>
        </SplitPane>
      </section>
    </main>

    <ProgressBar :running="running" :pct="progress" :done="done" :failed="failed"
                 :stage="stage" />

    <StatusModal :kind="modalKind" :report="report" :task-id="taskId"
                 @close="modalKind = ''" />

    <!-- CP-40: inputs that are missing/wrong are listed in a card BEFORE a merge
         starts (never as a mystery failure three seconds later) -->
    <NoticeCard ref="noticeCard" :open="noticeOpen" :errors="noticeErrors"
                :warnings="noticeWarnings" @close="noticeOpen = false" />

    <CommunityModal ref="join" :open="joinOpen" @close="joinOpen = false" />

    <Onboarding ref="onboard" />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import ThemeToggle from './components/ThemeToggle.vue'
import PathField from './components/PathField.vue'
import OptionsPanel from './components/OptionsPanel.vue'
import LogView from './components/LogView.vue'
import ResultPanel from './components/ResultPanel.vue'
import SplitPane from './components/SplitPane.vue'
import ProgressBar from './components/ProgressBar.vue'
import StatusModal from './components/StatusModal.vue'
import NoticeCard from './components/NoticeCard.vue'
import CommunityModal from './components/CommunityModal.vue'
import Onboarding from './components/Onboarding.vue'
import SquishSwitch from './components/SquishSwitch.vue'
import ScrambleText from './components/ScrambleText.vue'
import { api } from './api.js'
import { lang, setLang, t } from './i18n.js'
import { get as getPref, set as setPref } from './prefs.js'

const MAX_LINES = 4000
// assets live in gui/dist (vite's public dir) and are addressed at runtime:
// a static src= would make the Vue compiler try to resolve them as modules
const BRAND = 'T_UI.png'

const theme = ref(document.documentElement.dataset.theme || 'dark')
const version = ref('?')
//: 'single' = one material folder -> one _P (the original flow);
//: 'merge'  = several mods -> one _P (CP-38, core/merger.py).  Local switch, no
//: global tabs: the middle/right panes (log + verdict) are shared as-is.
const mode = ref('single')
const form = reactive({
  paks: '', srcm: '', fit: 'cover',
  dryRun: true, combined: false, force: false, noAtlas: false, exportSrc: false,
  ffmpeg: '', kit: '',
  // merge inputs
  mods: '', out: '',
  //: CP-41：合并模式的「仅产出不安装」（默认关闭 ⇒ 合并后自动装进游戏）
  mergeDryRun: false
})
//: the mods the Mods-root's index manifest declares (checkbox = participate)
const modRows = ref([])
const modsNote = ref('')
//: CP-40: the Mods root the backend finally used (it can differ from what the user
//: typed: `gui/mods.py` writes/uses an index or stages the `_src` folders)
const modsRoot = ref('')
//: CP-40: the pre-flight card (missing/wrong inputs, listed before anything runs)
const noticeCard = ref(null)
const noticeOpen = ref(false)
const noticeErrors = ref([])
const noticeWarnings = ref([])
const taskId = ref('')
const running = ref(false)
const stage = ref('')
const seen = ref({})
const lines = ref([])
const report = ref(null)
const rollbackText = ref('')
const notice = ref('')
const progress = ref(0)
const done = ref(false)
const failed = ref(false)
const modalKind = ref('')
const onboard = ref(null)
const join = ref(null)
const joinOpen = ref(false)
//: 50 = 左右对半 (the divider is draggable and remembered)
const splitRatio = ref(50)
const saved = Number(getPref('cala-split'))
if (saved >= 12 && saved <= 88) splitRatio.value = saved
let es = null
//: the stage chips follow the mode: L0..L5 for a build, M0..M7 for a merge
//: (M7 = 把合并结果装进游戏，CP-41；勾了「仅产出不安装」时不会出现)
const STAGES = computed(() => (mode.value === 'merge'
  ? ['M0', 'M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7']
  : ['L0', 'L1', 'L2', 'L3', 'L4', 'L5']))
const runLabel = computed(() => {
  if (running.value) return mode.value === 'merge' ? t('run.merging') : t('run.running')
  return mode.value === 'merge' ? t('run.merge') : t('run.start')
})

function setMode(m) {
  const next = m === 'merge' ? 'merge' : 'single'
  if (next === mode.value) return next
  mode.value = next
  notice.value = ''
  noticeOpen.value = false
  if (next === 'merge' && form.mods.trim() && !modRows.value.length) loadMods()
  return next
}

function onModsInput(v) { form.mods = v }

/** Read `<mods>/manifest.json` (the index) and list what it declares. */
async function loadMods() {
  modRows.value = []
  modsNote.value = ''
  modsRoot.value = ''
  const dir = (form.mods || '').trim()
  if (!dir) return { ok: false, count: 0 }
  try {
    const r = await api.listMods(dir)
    if (!r || !r.ok) {
      modsNote.value = (r && r.message) || '读取失败'
      return { ok: false, reason: (r && r.reason) || '', message: modsNote.value }
    }
    modRows.value = (r.mods || []).map(m => Object.assign({}, m, { on: true }))
    modsRoot.value = r.root || dir
    modsNote.value = t('inputs.modsFound', modRows.value.length, modsRoot.value)
    if (!form.out.trim()) {
      // default the output next to the Mods root (never inside it: the merger
      // treats the Mods tree as read-only)
      const parent = modsRoot.value.replace(/[\\/][^\\/]*$/, '')
      form.out = (parent || modsRoot.value) + '\\merged_out'
    }
    return { ok: true, count: modRows.value.length, root: modsRoot.value,
             source: r.source, written: !!r.written }
  } catch (e) {
    modsNote.value = String(e.message || e)
    return { ok: false, reason: 'http', message: modsNote.value }
  }
}

async function pickMods() {
  try {
    const r = await api.selectFolder('mods', form.mods || '')
    if (r && r.path) { form.mods = r.path; await loadMods() }
    else if (r && r.debug) notice.value = t('run.dialogNoPath') + JSON.stringify(r.debug)
  } catch (e) {
    notice.value = t('run.dialogFailed') + (e.message || e)
  }
}

function toggleMod(i, on) {
  const row = modRows.value[i]
  if (row) row.on = !!on
}

function removeMod(i) { modRows.value.splice(i, 1) }

function openGuide() {
  // the guide spotlights single-mode targets (#opt-force / #opt-adv), so make
  // sure we are in that mode before it starts
  setMode('single')
  if (onboard.value) onboard.value.restart(0)
}

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  document.documentElement.dataset.theme = theme.value
  setPref('cala-theme', theme.value)
}

//: The language switch (Squish Switch) -> setLang, plus the screen position of
//: the press so ScrambleText can spread its decode wave outward from there.
const langOrigin = ref({ x: 0, y: 0 })
function rememberLangOrigin(e) {
  if (e && typeof e.clientX === 'number') {
    langOrigin.value = { x: e.clientX, y: e.clientY }
  }
}
function onLangChange(next) {
  const el = document.getElementById('lang-switch')
  if (el && (!langOrigin.value.x && !langOrigin.value.y)) {
    const r = el.getBoundingClientRect()
    langOrigin.value = { x: r.left + r.width / 2, y: r.top + r.height / 2 }
  }
  setLang(next ? 'en' : 'zh', langOrigin.value)
}

function stageClass(s) {
  if (seen.value[s]) return 'on'
  if (running.value && stage.value === s) return 'now'
  return ''
}

function push(line) {
  lines.value.push(line)
  if (lines.value.length > MAX_LINES) lines.value.splice(0, lines.value.length - MAX_LINES)
}

function reset() {
  lines.value = []
  report.value = null
  rollbackText.value = ''
  notice.value = ''
  seen.value = {}
  stage.value = ''
  progress.value = 0
  done.value = false
  failed.value = false
  modalKind.value = ''
}

async function run() {
  if (running.value) return
  if (mode.value === 'merge') return runMerge()
  // CP-41：单包模式也开始前先校验（缺项/路径不存在 → 错误卡片，不启动任务）
  const v = await checkInputs([], 'single')
  if (!v.ok) { showNotice(v.errors, v.warnings); return }
  reset()
  running.value = true
  progress.value = 4
  try {
    const r = await api.start({
      paks: form.paks.trim(), srcm: form.srcm.trim(), fit: form.fit,
      dry_run: form.dryRun, combined: form.combined, force: form.force,
      no_atlas: form.noAtlas, export_src: form.exportSrc,
      ffmpeg: form.ffmpeg.trim(), kit: form.kit.trim()
    })
    taskId.value = r.task_id
    watchLogs(r.task_id)
  } catch (e) {
    running.value = false
    notice.value = t('run.startFailed') + (e.message || e)
  }
}

async function runMerge() {
  // the checklist drives `select`; a folder typed by hand has no list yet
  if (!modRows.value.length && form.mods.trim()) await loadMods()
  // CP-40: ask the backend what is actually wrong and list ALL of it in the card --
  // "填了但路径不存在" is checked server-side, so the page cannot guess wrong.
  const picked = modRows.value.filter(m => m.on).map(m => m.name)
  const v = await checkInputs(picked)
  if (!v.ok) { showNotice(v.errors, v.warnings); return }
  if (v.notes && v.notes.length) notice.value = v.notes.join(' ')
  reset()
  running.value = true
  progress.value = 4
  try {
    const r = await api.merge({
      mods: form.mods.trim(), paks: form.paks.trim(), out: form.out.trim(),
      select: picked, kit: form.kit.trim(),
      // CP-41：默认安装进游戏；勾了「仅产出不安装」才置 true
      dry_run: form.mergeDryRun
    })
    taskId.value = r.task_id
    watchLogs(r.task_id)
  } catch (e) {
    running.value = false
    notice.value = t('run.startFailed') + (e.message || e)
  }
}

/** 开始前校验（单包 / 合并共用）——列表交给错误卡片显示，不启动任何任务。 */
async function checkInputs(picked, m) {
  const md = m || (mode.value === 'merge' ? 'merge' : 'single')
  const body = { mode: md, paks: form.paks.trim() }
  if (md === 'merge') {
    body.mods = form.mods.trim()
    body.out = form.out.trim()
    body.select = picked || []
  } else {
    body.srcm = form.srcm.trim()
  }
  try {
    const v = await api.validate(body)
    return { ok: !!v.ok, errors: v.errors || [], warnings: v.warnings || [],
             root: v.root, notes: [] }
  } catch (e) {
    return { ok: false, errors: [t('run.startFailed') + (e.message || e)], warnings: [],
             notes: [] }
  }
}

function showNotice(errors, warnings) {
  noticeErrors.value = errors || []
  noticeWarnings.value = warnings || []
  noticeOpen.value = true
  return noticeErrors.value.length
}

function watchLogs(id) {
  if (es) { es.close(); es = null }
  es = api.logs(id)
  es.addEventListener('snapshot', ev => {
    const d = JSON.parse(ev.data)
    lines.value = d.lines || []
  })
  es.addEventListener('line', ev => push(JSON.parse(ev.data).line))
  es.addEventListener('stage', ev => {
    const d = JSON.parse(ev.data)
    seen.value[d.stage] = true
    stage.value = d.stage
    // the bar advances stage by stage; the remaining 8% lands on "finished"
    const i = STAGES.indexOf(d.stage)
    if (i >= 0) progress.value = Math.max(progress.value, 6 + (i / STAGES.length) * 92)
  })
  es.addEventListener('end', async () => {
    if (es) { es.close(); es = null }
    try {
      const rep = await api.report(id)
      const r0 = rep.report || {}
      const isMerge = mode.value === 'merge'
      const dep = r0.deploy || null
      report.value = Object.assign({}, r0, {
        out_patch: rep.out_patch, ok: rep.ok,
        error: rep.error, da_counts: r0.da_counts,
        materials: r0.materials, seconds: r0.seconds,
        // 单包的部署状态来自报告的 deployed；合并看 deploy 块（CP-41 自动安装）
        deployed: isMerge ? !!(dep && dep.ok !== false) : r0.deployed,
        deploy: dep,
        // tells the modal this was a merge
        merge: isMerge
      })
      if (rep.ok) push(t('run.done') + (rep.out_patch || ''))
      else push(t('run.failed') + (rep.error || ''))
      // the outcome decides the modal; a user cancel is not an error
      const okv = !!rep.ok
      const canceled = !okv && /取消|cancel/i.test(rep.error || '')
      done.value = okv
      failed.value = !okv && !canceled
      progress.value = 100
      modalKind.value = okv ? 'ok' : (canceled ? '' : 'fail')
    } catch (e) {
      notice.value = t('run.reportFailed') + (e.message || e)
    }
    running.value = false
  })
  es.onerror = () => { /* EventSource reconnects on its own */ }
}

async function cancel() {
  if (!taskId.value) return
  try { await api.cancel(taskId.value) } catch (e) { notice.value = String(e.message || e) }
}

async function openOut() {
  try { await api.openFolder(taskId.value, 'out') }
  catch (e) { notice.value = t('run.openFailed') + (e.message || e) }
}

async function rollback() {
  rollbackText.value = ''
  try {
    const r = await api.uninstall(taskId.value, form.paks.trim())
    rollbackText.value = 'uninstall.ps1 rc=' + r.rc + '\n' + (r.stdout || '').trim()
    // CP-41b：回滚成功 ⇒ 这次的安装已经撤掉了：标一声，右下角那颗按钮随之置灰
    // （没有可回滚的东西了），合并的"已安装到哪"信息块也收起来。
    if (r.rc === 0 && report.value) {
      report.value = Object.assign({}, report.value,
                                   { deployed: false, rolledBack: true })
    }
  } catch (e) {
    rollbackText.value = t('run.rollbackFailed') + (e.message || e)
  }
}

// ---------------------------------------------------------------- test hook
// Small, deliberately public surface so the automated GUI check (and the user)
// can drive the page without clicking:  window.__cala.setParams({...}); run()
onMounted(async () => {
  // keep every page-level JS error (Vue patch errors included) where a test can
  // read it -- a component that silently drops out of the DOM is otherwise
  // invisible from the outside
  window.__calaErrors = []
  window.addEventListener('error', e => {
    window.__calaErrors.push(String((e && (e.message || e.error)) || 'error'))
  })
  window.addEventListener('unhandledrejection', e => {
    window.__calaErrors.push('rejection: ' + String(e && e.reason))
  })

  // The hook is installed BEFORE the health round-trip: a probe that arrives
  // while the fetch is still in flight must already find __cala (the version
  // pill fills in a moment later).
  window.__cala = {
    setParams(p) { Object.assign(form, p); return { ...form } },
    getParams() { return { ...form } },
    run,
    cancel,
    //: 清掉上一次的结果（报告/进度/弹窗）。自检在"派发一次新任务"之前必须调它：
    //: 否则探针读到的还是上一次的 ok，会把等待循环当场放过去（CP-41 踩过）。
    reset() { reset(); return true },
    // CP-38: the local mode switch + the mod checklist, drivable by the tests
    setMode: (m) => setMode(m),
    getMode: () => mode.value,
    loadMods: () => loadMods(),
    modsRoot: () => modsRoot.value,
    setMods: (docs) => { modRows.value = (docs || []).map(d => Object.assign({ on: true }, d)); return modRows.value.length },
    toggleMod: (i, on) => { toggleMod(i, on); return !!modRows.value[i] && modRows.value[i].on },
    removeMod: (i) => { removeMod(i); return modRows.value.length },
    mods: () => modRows.value.map(m => ({ name: m.name, kind: m.kind, on: !!m.on })),
    // CP-40: the pre-flight card ("填错了" list) + the merge pre-check
    notice: () => ({ open: noticeOpen.value, errors: noticeErrors.value.slice(),
                     warnings: noticeWarnings.value.slice(),
                     visible: !!(noticeCard.value && noticeCard.value.isOpen()) }),
    closeNotice: () => { noticeOpen.value = false; return true },
    showNotice: (errors, warnings) => showNotice(errors, warnings),
    checkInputs: (picked) => checkInputs(picked || modRows.value.filter(m => m.on).map(m => m.name)),
    validateMerge: async (picked) => {
      const v = await checkInputs(picked || modRows.value.filter(m => m.on).map(m => m.name))
      if (!v.ok) showNotice(v.errors, v.warnings)
      return v
    },
    theme: () => theme.value,
    toggleTheme,
    closeModal() { modalKind.value = '' },
    modal() { return modalKind.value },
    progress: () => progress.value,
    // i18n: the language is a plain ref, so switching re-renders the template.
    // Passing an origin fires the decode ripple from that point.
    lang: () => lang.value,
    setLang: (l, origin) => setLang(l, origin),
    toggleLang: () => { onLangChange(lang.value === 'zh'); return lang.value },
    // the "Join us" hub + its two popups
    openJoin() { joinOpen.value = true; return true },
    closeJoin() { joinOpen.value = false; return true },
    joinState: () => (join.value ? join.value.state() : { open: false }),
    setSplit(p) {
      splitRatio.value = Math.min(88, Math.max(12, Number(p) || 50))
      return splitRatio.value
    },
    getSplit: () => splitRatio.value,
    // the first-run guide: state()/next()/prev()/skip()/restart(from)
    onboard: {
      state: () => (onboard.value ? onboard.value.state() : { exists: false }),
      next: () => onboard.value && onboard.value.next(),
      prev: () => onboard.value && onboard.value.prev(),
      finish: () => onboard.value && onboard.value.finish(),
      skip: () => onboard.value && onboard.value.skip(),
      restart: (from) => onboard.value && onboard.value.restart(from || 0)
    },
    state: () => ({
      running: running.value, taskId: taskId.value, stage: stage.value,
      mode: mode.value,
      mods: modRows.value.map(m => m.name + (m.on ? ':on' : ':off')),
      modsRoot: modsRoot.value,
      mergeDryRun: form.mergeDryRun,
      notice: { open: noticeOpen.value, n: noticeErrors.value.length },
      seen: { ...seen.value }, lines: lines.value.length,
      ok: report.value ? !!report.value.ok : null,
      deployed: report.value ? !!report.value.deployed : null,
      gates: report.value && report.value.gates
        ? Object.fromEntries(Object.entries(report.value.gates).map(([k, v]) => [k, !!v.ok]))
        : null,
      da_counts: report.value ? report.value.da_counts : null,
      error: report.value ? report.value.error : null,
      theme: theme.value, notice: notice.value,
      progress: progress.value, modal: modalKind.value,
      done: done.value, failed: failed.value,
      split: splitRatio.value,
      lang: lang.value,
      join: joinOpen.value ? (join.value ? join.value.isOpen() : true) : false,
      guide: onboard.value ? onboard.value.state().visible : false,
      // a page reload would reset everything; this lets a test prove it did not
      origin: Math.round(performance.timeOrigin)
    })
  }

  try {
    const h = await api.health()
    version.value = h.version
  } catch (e) { /* ignore */ }
})
const hasReport = computed(() => !!report.value)
void hasReport
</script>

<style scoped>
/* The whole shell is a flex column that always fills the window: header, the
   two-column work area (which takes every remaining pixel), the progress bar.
   Nothing has a fixed pixel height, so resizing just re-flows. */
.app {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 14px 16px 14px;
  gap: 12px;
  overflow: hidden;
}

.bar { flex: none; display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.brand { display: flex; align-items: center; gap: 10px; min-width: 0; }
.brand h1 { margin: 0; font-size: 16.5px; font-weight: 700; letter-spacing: .2px; white-space: nowrap; }
.brand-art {
  width: 34px; height: 34px; flex: none;
  object-fit: contain;
  filter: drop-shadow(0 4px 10px rgba(0, 0, 0, .45));
}
.bar-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.grid {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  /* the form column grows with the window but stays usable at the minimum size */
  grid-template-columns: clamp(330px, 30%, 460px) minmax(0, 1fr);
  gap: 14px;
}
.col { display: flex; flex-direction: column; gap: 12px; min-height: 0; }
/* `scrollbar-gutter: stable` reserves the track even when the column does not
   overflow yet -- without it the 11px scrollbar appeared the moment the options
   panel grew and every card inside got 11px narrower ("左栏加载后自己收缩") */
.left { overflow-y: auto; overflow-x: hidden; padding-right: 2px; scrollbar-gutter: stable; }
.left > * { flex: none; }
.right { overflow: hidden; }

.chips { flex: none; display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.growspace { flex: 1 1 auto; }

/* the run + cancel pair must never overflow the column: at 960 px the form column
   is 330 px wide, and a flex item's default `min-width:auto` refuses to shrink
   below its own text, so the row used to poke out of the column's right edge.
   `wrap` + `min-width:0` makes that structurally impossible. (CP-40) */
.runbar { flex: none; display: flex; gap: 10px; flex-wrap: wrap; }
.runbar .uv-btn { min-width: 0; }
.runbar .uv-btn-lg { padding-left: 20px; padding-right: 20px; }
.runbar .grow { flex: 1 1 auto; }
.runbar .shrink { flex: 0 1 auto; }

/* ---- CP-38: the local single/merge switch + the mod checklist ----------- */
.modes { display: flex; gap: 8px; flex-wrap: wrap; }
.modes .uv-btn { flex: 1 1 0; min-width: 0; }
/* the field row markup is also used by PathField, but its styles are scoped to
   that component -- these three are the only ones this file needs */
.uv-field-row { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.uv-label { font-size: 12.5px; font-weight: 600; color: var(--ink-dim); }
.uv-field-line { display: flex; gap: 8px; align-items: center; min-width: 0; }
.uv-field-line .uv-field { flex: 1 1 auto; min-width: 0; }
.mods-pick { flex: none; white-space: nowrap; }
.mods-list { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.mods-empty { font-size: 11.5px; line-height: 1.5; color: var(--ink-dim); }
.mod-row {
  display: flex; align-items: center; gap: 8px; min-width: 0;
  padding: 5px 7px; border-radius: 9px;
  border: 1px solid var(--panel-line);
  background: color-mix(in srgb, var(--ink) 6%, transparent);
}
.mod-row.off { opacity: .5; }
.mod-check { flex: none; width: 14px; height: 14px; accent-color: var(--c2); }
/* a long mod name must ellipsize, never widen the column (the layout assertion
   is "label scrollWidth <= clientWidth") */
.mod-name {
  flex: 1 1 auto; min-width: 0; font-size: 12.5px; font-weight: 600;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.mod-row .uv-pill { flex: none; font-size: 10.5px; padding: 1px 7px; }
.mod-x { flex: none; padding: 2px 7px; }
.notice {
  flex: none;
  font-size: 12.5px; color: var(--warn);
  background: color-mix(in srgb, var(--warn) 12%, transparent);
  border-radius: 10px; padding: 8px 11px;
}

/* the language switch lives in a solid chip like the theme one, so it stays
   readable on top of the photo */
.uv-scope .uv-lang-wrap {
  padding: 2px 8px;
  align-items: center;
}
.uv-scope .uv-btn-help .paw { font-size: 12.5px; line-height: 1; }

/* keep two columns all the way down to the window's minimum width (960 px);
   the single-column fallback is only for a browser at a narrow width. */
@media (max-width: 900px) {
  .grid { grid-template-columns: minmax(0, 1fr); overflow-y: auto; }
  .left { max-height: 46vh; }
  .right { min-height: 60vh; }
}
</style>
