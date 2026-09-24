<template>
  <!-- ReactBits "Glide Select", ported to Vue.
       Kept from the original: the popup's highlight is a single "pill" element
       that *glides* to the hovered/active row (`translateY(row * step)`), the
       menu pops with a scale/opacity transition and a top/bottom flip when there
       is no room, pointer scrubbing picks a row, and the label plays a small
       blur-swap animation when the value changes. -->
  <div ref="root" class="uv-gs" :data-size="size" :data-disabled="disabled ? '' : undefined"
       :style="vars">
    <button ref="trigger" class="uv-gs-trigger" type="button" role="combobox"
            aria-haspopup="listbox" :aria-expanded="phase === 'open' ? 'true' : 'false'"
            :aria-label="ariaLabel" :disabled="disabled"
            @pointerdown="onTriggerDown" @keydown="onKey">
      <span class="uv-gs-label" :data-empty="selected < 0 ? '' : undefined">{{ label }}</span>
      <span class="uv-gs-chev" aria-hidden="true">
        <svg viewBox="0 0 24 24"><path d="M6.5 9.5 12 15.2 17.5 9.5" fill="none" stroke="currentColor"
          stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </span>
    </button>

    <!-- Teleported to <body>: the popup used to live inside the options card,
         which is a stacking context (backdrop-filter) *and* whose rows carry
         z-index -- so the list painted BEHIND the next row (DryRun) and clicks
         landed on that row instead of on "contain".  Fixed + body-level, it is
         simply above everything. -->
    <Teleport to="body">
      <div v-if="phase !== 'closed'" ref="menu" class="uv-gs-menu" :data-state="menuState"
           :data-side="side" :style="[vars, menuStyle]">
        <div class="uv-gs-list" :data-live="active !== null ? '' : undefined"
             @pointerleave="onListLeave" @pointerdown="onListDown" @pointermove="onListMove"
             @pointerup="onListUp" @pointercancel="onListUp">
          <span ref="pill" class="uv-gs-pill" aria-hidden="true"></span>
          <div v-for="(it, i) in items" :key="it.value" class="uv-gs-opt" :data-index="i"
               role="option" :aria-selected="i === selected ? 'true' : 'false'"
               :id="listId + '-' + i" @pointerover="onOver">
            <span class="uv-gs-name">{{ it.label }}</span>
            <span v-if="showTags && it.tag" class="uv-gs-tag">{{ it.tag }}</span>
            <span class="uv-gs-check" :data-on="i === selected ? '' : undefined" aria-hidden="true">
              <svg viewBox="0 0 24 24"><path d="M5 12.6 9.4 17 19 7.2" fill="none" stroke="currentColor"
                stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </span>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  options: { type: Array, default: () => [] },
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: 'Select…' },
  size: { type: String, default: 'md' },              // sm | md | lg
  radius: { type: Number, default: 10 },
  menuMinWidth: { type: Number, default: 168 },
  showTags: { type: Boolean, default: true },
  rememberPosition: { type: Boolean, default: true },
  disabled: { type: Boolean, default: false },
  ariaLabel: { type: String, default: 'Select' },
  popDuration: { type: Number, default: 180 },
  glideDuration: { type: Number, default: 220 }
})
const emit = defineEmits(['update:modelValue', 'change'])

const SIZES = {
  sm: { chip: 27, row: 25, font: 11.5 },
  md: { chip: 31, row: 29, font: 12.5 },
  lg: { chip: 40, row: 36, font: 13.5 }
}
const GAP = 1
const PAD = 4
const MENU_GAP = 6

const root = ref(null)
const trigger = ref(null)
const pill = ref(null)
const menu = ref(null)
const phase = ref('closed')          // closed | open | closing
const menuState = ref('open')
const active = ref(null)
const side = ref('bottom')
const menuStyle = ref({})
const listId = 'gs-list'
//: breadcrumbs for the self-test.  Without them a popup that "closed but did
//: not pick" is invisible from the outside -- you cannot tell whether the
//: pointer events ever reached the rows.
const trace = []
function tr(what) {
  trace.push(what + '@' + Math.round(performance.now()))
  if (trace.length > 24) trace.splice(0, trace.length - 24)
  window.__calaGsTrace = trace.slice()
}
let closeTimer = null
let scrub = null
let instant = false

