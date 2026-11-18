<script setup lang="ts">
import { shallowRef, watch } from 'vue'
import { ImageOff } from 'lucide-vue-next'
const props = defineProps<{ src?: string | null; alt: string; large?: boolean }>()
const failed = shallowRef(false)
watch(() => props.src, () => { failed.value = false })
</script>
<template>
  <div class="exercise-image" :class="{ large }">
    <img v-if="src && !failed" :src="src" :alt="alt" loading="lazy" decoding="async" referrerpolicy="no-referrer" @error="failed = true" />
    <div v-else class="placeholder" role="img" :aria-label="`${alt}: chưa có hình ảnh`"><ImageOff :size="large ? 32 : 22" :stroke-width="1.4" aria-hidden="true" /><span v-if="large">Chưa có hình ảnh</span></div>
  </div>
</template>
<style scoped>
.exercise-image { width: 64px; height: 64px; border-radius: 12px; overflow: hidden; flex-shrink: 0; background: var(--hf-fill); }
.exercise-image img { display: block; height: 100%; width: 100%; object-fit: contain; }
.placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; color: var(--hf-muted); width: 100%; height: 100%; font-size: 12px; }
.large { width: 100%; height: 240px; }
@media (max-width: 600px) { .exercise-image:not(.large) { width: 52px; height: 52px; } .large { height: 210px; } }
</style>
