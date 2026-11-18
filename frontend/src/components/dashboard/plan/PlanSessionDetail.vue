<script setup lang="ts">
import { computed, useTemplateRef } from 'vue'
import { CalendarDays, ChevronLeft } from 'lucide-vue-next'
import { endedDay, taskState, type CompletionResult, type PlanEntry, type TrainingPlan } from '@/features/plan/model'
import { STATUS, type WeekDay } from '@/features/plan/weeks'
import { sessionMeasure } from '@/features/plan/exercises'
import { longDate } from '../format'
import PlanExerciseCard from './PlanExerciseCard.vue'
import CompletionAction from './CompletionAction.vue'
const props = defineProps<{ plan: TrainingPlan; entry: PlanEntry | null; day?: WeekDay; today: string; showBack?: boolean }>()
const emit = defineEmits<{ completed: [result: CompletionResult]; back: [] }>()
const title = useTemplateRef<HTMLElement>('title')
const status = computed(() => props.entry ? STATUS[taskState(props.entry, props.today, endedDay(props.plan))] : null)
const measure = computed(() => props.entry ? sessionMeasure(props.entry.items) : '')
const items = computed(() => [...(props.entry?.items || [])].sort((a, b) => (a.position ?? 0) - (b.position ?? 0)))
defineExpose({ focus: () => { title.value?.focus({ preventScroll: true }); title.value?.scrollIntoView({ block: window.innerWidth < 1024 ? 'start' : 'nearest', behavior: 'instant' }) } })
</script>
<template>
  <section class="session-detail" aria-label="Chi tiết buổi tập">
    <button v-if="showBack" type="button" class="detail-back" @click="emit('back')"><ChevronLeft :size="16" aria-hidden="true" />Chọn buổi khác</button>
    <template v-if="entry">
      <header class="detail-header">
        <div class="detail-kicker"><span>{{ longDate(entry.scheduled_date) }}/{{ entry.scheduled_date.slice(0, 4) }}</span><span v-if="status" class="status" :class="status.tone">{{ status.glyph }} {{ status.text }}</span></div>
        <h2 ref="title" tabindex="-1">{{ entry.label }}</h2>
        <p class="detail-meta">{{ entry.items.length }} bài tập<template v-if="measure"> · {{ measure }}</template></p>
        <p v-if="entry.note" class="session-note">{{ entry.note }}</p>
      </header>
      <div class="exercises"><PlanExerciseCard v-for="(item, i) in items" :key="`${entry.id}:${item.id ?? i}`" :item="item" :index="i" /></div>
      <footer class="detail-footer"><CompletionAction :plan="plan" :entry="entry" :today="today" @completed="emit('completed', $event)" /></footer>
    </template>
    <div v-else class="empty">
      <CalendarDays :size="32" :stroke-width="1.4" aria-hidden="true" />
      <p v-if="day" class="detail-meta">{{ longDate(day.date) }}</p>
      <h2 ref="title" tabindex="-1">{{ day?.rest ? 'Nghỉ theo kế hoạch' : 'Không có buổi tập' }}</h2>
      <p>Chọn một ngày hoặc buổi tập khác để xem chi tiết.</p>
    </div>
  </section>
</template>
<style scoped>
.session-detail { min-width: 0; border-radius: 22px; border: 1px solid var(--hf-line-2); background: var(--hf-card); align-self: start; overflow: hidden; }
.detail-back { display: none; }
.detail-header { padding: 24px 24px 18px; }
.detail-kicker { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; font-size: 12px; color: var(--hf-muted); }
h2 { margin: 14px 0 6px; font-size: 24px; font-weight: 700; line-height: 1.4; letter-spacing: -.03em; overflow-wrap: anywhere; scroll-margin-top: 20px; }
h2:focus-visible { outline-offset: 5px; }
.detail-meta { color: var(--hf-muted); font-size: 13px; margin: 0; }
.status { border-radius: 8px; padding: 5px 8px; background: var(--hf-fill); font-size: 11px; }
.done { color: var(--hf-ok-text); background: var(--hf-ok-bg); }
.overdue { color: var(--hf-warn-text); background: var(--hf-warn-bg); }
.session-note { color: var(--hf-sub); background: var(--hf-fill-2); padding: 12px 14px; border-radius: 10px; font-size: 13px; line-height: 1.7; margin: 16px 0 0; white-space: pre-line; }
.exercises { display: flex; flex-direction: column; gap: 12px; padding: 0 24px 24px; }
.detail-footer { padding: 20px 24px; border-top: 1px solid var(--hf-line-2); background: var(--hf-fill-2); }
.empty { padding: 60px 24px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 12px; color: var(--hf-muted); }
.empty h2 { color: var(--hf-ink); margin: 0; font-size: 22px; }
.empty p { font-size: 13px; line-height: 1.7; margin: 0; }
@media (max-width: 1023px) { .detail-back { display: flex; align-items: center; gap: 4px; min-height: 44px; margin: 8px 12px 0; padding: 8px; border: 0; border-radius: 8px; background: transparent; color: var(--hf-muted); font-size: 12px; } h2 { scroll-margin-top: 104px; } }
@media (max-width: 760px) { .detail-header { padding: 18px; } .exercises { padding: 0 14px 18px; } .detail-footer { padding: 18px; } h2 { font-size: 21px; } }
</style>
