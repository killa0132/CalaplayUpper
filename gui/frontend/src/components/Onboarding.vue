<template>
  <!-- First-run guide: a dimming mask with a hole punched over the thing being
       talked about, plus a card that hops from step to step.  Art:
       gui/dist/hello.png (welcome) / guide.png (the steps) / end.png (bye). -->
  <div v-if="visible" class="uv-ob" :class="{ leaving, flat: !hole, ready }" :data-step="step">
    <div v-if="hole" class="uv-ob-hole" :style="box(hole)"></div>
    <div v-if="hole" class="uv-ob-ring" :style="box(hole)"></div>

    <div ref="cardRef" class="uv-ob-card" :style="cardStyle" role="dialog" aria-modal="true"
         :aria-label="s.title">
      <div class="uv-ob-hero">
        <img class="uv-ob-art" :src="s.art" alt="">
        <div class="uv-ob-body">
          <div class="uv-ob-kicker">{{ step + 1 }} / {{ steps.length }} · {{ s.kicker }}</div>
          <h2 class="uv-ob-title">{{ s.title }}</h2>
          <p class="uv-ob-text" v-html="s.text"></p>
        </div>
      </div>

      <div class="uv-ob-acts">
        <button class="uv-btn uv-btn-sm uv-btn-ghost ob-act" type="button" @click="skip">{{ t('ob.skip') }}</button>
        <span class="uv-ob-dots">
          <i v-for="(x, i) in steps" :key="i" :class="{ on: i === step, past: i < step }"></i>
        </span>
        <button v-if="step > 0" class="uv-btn uv-btn-sm ob-act" type="button" @click="prev">{{ t('ob.prev') }}</button>
        <button id="ob-next" class="uv-btn uv-btn-sm uv-btn-primary ob-act" type="button" @click="next">
          {{ step === steps.length - 1 ? t('ob.start') : t('ob.next') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { t } from '../i18n.js'
import { get as getPref, set as setPref } from '../prefs.js'

const KEY = 'cala-onboarded'
const emit = defineEmits(['done'])

//: `target` is a CSS selector -- the spotlight follows that element so the text
//: and the thing it talks about are never apart.  `art`/`kicker`/`title`/`text`
//: are dictionary keys, resolved through t() so the whole guide flips language
//: together with the rest of the page.
const STEPS = [
  { art: 'hello.png', kicker: 'ob.welcomeKicker', title: 'ob.welcomeTitle',
    text: 'ob.welcomeText', target: null },
  { art: 'guide.png', kicker: 'ob.pathKicker', title: 'ob.pathTitle',
    text: 'ob.pathText', target: '#card-inputs' },
  { art: 'guide.png', kicker: 'ob.dryKicker', title: 'ob.dryTitle',
    text: 'ob.dryText', target: '#card-options' },
  { art: 'guide.png', kicker: 'ob.forceKicker', title: 'ob.forceTitle',
    text: 'ob.forceText', target: '#opt-force' },
  { art: 'guide.png', kicker: 'ob.advKicker', title: 'ob.advTitle',
    text: 'ob.advText', target: '#opt-adv' },
  { art: 'guide.png', kicker: 'ob.runKicker', title: 'ob.runTitle',
    text: 'ob.runText', target: '#run' },
  { art: 'guide.png', kicker: 'ob.splitKicker', title: 'ob.splitTitle',
    text: 'ob.splitText', target: '#split' },
  { art: 'guide.png', kicker: 'ob.joinKicker', title: 'ob.joinTitle',
    text: 'ob.joinText', target: '#join' },
  { art: 'end.png', kicker: 'ob.endKicker', title: 'ob.endTitle',
    text: 'ob.endText', target: null }
]

const steps = computed(() => STEPS.map(s => ({
  art: s.art, target: s.target,
  kicker: t(s.kicker), title: t(s.title), text: t(s.text)
})))

const step = ref(0)
const visible = ref(false)
const leaving = ref(false)
//: did the guide open by itself (first run) or because someone asked for it?
//: the self-test asserts the pair: fresh profile -> auto, seen profile -> not.
const autoOpened = ref(false)
//: the entrance is a *transition* (see the CSS), so it needs a one-frame gap
//: between "mounted at opacity 0" and "ready".  Keyframes with fill-mode `both`
//: were the first attempt and they flickered: a WebView2 compositor resume can
//: restart a keyframe animation, which snapped the card back to opacity 0.
const ready = ref(false)
const hole = ref(null)                 // the highlighted element, viewport coords
const cardRef = ref(null)
const cardStyle = ref({ left: '0px', top: '0px', visibility: 'hidden' })
let timer = 0

const s = computed(() => steps.value[step.value])

function box(r) {
  return { left: r.x + 'px', top: r.y + 'px', width: r.w + 'px', height: r.h + 'px' }
}

function nextFrame() {
  return new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
}

//: the nearest ancestor that really scrolls (the left column is one; the right
//: column is `overflow: hidden`, i.e. programmatically scrollable but with
//: nothing to scroll -- calling scrollIntoView on it would offset the panes for
//: good, so it is skipped on purpose)
function scrollParent(el) {
  let p = el.parentElement
  while (p && p !== document.body) {
    const cs = getComputedStyle(p)
    if (/(auto|scroll|overlay)/.test(cs.overflowY) && p.scrollHeight > p.clientHeight + 4) return p
    p = p.parentElement
  }
  return null
}
function bringIntoView(el, r) {
  const sc = scrollParent(el)
  if (sc) {
    const sr = sc.getBoundingClientRect()
    sc.scrollTop += (r.top - sr.top) - (sc.clientHeight - r.height) / 2
  } else if (document.scrollingElement) {
    el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'auto' })
  }
}

