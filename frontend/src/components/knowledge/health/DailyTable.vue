<script setup lang="ts">
import { computed } from 'vue'
import { Table2 } from 'lucide-vue-next'
import type { DailyHealth } from '@/types/api'
import { LEVEL_LABELS, duration, fmt, longDay, num } from './healthFormat'
import type { HealthData } from './useHealthData'

const props = defineProps<{ data: HealthData }>()
const COLUMNS: { label: string; value: (day: DailyHealth) => string }[] = [
  { label: 'Bước', value: d => fmt(d.steps) },
  { label: 'Quãng đường', value: d => num(d.distance_m) != null ? `${fmt(num(d.distance_m)! / 1000, 2)} km` : '—' },
  { label: 'Tầng', value: d => fmt(d.floors) },
  { label: 'Phút vận động', value: d => fmt(d.active_minutes) },
  { label: 'Theo mức', value: d => Object.entries(d.active_minutes_by_level ?? {}).map(([level, minutes]) => `${LEVEL_LABELS[level] ?? level} ${minutes}`).join(' · ') || '—' },
  { label: 'Phút vùng tim', value: d => fmt(d.active_zone_minutes) },
  { label: 'Tiêu hao', value: d => fmt(d.total_kcal) },
  { label: 'Calo vận động', value: d => fmt(d.active_kcal) },
  { label: 'Nhịp nghỉ', value: d => fmt(d.resting_hr_bpm) },
  { label: 'Nhịp TB', value: d => fmt(d.hr_avg_bpm, 1) },
  { label: 'Nhịp thấp–cao', value: d => d.hr_min_bpm != null ? `${d.hr_min_bpm}–${d.hr_max_bpm ?? '—'}` : '—' },
  { label: 'HRV (ms)', value: d => fmt(d.hrv_ms, 1) },
  { label: 'SpO2 (%)', value: d => fmt(d.spo2_avg_pct, 1) },
  { label: 'Nhịp thở', value: d => fmt(d.respiratory_rate, 1) },
  { label: 'VO2max', value: d => fmt(d.vo2_max, 1) },
  { label: 'Nước (ml)', value: d => fmt(d.hydration_ml) },
  { label: 'Ngủ', value: d => d.sleep_minutes != null ? duration(d.sleep_minutes) : '—' },
  { label: 'Δ nhiệt độ da', value: d => num(d.skin_temp_delta_c) != null ? `${fmt(d.skin_temp_delta_c, 2)} °C` : '—' },
]
const rows = computed(() => [...props.data.daily].sort((a, b) => b.local_date.localeCompare(a.local_date)))
const columns = computed(() => COLUMNS.filter(column => rows.value.some(row => column.value(row) !== '—')))
</script>

<template>
  <section class="card" aria-labelledby="daily-title">
    <details>
      <summary><span><span class="eyeline"><Table2 :size="13" /> BẢNG SỐ LIỆU</span><span id="daily-title" class="title">Mọi chỉ số theo ngày ({{ rows.length }} ngày)</span></span></summary>
      <div v-if="rows.length" class="table-wrap">
        <table>
          <thead><tr><th>Ngày</th><th v-for="column in columns" :key="column.label" class="num">{{ column.label }}</th></tr></thead>
          <tbody><tr v-for="row in rows" :key="row.id"><td>{{ longDay(row.local_date) }}</td><td v-for="column in columns" :key="column.label" class="num">{{ column.value(row) }}</td></tr></tbody>
        </table>
      </div>
      <p v-else class="none">Chưa có số liệu theo ngày.</p>
    </details>
  </section>
</template>

<style scoped src="./healthCard.css"></style>
<style scoped>
summary { cursor: pointer; list-style: none; }
summary::-webkit-details-marker { display: none; }
summary > span { display: flex; flex-direction: column; }
summary .eyeline { margin-bottom: 7px; }
.title { font-size: 14px; font-weight: 500; color: #e9e8e2; }
summary::after { content: 'Mở bảng'; float: right; margin-top: -26px; font-size: 10px; color: #a9c9d4; }
details[open] summary::after { content: 'Thu gọn'; }
.none { font-size: 10.5px; color: #8d949c; }
</style>
