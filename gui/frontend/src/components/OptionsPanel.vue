<template>
  <div class="uv-card uv-card-pad opts uv-card-orbit">
    <h3 class="uv-card-title">{{ t('opts.title') }}</h3>

    <!-- ReactBits "Line Sidebar": every option is a line that slides towards the
         cursor and lights up gold->cyan; the ones that are ON stay lit. -->
    <LineSidebar :items="rows" :active-ids="activeIds"
                 :marker-length="22" :marker-gap="8" :proximity-radius="90"
                 :max-shift="10" :item-gap="12" :smoothing="110"
                 @pick="onPick">
      <template #item="{ item }">
        <span class="lab" :class="{ hard: item.hard }">
          <b><ScrambleText :text="item.label" nowrap /></b>
          <i v-if="item.hint"><ScrambleText :text="item.hint" /></i>
        </span>
      </template>

      <template #side="{ item }">
        <!-- ReactBits Glide Select: the popup highlight is one pill that glides
             between rows instead of a background swapping instantly -->
        <span v-if="item.id === 'fit'" class="fit-wrap" @click.stop>
          <GlideSelect id="fit" :options="fitOptions" :model-value="fit" size="md"
                       :menu-min-width="216" :aria-label="t('opts.fit')"
                       @update:model-value="$emit('update:fit', $event)" />
        </span>
        <span v-else-if="item.id === 'strict'" id="strict-mark" class="hard-mark"
              :title="t('opts.strictHint')">!</span>
        <span v-else :id="'sw-' + item.id" class="uv-switch" role="switch"
              :aria-checked="on(item.id) ? 'true' : 'false'"
              :class="{ on: on(item.id) }"><i></i></span>
        <span v-if="item.id === 'adv'" class="chev" :class="{ open: advOpen }">▾</span>
      </template>

      <template #extra="{ item }">
        <div v-if="item.id === 'adv' && advOpen" class="adv">
          <div class="row">
            <span class="k">ffmpeg</span>
            <input id="ffmpeg" class="uv-field mono" type="text" spellcheck="false"
                   :placeholder="t('opts.ffmpegPh')" :value="ffmpeg"
                   @input="$emit('update:ffmpeg', $event.target.value)">
          </div>
          <div class="row">
            <span class="k">Kit</span>
            <input id="kit" class="uv-field mono" type="text" spellcheck="false"
                   :placeholder="t('opts.kitPh')" :value="kit"
                   @input="$emit('update:kit', $event.target.value)">
          </div>
        </div>
      </template>
    </LineSidebar>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import LineSidebar from './LineSidebar.vue'
import GlideSelect from './GlideSelect.vue'
import ScrambleText from './ScrambleText.vue'
import { t } from '../i18n.js'

const props = defineProps({
  fit: String, dryRun: Boolean, combined: Boolean, force: Boolean, noAtlas: Boolean,
  exportSrc: Boolean,
  //: 合并模式专用：勾上 = 只产出容器、不写游戏目录（等于单包的 -DryRun）
  mergeDryRun: Boolean,
  ffmpeg: String, kit: String,
  // 'single' (default) = the original packing options; 'merge' = the CP-38 merge
  // mode, whose only "option" is the protocol's always-on strict conflict rule
  mode: { type: String, default: 'single' }
})
const emit = defineEmits(['update:fit', 'update:dryRun', 'update:combined', 'update:force',
                          'update:noAtlas', 'update:exportSrc', 'update:mergeDryRun',
                          'update:ffmpeg', 'update:kit'])

const advOpen = ref(false)

const rows = computed(() => {
  if (props.mode === 'merge') {
    // 合并模式下只有两条：协议的硬性规定（`hard` = 金色加粗+感叹号徽章）与
    // 「仅产出不安装」（默认关闭 ⇒ 合并后自动装进游戏）
    return [{ id: 'strict', domId: 'opt-strict', label: t('opts.strict'),
              hint: t('opts.strictHint'), hard: true },
            { id: 'mergeDryRun', domId: 'opt-mergedry', label: t('opts.mergeDry'),
              hint: t('opts.mergeDryHint') }]
  }
  return [
    { id: 'fit', domId: 'opt-fit', label: t('opts.fit') },
    { id: 'dryRun', domId: 'opt-dryrun', label: t('opts.dryRun'), hint: t('opts.dryRunHint') },
    { id: 'combined', domId: 'opt-combined', label: t('opts.combined'), hint: t('opts.combinedHint') },
    { id: 'force', domId: 'opt-force', label: t('opts.force'), hint: t('opts.forceHint') },
    { id: 'noAtlas', domId: 'opt-noatlas', label: t('opts.noAtlas'), hint: t('opts.noAtlasHint') },
    { id: 'exportSrc', domId: 'opt-exportsrc', label: t('opts.exportSrc'),
      hint: t('opts.exportSrcHint') },
    { id: 'adv', domId: 'opt-adv', label: t('opts.adv'), hint: t('opts.advHint') }
  ]
})

