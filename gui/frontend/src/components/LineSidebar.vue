<template>
  <!-- ReactBits "Line Sidebar", ported to Vue.
       The original is a React component; the mechanism is kept verbatim:
       one rAF loop eases a per-item `--effect` (0..1) with frame-rate
       independent exponential smoothing, and every derived property
       (translateX, colour mix, marker scale) reads that same value -- so the
       row slides towards the cursor and lights up without staggered CSS
       transitions.  Rows marked `is-active` (a toggle that is on, an expanded
       section) are pinned at full effect. -->
  <nav class="uv-ls" :class="{ 'uv-ls--markers': showMarker, 'uv-ls--scale-tick': scaleTick }"
       :style="vars">
    <ul ref="list" class="uv-ls-list" @pointermove="onMove" @pointerleave="onLeave">
      <li v-for="(it, i) in items" :key="it.id || i" :id="it.domId"
          class="uv-ls-item" :class="{ 'is-active': activeIds.indexOf(it.id) >= 0 }"
          :data-ls-id="it.id"
          :aria-current="activeIds.indexOf(it.id) >= 0 ? 'true' : undefined">
        <span v-if="showMarker" class="uv-ls-marker" aria-hidden="true"></span>
        <div class="uv-ls-row" :data-ls-row="it.id" @click="$emit('pick', it, i)">
          <span v-if="showIndex" class="uv-ls-index">{{ String(i + 1).padStart(2, '0') }}</span>
          <span class="uv-ls-label"><slot name="item" :item="it" :index="i">{{ it.label }}</slot></span>
          <span class="uv-ls-side"><slot name="side" :item="it" :index="i" /></span>
        </div>
        <div v-if="$slots.extra" class="uv-ls-extra" :data-ls-extra="it.id"><slot name="extra" :item="it" :index="i" /></div>
      </li>
    </ul>
  </nav>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  //: item ids pinned at full effect (e.g. the toggles that are currently on)
  activeIds: { type: Array, default: () => [] },
  showIndex: { type: Boolean, default: true },
  showMarker: { type: Boolean, default: true },
  scaleTick: { type: Boolean, default: true },
  proximityRadius: { type: Number, default: 96 },
  maxShift: { type: Number, default: 12 },
  markerLength: { type: Number, default: 24 },
  markerGap: { type: Number, default: 8 },
  tickScale: { type: Number, default: 0.5 },
  itemGap: { type: Number, default: 10 },
  smoothing: { type: Number, default: 110 },
  //: linear | smooth | sharp
  falloff: { type: String, default: 'smooth' }
})
defineEmits(['pick'])

const FALLOFF = {
  linear: p => p,
  smooth: p => p * p * (3 - 2 * p),
  sharp: p => p * p * p
}

const list = ref(null)
const targets = []
const current = []
let raf = null
let last = 0

const vars = computed(() => ({
  '--ls-marker-len': props.markerLength + 'px',
  '--ls-marker-gap': props.markerGap + 'px',
  '--ls-tick-scale': props.tickScale,
  '--ls-shift': props.maxShift + 'px',
  '--ls-item-gap': props.itemGap + 'px'
}))

//: read the rows straight from the DOM -- a function ref would accumulate
//: duplicates on every re-render, and these are purely visual children anyway
function rows() {
  const ul = list.value
  return ul ? Array.prototype.slice.call(ul.children) : []
}

function frame(now) {
  const dt = Math.min((now - last) / 1000, 0.05)
  last = now
  const k = 1 - Math.exp(-dt / (Math.max(props.smoothing, 1) / 1000))
  let moving = false
  const els = rows()
  for (let i = 0; i < els.length; i++) {
    const el = els[i]
    const target = Math.max(targets[i] || 0, el.classList.contains('is-active') ? 1 : 0)
    const cur = current[i] || 0
    const next = cur + (target - cur) * k
    const settled = Math.abs(target - next) < 0.0015
    const value = settled ? target : next
    current[i] = value
    el.style.setProperty('--effect', value.toFixed(4))
    if (!settled) moving = true
  }
  raf = moving ? requestAnimationFrame(frame) : null
}

function start() {
  if (raf !== null) cancelAnimationFrame(raf)
  last = performance.now()
  raf = requestAnimationFrame(frame)
}