const S = computed(() => SIZES[props.size] || SIZES.md)
const items = computed(() => props.options.map(o => (typeof o === 'string' ? { value: o, label: o } : o)))
const selected = computed(() => items.value.findIndex(it => it.value === props.modelValue))
//: the trigger may show a shorter form than the menu row (`short`), so a long
//: explanation does not squeeze the label next to it
const label = computed(() => {
  if (selected.value < 0) return props.placeholder
  const it = items.value[selected.value]
  return it.short || it.label
})
const step = computed(() => S.value.row + GAP)
//: the popup is at body level, so it no longer inherits the --gs-* custom
//: properties set on `.uv-gs` -- the whole menu would fall back to `auto` row
//: heights and the pill would glide on a different pitch than the rows it is
//: supposed to highlight.  The vars ride on BOTH elements on purpose.
const vars = computed(() => ({
  '--gs-radius': props.radius + 'px',
  '--gs-inner-radius': Math.max(3, props.radius - 4) + 'px',
  '--gs-chip': S.value.chip + 'px',
  '--gs-row': S.value.row + 'px',
  '--gs-font': S.value.font + 'px',
  '--gs-menu-w': Math.max(props.menuMinWidth, 120) + 'px',
  '--gs-pop': props.popDuration + 'ms',
  '--gs-pop-out': Math.round((props.popDuration * 2) / 3) + 'ms',
  '--gs-glide': props.glideDuration + 'ms'
}))

function movePill(i, animate) {
  const p = pill.value
  if (!p) return
  if (i === null || i === undefined) { p.style.opacity = '0'; return }
  const jump = instant || p.style.opacity !== '1'
  p.style.transitionDuration = (animate === false || jump) ? '0ms, 150ms' : ''
  p.style.transform = 'translateY(' + (i * step.value) + 'px)'
  p.style.opacity = '1'
  instant = false
}

//: the popup is `position: fixed` at body level, so it has to be told where the
//: trigger currently is (and it re-anchors on scroll/resize while it is open)
function place() {
  const el = menu.value
  const tr = trigger.value
  if (!el || !tr) return
  const r = tr.getBoundingClientRect()
  const w = Math.max(props.menuMinWidth, Math.round(r.width))
  const h = el.offsetHeight
  const below = window.innerHeight - r.bottom - MENU_GAP
  const above = r.top - MENU_GAP
  const flip = below < h && above > below
  side.value = flip ? 'top' : 'bottom'
  const left = Math.min(Math.max(8, r.left), Math.max(8, window.innerWidth - 8 - w))
  const top = flip ? Math.max(8, r.top - MENU_GAP - h) : r.bottom + MENU_GAP
  menuStyle.value = {
    left: Math.round(left) + 'px',
    top: Math.round(top) + 'px',
    width: w + 'px'
  }
}

function onViewport() { if (phase.value === 'open') place() }

async function open(viaKey) {
  if (props.disabled) return
  clearTimeout(closeTimer)
  tr('open' + (viaKey ? ':key' : ''))
  instant = true
  active.value = selected.value >= 0 ? selected.value : (viaKey ? 0 : null)
  phase.value = 'open'
  menuState.value = 'open'
  await nextTick()
  place()
  const el = menu.value
  if (el) {
    el.dataset.state = 'closed'
    void el.offsetHeight
    el.dataset.state = 'open'
  }
  const p = pill.value
  if (p) {
    p.style.transition = 'none'
    p.style.transform = 'translateY(' + (Math.max(0, selected.value) * step.value) + 'px)'
    p.style.opacity = '0'
    void p.offsetHeight
    p.style.transition = ''
  }
  movePill(active.value, false)
  document.addEventListener('pointerdown', onOutside, true)
  window.addEventListener('scroll', onViewport, true)
  window.addEventListener('resize', onViewport)
}

function close(mode) {
  tr('close:' + mode)
  document.removeEventListener('pointerdown', onOutside, true)
  window.removeEventListener('scroll', onViewport, true)
  window.removeEventListener('resize', onViewport)
  active.value = null
  clearTimeout(closeTimer)
  if (mode === 'instant' || !menu.value) { phase.value = 'closed'; return }
  menuState.value = 'closed'
  menu.value.dataset.state = 'closed'
  phase.value = 'closing'
  closeTimer = setTimeout(() => { phase.value = 'closed' }, props.popDuration + 20)
}

