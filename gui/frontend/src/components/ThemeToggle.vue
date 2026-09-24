<template>
  <button id="theme-toggle" class="uv-theme" type="button"
          :title="theme === 'dark' ? '切换到亮色背景 / switch to light' : '切换到暗色背景 / switch to dark'"
          @click="$emit('toggle')">
    <span class="knob"></span>
    <span class="glyph moon">🌙</span>
    <span class="glyph sun">☀</span>
  </button>
</template>

<script setup>
defineProps({ theme: { type: String, default: 'dark' } })
defineEmits(['toggle'])
</script>
