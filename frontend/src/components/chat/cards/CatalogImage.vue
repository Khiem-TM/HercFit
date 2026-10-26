<script setup lang="ts">
import { shallowRef, watch } from 'vue'
import { Dumbbell, Footprints, ImageOff, UtensilsCrossed } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  src?: string | null
  alt: string
  icon?: 'food' | 'exercise' | 'run' | 'none'
  rounded?: string
}>(), { src: null, icon: 'none', rounded: 'rounded-xl' })

// A broken or missing picture falls back to an icon instead of an empty frame.
const failed = shallowRef(false)
watch(() => props.src, () => { failed.value = false })
const icons = { food: UtensilsCrossed, exercise: Dumbbell, run: Footprints, none: ImageOff }
</script>

<template>
  <div class="relative overflow-hidden bg-[#232323]" :class="rounded">
    <img
      v-if="src && !failed"
      :src="src"
      :alt="alt"
      loading="lazy"
      decoding="async"
      referrerpolicy="no-referrer"
      class="h-full w-full object-cover"
      @error="failed = true"
    />
    <div v-else class="flex h-full w-full items-center justify-center text-outline" role="img" :aria-label="alt">
      <component :is="icons[icon]" class="h-1/3 w-1/3 max-h-7 max-w-7" :stroke-width="1.5" aria-hidden="true" />
    </div>
  </div>
</template>
