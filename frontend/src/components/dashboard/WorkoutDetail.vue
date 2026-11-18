<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { ChevronLeft } from 'lucide-vue-next'
import { completionMessage, type CompletionResult, type TrainingPlan } from '@/features/plan/model'
import { usePlanToday } from '@/features/plan/usePlanToday'
import { longDate } from './format'
import { workoutView } from './today'
import PlanSessionDetail from './plan/PlanSessionDetail.vue'

const props = defineProps<{ plan: TrainingPlan | null; today: string }>()
const emit = defineEmits<{ back: []; done: [message: string]; changed: []; completed: [result: CompletionResult] }>()
const planToday = usePlanToday(() => props.plan)
const view = computed(() => workoutView(props.plan, planToday.value))
const sessions = computed(() => view.value.entry ? [view.value.entry, ...view.value.others] : [])
const selected = shallowRef<string>()
const entry = computed(() => sessions.value.find(item => item.id === selected.value) ?? sessions.value[0] ?? null)
const others = computed(() => sessions.value.filter(item => item.id !== entry.value?.id))
function completed(result: CompletionResult) {
  emit('completed', result)
  emit('done', `${completionMessage(result)} · ${result.entry.label}`)
  emit('changed')
}
</script>
<template>
  <div class="layer">
    <button type="button" class="hf-back" @click="emit('back')"><ChevronLeft :size="18" aria-hidden="true" />Hôm nay</button>
    <div v-if="!entry || !plan" class="hf-card empty"><h2>Hôm nay không có buổi tập</h2><p class="hf-mut">Ngày nghỉ theo kế hoạch hoặc bạn chưa có lịch tập.</p></div>
    <div v-else class="workout-layout">
      <PlanSessionDetail :plan="plan" :entry="entry" :today="planToday" @completed="completed" />
      <aside class="hf-stack">
        <section v-if="others.length" class="hf-card">
          <span class="hf-lbl">Buổi khác hôm nay</span>
          <button v-for="other in others" :key="other.id" type="button" class="other" @click="selected = other.id"><span><b>{{ other.label }}</b><br><span class="hf-mut small">{{ other.items.length }} bài</span></span><span class="hf-pill" :class="{ ok: other.completed_at }">{{ other.completed_at ? 'Đã tập' : 'Chưa ghi nhận' }}</span></button>
        </section>
        <section v-if="view.overdue" class="hf-card">
          <span class="hf-lbl">Buổi quá hạn</span><div class="hf-kv"><div><b>{{ view.overdue.label }}</b><br><span>{{ longDate(view.overdue.scheduled_date) }} · không thể ghi nhận bù</span></div><span class="hf-pill bad">Quá hạn</span></div>
        </section>
      </aside>
    </div>
  </div>
</template>
<style scoped>
.workout-layout { display: grid; grid-template-columns: minmax(0, 2fr) minmax(240px, 1fr); gap: 20px; margin-top: 16px; }
.empty { margin-top: 16px; padding: 32px; }
.empty h2 { margin: 0; font-size: 24px; }
.empty p { margin: 0; }
.small { font-size: 13px; }
.other { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; text-align: left; border: 0; background: var(--hf-fill-2); color: var(--hf-ink); border-radius: 14px; padding: 12px; font-size: 14px; min-height: 44px; }
.other:hover { background: var(--hf-hover); }
@media (max-width: 1023px) { .workout-layout { grid-template-columns: minmax(0, 1fr); } }
</style>
