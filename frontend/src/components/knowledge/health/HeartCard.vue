<script setup lang="ts">
import { computed } from 'vue'
import { CheckCircle2, HeartPulse, TriangleAlert } from 'lucide-vue-next'
import type { DailyHealth } from '@/types/api'
import LineChart from './LineChart.vue'
import { SERIES } from './healthColors'
import { fmt, num } from './healthFormat'
import type { HealthData } from './useHealthData'

const props = defineProps<{ data: HealthData }>()
const byDay = computed(() => new Map(props.data.daily.map(day => [day.local_date, day])))
const seriesOf = (pick: (day: DailyHealth) => number | null) =>
  props.data.days.map(day => { const row = byDay.value.get(day); return row ? pick(row) : null })
const known = (values: (number | null)[]) => values.filter((value): value is number => value != null)

const resting = computed(() => seriesOf(d => d.resting_hr_bpm))
const hrv = computed(() => seriesOf(d => num(d.hrv_ms)))
const spo2 = computed(() => seriesOf(d => num(d.spo2_avg_pct)))
const recovery = computed(() => props.data.overview?.recovery)
const heartRange = computed(() => {
  const average = known(seriesOf(d => num(d.hr_avg_bpm)))
  const lows = known(seriesOf(d => d.hr_min_bpm))
  const highs = known(seriesOf(d => d.hr_max_bpm))
  return { average: average.length ? average.reduce((a, b) => a + b, 0) / average.length : null,
           low: lows.length ? Math.min(...lows) : null, high: highs.length ? Math.max(...highs) : null }
})
const latest = (pick: (day: DailyHealth) => number | null) => {
  const rows = [...props.data.daily].sort((a, b) => b.local_date.localeCompare(a.local_date))
  const row = rows.find(day => pick(day) != null)
  return row ? { value: pick(row)!, day: row.local_date } : null
}
const vo2 = computed(() => latest(d => num(d.vo2_max)))
const skin = computed(() => latest(d => num(d.skin_temp_delta_c)))
const breathing = computed(() => latest(d => num(d.respiratory_rate)))
const hasData = computed(() => known(resting.value).length + known(hrv.value).length + known(spo2.value).length > 0
  || heartRange.value.average != null)
const restingBaseline = computed(() => recovery.value?.resting_hr_baseline != null
  ? { value: recovery.value.resting_hr_baseline, label: `Nền 28 ngày ${fmt(recovery.value.resting_hr_baseline)} bpm` } : null)
const hrvBaseline = computed(() => recovery.value?.hrv_baseline != null
  ? { value: recovery.value.hrv_baseline, label: `Nền 28 ngày ${fmt(recovery.value.hrv_baseline, 1)} ms` } : null)
</script>

<template>
  <section class="card" aria-labelledby="heart-title">
    <header class="card-head">
      <div><p class="eyeline"><HeartPulse :size="13" /> TIM MẠCH &amp; PHỤC HỒI</p><h3 id="heart-title">Nhịp tim nghỉ, HRV và chỉ số hô hấp</h3></div>
    </header>
    <template v-if="hasData">
      <div class="kpis">
        <div class="kpi"><span>Nhịp tim nghỉ · 7 ngày</span><strong>{{ fmt(recovery?.resting_hr_7d) }}<small>bpm</small></strong>
          <em v-if="recovery?.resting_hr_elevated != null" class="status" :class="recovery.resting_hr_elevated ? 'warn' : 'good'">
            <component :is="recovery.resting_hr_elevated ? TriangleAlert : CheckCircle2" :size="11" />{{ recovery.resting_hr_elevated ? 'Cao hơn nền' : 'Trong khoảng nền' }}</em>
          <em v-else>cần ≥ 7 ngày nền để so sánh</em></div>
        <div class="kpi"><span>HRV · 7 ngày</span><strong>{{ fmt(recovery?.hrv_7d, 1) }}<small>ms</small></strong>
          <em v-if="recovery?.hrv_suppressed != null" class="status" :class="recovery.hrv_suppressed ? 'warn' : 'good'">
            <component :is="recovery.hrv_suppressed ? TriangleAlert : CheckCircle2" :size="11" />{{ recovery.hrv_suppressed ? 'Thấp hơn nền' : 'Trong khoảng nền' }}</em></div>
        <div class="kpi"><span>Nhịp tim trong kỳ</span><strong>{{ fmt(heartRange.average) }}<small>bpm TB</small></strong>
          <em v-if="heartRange.low != null">thấp nhất {{ heartRange.low }} · cao nhất {{ heartRange.high }} bpm</em></div>
        <div class="kpi"><span>SpO2 · 7 ngày</span><strong>{{ fmt(recovery?.spo2_avg, 1) }}<small>%</small></strong></div>
        <div class="kpi"><span>Nhịp thở khi ngủ</span><strong>{{ fmt(breathing?.value ?? recovery?.respiratory_rate_avg, 1) }}<small>lần/phút</small></strong></div>
        <div class="kpi"><span>VO2max</span><strong>{{ fmt(vo2?.value, 1) }}<small>ml/kg/phút</small></strong></div>
        <div class="kpi"><span>Nhiệt độ da khi ngủ</span><strong>{{ skin ? `${skin.value > 0 ? '+' : ''}${fmt(skin.value, 2)}` : '—' }}<small>°C so với nền</small></strong></div>
      </div>
      <div class="charts">
        <div v-if="known(resting).length">
          <p class="chart-title">Nhịp tim nghỉ (bpm)</p>
          <LineChart label="Nhịp tim nghỉ theo ngày" :days="data.days" :values="resting" :color="SERIES" :baseline="restingBaseline" :format="v => `${fmt(v)} bpm`" />
        </div>
        <div v-if="known(hrv).length">
          <p class="chart-title">HRV (ms)</p>
          <LineChart label="HRV theo ngày" :days="data.days" :values="hrv" :color="SERIES" :baseline="hrvBaseline" :format="v => `${fmt(v, 1)} ms`" />
        </div>
        <div v-if="known(spo2).length > 1">
          <p class="chart-title">SpO2 trung bình đêm (%)</p>
          <LineChart label="SpO2 theo ngày" :days="data.days" :values="spo2" :color="SERIES" :format="v => `${fmt(v, 1)}%`" />
        </div>
      </div>
      <ul v-if="recovery?.signals.length" class="signals">
        <li v-for="signal in recovery.signals" :key="signal"><TriangleAlert :size="13" />{{ signal }}</li>
      </ul>
      <p class="note">Tín hiệu phục hồi so với chính bạn trong 28 ngày, không phải chẩn đoán y khoa. Có triệu chứng bất thường hãy gặp nhân viên y tế.</p>
    </template>
    <div v-else class="empty">Chưa có dữ liệu nhịp tim trong khoảng này.<small>Cần thiết bị đo nhịp tim và quyền "Chỉ số cơ thể &amp; tim mạch".</small></div>
  </section>
</template>

<style scoped src="./healthCard.css"></style>
<style scoped>
.charts { display: grid; gap: 18px; grid-template-columns: minmax(0, 1fr); }
.chart-title { margin: 0 0 6px; font-size: 10.5px; color: #a3a8ae; }
@container card (min-width: 720px) { .charts { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
