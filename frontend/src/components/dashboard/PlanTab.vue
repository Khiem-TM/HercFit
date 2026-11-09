<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { endedDay, planProgress, taskState, type PlanEntry, type TrainingPlan } from '@/features/plan/model'
import { ddmm, ddmmyyyy, longDate, WEEKDAY_LONG, weekday } from './format'
import type { DashboardData } from './useDashboardData'

/** Lịch tập đang theo: tiến độ các buổi đến hạn, khuôn mẫu mỗi tuần và toàn bộ các buổi. */
const props = defineProps<{ data: DashboardData }>()
const emit = defineEmits<{ 'create-plan': []; ask: [text: string] }>()
const { authFetch } = useAuth()

const plan = computed<TrainingPlan | null>(() => props.data.plan.value ?? props.data.previousPlan.value)
const active = computed(() => !!props.data.plan.value)
const today = props.data.today
const ended = computed(() => (plan.value ? endedDay(plan.value) : null))
const progress = computed(() => (plan.value ? planProgress(plan.value, today) : null))
const sessions = computed(() => (plan.value?.entries ?? []).filter(entry => !entry.is_rest)
  .sort((a, b) => a.scheduled_date.localeCompare(b.scheduled_date)))
const state = (entry: PlanEntry) => taskState(entry, today, ended.value)
const STATUS: Record<string, { text: string; cls: string }> = {
  done: { text: 'Đã tập', cls: 'ok' }, overdue: { text: 'Chưa hoàn thành', cls: 'bad' }, today: { text: 'Hôm nay', cls: '' },
  upcoming: { text: 'Sắp tới', cls: '' }, cancelled: { text: 'Đã huỷ', cls: '' },
}
const weekIndex = computed(() => {
  if (!plan.value) return null
  const start = new Date(`${plan.value.start_date}T12:00:00Z`).getTime()
  const end = new Date(`${plan.value.end_date}T12:00:00Z`).getTime()
  const now = new Date(`${today}T12:00:00Z`).getTime()
  const total = Math.max(1, Math.ceil((end - start) / 86400000 / 7 + 1e-9))
  const current = Math.min(total, Math.max(1, Math.floor((now - start) / 86400000 / 7) + 1))
  return { current, total }
})
const weekdays = computed(() => [...new Set(sessions.value.map(entry => weekday(entry.scheduled_date)))]
  .sort((a, b) => ((a + 6) % 7) - ((b + 6) % 7)))
const pattern = computed(() => weekdays.value.map(day => {
  const sample = sessions.value.filter(entry => weekday(entry.scheduled_date) === day)
  const labels = [...new Set(sample.map(entry => entry.label))]
  return { day: WEEKDAY_LONG[day], label: labels.join(' / '), count: `${sample[0]?.items.length ?? 0} bài` }
}))
const dots = computed(() => sessions.value.map(entry => state(entry)))
const list = computed(() => [...sessions.value].reverse())

