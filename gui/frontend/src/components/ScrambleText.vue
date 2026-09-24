<template>
  <!-- ReactBits "Scrambled Text", re-shaped for this app.
       Upstream scrambles whatever character sits close to the moving pointer;
       we deliberately do **not** do that.  Here the scramble is a one-shot
       "decode" wave fired by the language switch (see i18n.js): every character
       starts as noise and settles into the real glyph, with the settle time
       proportional to its distance from the button that was clicked -- so the
       text decodes outward from the click, like a ripple.  It never reacts to
       hover, and it only plays again on the next language switch. -->
  <span ref="root" class="uv-scramble" :class="{ 'uv-scramble-nowrap': nowrap }"
        :data-settled="!running ? '' : undefined">{{ shown }}</span>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { scrambleOrigin, scrambleTick } from '../i18n.js'

const props = defineProps({
  text: { type: String, default: '' },
  //: how long a single character keeps flickering once its turn has come
  charMs: { type: Number, default: 130 },
  //: the ripple travels at this many px/ms from the click origin (slow enough
  //: to actually read as a wave -- a fast one looks like an instant swap)
  speed: { type: Number, default: 1.7 },
  //: hard cap so a very wide window still finishes quickly
  maxDelayMs: { type: Number, default: 620 },
  //: `pre-wrap` is the default (a scrambling glyph must not make the line
  //: reflow), but a label that must stay on ONE line has to opt out of wrapping
  nowrap: { type: Boolean, default: false }
})

//: glyph pools chosen per script so a scrambling character has roughly the same
//: advance width as the one it replaces -- otherwise the whole line reflows
const CJK = '的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意建月公无系军很情者最立代想已通并提直题党程展五果料象员革位入常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放决西被干做必战先回则任取据处队南给色光门即保治北造百规热领七海口东导器压志世金增争济阶油思术极交受联什认六共权收证改清己美再采转更单风切打白教速花带安场身车例真务具万每目至达走积示议声报斗完类八离华名确才科张信马节话米整空元况今集温传土许步群广石记需段研界拉林律叫且究观越织装影算低持音众书布复容儿须际商非验连断深难近矿千周委素技备半办青省列习响约支般史感劳便团往酸历市克何除消构府称太准精值号率族维划选标写存候毛亲快效斯院查江型眼王按格养易置派层片始却专状育厂京识适属圆包火住调满县局照参红细引听该铁价严龙飞'

const shown = ref(props.text || '')
const running = ref(false)
const root = ref(null)
let raf = null
let t0 = 0
let plan = null
let lastTick = -1

function isCJK(ch) {
  const c = ch.codePointAt(0)
  return (c >= 0x4e00 && c <= 0x9fff) || (c >= 0x3400 && c <= 0x4dbf)
}

function noiseFor(ch) {
  if (isCJK(ch)) return CJK[(Math.random() * CJK.length) | 0]
  if (ch >= 'A' && ch <= 'Z') return String.fromCharCode(65 + ((Math.random() * 26) | 0))
  if (ch >= 'a' && ch <= 'z') return String.fromCharCode(97 + ((Math.random() * 26) | 0))
  if (ch >= '0' && ch <= '9') return String((Math.random() * 10) | 0)
  return ch
}

//: build the per-character settle schedule from the ripple origin
function buildPlan(target) {
  const chars = Array.from(target)
  const o = scrambleOrigin.value || { x: 0, y: 0 }
  let rect = null
  try { rect = root.value ? root.value.getBoundingClientRect() : null } catch (e) { rect = null }
  const n = chars.length
  return chars.map((ch, i) => {
    //: rough position of this character inside the node, so the wave really
    //: travels across the text instead of all characters firing at once
    const fx = rect ? rect.left + (rect.width * (i + 0.5)) / Math.max(1, n) : o.x
    const fy = rect ? rect.top + rect.height / 2 : o.y
    const dist = Math.hypot(fx - o.x, fy - o.y)
    const delay = Math.min(props.maxDelayMs, dist / props.speed)
    return { ch, settle: delay + props.charMs }
  })
}

function paint(elapsed) {
  if (!plan) return false
  let out = ''
  let done = true
  for (let i = 0; i < plan.length; i++) {
    const p = plan[i]
    if (elapsed >= p.settle) out += p.ch
    else { out += noiseFor(p.ch); done = false }
  }
  shown.value = out
  return done
}

function frame(now) {
  const elapsed = now - t0
  const done = paint(elapsed)
  if (done) {
    shown.value = props.text
    running.value = false
    raf = null
    return
  }
  raf = requestAnimationFrame(frame)
}

function play() {
  if (!props.text) { shown.value = ''; return }
  if (raf !== null) { cancelAnimationFrame(raf); raf = null }
  plan = buildPlan(props.text)
  running.value = true
  t0 = performance.now()
  paint(0)
  raf = requestAnimationFrame(frame)
}

watch(() => props.text, (v) => {
  //: a text change that did NOT come from a language switch (a dynamic label)
  //: must not scramble -- the switch is the only trigger, and it re-scrambles
  //: from the tick watcher below once the new strings have landed in props
  if (!running.value) shown.value = v
})

watch(scrambleTick, async () => {
  lastTick = scrambleTick.value
  //: the tick fires before the templates re-render with the new language, so
  //: wait for that flush -- otherwise the wave would decode the OLD text
  await nextTick()
  play()
})

onMounted(() => {
  lastTick = scrambleTick.value
  shown.value = props.text
  //: a guide/modal can mount mid-wave; catch it up instead of staying noise
  if (running.value) play()
})
onBeforeUnmount(() => { if (raf !== null) cancelAnimationFrame(raf); raf = null })

function state() {
  return { text: props.text, shown: shown.value, running: running.value,
           settled: !running.value }
}
defineExpose({ state, play })
</script>

<style scoped>
.uv-scramble { white-space: pre-wrap; }
.uv-scramble-nowrap { white-space: nowrap; }
</style>
