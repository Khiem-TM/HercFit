<script setup lang="ts">
import { computed } from 'vue'
import { CheckCircle2, CircleDashed, Gauge, Info, MessageCircle, TriangleAlert } from 'lucide-vue-next'
import type { DailyAssessment, ReasonKind } from '@/types/api'
import SleepLogForm from './SleepLogForm.vue'
import { SLEEP_STAGES } from './healthColors'
import { dayLabel, duration, fmt } from './healthFormat'

/** Đánh giá hôm nay do backend tính (tất định); thẻ chỉ hiển thị, không tính lại số nào. */
const props = defineProps<{ assessment: DailyAssessment | null; connected: boolean }>()
const emit = defineEmits<{ ask: [text: string]; logged: [] }>()

const QUESTION = 'Phân tích độ sẵn sàng tập luyện hôm nay của tôi và gợi ý buổi tập phù hợp.'
const CONFIDENCE = { high: 'cao', medium: 'vừa', low: 'thấp' } as const
const TONE: Record<string, string> = { ready: 'good', steady: 'good', ease_off: 'warn', recover: 'warn',
                                       needs_review: 'warn', insufficient_data: 'muted' }
const ICONS: Record<ReasonKind, typeof Info> = { strain: TriangleAlert, review: TriangleAlert, positive: CheckCircle2,
                                                 info: Info, data: CircleDashed }
const CORE = ['sleep_minutes', 'hrv_ms', 'resting_hr_bpm']

const a = computed(() => props.assessment)
const summary = computed(() => {
  const text = a.value?.summary ?? ''
  return a.value && text.startsWith(`${a.value.label}: `) ? text.slice(a.value.label.length + 2) : text
})
const core = computed(() => (a.value?.metrics ?? []).filter(metric => CORE.includes(metric.metric)))
const night = computed(() => a.value?.sleep?.last_night)
const week = computed(() => a.value?.sleep?.week)
const stages = computed(() => {
  const n = night.value
  if (!n || n.manual) return []
  const parts = [{ key: 'DEEP', label: 'Sâu', minutes: n.deep_minutes }, { key: 'LIGHT', label: 'Nông', minutes: n.light_minutes },
                 { key: 'REM', label: 'REM', minutes: n.rem_minutes }]
  const total = parts.reduce((sum, part) => sum + (part.minutes ?? 0), 0)
  return total ? parts.filter(part => part.minutes).map(part => ({ ...part, share: (100 * (part.minutes ?? 0)) / total,
    color: SLEEP_STAGES[part.key as keyof typeof SLEEP_STAGES] })) : []
})
const reading = (value: number | undefined, unit: string) =>
  unit === 'min' ? duration(value) : `${fmt(value, unit === 'ms' ? 1 : 0)} ${unit}`
</script>

<template>
  <section class="card readiness" aria-labelledby="readiness-title" :data-state="a?.state">
    <header class="card-head">
      <div><p class="eyeline"><Gauge :size="13" /> SẴN SÀNG HÔM NAY{{ a ? ` · ${dayLabel(a.date)}` : '' }}</p>
        <h3 id="readiness-title" :class="['state', a ? TONE[a.state] : 'muted']">{{ a?.label ?? 'Chưa có đánh giá' }}</h3></div>
      <span v-if="a" class="chip" :class="a.confidence">Độ tin cậy {{ CONFIDENCE[a.confidence] }}</span>
    </header>
    <template v-if="a">
      <p v-if="summary" class="summary">{{ summary }}</p>
      <ul class="reasons">
        <li v-for="reason in a.reasons" :key="reason.code" :class="reason.kind">
          <component :is="ICONS[reason.kind]" :size="12" />{{ reason.text }}</li>
      </ul>
      <p v-if="a.recommendations.length" class="advice">{{ a.recommendations[0].text }}</p>
      <div class="kpis">
        <div v-for="metric in core" :key="metric.metric" class="kpi"><span>{{ metric.label }}</span>
          <strong>{{ metric.value != null ? reading(metric.value, metric.unit) : '—' }}</strong>
          <em v-if="metric.baseline != null">nền {{ reading(metric.baseline, metric.unit) }} · {{ metric.baseline_n }} ngày</em>
          <em v-else-if="metric.value == null">chưa có dữ liệu</em>
          <em v-else>chưa đủ ngày để có nền</em></div>
      </div>
      <div v-if="night || week?.nights" class="sleep">
        <p v-if="night"><strong>{{ night.bedtime }} → {{ night.wake_time }}</strong> · ngủ {{ duration(night.minutes_asleep) }}
          <template v-if="night.efficiency_pct != null && !night.manual"> · hiệu quả {{ fmt(night.efficiency_pct) }}%</template>
          <span v-if="night.manual" class="tag">ghi tay</span></p>
        <div v-if="stages.length" class="stages" role="img" :aria-label="stages.map(s => `${s.label} ${Math.round(s.share)}%`).join(', ')">
          <span v-for="stage in stages" :key="stage.key" :style="{ width: `${stage.share}%`, background: stage.color }" />
        </div>
        <p v-if="stages.length" class="legend"><span v-for="stage in stages" :key="stage.key"><i :style="{ background: stage.color }" />{{ stage.label }} {{ Math.round(stage.share) }}%</span></p>
        <p v-if="week" class="week">{{ week.nights }}/7 đêm có dữ liệu
          <template v-if="week.debt_minutes != null"> · nợ ngủ {{ duration(week.debt_minutes) }}</template>
          <template v-if="week.bedtime_sd_minutes != null"> · giờ ngủ lệch ±{{ fmt(week.bedtime_sd_minutes) }} phút</template></p>
      </div>
      <SleepLogForm v-if="!night" :day="a.date" @saved="emit('logged')" />
      <footer>
        <p class="note">{{ a.disclaimer }} <small>({{ a.algorithm_version }})</small></p>
        <button type="button" class="ask" @click="emit('ask', QUESTION)"><MessageCircle :size="12" /> Hỏi trợ lý</button>
      </footer>
    </template>
    <div v-else class="empty"><CircleDashed :size="20" />Chưa có đánh giá hôm nay.
      <small>{{ connected ? 'Đánh giá cần dữ liệu thiết bị đã đồng bộ.' : 'Kết nối Google Health để có đánh giá độ sẵn sàng mỗi sáng.' }}</small></div>
  </section>
