<template>
  <div id="progress" class="uv-prog" :class="{ running, done: done && !running, failed }"
       :style="{ '--p': pct }">
    <div class="uv-prog-cap">
      <span><ScrambleText :text="label" /></span>
      <b>{{ shown }}%</b>
    </div>
    <div class="uv-prog-track">
      <div class="uv-prog-fill"></div>
      <img class="uv-prog-head" :src="HEAD" alt="冲" draggable="false">
    </div>
    <div class="uv-prog-state">{{ stateText }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { t } from '../i18n.js'
import ScrambleText from './ScrambleText.vue'

//: addressed at runtime from the public dir (see App.vue's BRAND note)
const HEAD = 'chongci.gif'

const props = defineProps({
  running: { type: Boolean, default: false },
  //: 0..100, already smoothed by the parent
  pct: { type: Number, default: 0 },
  done: { type: Boolean, default: false },
  failed: { type: Boolean, default: false },
  stage: { type: String, default: '' }
})

// zero-width fills look broken; keep a couple of percent visible once started
const shown = computed(() => Math.round(props.pct))
const label = computed(() => {
  if (props.running) return props.stage ? t('prog.packing') + ' ' + props.stage : t('prog.packing')
  if (props.failed) return t('prog.failed')
  if (props.done) return t('prog.done')
  return t('prog.idle')
})
const stateText = computed(() => {
  if (props.running) return 'L0 → L5'
  if (props.failed) return 'FAILED'
  if (props.done) return 'ALL PASS'
  return 'IDLE'
})
</script>
