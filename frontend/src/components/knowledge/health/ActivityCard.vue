<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { CheckCircle2, Footprints, TriangleAlert } from 'lucide-vue-next'
import type { DailyHealth } from '@/types/api'
import ColumnChart from './ColumnChart.vue'
import { SERIES } from './healthColors'
import { ACTIVITY_LABELS, fmt, num } from './healthFormat'
import type { HealthData } from './useHealthData'

const props = defineProps<{ data: HealthData }>()
const WHO_DAILY = 150 / 7

type Metric = { key: string; label: string; unit: string; digits: number; pick: (day: DailyHealth) => number | null; target?: { value: number; label: string } }
const METRICS: Metric[] = [
  { key: 'steps', label: 'Bước chân', unit: 'bước', digits: 0, pick: d => d.steps },
  { key: 'active', label: 'Phút vận động', unit: 'phút', digits: 0, pick: d => d.active_minutes,
    target: { value: WHO_DAILY, label: 'WHO ~21 phút/ngày' } },
  { key: 'azm', label: 'Phút vùng tim', unit: 'phút', digits: 0, pick: d => d.active_zone_minutes },
  { key: 'kcal', label: 'Calo tiêu hao', unit: 'kcal', digits: 0, pick: d => num(d.total_kcal) },
  { key: 'active_kcal', label: 'Calo vận động', unit: 'kcal', digits: 0, pick: d => num(d.active_kcal) },
  { key: 'distance', label: 'Quãng đường', unit: 'km', digits: 2, pick: d => { const m = num(d.distance_m); return m == null ? null : m / 1000 } },
  { key: 'floors', label: 'Tầng leo', unit: 'tầng', digits: 0, pick: d => d.floors },
  { key: 'water', label: 'Nước uống', unit: 'ml', digits: 0, pick: d => num(d.hydration_ml) },
]
const selected = shallowRef('steps')
const byDay = computed(() => new Map(props.data.daily.map(day => [day.local_date, day])))
const available = computed(() => METRICS.filter(metric => props.data.daily.some(day => metric.pick(day) != null)))
const metric = computed(() => available.value.find(item => item.key === selected.value) ?? available.value[0])
const values = computed(() => metric.value
  ? props.data.days.map(day => { const row = byDay.value.get(day); return row ? metric.value!.pick(row) : null }) : [])
const reference = computed(() => {
  if (!metric.value) return null
  if (metric.value.target) return metric.value.target
  // Bước chân dùng trung bình của backend (chỉ các ngày có đeo) để đường khớp với con số chính.
  const overview = props.data.overview?.activity.steps_avg
  if (metric.value.key === 'steps' && overview != null) return { value: overview, label: `TB ${fmt(overview)} bước (ngày có đeo)` }
  // Hôm nay vẫn đang được ghi, nên không tính vào trung bình.
  const known = values.value.filter((value, i): value is number => value != null && props.data.days[i] !== props.data.end)
  if (known.length < 2) return null
  const average = known.reduce((sum, value) => sum + value, 0) / known.length
  return { value: average, label: `TB ${fmt(average, metric.value.digits)} ${metric.value.unit}` }
})
const format = (value: number) => `${fmt(value, metric.value?.digits ?? 0)} ${metric.value?.unit ?? ''}`
const activity = computed(() => props.data.overview?.activity)
const workouts = computed(() => props.data.workouts.length)
</script>

<template>
  <section class="card" aria-labelledby="activity-title">
    <header class="card-head">
      <div><p class="eyeline"><Footprints :size="13" /> VẬN ĐỘNG</p><h3 id="activity-title">Bước chân, phút vận động và năng lượng</h3></div>
    </header>
    <div v-if="activity" class="kpis">
      <div class="kpi"><span>Bước TB/ngày</span><strong>{{ fmt(activity.steps_avg) }}</strong>
        <em>7 ngày {{ fmt(activity.steps_avg_7d) }}<template v-if="activity.steps_trend_pct != null"> ({{ activity.steps_trend_pct > 0 ? '+' : '' }}{{ fmt(activity.steps_trend_pct, 1) }}%)</template></em></div>
      <div class="kpi"><span>Phút vận động · 7 ngày</span><strong>{{ fmt(activity.active_minutes_week) }}<small>/ 150</small></strong>
        <em v-if="activity.meets_who_guideline != null" class="status" :class="activity.meets_who_guideline ? 'good' : 'warn'">
          <component :is="activity.meets_who_guideline ? CheckCircle2 : TriangleAlert" :size="11" />{{ activity.meets_who_guideline ? 'Đạt khuyến nghị WHO' : 'Chưa đạt khuyến nghị WHO' }}</em></div>
      <div class="kpi"><span>Phút vùng tim · 7 ngày</span><strong>{{ fmt(activity.active_zone_minutes_week) }}</strong></div>
      <div class="kpi"><span>Quãng đường TB</span><strong>{{ fmt(activity.distance_km_avg, 2) }}<small>km/ngày</small></strong></div>
      <div class="kpi"><span>Tiêu hao TB (ước tính)</span><strong>{{ fmt(activity.total_kcal_avg) }}<small>kcal</small></strong>
        <em v-if="activity.active_kcal_avg != null">vận động {{ fmt(activity.active_kcal_avg) }} kcal</em></div>
      <div class="kpi"><span>Mức vận động thực tế</span><strong class="text">{{ activity.observed_level ? ACTIVITY_LABELS[activity.observed_level] : '—' }}</strong>
        <em>{{ activity.days_with_data }} ngày có đeo thiết bị · {{ workouts }} buổi ghi bởi thiết bị</em></div>
    </div>
    <template v-if="metric">
      <div class="picker" role="group" aria-label="Chỉ số hiển thị">
        <button v-for="item in available" :key="item.key" type="button" :aria-pressed="metric.key === item.key" @click="selected = item.key">{{ item.label }}</button>
      </div>
      <ColumnChart class="chart" :label="`${metric.label} theo ngày`" :days="data.days" :format="format" :reference="reference"
                   :series="[{ key: metric.key, label: metric.label, color: SERIES, values }]" />
      <p class="note">Ngày dưới 500 bước thường là chưa đeo thiết bị nên không tính vào trung bình. Calo tiêu hao do thiết bị ước tính.</p>
    </template>
    <div v-else class="empty">Chưa có dữ liệu vận động trong khoảng này.<small>Dữ liệu xuất hiện sau lần đồng bộ Google Health đầu tiên.</small></div>
  </section>
</template>

<style scoped src="./healthCard.css"></style>
<style scoped>
.chart { margin-top: 14px; }
.kpi > strong.text { font-size: 15px; }
</style>
