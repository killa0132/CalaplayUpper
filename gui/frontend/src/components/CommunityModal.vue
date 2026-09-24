<template>
  <!-- ---------------- hub ---------------- -->
  <div v-if="show" class="uv-modal-backdrop" :class="{ leaving }" data-kind="join"
       @click.self="onBackdrop">
    <div class="uv-modal join" role="dialog" aria-modal="true">
      <button class="uv-join-x" type="button" aria-label="close" @click="close">✕</button>

      <img class="uv-modal-art join-art" :src="ART" :alt="t('join.alt')">
      <h2 class="uv-modal-text">{{ t('join.title') }}</h2>
      <p class="uv-modal-sub join-body" v-html="t('join.body')"></p>

      <div class="uv-modal-acts join-acts">
        <a id="join-discord" class="uv-btn join-btn join-btn-lead" :href="DISCORD"
           target="_blank" rel="noopener" @click.prevent="open(DISCORD)">
          <svg class="ic" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 5.5h16v10.2H9.6L5.2 19.6V15.7H4z" fill="none" stroke="currentColor"
                  stroke-width="1.7" stroke-linejoin="round"/>
            <circle cx="9.2" cy="10.6" r="1.35" fill="currentColor"/>
            <circle cx="14.8" cy="10.6" r="1.35" fill="currentColor"/>
          </svg>
          <span>{{ t('join.discord') }}</span>
        </a>

        <a id="join-bili" class="uv-btn join-btn" href="#" @click.prevent="openBili">
          <svg class="ic" viewBox="0 0 24 24" aria-hidden="true">
            <rect x="3.5" y="7" width="17" height="11.5" rx="3" fill="none"
                  stroke="currentColor" stroke-width="1.7"/>
            <path d="M7.5 3.6 10.4 6.6M16.5 3.6 13.6 6.6" fill="none" stroke="currentColor"
                  stroke-width="1.7" stroke-linecap="round"/>
            <circle cx="9" cy="12.8" r="1.15" fill="currentColor"/>
            <circle cx="15" cy="12.8" r="1.15" fill="currentColor"/>
          </svg>
          <span>{{ t('join.bili') }}</span>
        </a>

        <!-- GitHub: the icon is wrapped in a field of stars flying everywhere -->
        <a id="join-github" class="uv-btn join-btn join-btn-gh" :href="GH"
           target="_blank" rel="noopener" @click.prevent="openGitHub">
          <span class="gh-fly" aria-hidden="true">
            <i v-for="n in 9" :key="n" :style="flyVars(n)"><svg viewBox="0 0 24 24">
              <path d="M12 2.6l2.9 6.06 6.6.9-4.8 4.6 1.2 6.6L12 17.5l-5.9 3.26 1.2-6.6-4.8-4.6 6.6-.9z"
                    fill="currentColor"/></svg></i>
          </span>
          <svg class="ic gh-ic" viewBox="0 0 24 24" aria-hidden="true">
            <path fill="currentColor" d="M10.226 17.284c-2.965-.36-5.054-2.493-5.054-5.256 0-1.123.404-2.336 1.078-3.144-.292-.741-.247-2.314.09-2.965.898-.112 2.111.36 2.83 1.01.853-.269 1.752-.404 2.853-.404 1.1 0 1.999.135 2.807.382.696-.629 1.932-1.1 2.83-.988.315.606.36 2.179.067 2.942.72.854 1.101 2 1.101 3.167 0 2.763-2.089 4.852-5.098 5.234.763.494 1.28 1.572 1.28 2.807v2.336c0 .674.561 1.056 1.235.786 4.066-1.55 7.255-5.615 7.255-10.646C23.5 6.188 18.334 1 11.978 1 5.62 1 .5 6.188.5 12.545c0 4.986 3.167 9.12 7.435 10.669.606.225 1.19-.18 1.19-.786V20.63a2.9 2.9 0 0 1-1.078.224c-1.483 0-2.359-.808-2.987-2.313-.247-.607-.517-.966-1.034-1.033-.27-.023-.359-.135-.359-.27 0-.27.45-.471.898-.471.652 0 1.213.404 1.797 1.235.45.651.921.943 1.483.943.561 0 .92-.202 1.437-.719.382-.381.674-.718.944-.943"/>
          </svg>
          <span>{{ t('join.github') }}</span>
        </a>

        <a id="join-qq" class="uv-btn join-btn join-btn-qq" href="#" @click.prevent="openQQ">
          <svg class="ic" viewBox="0 0 24 24" aria-hidden="true">
            <ellipse cx="12" cy="13" rx="7" ry="7.6" fill="none" stroke="currentColor" stroke-width="1.7"/>
            <path d="M7.6 6.4 6.1 3.6M16.4 6.4l1.5-2.8" fill="none" stroke="currentColor"
                  stroke-width="1.7" stroke-linecap="round"/>
            <circle cx="9.4" cy="12" r="1.15" fill="currentColor"/>
            <circle cx="14.6" cy="12" r="1.15" fill="currentColor"/>
            <path d="M9.6 16.2c1.4 1 3.4 1 4.8 0" fill="none" stroke="currentColor"
                  stroke-width="1.5" stroke-linecap="round"/>
          </svg>
          <span>{{ t('join.qq') }}</span>
        </a>
      </div>

      <div class="uv-modal-note join-note" :class="noteKind">{{ note }}</div>
    </div>
  </div>

  <!-- ---------------- "leave me a star" (vertical: art on top, copy below) ---------------- -->
  <div v-if="starOpen" class="uv-modal-backdrop" :class="{ leaving: starLeaving }" data-kind="star"
       @click.self="onStarBackdrop">
    <div class="uv-modal join star" role="dialog" aria-modal="true">
      <button class="uv-join-x" type="button" aria-label="close" @click="closeStar">✕</button>
      <img class="uv-modal-art star-art" :src="STAR" :alt="t('join.starAlt')">
      <h2 class="uv-modal-text">{{ t('join.starTitle') }}</h2>
      <p class="uv-modal-sub join-body" v-html="t('join.starBody')"></p>
      <div class="uv-modal-acts join-acts">
        <a id="star-go" class="uv-btn join-btn join-btn-lead" :href="GH" target="_blank"
           rel="noopener" @click.prevent="open(GH)">
          <svg class="ic" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 2.6l2.9 6.06 6.6.9-4.8 4.6 1.2 6.6L12 17.5l-5.9 3.26 1.2-6.6-4.8-4.6 6.6-.9z"
                  fill="currentColor"/>
          </svg>
          <span>{{ t('join.starGo') }}</span>
        </a>
        <button id="star-later" class="uv-btn join-btn" type="button" @click="closeStar">
          {{ t('join.starLater') }}
        </button>
      </div>
    </div>
  </div>

  <!-- ---------------- QQ group ---------------- -->
  <div v-if="qqOpen" class="uv-modal-backdrop" :class="{ leaving: qqLeaving }" data-kind="qq"
       @click.self="onQqBackdrop">
    <div class="uv-modal join qq" role="dialog" aria-modal="true">
      <button class="uv-join-x" type="button" aria-label="close" @click="closeQQ">✕</button>
      <img class="uv-modal-art qq-art" :src="QQIMG" :alt="t('join.qqAlt')">
      <h2 class="uv-modal-text">{{ t('join.qqTitle') }}</h2>
      <div class="uv-qq-no">
        <span>{{ t('join.qqNumber') }}</span>
        <b id="qq-no">{{ QQ_NO }}</b>
      </div>
      <p class="uv-modal-sub join-body" v-html="t('join.qqBody')"></p>
      <div class="uv-modal-acts join-acts">
        <button id="qq-copy" class="uv-btn join-btn join-btn-lead" type="button" @click="copyQQ">
          <span class="glyph">⧉</span><span>{{ t('join.qqCopy') }}</span>
        </button>
        <button id="qq-close" class="uv-btn join-btn" type="button" @click="closeQQ">
          {{ t('join.close') }}
        </button>
      </div>
      <div class="uv-modal-note join-note" :class="qqNoteKind">{{ qqNote }}</div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import { t } from '../i18n.js'