function onMove(e) {
  const ul = list.value
  if (!ul) return
  const rect = ul.getBoundingClientRect()
  const py = e.clientY - rect.top
  const ease = FALLOFF[props.falloff] || FALLOFF.linear
  const els = rows()
  for (let i = 0; i < els.length; i++) {
    const el = els[i]
    // exact centres: getBoundingClientRect is immune to whatever the offsetParent
    // happens to be (the React original uses offsetTop, which is only equivalent
    // when the nav itself is the offsetParent)
    const r = el.getBoundingClientRect()
    const center = r.top - rect.top + r.height / 2
    targets[i] = ease(Math.max(0, 1 - Math.abs(py - center) / props.proximityRadius))
  }
  start()
}

function onLeave() {
  for (let i = 0; i < targets.length; i++) targets[i] = 0
  start()
}

//: for the self-test: kick the effect from a synthetic pointer position
function poke(clientY) {
  const ul = list.value
  if (!ul) return false
  const rect = ul.getBoundingClientRect()
  ul.dispatchEvent(new PointerEvent('pointermove', {
    bubbles: true, clientY, clientX: Math.round(rect.left + 40)
  }))
  return true
}

onMounted(() => { start() })
onBeforeUnmount(() => { if (raf !== null) cancelAnimationFrame(raf); raf = null })

defineExpose({ poke })
</script>

<style scoped>
/* `--effect` (0..1) is written per <li> by the rAF loop above; everything below
   reads that one value so shift, colour and scale never drift apart. */
.uv-ls { position: relative; padding-left: calc(var(--ls-marker-len, 24px) + var(--ls-marker-gap, 8px)); }
.uv-ls-list {
  list-style: none; margin: 0; padding: 0;
  display: flex; flex-direction: column; gap: var(--ls-item-gap, 10px);
}
.uv-ls-item { position: relative; }
/* widen the pointer target so a row reacts a touch before the cursor arrives */
.uv-ls-item::before { content: ''; position: absolute; inset: -5px -18px; }

.uv-ls-row {
  position: relative;
  display: flex; align-items: center; gap: 6px;
  cursor: pointer;
  transform: translateX(calc(var(--effect, 0) * var(--ls-shift, 12px)));
}
.uv-ls-index {
  flex: none;
  font-family: Consolas, "Cascadia Mono", monospace;
  font-size: 10.5px;
  letter-spacing: .04em;
  color: var(--ink-dim);
  opacity: calc(0.55 + var(--effect, 0) * 0.45);
}
.uv-ls-label {
  flex: 1 1 auto; min-width: 0;
  overflow: hidden;
  /* the ReactBits colour mix: the text colour slides into the accent as the
     cursor gets close (the accent is handed in from the page, chongci palette) */
  color: color-mix(in srgb, var(--ls-accent, var(--c2)) calc(var(--effect, 0) * 100%), var(--ink-soft));
}
/* the right-hand control (a switch, a dropdown chip) gives way before the label
   does -- a 4-character label must never be broken into two lines */
.uv-ls-side { flex: 0 1 auto; min-width: 0; display: inline-flex; align-items: center; }

/* the little line on the left (it does NOT translate -- only the row does) */
.uv-ls-marker {
  position: absolute;
  top: 50%;
  left: calc(-1 * var(--ls-marker-len, 24px) - var(--ls-marker-gap, 8px));
  height: 2px;
  width: var(--ls-marker-len, 24px);
  border-radius: 2px;
  background: color-mix(in srgb, var(--ls-accent, var(--c2)) calc(var(--effect, 0) * 100%), var(--ink-dim));
  transform-origin: left center;
  transform: translateY(-50%) scaleX(calc(0.62 + var(--effect, 0) * 0.55));
  transition: box-shadow .25s var(--ease);
}
.uv-ls-item.is-active .uv-ls-marker {
  box-shadow: 0 0 10px -1px color-mix(in srgb, var(--ls-accent, var(--c2)) 70%, transparent);
}

/* short static tick between two items */
.uv-ls--markers .uv-ls-item:not(:last-child)::after {
  content: '';
  position: absolute;
  top: calc(100% + var(--ls-item-gap, 10px) / 2);
  left: calc(-1 * var(--ls-marker-len, 24px) - var(--ls-marker-gap, 8px));
  height: 1px;
  width: calc(var(--ls-marker-len, 24px) * var(--ls-tick-scale, .5));
  background: var(--ink-dim);
  opacity: .45;
  transform: translateY(-50%);
  transform-origin: left center;
}
.uv-ls--scale-tick .uv-ls-item:not(:last-child)::after {
  transform: translateY(-50%) scaleX(calc(0.7 + var(--effect, 0) * 0.6));
}
.uv-ls-extra { margin-top: 8px; }
</style>
