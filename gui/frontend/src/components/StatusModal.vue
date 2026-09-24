<template>
  <div v-if="show" class="uv-modal-backdrop" :class="{ leaving }" :data-kind="kind"
       @click.self="onBackdrop">
    <div class="uv-modal" role="dialog" aria-modal="true">
      <img class="uv-modal-art" :src="art" :alt="kind === 'ok' ? 'OK' : 'FAIL'">
      <h2 class="uv-modal-text">{{ title }}</h2>
      <p class="uv-modal-sub">{{ sub }}</p>

      <div v-if="kind === 'fail' && errorText" class="uv-modal-err">{{ errorText }}</div>

      <div class="uv-modal-acts">
        <!-- the export button only exists on the failure side (as asked) -->
        <button v-if="kind === 'fail'" id="export-log" class="uv-btn" type="button"
                :disabled="busy" @click="doExport">
          <span class="glyph">⬇</span>{{ busy ? t('modal.exporting') : t('modal.export') }}
        </button>
        <button class="uv-btn" :class="kind === 'ok' ? 'uv-btn-primary' : ''"
                type="button" @click="close">{{ kind === 'ok' ? t('modal.yay') : t('modal.close') }}</button>
      </div>

      <div class="uv-modal-note" :class="noteKind">{{ note }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import { t } from '../i18n.js'

const props = defineProps({
  kind: { type: String, default: '' },        // 'ok' | 'fail' | ''
  report: { type: Object, default: null },
  taskId: { type: String, default: '' }
})
const emit = defineEmits(['close'])

const show = ref(false)
const leaving = ref(false)
const busy = ref(false)
const note = ref('')
const noteKind = ref('')

//: tiny breadcrumb trail (window.__calaModalTrace) so a test can tell WHY the
//: dialog is or is not on screen; a disappearing modal is otherwise invisible
const trace = []
function note_(what) {
  trace.push(what + '@' + Math.round(performance.now()))
  if (trace.length > 12) trace.splice(0, trace.length - 12)
  window.__calaModalTrace = trace.slice()
  window.__calaModalState = {
    show: show.value, leaving: leaving.value, kind: props.kind || '', last: what
  }
}
onMounted(() => note_('mount'))

const art = computed(() => (props.kind === 'ok' ? 'success.png' : 'cry.png'))
const title = computed(() => (props.kind === 'ok' ? t('modal.okTitle') : t('modal.failTitle')))
const errorText = computed(() => (props.report && props.report.error) || '')
const sub = computed(() => {
  if (props.kind === 'ok') {
    const r = props.report || {}
    if (r.deployed === false) return t('modal.okDry')
    return t('modal.okDeployed')
  }
  return t('modal.failSub')
})

watch(() => props.kind, (v) => {
  note_('kind=' + (v || '-'))
  if (v) {
    show.value = true
    leaving.value = false
    note.value = ''
    noteKind.value = ''
  } else if (show.value) {
    close()                      // the page cleared the outcome -> animate out
  }
})

//: clicking the dimmed area dismisses the dialog -- but only for a real click.
//: A synthetic one (script, or a message pumped in by the host UI loop while a
//: JS evaluation is in flight) must not make the result popup vanish by itself.
function onBackdrop(e) {
  if (e && e.isTrusted) close()
}

function close() {
  if (leaving.value) return
  note_('close()')
  leaving.value = true
  setTimeout(() => {
    note_('closed')
    show.value = false
    leaving.value = false
    emit('close')
  }, 220)
}

async function doExport() {
  if (busy.value) return
  busy.value = true
  note.value = ''
  noteKind.value = ''
  try {
    const r = await api.exportLog(props.taskId)
    if (r && r.ok) {
      note.value = t('modal.exported') + r.path
      noteKind.value = 'ok'
    } else {
      // The backend answers with a machine-readable `reason`; the wording shown
      // to the user is picked here so it follows the UI language ("nothing to
      // export" / "cancelled" are normal answers, not failures).
      const reason = r && r.reason
      if (reason === 'empty') note.value = t('modal.exportEmpty')
      else if (reason === 'cancelled') note.value = t('modal.exportCancelled')
      else note.value = (r && r.message) || t('modal.exportFailed')
      noteKind.value = reason === 'cancelled' || reason === 'empty' ? '' : 'bad'
    }
  } catch (e) {
    note.value = t('modal.exportFailedWhy') + (e.message || e)
    noteKind.value = 'bad'
  } finally {
    busy.value = false
  }
}

defineExpose({ close, doExport, isOpen: () => show.value })
</script>