//: Where the spotlight goes.  A target can sit below the fold (the left column
//: scrolls), and a spotlight on an off-screen element is useless -- so the
//: element is scrolled into view first and measured AGAIN afterwards.  If it is
//: still not (fully) on screen we hand back the visible intersection instead of
//: a rectangle nobody can see; if even that is a sliver, there is no hole at all
//: and the card centres itself (a blank spotlight is worse than no spotlight).
async function measure() {
  const sel = s.value.target
  if (!sel) return null
  const el = document.querySelector(sel)
  if (!el) return null
  let r = el.getBoundingClientRect()
  const off = (b) => b.top < 8 || b.bottom > window.innerHeight - 8
                    || b.left < 8 || b.right > window.innerWidth - 8
  if (off(r)) {
    bringIntoView(el, r)
    await nextFrame()
    r = el.getBoundingClientRect()
  }
  if (r.width < 4 || r.height < 4) return null
  const vw = window.innerWidth
  const vh = window.innerHeight
  const x1 = Math.max(0, r.left)
  const y1 = Math.max(0, r.top)
  const x2 = Math.min(vw, r.right)
  const y2 = Math.min(vh, r.bottom)
  if (x2 - x1 < 8 || y2 - y1 < 8) return null
  return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 }
}

//: place the card next to the spotlight (right when the target sits in the left
//: half, left otherwise) and clamp it into the window
async function layout() {
  hole.value = await measure()
  await nextTick()
  const el = cardRef.value
  if (!el) return
  const vw = window.innerWidth
  const vh = window.innerHeight
  const cw = el.offsetWidth || 380
  const ch = el.offsetHeight || 220
  const gap = 16
  let left
  let top
  const r = hole.value
  if (!r) {
    left = (vw - cw) / 2
    top = (vh - ch) / 2
  } else {
    left = (r.x + r.w / 2 > vw / 2) ? r.x - cw - gap : r.x + r.w + gap
    top = r.y + Math.min(28, r.h * 0.35)
    if (left < gap) left = (vw - cw) / 2
    if (left + cw > vw - gap) left = vw - cw - gap
    top = Math.min(Math.max(gap, top), Math.max(gap, vh - ch - gap))
  }
  cardStyle.value = {
    left: Math.round(Math.max(gap, left)) + 'px',
    top: Math.round(top) + 'px',
    visibility: 'visible'
  }
}

function onResize() {
  if (!visible.value) return
  clearTimeout(timer)
  timer = setTimeout(layout, 90)
}

