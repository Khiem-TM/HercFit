<script setup lang="ts">
import { computed } from 'vue'
import { ArrowUpRight, Dumbbell, MessageCircle, Scale, Target, Utensils } from 'lucide-vue-next'
import { hubColor, type KnowledgeHub, type KnowledgeInsight } from '@/types/knowledge'

const props = defineProps<{ insight: KnowledgeInsight; index: number }>()
const emit = defineEmits<{ open: [] }>()
const icons: Record<KnowledgeHub, typeof Target> = { goal: Target, body: Scale, nutrition: Utensils, training: Dumbbell, conversation: MessageCircle }
const progress = computed(() => Math.max(0, Math.min(1, props.insight.progress ?? 0)))
const bars = computed(() => {
  const values = props.insight.bars ?? props.insight.series ?? []
  const max = Math.max(1, ...values.map(value => value ?? 0))
  return values.map(value => ({ height: value == null ? 3 : Math.max(3, value / max * 100), missing: value == null }))
})
</script>

<template>
  <button type="button" class="insight-card" :style="{ '--accent': hubColor(insight.hub), '--delay': `${index * 55}ms` }"
          aria-haspopup="dialog" :aria-label="`Xem nhanh ${insight.title.toLocaleLowerCase('vi')}`" @click="emit('open')">
    <span class="card-heading"><span class="card-icon"><component :is="icons[insight.hub]" :size="16" :stroke-width="1.6" /></span>{{ insight.title }}<ArrowUpRight class="open-icon" :size="15" /></span>
    <span class="card-body">
      <span class="card-value">{{ insight.value }}</span>
      <svg v-if="insight.progress != null" class="progress-ring" viewBox="0 0 40 40" aria-hidden="true">
        <circle cx="20" cy="20" r="17" class="ring-track" />
        <circle cx="20" cy="20" r="17" class="ring-fill" :stroke-dasharray="2 * Math.PI * 17" :stroke-dashoffset="2 * Math.PI * 17 * (1 - progress)" />
      </svg>
    </span>
    <span v-if="insight.caption" class="card-caption">{{ insight.caption }}</span>
    <span v-if="bars.length && insight.progress == null" class="mini-bars" aria-hidden="true">
      <i v-for="(bar, i) in bars" :key="i" :class="{ missing: bar.missing }" :style="{ height: `${bar.height}%`, animationDelay: `${i * 20}ms` }" />
    </span>
    <span class="card-footer"><span>{{ insight.detail || 'Khám phá dữ liệu của bạn' }}</span><span class="quick-label">Xem nhanh</span></span>
  </button>
</template>

<style scoped>
.insight-card { container: insight / inline-size; min-width: 0; display: flex; flex-direction: column; gap: 9px; text-align: left; padding: 16px; border: 1px solid #ffffff12; border-radius: 16px; background: radial-gradient(ellipse at 100% 0, color-mix(in srgb, var(--accent) 11%, transparent), transparent 65%), #171a20; box-shadow: 0 2px 3px #0001; animation: arrive 450ms ease-out backwards; animation-delay: var(--delay); transition: transform 220ms, border-color 220ms, box-shadow 220ms; }
.insight-card:hover, .insight-card:focus-visible { transform: translateY(-4px); border-color: color-mix(in srgb, var(--accent) 55%, transparent); box-shadow: 0 12px 26px #0004; }
.insight-card:active { transform: translateY(-1px) scale(.985); }
.insight-card:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
.card-heading { display: flex; align-items: center; gap: 8px; color: var(--accent); font-size: 12px; font-weight: 500; }
.card-icon { display: grid; place-items: center; width: 29px; height: 29px; border-radius: 9px; background: color-mix(in srgb, var(--accent) 10%, transparent); }
.open-icon { margin-left: auto; opacity: .5; transition: transform 220ms, opacity 220ms; }
.insight-card:hover .open-icon { transform: translate(2px, -2px); opacity: 1; }
.card-body { display: flex; gap: 12px; align-items: center; justify-content: space-between; min-height: 42px; }
.card-value { font-family: 'Playfair Display', serif; font-size: clamp(24px, 13cqi, 36px); letter-spacing: -.025em; line-height: 1.15; color: #f4ecdc; overflow-wrap: anywhere; transition: font-size 200ms; }
.card-caption { font-size: 11px; line-height: 1.6; color: #adaaa1; }
.card-footer { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 5px 10px; margin-top: auto; padding-top: 10px; border-top: 1px solid #ffffff0d; font-size: 10px; line-height: 1.5; color: #96978f; }
.quick-label { color: var(--accent); white-space: nowrap; }
.mini-bars { height: clamp(27px, 14cqi, 44px); display: flex; align-items: flex-end; gap: 4px; margin: 4px 0; }
.mini-bars i { flex: 1; border-radius: 3px 3px 1px 1px; background: var(--accent); opacity: .5; transform-origin: bottom; animation: grow 700ms ease-out backwards; }
.mini-bars i:last-child { opacity: 1; }
.mini-bars i.missing { background: #ffffff24; }
/* Not `.ring`: Tailwind generates a utility of that name, which adds a blue box-shadow. */
.progress-ring { width: 42px; height: 42px; flex-shrink: 0; transform: rotate(-90deg); }
.ring-track, .ring-fill { fill: none; stroke: #ffffff10; stroke-width: 3; }
.ring-fill { stroke: var(--accent); stroke-linecap: round; animation: ring-in 900ms ease-out backwards; transition: stroke-dashoffset 700ms; }
@keyframes arrive { from { opacity: 0; transform: translateY(8px); } }
@keyframes grow { from { transform: scaleY(0); } }
@keyframes ring-in { from { stroke-dashoffset: 107; } }
@media (prefers-reduced-motion: reduce) { .insight-card, .mini-bars i, .ring-fill { animation: none; transition: none; } .insight-card:hover, .insight-card:focus-visible, .insight-card:active { transform: none; } }
</style>
