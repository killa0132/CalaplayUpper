<template>
  <!-- Two panes side by side with a draggable divider (the VSCode sidebar
       idiom).  The panes share the free space in proportion to :ratio, so the
       handle keeps its exact width and nothing ever overflows. -->
  <div ref="root" class="uv-split" :class="{ dragging }" id="split">
    <div class="uv-pane" :style="{ flexGrow: ratio }">
      <slot name="a" />
    </div>

    <div class="uv-handle" role="separator" aria-orientation="vertical" tabindex="0"
         :aria-label="label" :aria-valuenow="Math.round(ratio)"
         :aria-valuemin="min" :aria-valuemax="max"
         @pointerdown="start" @dblclick="reset" @keydown="onKey">
      <i class="uv-grip"></i><i class="uv-grip"></i><i class="uv-grip"></i>
    </div>

    <div class="uv-pane" :style="{ flexGrow: 100 - ratio }">
      <slot name="b" />
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { set as setPref } from '../prefs.js'

const props = defineProps({
  //: percentage given to pane A (left); 50 = 左右对半
  ratio: { type: Number, default: 50 },
  min: { type: Number, default: 12 },
  max: { type: Number, default: 88 },
  //: remember the position between runs (durable key, see prefs.js); '' = do not
  storeKey: { type: String, default: '' },
  label: { type: String, default: '拖动可调整两边宽度' }
})
const emit = defineEmits(['update:ratio'])

const root = ref(null)
const dragging = ref(false)
let startX = 0
let startRatio = 50
let width = 1
//: a drag fires `set()` dozens of times; the durable write waits for the drop
//: (one POST instead of one per pointermove)
let pendingStore = null

function set(v) {
  const c = Math.min(props.max, Math.max(props.min, Math.round(v * 10) / 10))
  emit('update:ratio', c)
  if (props.storeKey) {
    if (dragging.value) pendingStore = c
    else setPref(props.storeKey, String(c))
  }
}

function flushStore() {
  if (props.storeKey && pendingStore !== null) {
    setPref(props.storeKey, String(pendingStore))
    pendingStore = null
  }
}

function start(e) {
  if (e.button !== undefined && e.button !== 0) return
  const el = root.value
  if (!el) return
  width = el.getBoundingClientRect().width || 1
  startX = e.clientX
  startRatio = props.ratio
  dragging.value = true
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop)
  window.addEventListener('pointercancel', stop)
  if (e.preventDefault) e.preventDefault()
}

function move(e) {
  set(startRatio + ((e.clientX - startX) / width) * 100)
}

function stop() {
  if (!dragging.value) return
  dragging.value = false
  window.removeEventListener('pointermove', move)
  window.removeEventListener('pointerup', stop)
  window.removeEventListener('pointercancel', stop)
  flushStore()
}

//: double-click (or Home) snaps back to the 50/50 starting point
function reset() { set(50) }

function onKey(e) {
  if (e.key === 'ArrowLeft') { set(props.ratio - 2); e.preventDefault() }
  else if (e.key === 'ArrowRight') { set(props.ratio + 2); e.preventDefault() }
  else if (e.key === 'Home') { reset(); e.preventDefault() }
  else if (e.key === 'End') { set(100); e.preventDefault() }
}

onBeforeUnmount(() => { stop(); flushStore() })
defineExpose({ reset, set })
</script>

<style scoped>
.uv-split {
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  display: flex;
  align-items: stretch;
}
.uv-pane {
  flex-basis: 0;
  flex-shrink: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* the divider: a slim hit area with a gradient bar that lights up */
.uv-handle {
  flex: 0 0 14px;
  position: relative;
  align-self: stretch;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  cursor: col-resize;
  touch-action: none;
  outline: none;
}
.uv-handle::before {
  content: '';
  position: absolute;
  top: 6px;
  bottom: 6px;
  left: 5px;
  right: 5px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--ink) 16%, transparent);
  transition: background .25s var(--ease), box-shadow .25s var(--ease);
}
.uv-handle:hover::before,
.uv-handle:focus-visible::before,
.uv-split.dragging .uv-handle::before {
  background: linear-gradient(180deg, var(--c1), var(--c2));
  box-shadow: 0 0 12px -2px color-mix(in srgb, var(--c2) 75%, transparent);
}
.uv-grip {
  position: relative;
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--ink) 45%, transparent);
  transition: background .25s var(--ease);
}
.uv-handle:hover .uv-grip,
.uv-split.dragging .uv-grip { background: var(--panel-solid); }

/* while dragging, never let the pointer select text or hover things */
.uv-split.dragging { user-select: none; }
.uv-split.dragging .uv-pane { pointer-events: none; }
</style>