function on(id) {
  if (id === 'dryRun') return !!props.dryRun
  if (id === 'combined') return !!props.combined
  if (id === 'force') return !!props.force
  if (id === 'noAtlas') return !!props.noAtlas
  if (id === 'exportSrc') return !!props.exportSrc
  if (id === 'mergeDryRun') return !!props.mergeDryRun
  if (id === 'adv') return advOpen.value
  if (id === 'strict') return true     // the merge protocol is always strict
  return true                       // the fit row always shows a value
}

const fitOptions = computed(() => [
  // `label` is what the menu lists (the full explanation); `short` is what the
  // closed trigger shows -- a 198 px chip leaves no room for the row title in a
  // 330 px column (the minimum window width)
  { value: 'cover', label: t('opts.fitCover'), short: t('opts.fitCoverShort') },
  { value: 'contain', label: t('opts.fitContain'), short: t('opts.fitContainShort') }
])

const activeIds = computed(() => rows.value.map(r => r.id).filter(on))

function onPick(item) {
  if (item.id === 'dryRun') emit('update:dryRun', !props.dryRun)
  else if (item.id === 'combined') emit('update:combined', !props.combined)
  else if (item.id === 'force') emit('update:force', !props.force)
  else if (item.id === 'noAtlas') emit('update:noAtlas', !props.noAtlas)
  else if (item.id === 'exportSrc') emit('update:exportSrc', !props.exportSrc)
  else if (item.id === 'mergeDryRun') emit('update:mergeDryRun', !props.mergeDryRun)
  else if (item.id === 'adv') advOpen.value = !advOpen.value
  // 'fit' is driven by its own <select>; 'strict' is an always-on notice
}
defineExpose({ advOpen })
</script>

<style scoped>
.opts { display: flex; flex-direction: column; gap: 10px; }
.lab { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
/* the row title never wraps and never squeezes: it ellipsizes instead (the
   value chip on the right is the one that gives way) */
.lab b { font-weight: 700; font-size: 13px; letter-spacing: .01em; white-space: nowrap;
         overflow: hidden; text-overflow: ellipsis; }
.lab i { font-style: normal; font-size: 11.5px; line-height: 1.45; color: var(--ink-dim); }
/* the merge protocol's hard rule: gold + bold, with an exclamation mark, so it
   reads as a regulation and not as a switch someone could turn off */
.lab.hard i {
  color: var(--c1);
  font-weight: 800;
  letter-spacing: .3px;
  text-shadow: 0 0 12px color-mix(in srgb, var(--c1) 45%, transparent);
}
html[data-theme='light'] .lab.hard i {
  color: #a5811c;
  text-shadow: none;
}
.hard-mark {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 21px; height: 21px;
  border-radius: 50%;
  font-weight: 900; font-size: 13.5px; line-height: 1;
  color: #101418;
  background: linear-gradient(135deg, var(--c1), var(--c2));
  box-shadow: 0 0 12px -1px color-mix(in srgb, var(--c1) 70%, transparent);
  animation: uv-hard-pulse 1.9s var(--ease) infinite;
}
@keyframes uv-hard-pulse {
  0%, 100% { transform: scale(1); }
  50%      { transform: scale(1.14); }
}

/* the on/off pill on the right of a line */
.uv-switch {
  position: relative;
  display: inline-block;
  width: 34px; height: 19px;
  flex: none;
  border-radius: 999px;
  border: 1px solid var(--panel-line);
  background: color-mix(in srgb, var(--ink) 16%, transparent);
  transition: background .28s var(--ease), border-color .28s var(--ease), box-shadow .28s var(--ease);
}
.uv-switch i {
  position: absolute; top: 2px; left: 2px;
  width: 13px; height: 13px; border-radius: 50%;
  background: var(--panel-solid);
  box-shadow: 0 1px 3px rgba(0, 0, 0, .35);
  transition: transform .32s cubic-bezier(.34, 1.56, .64, 1), background .28s var(--ease);
}
.uv-switch.on {
  background: linear-gradient(90deg, var(--c1), var(--c2));
  border-color: transparent;
}
.uv-switch.on i { transform: translateX(15px); }

.sel { width: auto; min-width: 118px; padding: 6px 9px; font-size: 12px; }
.fit-wrap { display: inline-flex; align-items: center; min-width: 0; max-width: 100%; }

.adv { display: flex; flex-direction: column; gap: 8px; padding-left: 26px; }
.row { display: flex; align-items: center; gap: 8px; }
.k { flex: none; width: 52px; font-size: 12px; color: var(--ink-dim); }
.chev { font-size: 10px; color: var(--ink-dim); margin-left: 6px; transition: transform .3s var(--ease); }
.chev.open { transform: rotate(180deg); }
</style>