</template>

<style scoped src="./healthCard.css"></style>
<style scoped>
.state.good { color: light-dark(#417e58, #9fd3b0); }
.state.warn { color: light-dark(#8f6817, #e8c07d); }
.state.muted { color: light-dark(#60676e, #8d949c); }
h3.state { font: 500 clamp(18px, 4.6cqi, 22px) Geist, sans-serif; }
.chip { padding: 3px 9px; border-radius: 999px; font-size: 10px; border: 1px solid light-dark(#18181818, #ffffff18); color: light-dark(#53575d, #a3a8ae); }
.chip.high { color: light-dark(#417e58, #9fd3b0); border-color: light-dark(#417e5840, #9fd3b040); }
.chip.low { color: light-dark(#8f6817, #e8c07d); border-color: light-dark(#8f681740, #e8c07d40); }
.summary { margin: 10px 0 0; font-size: 12px; line-height: 1.6; color: light-dark(#363530, #d9d8d2); }
.reasons { display: flex; flex-direction: column; gap: 5px; margin: 12px 0 0; padding: 0; list-style: none; }
.reasons li { display: flex; gap: 7px; align-items: flex-start; font-size: 10.5px; line-height: 1.5; color: light-dark(#53575d, #a3a8ae); }
.reasons li svg { flex: none; margin-top: 2px; }
.reasons li.strain svg, .reasons li.review svg { color: light-dark(#8f6817, #e8c07d); }
.reasons li.positive svg { color: light-dark(#417e58, #9fd3b0); }
.advice { margin: 12px 0 0; padding: 9px 11px; border-radius: 10px; background: light-dark(#3676890d, #8fc3d40d); font-size: 11px; line-height: 1.55; color: light-dark(#1d3137, #cfe7ef); }
.sleep { display: flex; flex-direction: column; gap: 6px; padding-top: 12px; border-top: 1px solid light-dark(#1818180c, #ffffff0c); }
.sleep p { margin: 0; font-size: 11px; color: light-dark(#53575d, #a3a8ae); }
.sleep strong { color: light-dark(#24231f, #f1f0eb); font-weight: 600; }
.tag { margin-left: 6px; padding: 1px 6px; border-radius: 6px; font-size: 9.5px; background: light-dark(#18181810, #ffffff10); }
.stages { display: flex; height: 8px; overflow: hidden; border-radius: 4px; background: light-dark(#18181810, #ffffff10); }
.stages span { display: block; height: 100%; }
.legend { display: flex; flex-wrap: wrap; gap: 10px; }
.legend span { display: inline-flex; align-items: center; gap: 4px; font-size: 10px; }
.legend i { width: 8px; height: 8px; border-radius: 2px; }
.week { font-size: 10.5px; }
footer { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 10px; }
footer .note { flex: 1 1 220px; }
.ask { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border: 1px solid light-dark(#36768940, #8fc3d440); border-radius: 999px; font-size: 11px; color: light-dark(#367689, #8fc3d4); }
.ask:hover { background: light-dark(#3676890f, #8fc3d40f); }
</style>