function onKey(e) {
  if (!visible.value) return
  if (e.key === 'Escape') { skip(); e.preventDefault() }
  else if (e.key === 'ArrowRight' || e.key === 'Enter') { next(); e.preventDefault() }
  else if (e.key === 'ArrowLeft' && step.value > 0) { prev(); e.preventDefault() }
}

function next() {
  if (step.value >= steps.value.length - 1) { finish(); return }
  step.value += 1
}
function prev() {
  if (step.value > 0) step.value -= 1
}
function finish() {
  if (leaving.value) return
  leaving.value = true
  //: durable, not localStorage: the page's origin carries a fresh random port
  //: on every launch, so localStorage here was per-launch and the guide came
  //: back every single time.  See gui/prefs.py.
  setPref(KEY, '1')
  setTimeout(() => {
    visible.value = false
    leaving.value = false
    emit('done')
  }, 200)
}
function skip() { finish() }

function restart(from = 0) {
  clearTimeout(timer)
  autoOpened.value = false
  step.value = Math.min(Math.max(0, from), steps.value.length - 1)
  leaving.value = false
  ready.value = false
  visible.value = true
  layout()
  nextTick(() => { ready.value = true })
}

watch(step, () => { if (visible.value) layout() })
// a language switch re-renders the copy (and can change the card size), so the
// tooltip has to be re-measured and re-placed
watch(() => steps.value, () => { if (visible.value) layout() })

onMounted(() => {
  window.addEventListener('resize', onResize)
  window.addEventListener('keydown', onKey)
  // "只在首次打开时自动弹出": the flag now comes from prefs.json, which really
  // does survive the next launch (main.js has already loaded it before mount)
  const done = getPref(KEY) === '1'
  if (!done) {
    visible.value = true
    autoOpened.value = true
    nextTick(() => { ready.value = true })
    nextTick(layout)
  }
})
onBeforeUnmount(() => {
  clearTimeout(timer)
  window.removeEventListener('resize', onResize)
  window.removeEventListener('keydown', onKey)
})

//: the automation/test surface (also used by gui/desktop.py --selftest)
function state() {
  const el = document.querySelector('.uv-ob-hole')
  const im = document.querySelector('.uv-ob-art')
  let mask = null
  if (el) {
    const r = el.getBoundingClientRect()
    mask = { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) }
  }
  let stored = false
  try { stored = getPref(KEY) === '1' } catch (e) { /* ignore */ }
  const card = document.querySelector('.uv-ob-card')
  return {
    visible: visible.value, leaving: leaving.value,
    auto: autoOpened.value,
    step: step.value, total: steps.value.length,
    art: s.value.art, artOk: im ? !!(im.complete && im.naturalWidth > 0) : false,
    kicker: s.value.kicker, title: s.value.title,
    //: plain text (tags stripped) so a test can assert on the copy itself
    text: String(s.value.text || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim(),
    target: s.value.target || '',
    //: the footer must never wrap or squeeze its buttons
    acts: card ? (() => {
      const f = card.querySelector('.uv-ob-acts')
      if (!f) return null
      const r = f.getBoundingClientRect()
      const bw = Array.prototype.map.call(f.querySelectorAll('button'),
        b => Math.round(b.getBoundingClientRect().width))
      const bh = Array.prototype.map.call(f.querySelectorAll('button'),
        b => Math.round(b.getBoundingClientRect().height))
      const cardW = card.getBoundingClientRect().width
      const lines = new Set(Array.prototype.map.call(f.querySelectorAll('button'),
        b => Math.round(b.getBoundingClientRect().top)))
      return { w: Math.round(r.width), cardW: Math.round(cardW),
               btns: bw.length, btnH: bh, rows: lines.size,
               nowrap: getComputedStyle(f).flexWrap,
               overflow: Math.round(f.scrollWidth - f.clientWidth) }
    })() : null,
    hole: hole.value ? { x: Math.round(hole.value.x), y: Math.round(hole.value.y),
                         w: Math.round(hole.value.w), h: Math.round(hole.value.h) } : null,
    mask, stored
  }
}
defineExpose({ state, next, prev, finish, skip, restart })
</script>
