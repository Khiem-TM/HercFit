<script setup lang="ts">
import { computed } from 'vue'
import { CheckCircle2, MoonStar, TriangleAlert } from 'lucide-vue-next'
import type { SleepSession } from '@/types/api'
import ColumnChart, { type ColumnSeries } from './ColumnChart.vue'
import { SLEEP_STAGES, UNSTAGED } from './healthColors'
import { clock, dayLabel, duration, fmt, num } from './healthFormat'
import type { HealthData } from './useHealthData'

const props = defineProps<{ data: HealthData }>()
const STAGES = [
  { key: 'deep', label: 'Ngủ sâu', color: SLEEP_STAGES.DEEP },
  { key: 'light', label: 'Ngủ nhẹ', color: SLEEP_STAGES.LIGHT },
  { key: 'rem', label: 'REM', color: SLEEP_STAGES.REM },
  { key: 'awake', label: 'Thức giấc', color: SLEEP_STAGES.AWAKE },
] as const

const main = computed(() => props.data.sleep.filter(session => !session.is_nap))
const naps = computed(() => props.data.sleep.filter(session => session.is_nap))
/** Main sleep per wake-up date, in hours; nights without stages are one neutral segment. */
const series = computed<ColumnSeries[]>(() => {
  const nights = new Map<string, SleepSession[]>()
  for (const session of main.value) nights.set(session.local_date, [...(nights.get(session.local_date) ?? []), session])
  const sum = (day: string, pick: (s: SleepSession) => number | null) => {
    const sessions = nights.get(day)
    if (!sessions) return null
    const values = sessions.map(pick).filter((value): value is number => value != null)
    return values.length ? values.reduce((a, b) => a + b, 0) / 60 : null
  }
  const staged = (s: SleepSession) => s.deep_minutes != null && s.rem_minutes != null
  const stageSeries = STAGES.map(stage => ({
    ...stage, values: props.data.days.map(day => sum(day, s => staged(s) ? s[`${stage.key}_minutes` as 'deep_minutes'] : null)),
  }))
  const unstaged = props.data.days.map(day => sum(day, s => staged(s) ? null : s.minutes_asleep))
  return unstaged.some(value => value != null)
    ? [...stageSeries, { key: 'unstaged', label: 'Ngủ (không phân giai đoạn)', color: UNSTAGED, values: unstaged }]
    : stageSeries
})
const sleep = computed(() => props.data.overview?.sleep)
const hasData = computed(() => main.value.length > 0)
const band = computed(() => {
  const [low, high] = sleep.value?.recommended_hours ?? [7, 9]
  return { low, high, label: `Khuyến nghị ${low}–${high} giờ` }
})
const enough = computed(() => sleep.value?.avg_minutes != null && sleep.value.avg_minutes >= (sleep.value.recommended_hours[0] * 60))
const last = computed(() => sleep.value?.last_night ?? main.value.at(-1) ?? null)
const format = (hours: number) => duration(hours * 60)
</script>

<template>
  <section class="card" aria-labelledby="sleep-title">
    <header class="card-head">
      <div><p class="eyeline"><MoonStar :size="13" /> GIẤC NGỦ</p><h3 id="sleep-title">Thời lượng và các giai đoạn ngủ</h3></div>
    </header>
    <template v-if="hasData && sleep">
      <div class="kpis">
        <div class="kpi"><span>TB mỗi đêm</span><strong>{{ duration(sleep.avg_minutes) }}</strong>
          <em class="status" :class="enough ? 'good' : 'warn'"><component :is="enough ? CheckCircle2 : TriangleAlert" :size="11" />{{ enough ? 'Đủ khuyến nghị' : 'Dưới khuyến nghị' }} {{ sleep.recommended_hours[0] }}–{{ sleep.recommended_hours[1] }} giờ</em></div>
        <div class="kpi"><span>7 đêm gần nhất</span><strong>{{ duration(sleep.avg_minutes_7d) }}</strong>
          <em>{{ sleep.nights_below_recommended }}/{{ sleep.nights }} đêm thiếu ngủ</em></div>
        <div class="kpi"><span>Ngủ sâu · REM</span><strong>{{ fmt(sleep.deep_pct, 1) }}%<small>· {{ fmt(sleep.rem_pct, 1) }}%</small></strong>
          <em>tỉ lệ trên thời gian ngủ</em></div>
        <div class="kpi"><span>Hiệu quả giấc ngủ</span><strong>{{ fmt(sleep.efficiency_pct, 1) }}<small>%</small></strong></div>
        <div class="kpi"><span>Độ đều giờ đi ngủ</span><strong>±{{ fmt(sleep.bedtime_stdev_minutes) }}<small>phút</small></strong>
          <em>độ lệch chuẩn giờ lên giường</em></div>
      </div>
      <ColumnChart label="Thời gian ngủ mỗi đêm theo giai đoạn" :days="data.days" :series="series" :format="format" :band="band" :tick-step="2" :height="210" />
      <div v-if="last" class="last-night">
        <span>Đêm gần nhất · {{ dayLabel(last.local_date) }}</span>
        <p><strong>{{ clock(last.start_at) }} → {{ clock(last.end_at) }}</strong> · ngủ {{ duration(last.minutes_asleep) }}
          <template v-if="last.minutes_to_fall_asleep != null"> · chờ ngủ {{ last.minutes_to_fall_asleep }} phút</template>
          <template v-if="last.minutes_awake != null"> · thức {{ last.minutes_awake }} phút</template>
          <template v-if="num(last.efficiency_pct) != null"> · hiệu quả {{ fmt(last.efficiency_pct, 1) }}%</template></p>
        <p v-if="last.data_source?.device" class="device">Thiết bị: {{ last.data_source.device }}</p>
      </div>
      <p v-if="naps.length" class="note">{{ naps.length }} giấc ngủ ngắn (không tính vào thời lượng ngủ đêm).</p>
    </template>
    <div v-else class="empty">Chưa có phiên ngủ trong khoảng này.<small>Cần đồng hồ hoặc vòng đeo theo dõi giấc ngủ và quyền "Giấc ngủ".</small></div>
  </section>
</template>

<style scoped src="./healthCard.css"></style>
<style scoped>
.last-night { margin-top: 14px; padding: 11px 0; border-block: 1px solid light-dark(#1818180c, #ffffff0c); font-size: 11px; color: light-dark(#3d3f42, #c9cbcf); }
.last-night > span { font-size: 10px; color: light-dark(#60676e, #8d949c); }
.last-night p { margin: 4px 0 0; line-height: 1.6; }
.last-night strong { color: light-dark(#24231f, #f1f0eb); font-weight: 600; }
.last-night .device { font-size: 10px; color: light-dark(#60676e, #8d949c); }
</style>
