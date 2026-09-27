<template>
  <!-- The card itself is fixed (so the border glow can sit on it and the header
       stays put); only the body scrolls, with its own themed scrollbar. -->
  <div class="uv-card uv-card-pad res uv-border-glow" :class="{ on: !!rep, pass: !!(rep && rep.ok) }"
       id="card-gates" @mousemove="onGlow" @mouseleave="glowOff">
    <h3 class="uv-card-title">
      <ScrambleText :text="t('gates.title')" />
      <span v-if="rep" class="uv-pill" :class="rep.ok ? 'on' : 'fail'">
        {{ rep.ok ? t('gates.allPass') : t('gates.failed') }}
      </span>
      <span v-if="rep" class="uv-pill" :class="rep.deployed ? 'on' : ''">
        {{ rep.deployed ? t('gates.deployed') : t('gates.notDeployed') }}
      </span>
      <span v-if="rep && isMerge && rep.ok" class="uv-pill on">{{ t('gates.merged') }}</span>
    </h3>

    <div class="res-body uv-scroll">
      <div v-if="!rep" class="none"><ScrambleText :text="t('gates.none')" /></div>

      <template v-else>
        <table class="uv-table" v-if="rep.gates">
          <tbody>
            <tr v-for="g in gateRows" :key="g.id">
              <th style="width:60px">{{ g.id }}</th>
              <td :class="g.ok ? 'ok' : 'bad'" style="width:52px">{{ g.ok ? 'PASS' : 'FAIL' }}</td>
              <td class="detail" :title="g.detail">{{ g.detail }}</td>
            </tr>
          </tbody>
        </table>

        <!-- CP-38: a refused merge lists exactly who wanted what -->
        <div v-if="isMerge && conflicts.length" class="errbox">
          <b>{{ t('gates.conflicts') }}</b>
          <div v-for="(c, i) in conflicts" :key="i">{{ c }}</div>
        </div>

        <div class="meta">
          <span v-if="rep.da_counts">{{ t('gates.daRows') }}<b>{{ da }}</b></span>
          <span v-if="rep.materials">{{ t('gates.materials') }}<b>{{ rep.materials.length }}</b>{{ t('gates.materialsUnit') }}</span>
          <span v-if="isMerge && rep.mods"><b>{{ rep.mods.length }}</b>{{ t('gates.modsUnit') }}</span>
          <span v-if="isMerge && rep.tables"><b>{{ tableCount }}</b>{{ t('gates.tablesUnit') }}</span>
          <span v-if="isMerge && rep.files"><b>{{ rep.files.length }}</b>{{ t('gates.filesUnit') }}</span>
          <span v-if="size">{{ t('gates.container') }}<b>{{ size }}</b></span>
          <span v-if="rep.seconds">{{ t('gates.seconds') }}<b>{{ rep.seconds }} s</b></span>
        </div>

        <table class="uv-table" v-if="isMerge && tables.length">
          <tbody>
            <tr v-for="r in tables" :key="r.tag">
              <th style="width:150px">{{ r.tag }}</th>
              <td class="detail">{{ r.text }}</td>
            </tr>
          </tbody>
        </table>

        <div v-if="rep.error" class="errbox">{{ rep.error }}</div>
        <!-- CP-41：合并现在会自动装进游戏，把"装到哪、备份在哪"直接写出来 -->
        <div v-if="isMerge && rep.deploy && rep.deploy.ok !== false && !rep.rolledBack"
             class="errbox ok2" id="deploy-box">
          <div>{{ t('gates.installed') }}</div>
          <div>{{ t('gates.deployTo') }}{{ rep.deploy.target }}</div>
          <div v-if="rep.deploy.backup">{{ t('gates.backupDir') }}{{ rep.deploy.backup }}</div>
        </div>
        <div v-if="rollbackText" id="rollback-text" class="errbox ok2">{{ rollbackText }}</div>
      </template>
    </div>

    <div v-if="rep" class="acts">
      <button class="uv-btn uv-btn-sm" type="button" :disabled="!rep.out_patch"
              @click="$emit('open-out')"><ScrambleText :text="t('gates.openOut')" /></button>
      <!-- CP-41b：这一颗按钮**永远**跟着结果一起出现（v1.1.0 就是这么做的）：
           没有产物/没安装时**置灰**而不是消失 —— 之前用 v-if 藏掉它，
           单包 DryRun（默认）下就再也看不到回滚入口了（用户报的回归）。 -->
      <button id="rollback" class="uv-btn uv-btn-sm uv-btn-danger" type="button"
              :disabled="!canRollback" :title="rollbackHint" @click="$emit('rollback')">
        <ScrambleText :text="t('gates.rollback')" /></button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { t } from '../i18n.js'