const ending = shallowRef(false)
const busy = shallowRef(false)
const notice = shallowRef('')
async function endPlan() {
  if (!props.data.plan.value || busy.value) return
  busy.value = true
  notice.value = ''
  try {
    const response = await authFetch(`/api/training-plans/${props.data.plan.value.id}/end`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_version_id: props.data.plan.value.version_id, reason: 'ENDED_EARLY' }),
    })
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}))
      throw new Error(typeof detail?.detail === 'string' ? detail.detail : 'Chưa kết thúc được lịch. Thử lại sau.')
    }
    ending.value = false
    await props.data.reloadPlan()
  } catch (error) {
    notice.value = error instanceof Error ? error.message : 'Chưa kết thúc được lịch. Thử lại sau.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="plan && progress" class="hf-grid hf-stagger">
    <section class="hf-card hf-inv hf-c8">
      <div class="hf-hd">
        <span class="hf-lbl">{{ active ? 'Kế hoạch đang theo' : 'Kế hoạch đã kết thúc' }}</span>
        <span v-if="active && weekIndex" class="hf-pill">Tuần {{ weekIndex.current }} / {{ weekIndex.total }}</span>
        <span v-else class="hf-pill">Chỉ đọc</span>
      </div>
      <div class="hf-big">{{ plan.name }}</div>
      <div class="hf-mut small">{{ ddmmyyyy(plan.start_date) }} – {{ ddmmyyyy(plan.end_date) }}<template v-if="pattern.length"> · {{ pattern.map(item => item.day).join(', ') }}</template></div>
      <div class="big-row">
        <span class="hf-dg" style="font-size: 72px; color: #fff">{{ progress.done }}</span>
        <span class="due">/ {{ progress.due }} buổi đến hạn đã hoàn thành</span>
      </div>
      <div class="pdots" role="img" :aria-label="`${progress.done} trên ${progress.due} buổi đến hạn đã hoàn thành, tổng kế hoạch ${progress.total} buổi`">
        <span v-for="(item, index) in dots" :key="index" class="pd" :class="item" />
      </div>
      <div class="hf-lg legend">
        <span><i style="background: var(--hf-acc)" />Đã hoàn thành</span>
        <span><i style="border: 2px solid #fff" />Chưa hoàn thành</span>
        <span><i style="background: #2E2E33" />Sắp tới</span>
        <span>Tổng kế hoạch: {{ progress.total }} buổi</span>
      </div>
      <p v-if="notice" class="hf-warn">{{ notice }}</p>
      <div v-if="active" class="hf-acts">
        <button v-if="!ending" type="button" class="hf-btn" @click="ending = true">Kết thúc lịch sớm</button>
        <template v-else>
          <span class="hf-mut small confirm-text">Các buổi đã tập được giữ; buổi còn lại bị huỷ.</span>
          <button type="button" class="hf-btn" @click="ending = false">Huỷ</button>
          <button type="button" class="hf-btn lt" :disabled="busy" @click="endPlan">{{ busy ? 'Đang kết thúc…' : 'Kết thúc lịch' }}</button>
        </template>
      </div>
    </section>
    <section class="hf-card hf-c4">
      <span class="hf-lbl">Lịch mỗi tuần</span>
      <div>
        <div v-for="item in pattern" :key="item.day" class="hf-kv"><div><b>{{ item.day }}</b><br><span>{{ item.label }}</span></div><div class="v">{{ item.count }}</div></div>
      </div>
      <div class="grow" />
      <button v-if="active" type="button" class="hf-btn" @click="emit('ask', 'Chỉnh lịch tập hiện tại của mình.')">Chỉnh lịch với trợ lý</button>
      <button v-else type="button" class="hf-btn pri" @click="emit('create-plan')">Lập lịch mới</button>
    </section>
    <section class="hf-card hf-c12">
      <div class="hf-hd"><h2 class="list-title">Các buổi trong kế hoạch</h2><span class="hf-mut small">Mới nhất trước</span></div>
      <div class="sessions">
        <div v-for="entry in list" :key="entry.id" class="session">
          <div><div class="s-name">{{ entry.label }}</div><div class="hf-mut tiny">{{ longDate(entry.scheduled_date) }}</div></div>
          <span class="hf-pill" :class="STATUS[state(entry)].cls">{{ STATUS[state(entry)].text }}</span>
        </div>
      </div>
      <p v-if="!list.length" class="hf-mut small">Lịch chưa có buổi tập nào.</p>
    </section>
  </div>
  <div v-else class="hf-card empty">
    <div class="empty-title">Bạn chưa có lịch tập</div>
    <p class="hf-mut">Lập lịch với trợ lý để theo dõi các buổi tập, tiến độ tuần và kế hoạch dài hạn.</p>
    <button type="button" class="hf-btn pri" @click="emit('create-plan')">Lập lịch với trợ lý</button>
  </div>
  <p v-if="plan && !active && ended" class="hf-mut tiny note">Kết thúc ngày {{ ddmm(ended) }}. Khi bạn lập lịch mới, lịch này sẽ được thay thế.</p>
</template>

<style scoped>
.small { font-size: 14px; }
.tiny { font-size: 12px; }
.big-row { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.due { font-size: 18px; font-weight: 600; }
.pdots { display: grid; grid-template-columns: repeat(16, minmax(0, 1fr)); gap: 8px; justify-items: center; }
.pd { width: 14px; height: 14px; border-radius: 50%; background: #2E2E33; }
.pd.done { background: var(--hf-acc); }
.pd.overdue { background: transparent; box-shadow: inset 0 0 0 2px #fff; }
.pd.cancelled { opacity: .35; }
.legend { color: #B4B4BA; }
.confirm-text { align-self: center; }
.grow { flex: 1; }
.list-title { margin: 0; font-size: 18px; }
.sessions { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
.session { display: flex; justify-content: space-between; align-items: center; gap: 10px; background: var(--hf-fill-2); border-radius: 16px; padding: 12px 14px; }
.s-name { font-weight: 600; font-size: 14px; }
.empty { align-items: flex-start; padding: 40px; }
.empty-title { font-size: 26px; font-weight: 700; }
.empty p { margin: 0; font-size: 15px; line-height: 1.55; }
.note { margin: 12px 0 0; }
@media (max-width: 760px) { .pdots { grid-template-columns: repeat(10, minmax(0, 1fr)); } }
</style>
