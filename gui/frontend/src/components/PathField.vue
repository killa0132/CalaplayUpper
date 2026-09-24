<template>
  <div class="uv-field-row">
    <label class="uv-label" :for="id"><ScrambleText :text="label" /></label>
    <div class="uv-field-line">
      <input :id="id" class="uv-field mono" type="text" spellcheck="false"
             :placeholder="placeholder" :value="modelValue"
             @input="$emit('update:modelValue', $event.target.value)">
      <button v-if="browse" class="uv-btn uv-btn-sm uv-btn-ghost uv-browse" type="button"
              :disabled="busy" @click="pick" :title="t('inputs.browse')">
        <svg class="folder" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M3.2 7.4a2 2 0 0 1 2-2h3.1l1.7 2h8.8a2 2 0 0 1 2 2v7.2a2 2 0 0 1-2 2H5.2a2 2 0 0 1-2-2z"
                fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>
          <path d="M3.6 10.4h16.8" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/>
        </svg>
        <!-- "浏览…" used to be squeezed to a sliver because the button was a
             flexible flex item next to a growing input: the folder icon + a
             `flex:none; white-space:nowrap` button fixes the width for good -->
        <ScrambleText :text="t('inputs.browse')" nowrap />
      </button>
    </div>
    <div v-if="hint" class="uv-hint">{{ hint }}</div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { api } from '../api.js'
import { t } from '../i18n.js'
import ScrambleText from './ScrambleText.vue'

const props = defineProps({
  id: { type: String, required: true },
  label: { type: String, required: true },
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  browse: { type: Boolean, default: true },
  kind: { type: String, default: 'srcm' },
  hint: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue', 'error'])
const busy = ref(false)

async function pick() {
  busy.value = true
  try {
    // open the dialog in the folder that is already typed in (the backend falls
    // back to the user's home when this is not an existing directory)
    const r = await api.selectFolder(props.kind, props.modelValue)
    if (r && r.path) emit('update:modelValue', r.path)
    else if (r && r.debug) emit('error', t('run.dialogNoPath') + JSON.stringify(r.debug))
  } catch (e) {
    emit('error', t('run.dialogFailed') + (e.message || e))
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.uv-field-row { display: flex; flex-direction: column; gap: 6px; }
.uv-label { font-size: 12.5px; font-weight: 600; color: var(--ink-dim); }
.uv-field-line { display: flex; gap: 8px; align-items: center; }
.uv-field-line .uv-field { flex: 1 1 auto; min-width: 0; }
/* the browse button keeps its own width -- it must never be the thing that
   gives way when the path gets long */
.uv-browse { flex: none; white-space: nowrap; display: inline-flex; align-items: center; gap: 6px; }
.uv-browse .folder { width: 15px; height: 15px; flex: none; opacity: .85; }
.uv-hint { font-size: 11.5px; color: var(--ink-dim); }
</style>