const props = defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['close'])

//: addressed at runtime from the public dir (see App.vue's BRAND note)
const ART = 'joinus.png'
const STAR = 'star.png'
const QQIMG = 'joinQQ.png'
const DISCORD = 'https://discord.com/invite/BGeYfMBwaw/login'
const GH = 'https://github.com/killa0132/CalaplayUpper'
const QQ_NO = '1054243070'
//: the user will fill in a real Bilibili link later; today it is a placeholder
const BILI = ''

const show = ref(false)
const leaving = ref(false)
const note = ref('')
const noteKind = ref('')

const starOpen = ref(false)
const starLeaving = ref(false)
const qqOpen = ref(false)
const qqLeaving = ref(false)
const qqNote = ref('')
const qqNoteKind = ref('')

const trace = []
function note_(what) {
  trace.push(what + '@' + Math.round(performance.now()))
  if (trace.length > 16) trace.splice(0, trace.length - 16)
  window.__calaJoinTrace = trace.slice()
  window.__calaJoinState = {
    show: show.value, star: starOpen.value, qq: qqOpen.value,
    leaving: leaving.value, last: what
  }
}
onMounted(() => note_('mount'))

watch(() => props.open, (v) => {
  note_('open=' + (v ? '1' : '0'))
  if (v) {
    show.value = true
    leaving.value = false
    note.value = ''
    noteKind.value = ''
  } else if (show.value) {
    close()
  }
})