function onOutside(e) {
  const r = root.value
  const m = menu.value
  if (r && r.contains(e.target)) return
  if (m && m.contains(e.target)) return          // the popup is not a child any more
  tr('outside')
  close('pop')
}

function pick(i, viaKey) {
  const it = items.value[i]
  tr('pick:' + i + (viaKey ? ':key' : '') + '=' + (it ? it.value : 'none'))
  if (!it) { close('instant'); return }
  if (it.value !== props.modelValue) {
    emit('update:modelValue', it.value)
    emit('change', it.value, it)
    if (!viaKey && root.value) {
      root.value.dataset.swap = ''
      setTimeout(() => { if (root.value) delete root.value.dataset.swap }, 200)
    }
  }
  close('instant')
  if (trigger.value) trigger.value.focus({ preventScroll: true })
}

function onTriggerDown(e) {
  if (e.button !== 0 || props.disabled) return
  e.currentTarget.focus({ preventScroll: true })
  if (phase.value === 'open') close('pop')
  else open(false)
}

function onKey(e) {
  const k = e.key
  const n = items.value.length
  if (phase.value !== 'open') {
    if (k === 'Enter' || k === ' ' || k === 'ArrowDown' || k === 'ArrowUp') {
      e.preventDefault(); open(true)
    }
    return
  }
  const cur = active.value === null ? Math.max(0, selected.value) : active.value
  if (k === 'ArrowDown' || k === 'ArrowUp') {
    e.preventDefault(); instant = true
    active.value = Math.min(n - 1, Math.max(0, cur + (k === 'ArrowDown' ? 1 : -1)))
  } else if (k === 'Home' || k === 'End') {
    e.preventDefault(); instant = true
    active.value = k === 'Home' ? 0 : n - 1
  } else if (k === 'Enter' || k === ' ') {
    e.preventDefault(); pick(cur, true)
  } else if (k === 'Escape' || k === 'Tab') {
    if (k === 'Escape') e.preventDefault()
    close('instant')
  }
}

function rowAt(y) {
  if (!scrub) return null
  const i = Math.floor((y - scrub.top - PAD) / step.value)
  return i >= 0 && i < items.value.length ? i : null
}
function onListDown(e) {
  if (scrub) return
  tr('down:' + Math.round(e.clientY))
  try { e.currentTarget.setPointerCapture(e.pointerId) } catch (err) { /* ignore */ }
  scrub = { id: e.pointerId, top: e.currentTarget.getBoundingClientRect().top }
  instant = true
  active.value = rowAt(e.clientY)
  tr('down@' + active.value)
}
function onListMove(e) {
  if (!scrub || scrub.id !== e.pointerId) return
  const i = rowAt(e.clientY)
  if (i !== active.value) active.value = i
}
function onListUp(e) {
  if (!scrub || scrub.id !== e.pointerId) return
  const i = e.type === 'pointerup' ? rowAt(e.clientY) : null
  tr('up:' + Math.round(e.clientY) + '->' + i)
  scrub = null
  if (i !== null) pick(i, false)
  else if (!props.rememberPosition) active.value = null
}
function onOver(e) {
  if (e.pointerType === 'touch' || scrub) return
  const row = e.target.closest('[data-index]')
  if (!row) return
  const i = Number(row.dataset.index)
  if (i !== active.value) active.value = i
}
function onListLeave() {
  if (!scrub && !props.rememberPosition) active.value = null
}

watch(active, (v) => { if (phase.value === 'open') movePill(v) })
watch(() => props.disabled, (v) => { if (v && phase.value !== 'closed') close('instant') })
onBeforeUnmount(() => {
  clearTimeout(closeTimer)
  document.removeEventListener('pointerdown', onOutside, true)
  window.removeEventListener('scroll', onViewport, true)
  window.removeEventListener('resize', onViewport)
})

//: for the self-test: the menu state + where the pill currently sits
function state() {
  const p = pill.value
  const tr = p ? getComputedStyle(p).transform : ''
  let ty = 0
  const m = /matrix\(([^)]+)\)/.exec(tr)
  if (m) ty = Number(m[1].split(',')[5])
  return {
    value: props.modelValue, label: label.value,
    phase: phase.value, state: menu.value ? menu.value.dataset.state : 'absent',
    side: side.value, active: active.value,
    pillY: Math.round(ty * 100) / 100,
    pillOpacity: p ? Number(getComputedStyle(p).opacity) : 0,
    options: items.value.map(it => it.label),
    swap: root.value ? root.value.dataset.swap !== undefined : false,
    trace: (window.__calaGsTrace || []).join(' ')
  }
}
defineExpose({ state, open, close, pick })
</script>

