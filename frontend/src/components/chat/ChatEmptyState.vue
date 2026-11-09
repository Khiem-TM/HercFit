<script setup lang="ts">
import { computed } from 'vue'
import type { UserProfile } from '@/types/api'
import HfLogo from '@/components/app/HfLogo.vue'

const props = defineProps<{
  user: UserProfile | null
}>()

const displayName = computed(() => props.user?.nick_name || props.user?.fullname || 'Bạn')
</script>

<template>
  <div class="empty hf-stagger">
    <HfLogo :size="48" />
    <p class="hello">Xin chào, {{ displayName }}</p>
    <h1>Hôm nay mình có thể giúp gì?</h1>
    <div class="slot">
      <slot name="composer" />
    </div>
  </div>
</template>

<style scoped>
.empty { width: 100%; max-width: 720px; margin: 0 auto; padding: 32px 24px; display: flex; flex-direction: column; align-items: center; text-align: center; }
.hello { margin: 20px 0 0; font-size: 16px; color: var(--hf-muted); }
h1 { margin: 6px 0 28px; font-size: 32px; line-height: 1.15; font-weight: 700; letter-spacing: -0.02em; color: var(--hf-ink); }
.slot { width: 100%; text-align: left; }
@media (max-width: 760px) { h1 { font-size: 26px; } }
</style>
