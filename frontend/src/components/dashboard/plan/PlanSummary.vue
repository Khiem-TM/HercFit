<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { ChevronDown } from 'lucide-vue-next'
import { useAuth } from '@/composables/useAuth'
import { endedDay, planProgress, type TrainingPlan } from '@/features/plan/model'
import { ddmmyyyy } from '../format'
import PlanConfirmDialog from './PlanConfirmDialog.vue'
const props = defineProps<{ plan: TrainingPlan; today: string; active: boolean }>()
const emit = defineEmits<{ create: []; ended: [] }>()
const { authFetch } = useAuth()
const progress = computed(() => planProgress(props.plan, props.today))
const pendingDue = computed(() => Math.max(0, progress.value.due - progress.value.done))
const ended = computed(() => endedDay(props.plan))
const confirming = shallowRef(false), busy = shallowRef(false), error = shallowRef('')
async function endPlan() {
  if (!props.active || busy.value) return
  busy.value = true; error.value = ''
  try {
    const response = await authFetch(`/api/training-plans/${props.plan.id}/end`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_version_id: props.plan.version_id, reason: 'ENDED_EARLY' }),
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(typeof body.detail === 'string' ? body.detail : 'Chưa kết thúc được lịch. Thử lại sau.')
    }
    confirming.value = false; emit('ended')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Chưa kết thúc được lịch.' }
  finally { busy.value = false }
}
</script>
<template>
  <section class="summary">
    <div class="heading">
      <div class="identity">
        <span class="eyebrow">{{ active ? 'Kế hoạch đang theo' : 'Kế hoạch đã kết thúc · chỉ xem' }}</span>
        <h2>{{ plan.name }}</h2>
        <p class="dates">{{ ddmmyyyy(plan.start_date) }} – {{ ddmmyyyy(plan.end_date) }}<template v-if="ended"> · Kết thúc {{ ddmmyyyy(ended) }}</template></p>
      </div>
      <div class="summary-actions">
        <button v-if="!active" type="button" class="hf-btn pri" @click="emit('create')">Lập lịch mới</button>
        <details v-if="active" class="management">
          <summary>Quản lý kế hoạch <ChevronDown :size="14" aria-hidden="true" /></summary>
          <button type="button" class="end-button" @click="confirming = true; error = ''">Kết thúc lịch sớm</button>
        </details>
      </div>
    </div>
    <div class="progress-row">
      <div class="progress-text"><strong>{{ progress.done }}<span> / {{ progress.total }}</span></strong><span>buổi đã hoàn thành</span></div>
      <div class="track" role="progressbar" :aria-valuenow="progress.done" :aria-valuemax="Math.max(1, progress.total)" :aria-valuemin="0" aria-label="Tiến độ toàn kế hoạch"><div :style="{ width: `${progress.percent}%` }" /></div>
      <span class="due" :class="{ pending: pendingDue > 0 }">{{ pendingDue }} buổi đến hạn chưa hoàn thành</span>
    </div>
    <p v-if="plan.note" class="note">{{ plan.note }}</p>
    <PlanConfirmDialog v-if="confirming" title="Kết thúc kế hoạch này?" description="Các buổi đã tập được giữ lại. Các buổi chưa tập từ hôm nay sẽ bị hủy. Bạn vẫn có thể xem chi tiết kế hoạch đã kết thúc." :busy="busy" :error="error" confirm-label="Kết thúc lịch" @cancel="confirming = false" @confirm="endPlan" />
  </section>
</template>
<style scoped>
.summary { background: var(--hf-card); border-radius: 22px; padding: 20px 24px; border: 1px solid var(--hf-line-2); }
.heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.identity { min-width: 0; }
.eyebrow { font-size: 11px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--hf-muted); }
h2 { font-weight: 700; margin: 6px 0; font-size: clamp(20px, 2.2vw, 28px); line-height: 1.3; letter-spacing: -.04em; overflow-wrap: anywhere; }
.dates, .note { font-size: 13px; color: var(--hf-muted); margin: 0; line-height: 1.6; }
.note { margin-top: 14px; white-space: pre-line; }
.progress-row { display: flex; align-items: center; gap: 20px; margin-top: 16px; }
.progress-text { display: flex; align-items: baseline; gap: 8px; white-space: nowrap; font-size: 12px; color: var(--hf-muted); }
.progress-text strong { font-family: var(--hf-mono); font-size: 22px; color: var(--hf-ink); letter-spacing: -.05em; }
.progress-text strong span { color: var(--hf-muted); font-size: 15px; font-weight: 400; }
.track { height: 6px; border-radius: 8px; background: var(--hf-track); flex: 1; min-width: 60px; overflow: hidden; }
.track > div { height: 100%; background: var(--hf-acc); border-radius: inherit; }
.due { font-size: 12px; color: var(--hf-muted); }
.due.pending { color: var(--hf-warn-text); }
.summary-actions { display: flex; flex-direction: column; align-items: flex-end; flex-shrink: 0; }
.management { position: relative; font-size: 12px; color: var(--hf-muted); }
.management summary { display: flex; align-items: center; gap: 6px; cursor: pointer; min-height: 44px; width: fit-content; list-style: none; }
.management summary::-webkit-details-marker { display: none; }
.end-button { position: absolute; z-index: 3; top: 100%; right: 0; white-space: nowrap; box-shadow: 0 8px 20px var(--hf-shadow); min-height: 44px; background: var(--hf-err-bg); color: var(--hf-bad); border: 0; border-radius: 10px; padding: 8px 14px; }
.hf-btn { min-height: 44px; flex-shrink: 0; font-size: 13px; }
@media (max-width: 760px) {
  .summary { padding: 18px; }
  .heading { align-items: flex-start; flex-direction: column; gap: 12px; }
  .summary-actions { flex-direction: row; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; width: 100%; }
  .progress-row { gap: 12px; flex-wrap: wrap; margin-top: 18px; }
  .due { flex-basis: 100%; }
}
</style>