import ScrambleText from './ScrambleText.vue'

const props = defineProps({
  rep: { type: Object, default: null },
  rollbackText: { type: String, default: '' },
  // 'merge' -> the report is a MergeReport (tables/conflicts/mods), not a build
  mode: { type: String, default: 'single' }
})
defineEmits(['open-out', 'rollback'])

const isMerge = computed(() => props.mode === 'merge')
//: 能不能真的回滚：单包 = 这次真的部署过（`deployed`）；合并 = 报告里有安装块
//: （CP-41 自动安装留下的 `install_backup_*`）。两者都不是时按钮**置灰**。
//: 已经回滚过（`rolledBack`）就没有东西可回滚了 —— 也得置灰。
const canRollback = computed(() => !!props.rep && !props.rep.rolledBack
                          && (!!props.rep.deployed
                              || (!!props.rep.deploy && props.rep.deploy.ok !== false)))
const rollbackHint = computed(() => {
  if (!props.rep) return ''
  if (canRollback.value) {
    return isMerge.value ? t('gates.rollbackMergeHint') : t('gates.rollbackHint')
  }
  return t('gates.rollbackOff')
})
const conflicts = computed(() => (props.rep && props.rep.conflicts) || [])
const tables = computed(() => {
  const d = (props.rep && props.rep.tables) || {}
  return Object.keys(d).sort().map(k => {
    const v = d[k] || {}
    return { tag: k, text: v.native + ' → ' + v.final + '  (+' + v.appended + ' / -'
      + v.deleted + ' / ~' + v.modified + ')' }
  })
})
const tableCount = computed(() => Object.keys((props.rep && props.rep.tables) || {}).length)

// ReactBits' BorderGlow tracks the pointer and paints the glow at that spot;
// here the position is handed to CSS as two custom properties.
function onGlow(e) {
  const el = e.currentTarget
  if (!el) return
  const r = el.getBoundingClientRect()
  if (!r.width || !r.height) return
  el.style.setProperty('--gx', (((e.clientX - r.left) / r.width) * 100).toFixed(1) + '%')
  el.style.setProperty('--gy', (((e.clientY - r.top) / r.height) * 100).toFixed(1) + '%')
}
function glowOff(e) {
  const el = e.currentTarget
  if (el) { el.style.removeProperty('--gx'); el.style.removeProperty('--gy') }
}

const gateRows = computed(() => {
  const g = (props.rep && props.rep.gates) || {}
  return Object.keys(g).sort().map(k => ({ id: k, ok: !!g[k].ok, detail: g[k].detail || '' }))
})
const da = computed(() => {
  const d = (props.rep && props.rep.da_counts) || {}
  return Object.entries(d).map(([k, v]) => k.replace('DA_', '') + '=' + v).join('  ')
})
const size = computed(() => {
  const f = props.rep && props.rep.container && props.rep.container.files
  if (!f) return ''
  const b = Object.values(f).reduce((a, x) => a + (x.bytes || 0), 0)
  return (b / 1048576).toFixed(1) + ' MiB'
})
</script>

<style scoped>
/* the card never grows past its pane: header + footer are pinned, the middle
   scrolls (this is the "判据条目多的时候能滚动" fix) */
.res {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: hidden;
}
.res-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-right: 4px;
}
.none { color: var(--ink-dim); font-size: 12.8px; }
.detail {
  color: var(--ink-dim); font-size: 12px;
  max-width: 1px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.meta { display: flex; flex-wrap: wrap; gap: 12px 14px; font-size: 12.5px; color: var(--ink-soft); }
.acts { flex: none; display: flex; flex-wrap: wrap; gap: 8px; }
.errbox {
  border-radius: 10px; padding: 9px 11px; font-size: 12.3px;
  background: color-mix(in srgb, var(--bad) 12%, transparent);
  color: var(--bad); white-space: pre-wrap; word-break: break-word;
}
.errbox.ok2 { background: color-mix(in srgb, var(--ok) 12%, transparent); color: var(--ok); }
.uv-card-title { gap: 10px; flex: none; margin-bottom: 0; }
</style>
