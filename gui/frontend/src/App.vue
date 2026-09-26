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
                @click="onboard && onboard.restart(0)">
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
          <PathField id="paks" v-model="form.paks" :label="t('inputs.paks')"
                     placeholder="D:\CalabiyanGalgameMaker\CalaPlayer" kind="paks"
                     @error="notice = $event" />
          <div style="height:10px"></div>
          <PathField id="srcm" v-model="form.srcm" :label="t('inputs.srcm')"
                     placeholder="D:\mytest" kind="srcm" @error="notice = $event" />
        </div>

        <OptionsPanel id="card-options" :class="{ busy: running }"
                      v-model:fit="form.fit" v-model:dry-run="form.dryRun"
                      v-model:combined="form.combined" v-model:force="form.force"
                      v-model:noAtlas="form.noAtlas"
                      v-model:ffmpeg="form.ffmpeg" v-model:kit="form.kit" />

        <div class="runbar">
          <button id="run" class="uv-btn uv-btn-primary uv-btn-lg grow" type="button"
                  :disabled="running || !api.hasToken" @click="run">
            <span v-if="running" class="uv-spin"></span>
            <ScrambleText :text="running ? t('run.running') : t('run.start')" />
          </button>
          <button id="cancel" class="uv-btn uv-btn-lg" type="button"
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
            <ResultPanel :rep="report" :rollback-text="rollbackText"
                         @open-out="openOut" @rollback="rollback" />
          </template>
        </SplitPane>
      </section>
    </main>

    <ProgressBar :running="running" :pct="progress" :done="done" :failed="failed"
                 :stage="stage" />

    <StatusModal :kind="modalKind" :report="report" :task-id="taskId"
                 @close="modalKind = ''" />

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
import CommunityModal from './components/CommunityModal.vue'
import Onboarding from './components/Onboarding.vue'
import SquishSwitch from './components/SquishSwitch.vue'
import ScrambleText from './components/ScrambleText.vue'
import { api } from './api.js'
import { lang, setLang, t } from './i18n.js'
import { get as getPref, set as setPref } from './prefs.js'

const STAGES = ['L0', 'L1', 'L2', 'L3', 'L4', 'L5']
const MAX_LINES = 4000
// assets live in gui/dist (vite's public dir) and are addressed at runtime:
// a static src= would make the Vue compiler try to resolve them as modules
const BRAND = 'T_UI.png'

const theme = ref(document.documentElement.dataset.theme || 'dark')
const version = ref('?')
const form = reactive({
  paks: '', srcm: '', fit: 'cover',
  dryRun: true, combined: false, force: false, noAtlas: false, ffmpeg: '', kit: ''
})
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
  if (!form.paks.trim() || !form.srcm.trim()) {
    notice.value = t('run.needPaths')
    return
  }
  reset()
  running.value = true
  progress.value = 4
  try {
    const r = await api.start({
      paks: form.paks.trim(), srcm: form.srcm.trim(), fit: form.fit,
      dry_run: form.dryRun, combined: form.combined, force: form.force,
      no_atlas: form.noAtlas,
      ffmpeg: form.ffmpeg.trim(), kit: form.kit.trim()
    })
    taskId.value = r.task_id
    watchLogs(r.task_id)
  } catch (e) {
    running.value = false
    notice.value = t('run.startFailed') + (e.message || e)
  }
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
      report.value = Object.assign({}, rep.report || {}, {
        out_patch: rep.out_patch, deployed: (rep.report || {}).deployed, ok: rep.ok,
        error: rep.error, da_counts: (rep.report || {}).da_counts,
        materials: (rep.report || {}).materials, seconds: (rep.report || {}).seconds
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

.runbar { flex: none; display: flex; gap: 10px; }
.grow { flex: 1 1 auto; }
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