//: only a real click dismisses a dialog (a synthetic one pumped in by the host
//: message loop must not close it -- same reason as StatusModal)
function onBackdrop(e) { if (e && e.isTrusted) close() }
function onStarBackdrop(e) { if (e && e.isTrusted) closeStar() }
function onQqBackdrop(e) { if (e && e.isTrusted) closeQQ() }

function fade(setOpen, setLeaving) {
  setLeaving(true)
  setTimeout(() => { setOpen(false); setLeaving(false) }, 220)
}

function close() {
  if (leaving.value) return
  note_('close()')
  //: closing the hub takes its popups with it
  if (starOpen.value) { starOpen.value = false; starLeaving.value = false }
  if (qqOpen.value) { qqOpen.value = false; qqLeaving.value = false }
  fade(() => { show.value = false }, (v) => { leaving.value = v })
  setTimeout(() => emit('close'), 230)
}

async function open(url) {
  note.value = ''
  noteKind.value = ''
  try {
    const r = await api.openUrl(url)
    if (r && r.ok) note.value = url
    else note.value = (r && r.message) || t('modal.exportFailed')
    noteKind.value = r && r.ok ? 'ok' : 'bad'
  } catch (e) {
    note.value = String(e.message || e)
    noteKind.value = 'bad'
  }
}

function openBili() {
  if (BILI) { open(BILI); return }
  note.value = t('join.soon')
  noteKind.value = ''
}

//: GitHub: open the real repository AND pop the "leave me a star" dialog
async function openGitHub() {
  note_('github')
  await open(GH)
  openStar()
}
function openStar() {
  note_('star-open')
  starLeaving.value = false
  starOpen.value = true
}
function closeStar() {
  if (!starOpen.value || starLeaving.value) return
  note_('star-close')
  fade(() => { starOpen.value = false }, (v) => { starLeaving.value = v })
}

async function copyQQ() {
  qqNote.value = ''
  qqNoteKind.value = ''
  try {
    const r = await api.copyText(QQ_NO)
    if (r && r.ok) { qqNote.value = t('join.qqCopied') + ' · ' + QQ_NO; qqNoteKind.value = 'ok' }
    else { qqNote.value = (r && r.message) || t('join.copyFailed'); qqNoteKind.value = 'bad' }
  } catch (e) {
    qqNote.value = t('join.copyFailed') + ': ' + (e.message || e)
    qqNoteKind.value = 'bad'
  }
}
async function openQQ() {
  note_('qq')
  qqLeaving.value = false
  qqOpen.value = true
  await copyQQ()               // "click = the number is already on your clipboard"
}
function closeQQ() {
  if (!qqOpen.value || qqLeaving.value) return
  note_('qq-close')
  fade(() => { qqOpen.value = false }, (v) => { qqLeaving.value = v })
}

//: 9 stars, each flying out of the button in its own direction / rhythm.  The
//: radius is deliberately modest: absolute children enlarge an ancestor's
//: scrollable overflow, and the wide radius was what pulled a horizontal
//: scrollbar out of the dialog on hover.
function flyVars(n) {
  const a = (n * 137.5) * Math.PI / 180
  const r = 13 + (n % 4) * 5
  return {
    '--dx': Math.round(Math.cos(a) * r) + 'px',
    '--dy': Math.round(Math.sin(a) * r - 5) + 'px',
    '--d': (1.5 + (n % 5) * 0.22).toFixed(2) + 's',
    '--delay': (-(n % 7) * 0.31).toFixed(2) + 's',
    '--s': (0.5 + (n % 3) * 0.18).toFixed(2)
  }
}

function state() {
  return {
    open: show.value, leaving: leaving.value,
    star: starOpen.value, starLeaving: starLeaving.value,
    qq: qqOpen.value, qqLeaving: qqLeaving.value,
    note: note.value, qqNote: qqNote.value, qqNo: QQ_NO, github: GH
  }
}
defineExpose({ state, close, open, openBili, openGitHub, openStar, closeStar,
               openQQ, closeQQ, copyQQ, isOpen: () => show.value })
</script>
