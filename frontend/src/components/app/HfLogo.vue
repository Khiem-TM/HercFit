<script setup lang="ts">
/** Dấu HercFit: ô bo góc màu mực, chữ H và chấm nhấn đỏ. */
withDefaults(defineProps<{ size?: number }>(), { size: 28 })
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 30 30" aria-hidden="true" class="hf-logo">
    <rect width="30" height="30" rx="9" class="plate" />
    <path d="M9 9v12M21 9v12M9 15h12" class="mark" stroke-width="2.4" stroke-linecap="round" />
    <circle cx="24" cy="6" r="3" fill="#E1262D" />
  </svg>
</template>

<style scoped>
.hf-logo { flex: none; display: block; }
.plate { fill: var(--hf-ink); }
.mark { stroke: var(--hf-on-ink); fill: none; }
</style>
