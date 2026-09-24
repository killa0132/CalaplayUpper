<template>
  <!-- ReactBits "Squish Switch", ported to Vue.
       The mechanism is kept: the knob is driven by a real spring integrator (no
       CSS transition), and the *velocity* of that spring stretches the knob along
       the travel axis while squashing it on the other one -- that is the squish.
       Hovering swells it slightly, dragging past a 4 px slop picks it up. -->
  <button :id="id" type="button" class="uv-ss" role="switch"
          :aria-checked="on ? 'true' : 'false'" :aria-disabled="disabled || undefined"
          :aria-label="ariaLabel" :data-on="on ? '' : undefined"
          :data-held="dragging ? '' : undefined" :style="styleVars"
          @pointerdown="down" @pointermove="move"
          @pointerup="up($event, false)" @pointercancel="up($event, true)"
          @pointerenter="enter" @pointerleave="leave">
    <span ref="trackEl" class="uv-ss-track">
      <span v-if="offLabel" class="uv-ss-face f-l" :class="{ dim: on }">{{ offLabel }}</span>
      <span v-if="onLabel" class="uv-ss-face f-r" :class="{ dim: !on }">{{ onLabel }}</span>
      <span ref="thumbEl" class="uv-ss-thumb" aria-hidden="true"></span>
    </span>
    <span v-if="label" class="uv-ss-label">{{ label }}</span>
  </button>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  checked: { type: Boolean, required: true },
  id: { type: String, default: 'squish-switch' },
  label: { type: String, default: '' },
  offLabel: { type: String, default: '' },
  onLabel: { type: String, default: '' },
  ariaLabel: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  width: { type: Number, default: 76 },
  height: { type: Number, default: 34 },
  //: 0 = the ReactBits default (a square knob); set it for a 2-face segmented look
  thumbWidth: { type: Number, default: 0 },
  speed: { type: Number, default: 50 },
  stretch: { type: Number, default: 36 },
  hoverScale: { type: Number, default: 1.035 }
})
const emit = defineEmits(['change'])

const MAX_STRETCH = 0.4
const STRETCH_SPEED = 600
const TAP_SLOP = 4
const FLOW_SPRING = { stiffness: 320, damping: 40, mass: 0.6 }
const SWELL_SPRING = { stiffness: 520, damping: 34, mass: 0.6 }

const trackEl = ref(null)
const thumbEl = ref(null)
const dragging = ref(false)

const inset = Math.max(3, Math.round(props.height * 0.11))
const thumbSize = props.thumbWidth > 0
  ? Math.round(props.thumbWidth)
  : props.height - inset * 2
const min = inset
const max = props.width - inset - thumbSize
const mid = (min + max) / 2
const gain = Math.max(0, Math.min(100, props.stretch)) / 100
const travelStiffness = 170 - (50 - Math.max(0, Math.min(100, props.speed))) * 1.1

const on = computed(() => props.checked)
const styleVars = computed(() => ({
  '--ss-w': props.width + 'px',
  '--ss-h': props.height + 'px',
  '--ss-inset': inset + 'px',
  '--ss-thumb': thumbSize + 'px',
  '--ss-r': Math.min(props.height / 2, props.height / 2) + 'px',
  '--ss-thumb-r': Math.max(2, props.height / 2 - inset) + 'px'
}))

//: two springs, integrated in one rAF loop (this is what framer-motion did for
//: the original: `x` with a travel spring, `swell` with a stiffer one)
const travel = { x: on.value ? max : min, v: 0 }
const flow = { x: 0, v: 0 }
const swell = { x: 1, v: 0 }
let raf = null
let last = 0

function step(s, target, cfg, dt) {
  const a = (-cfg.stiffness * (s.x - target) - cfg.damping * s.v) / cfg.mass
  s.v += a * dt
  s.x += s.v * dt
}

function stretchOf(v) {
  return 1 + Math.min(MAX_STRETCH, Math.abs(v) / STRETCH_SPEED) * gain
}

function frame(now) {
  const dt = Math.min(Math.max((now - last) / 1000, 0.001), 0.05)
  last = now
  if (!dragging.value) step(travel, on.value ? max : min, { stiffness: travelStiffness, damping: 21.5, mass: 0.9 }, dt)
  step(flow, travel.v, FLOW_SPRING, dt)
  step(swell, swell.target, SWELL_SPRING, dt)

  const el = thumbEl.value
  if (el) {
    const st = stretchOf(flow.x)
    el.style.transform = 'translateX(' + travel.x.toFixed(2) + 'px) scaleX('
      + (st * swell.x).toFixed(4) + ') scaleY(' + (swell.x / st).toFixed(4) + ')'
  }
  const settled = Math.abs(travel.x - (on.value ? max : min)) < 0.05
    && Math.abs(travel.v) < 0.8
    && Math.abs(flow.x) < 1 && Math.abs(flow.v) < 1
    && Math.abs(swell.x - swell.target) < 0.001 && Math.abs(swell.v) < 0.01
  if (settled && !dragging.value) {
    if (el) {
      el.style.transform = 'translateX(' + (on.value ? max : min).toFixed(2) + 'px) scaleX(1) scaleY(1)'
    }
    raf = null
    return
  }
  raf = requestAnimationFrame(frame)
}

function start() {
  if (raf !== null) return
  last = performance.now()
  raf = requestAnimationFrame(frame)
}

