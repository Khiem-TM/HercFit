<script setup lang="ts">
import { CalendarDays, LayoutDashboard, Orbit, TrendingUp } from 'lucide-vue-next'
import { motion } from 'motion-v'
import { indicatorTransition } from '@/motion'
import type { DashboardTab } from '@/components/dashboard/DashboardModal.vue'
import HfLogo from './HfLogo.vue'

/**
 * Thanh tab dưới của bố cục điện thoại: bốn trang Dashboard quanh nút Trợ lý ở giữa. Trên điện thoại nó thay cho
 * thanh bên và hàng tab trong Dashboard, nên mỗi trang chỉ cách một chạm.
 */
export type MobileTab = 'chat' | DashboardTab

defineProps<{ active: MobileTab }>()
const emit = defineEmits<{ select: [tab: MobileTab] }>()

const LEFT = [
  { id: 'today', label: 'Hôm nay', icon: LayoutDashboard },
  { id: 'progress', label: 'Tiến độ', icon: TrendingUp },
] as const
const RIGHT = [
  { id: 'plan', label: 'Kế hoạch', icon: CalendarDays },
  { id: 'map', label: 'Bản đồ', icon: Orbit },
] as const
</script>

<template>
  <nav class="hf mtab" aria-label="Điều hướng chính">
    <template v-for="(group, side) in [LEFT, RIGHT]" :key="side">
      <button v-if="side === 1" type="button" class="assistant" :class="{ on: active === 'chat' }"
              :aria-current="active === 'chat' ? 'page' : undefined" aria-label="Trợ lý" @click="emit('select', 'chat')">
        <HfLogo :size="30" />
      </button>
      <button v-for="item in group" :key="item.id" type="button" class="item" :class="{ on: active === item.id }"
              :aria-current="active === item.id ? 'page' : undefined" @click="emit('select', item.id)">
        <span class="icon">
          <motion.span v-if="active === item.id" layout-id="mobile-tab" class="ind" :transition="indicatorTransition" />
          <component :is="item.icon" :size="20" :stroke-width="active === item.id ? 2.2 : 1.8" aria-hidden="true" />
        </span>
        {{ item.label }}
      </button>
    </template>
  </nav>
</template>

<style scoped>
.mtab {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 46; height: var(--hf-tabbar-h); padding: 0 6px var(--hf-safe-bottom);
  display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); align-items: center;
  background: color-mix(in srgb, var(--hf-canvas) 88%, transparent); border-top: 1px solid var(--hf-line-2);
  -webkit-backdrop-filter: blur(18px) saturate(1.4); backdrop-filter: blur(18px) saturate(1.4); user-select: none;
}
.item {
  border: 0; background: transparent; padding: 0; height: 100%; min-width: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px;
  font-size: 11px; font-weight: 500; color: var(--hf-muted); white-space: nowrap;
  transition: color var(--hf-dur-fast) var(--hf-ease-out);
}
.item.on { color: var(--hf-ink); font-weight: 700; }
.icon { position: relative; width: 52px; height: 28px; display: flex; align-items: center; justify-content: center; }
.icon svg { position: relative; }
.ind { position: absolute; inset: 0; border-radius: 999px; background: var(--hf-press); }
.item:active .icon { transform: scale(.92); }
.icon { transition: transform var(--hf-dur-instant) var(--hf-ease-out); }
/* Nút Trợ lý: dấu HercFit trong vòng tròn mực; đang ở khung chat thì có vòng nhấn quanh. */
.assistant {
  justify-self: center; width: 48px; height: 48px; border-radius: 50%; border: 0; padding: 0;
  background: var(--hf-ink); display: flex; align-items: center; justify-content: center;
  box-shadow: 0 6px 16px var(--hf-shadow-2); outline: 0 solid transparent;
  transition: transform var(--hf-dur-instant) var(--hf-ease-out), box-shadow var(--hf-dur-base) var(--hf-ease-out);
}
.assistant.on { box-shadow: 0 0 0 3px var(--hf-canvas), 0 0 0 5px var(--hf-ink); }
.assistant:active { transform: scale(.94); }
@media (prefers-reduced-motion: reduce) { .item:active .icon, .assistant:active { transform: none; } }
</style>
