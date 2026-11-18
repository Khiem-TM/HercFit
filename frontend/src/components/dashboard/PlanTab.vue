<script setup lang="ts">
import { computed, nextTick, useTemplateRef } from 'vue'
import { CalendarDays, RefreshCw } from 'lucide-vue-next'
import { completionMessage, type CompletionResult, type TrainingPlan } from '@/features/plan/model'
import { usePlanBrowser } from '@/features/plan/usePlanBrowser'
import { usePlanToday } from '@/features/plan/usePlanToday'
import type { DashboardData } from './useDashboardData'
import PlanSummary from './plan/PlanSummary.vue'
import PlanWeekNav from './plan/PlanWeekNav.vue'
import PlanSessionList from './plan/PlanSessionList.vue'
import PlanSessionDetail from './plan/PlanSessionDetail.vue'
const props = defineProps<{ data: DashboardData }>()
const emit = defineEmits<{ 'create-plan': []; done: [message: string] }>()
const plan = computed<TrainingPlan | null>(() => props.data.plan.value ?? props.data.previousPlan.value)
const active = computed(() => !!props.data.plan.value && plan.value?.status !== 'ENDED')
const today = usePlanToday(() => plan.value)
const { weeks, week, index, entry, day, selectedDate, selectedId, currentIndex, selectWeek, selectDay, selectSession } = usePlanBrowser(() => plan.value, () => today.value)
const detail = useTemplateRef<InstanceType<typeof PlanSessionDetail>>('detail')
const navigation = useTemplateRef<InstanceType<typeof PlanWeekNav>>('navigation')
const failed = computed(() => props.data.failed.value.includes('plan'))
async function chooseDay(date: string) { selectDay(date); await nextTick(); detail.value?.focus() }
async function chooseSession(id: string) { selectSession(id); await nextTick(); detail.value?.focus() }
async function completed(result: CompletionResult) {
  props.data.applyPlanCompletion(result)
  emit('done', `${completionMessage(result)} · ${result.entry.label}`)
  await props.data.refresh()
}
</script>
<template>
  <div class="plan-page">
    <div v-if="failed" class="load-error" role="alert"><span>Không tải được kế hoạch mới nhất. {{ plan ? 'Đang hiển thị dữ liệu đã tải.' : 'Kiểm tra kết nối và thử lại.' }}</span><button type="button" class="hf-btn" :disabled="data.planLoading.value" @click="data.reloadPlan()"><RefreshCw :size="16" aria-hidden="true" />Thử lại</button></div>
    <div v-if="data.planLoading.value && !plan" class="loading" role="status"><div class="skeleton short" /><div class="skeleton" /><div class="skeleton calendar" /><span>Đang tải kế hoạch…</span></div>
    <template v-else-if="plan">
      <PlanSummary :key="plan.id" :plan="plan" :today="today" :active="active" @create="emit('create-plan')" @ended="data.reloadPlan()" />
      <PlanWeekNav v-if="weeks.length" ref="navigation" :weeks="weeks" :index="index" :selected-date="selectedDate" :today="today" :current-index="currentIndex" @week="selectWeek" @day="chooseDay" />
      <div class="workspace">
        <PlanSessionList :plan="plan" :entries="week?.sessions ?? []" :selected-id="selectedId" :today="today" @select="chooseSession" />
        <PlanSessionDetail ref="detail" :plan="plan" :entry="entry" :day="day" :today="today" show-back @completed="completed" @back="navigation?.focus()" />
      </div>
    </template>
    <div v-else-if="!failed" class="empty">
      <CalendarDays :size="40" :stroke-width="1.3" aria-hidden="true" /><h2>Bắt đầu với một kế hoạch</h2>
      <p>Lập lịch cùng trợ lý để biết mỗi ngày tập gì, xem hướng dẫn và theo dõi tiến độ từng tuần.</p>
      <button type="button" class="hf-btn pri" @click="emit('create-plan')">Lập lịch với trợ lý</button>
    </div>
  </div>
</template>
<style scoped>
.plan-page { display: flex; flex-direction: column; gap: 18px; padding-bottom: 8px; }
.workspace { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 20px; align-items: start; }
.load-error { display: flex; align-items: center; justify-content: space-between; gap: 12px; background: var(--hf-warn-bg); color: var(--hf-warn-text); padding: 14px 18px; border-radius: 14px; font-size: 13px; line-height: 1.6; }
.load-error .hf-btn { flex: none; min-height: 44px; }
.loading { padding: 28px; background: var(--hf-card); border-radius: 22px; color: var(--hf-muted); font-size: 14px; display: grid; gap: 20px; }
.skeleton { height: 30px; background: var(--hf-fill); border-radius: 10px; }
.skeleton.short { width: 40%; }
.skeleton.calendar { height: 140px; }
.empty { padding: 64px 24px; border-radius: 24px; background: var(--hf-card); display: flex; align-items: center; flex-direction: column; gap: 16px; text-align: center; }
.empty h2 { font-size: 26px; margin: 0; }
.empty p { max-width: 440px; margin: 0 0 8px; font-size: 14px; line-height: 1.8; color: var(--hf-muted); }
.plan-page :deep(button:focus-visible), .plan-page :deep(select:focus-visible), .plan-page :deep(summary:focus-visible) { outline: 2px solid var(--hf-acc); outline-offset: 3px; }
@media (min-width: 1280px) { .workspace { grid-template-columns: 320px minmax(0, 1fr); } }
@media (max-width: 1023px) { .workspace { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 600px) { .load-error { align-items: flex-start; flex-direction: column; } }
</style>
