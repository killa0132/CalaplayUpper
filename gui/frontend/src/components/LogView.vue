<template>
  <div class="logwrap">
    <div ref="box" class="uv-log" id="log" @scroll="onScroll">
      <div v-for="(l, i) in lines" :key="i" :class="cls(l)">{{ l }}</div>
      <div v-if="!lines.length" class="empty">
        <ScrambleText :text="t('log.empty')" />
      </div>
    </div>
    <button v-if="!stuck" class="uv-btn uv-btn-sm jump" type="button" @click="toBottom">
      <ScrambleText :text="t('log.jump')" />
    </button>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { t } from '../i18n.js'
import ScrambleText from './ScrambleText.vue'

const props = defineProps({ lines: { type: Array, default: () => [] } })
const box = ref(null)
const stuck = ref(true)
let ro = null

function cls(l) {
  if (!l) return ''
  if (l.includes('[ERR]') || l.includes('FAIL')) return 'l-err'
  if (l.includes('GATE]')) return 'l-gate'
  if (l.includes('QUALITY:')) return 'l-quality'
  if (l.includes('AUDIO:') || l.includes('transcode')) return 'l-audio'
  if (l.includes('CMD:')) return 'l-cmd'
  return ''
}

function onScroll() {
  const el = box.value
  if (!el) return
  stuck.value = el.scrollHeight - el.scrollTop - el.clientHeight < 40
}

function toBottom() {
  const el = box.value
  if (el) el.scrollTop = el.scrollHeight
  stuck.value = true
}

watch(() => props.lines.length, async () => {
  if (!stuck.value) return
  await nextTick()
  toBottom()
})

// The log box also changes height without a new line: when the run finishes the
// 判据 panel fills in and takes space away from the log, so "keep following"
// has to react to a resize too -- otherwise the last lines silently scroll out
// of view exactly when the user wants to read the verdict.
onMounted(() => {
  if (typeof ResizeObserver === 'undefined' || !box.value) return
  ro = new ResizeObserver(() => { if (stuck.value) toBottom() })
  ro.observe(box.value)
})
onBeforeUnmount(() => { if (ro) ro.disconnect() })
</script>

<style scoped>
/* fills whatever height the right column has left; the panel itself scrolls
   (overflow-y is set in uiverse/basic.css so the scrollbar is themed) */
.logwrap {
  position: relative;
  flex: 1 1 auto;
  min-height: 120px;
  display: flex;
  flex-direction: column;
}
.uv-log { flex: 1 1 auto; min-height: 0; }
.empty { color: var(--ink-dim); font-family: inherit; }
.jump {
  position: absolute; right: 16px; bottom: 12px;
  box-shadow: var(--shadow);
}
</style>
