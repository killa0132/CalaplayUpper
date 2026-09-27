<template>
  <!-- CP-40: the "explain yourself" card.  Unlike the success/failure modal this one
       fires BEFORE anything runs: the merge inputs are checked by the backend
       (/api/validate) and every problem is listed here, one line each, next to a
       clearly unhappy cat.  Same backdrop/scale-in machinery as the other dialogs,
       so it belongs to the same widget family. -->
  <div v-if="show" class="uv-modal-backdrop" :class="{ leaving }" data-kind="notice"
       @click.self="onBackdrop">
    <div id="notice-card" class="uv-modal notice" role="dialog" aria-modal="true">
      <img class="uv-modal-art notice-art" :src="ART" alt="">
      <h2 class="uv-modal-text">{{ t('notice.title') }}</h2>
      <p class="uv-modal-sub">{{ t('notice.meow') }}</p>

      <ul id="notice-errors" class="notice-list">
        <li v-for="(e, i) in errors" :key="'e' + i">{{ e }}</li>
      </ul>

      <div v-if="warnings.length" class="uv-modal-note notice-warns">
        <div v-for="(w, i) in warnings" :key="'w' + i">· {{ w }}</div>
      </div>

      <div class="uv-modal-acts">
        <button id="notice-ok" class="uv-btn uv-btn-primary" type="button" @click="close">
          <ScrambleText :text="t('notice.ok')" />
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { t } from '../i18n.js'
import ScrambleText from './ScrambleText.vue'

//: addressed at runtime from the public dir (see App.vue's BRAND note)
const ART = 'wrong.png'

const props = defineProps({
  open: { type: Boolean, default: false },
  errors: { type: Array, default: () => [] },
  warnings: { type: Array, default: () => [] }
})
const emit = defineEmits(['close'])

const show = ref(false)
const leaving = ref(false)

//: a breadcrumb so the self-test can tell WHY the card is or is not on screen
const trace = []
function note_(what) {
  trace.push(what + '@' + Math.round(performance.now()))
  if (trace.length > 8) trace.splice(0, trace.length - 8)
  window.__calaNoticeTrace = trace.slice()
}
onMounted(() => note_('mount'))

watch(() => props.open, (v) => {
  note_('open=' + (v ? '1' : '0') + ' n=' + props.errors.length)
  if (v) {
    show.value = true
    leaving.value = false
  } else if (show.value) {
    close()
  }
})

function onBackdrop(e) {
  if (e && e.isTrusted) close()      // a synthetic click must not dismiss it
}

function close() {
  if (leaving.value) return
  leaving.value = true
  setTimeout(() => {
    show.value = false
    leaving.value = false
    emit('close')
  }, 220)
}

const state = computed(() => ({ open: show.value, leaving: leaving.value,
                                errors: props.errors.length }))
defineExpose({ close, isOpen: () => show.value, state: () => state.value })
</script>