swell.target = 1

let grip = null
function localX(clientX) {
  const el = trackEl.value
  if (!el) return 0
  return clientX - el.getBoundingClientRect().left
}
function down(e) {
  if (props.disabled || e.button !== 0) return
  grip = { id: e.pointerId, grab: null, moved: false, startX: e.clientX, onAtPress: on.value }
  try { e.currentTarget.setPointerCapture(e.pointerId) } catch (err) { /* ignore */ }
  dragging.value = true
  swell.target = props.hoverScale
  start()
}
function move(e) {
  if (!grip || grip.id !== e.pointerId) return
  const lx = localX(e.clientX)
  if (grip.grab === null) { grip.grab = lx - travel.x; return }
  if (!grip.moved && Math.abs(e.clientX - grip.startX) > TAP_SLOP) grip.moved = true
  if (!grip.moved) return
  const nx = Math.min(max, Math.max(min, lx - grip.grab))
  travel.v = 0
  flow.x = (nx - travel.x) * 60        // keep the squish reading the drag speed
  travel.x = nx
  commit(nx > mid)
}
function up(e, cancelled) {
  if (!grip || grip.id !== e.pointerId) return
  const g = grip
  grip = null
  try { e.currentTarget.releasePointerCapture(e.pointerId) } catch (err) { /* ignore */ }
  dragging.value = false
  swell.target = props.hoverScale
  if (cancelled) commit(g.onAtPress)
  else if (!g.moved) commit(!g.onAtPress)
  start()
}
function commit(next) {
  if (next === on.value) return
  emit('change', next)
}
function enter() { swell.target = props.disabled ? 1 : props.hoverScale; start() }
function leave() { swell.target = 1; start() }

watch(() => props.checked, () => start())
onMounted(() => {
  travel.x = on.value ? max : min
  if (thumbEl.value) {
    thumbEl.value.style.transform = 'translateX(' + travel.x.toFixed(2) + 'px)'
  }
  start()
})
onBeforeUnmount(() => { if (raf !== null) cancelAnimationFrame(raf); raf = null })

//: for the self-test: read the live knob state (position + squish scale)
function probe() {
  const el = thumbEl.value
  const tr = el ? getComputedStyle(el).transform : ''
  let tx = 0; let sx = 1; let sy = 1
  const m = /matrix\(([^)]+)\)/.exec(tr)
  if (m) {
    const p = m[1].split(',').map(Number)
    sx = p[0]; sy = p[3]; tx = p[4]
  }
  return { on: on.value, tx: Math.round(tx * 100) / 100, sx: Math.round(sx * 10000) / 10000,
           sy: Math.round(sy * 10000) / 10000, min: min, max: max, dragging: dragging.value }
}
defineExpose({ probe })
</script>

<style scoped>
/* The track/knob colours follow the theme; the knob travel + squish are written
   per frame by the spring loop above, so there is deliberately no CSS transition
   on the transform (a transition would fight the spring). */
.uv-ss {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 9px;
  margin: 0;
  padding: 0;
  border: 0;
  background: none;
  cursor: pointer;
  outline: none;
  touch-action: pan-y;
  user-select: none;
  -webkit-tap-highlight-color: transparent;
}
.uv-ss::after { content: ''; position: absolute; inset: -8px; }
.uv-ss[data-held] { cursor: grabbing; }
.uv-ss[aria-disabled='true'] { cursor: not-allowed; opacity: .5; }

.uv-ss-track {
  position: relative;
  display: block;
  width: var(--ss-w);
  height: var(--ss-h);
  border-radius: var(--ss-r);
  border: 1px solid var(--panel-line);
  background: color-mix(in srgb, var(--ink) 16%, var(--panel-solid));
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, .35);
  overflow: hidden;
  transition: background .32s var(--ease), border-color .32s var(--ease);
}
.uv-ss[data-on] .uv-ss-track {
  background: linear-gradient(100deg, var(--c1), var(--c2));
  border-color: transparent;
}

.uv-ss-thumb {
  position: absolute;
  top: var(--ss-inset);
  left: 0;
  width: var(--ss-thumb);
  height: var(--ss-thumb);
  border-radius: var(--ss-thumb-r);
  background: var(--panel-solid);
  box-shadow: 0 1px 4px rgba(0, 0, 0, .35);
  will-change: transform;
  transform-origin: center center;
}
.uv-ss[data-on] .uv-ss-thumb {
  background: #10141c;
  box-shadow: 0 1px 5px rgba(0, 0, 0, .45);
}

/* the two faces inside the track (opt-in): the one that is active stays crisp */
.uv-ss-face {
  position: absolute;
  top: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: var(--ss-thumb);
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: .02em;
  color: var(--ink);
  pointer-events: none;
  transition: color .3s var(--ease), opacity .3s var(--ease);
}
/* NB: the face classes are deliberately .f-l/.f-r and not .left/.right -- a
   generic `.left` here would shadow the app's `.grid > .left` column for any
   document.querySelector('.left') (the layout probe found that the hard way). */
.uv-ss-face.f-l { left: var(--ss-inset); }
.uv-ss-face.f-r { right: var(--ss-inset); }
.uv-ss-face.dim { opacity: .45; color: var(--ink-dim); }
.uv-ss-label { font-size: 12.5px; font-weight: 700; color: var(--ink); }
</style>