<style scoped>
.uv-gs { position: relative; display: inline-block; max-width: 100%; min-width: 0; }
.uv-gs[data-disabled] { opacity: .5; }
.uv-gs[data-swap] .uv-gs-label { animation: gs-swap 180ms var(--ease); }
@keyframes gs-swap { from { opacity: .55; filter: blur(2px); } }

.uv-gs-trigger {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  height: var(--gs-chip);
  margin: 0;
  padding: 0 6px 0 9px;
  border: 1px solid var(--panel-line);
  border-radius: var(--gs-inner-radius);
  background: var(--field);
  color: var(--ink);
  font: inherit;
  font-size: var(--gs-font);
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  outline: none;
  user-select: none;
  transition: background .16s var(--ease), border-color .16s var(--ease), transform .16s var(--ease);
}
.uv-gs-trigger:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--c2) 55%, transparent);
  background: color-mix(in srgb, var(--c2) 12%, var(--field));
}
.uv-gs-trigger[aria-expanded='true'] {
  border-color: color-mix(in srgb, var(--c2) 65%, transparent);
  background: color-mix(in srgb, var(--c2) 16%, var(--field));
}
.uv-gs-trigger:not(:disabled):active { transform: scale(.97); }
.uv-gs-trigger:disabled { cursor: default; }
.uv-gs-label { flex: 1 1 auto; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.uv-gs-label[data-empty] { opacity: .6; }
.uv-gs-chev { display: inline-flex; flex: none; color: var(--ink-dim); transition: transform .2s var(--ease); }
.uv-gs-chev svg { width: 13px; height: 13px; }
.uv-gs-trigger[aria-expanded='true'] .uv-gs-chev { transform: rotate(180deg); }

.uv-gs-menu {
  position: fixed;
  z-index: 38;                       /* body-level: above every card/row (see template) */
  min-width: 120px;
  padding: 4px;
  border: 1px solid var(--panel-line);
  border-radius: var(--gs-radius);
  background: var(--panel-solid);
  box-shadow: 0 10px 30px -10px rgba(0, 0, 0, .65), var(--shadow);
  opacity: 0;
  transform: scale(.95) translateY(-4px);
  transition: opacity var(--gs-pop) var(--ease), transform var(--gs-pop) var(--ease);
}
.uv-gs-menu[data-side='top'] { transform-origin: bottom center; }
.uv-gs-menu[data-state='open'] { opacity: 1; transform: none; }
.uv-gs-menu[data-state='closed'] {
  transition-duration: var(--gs-pop-out);
  pointer-events: none;
  opacity: 0;
  transform: scale(.96) translateY(-3px);
}

.uv-gs-list { position: relative; display: grid; gap: 1px; touch-action: none; }
/* one element gliding between rows -- that is the whole effect */
.uv-gs-pill {
  position: absolute;
  top: 0; right: 0; left: 0;
  height: var(--gs-row);
  border-radius: var(--gs-inner-radius);
  background: linear-gradient(100deg,
              color-mix(in srgb, var(--c1) 34%, transparent),
              color-mix(in srgb, var(--c2) 34%, transparent));
  opacity: 0;
  pointer-events: none;
  transition: transform var(--gs-glide) var(--ease), opacity .15s var(--ease);
}
.uv-gs-opt {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  height: var(--gs-row);
  padding: 0 8px 0 10px;
  border-radius: var(--gs-inner-radius);
  color: var(--ink);
  font-size: var(--gs-font);
  cursor: pointer;
  user-select: none;
}
.uv-gs-opt[aria-selected='true'] { background: color-mix(in srgb, var(--c2) 14%, transparent); }
.uv-gs-list[data-live] .uv-gs-opt[aria-selected='true'] { background: transparent; }
.uv-gs-name { flex: 1 1 auto; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.uv-gs-tag { flex: none; color: var(--ink-dim); font-size: calc(var(--gs-font) - 1.5px); }
.uv-gs-check { display: inline-flex; flex: none; color: var(--c2); visibility: hidden; }
.uv-gs-check svg { width: 13px; height: 13px; }
.uv-gs-check[data-on] { visibility: visible; }
</style>
