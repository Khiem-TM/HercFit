<script setup lang="ts">
import { computed } from 'vue'
import { Scale } from 'lucide-vue-next'
import ColumnChart from './ColumnChart.vue'
import { DIVERGING } from './healthColors'
import { dayLabel, fmt, num } from './healthFormat'
import type { HealthData } from './useHealthData'

const props = defineProps<{ data: HealthData }>()
/** Chỉ các ngày đã trọn trong quá khứ: ít nhất hai bữa có năng lượng đã biết và có tổng từ thiết bị. */
const rows = computed(() => props.data.progress.flatMap(day => {
  const intake = num(day.calories_in.actual)
  const out = num(day.calories_out_actual)
  if (day.date >= props.data.end || intake == null || out == null || day.meal_count < 2) return []
  return [{ date: day.date, intake, out, balance: intake - out }]
}))
const byDay = computed(() => new Map(rows.value.map(row => [row.date, row.balance])))
const values = computed(() => props.data.days.map(day => byDay.value.get(day) ?? null))
const energy = computed(() => props.data.overview?.energy)
const signed = { ...DIVERGING, negativeLabel: 'Thâm hụt (nạp < tiêu hao)', positiveLabel: 'Dư (nạp > tiêu hao)' }
const format = (value: number) => `${value > 0 ? '+' : ''}${fmt(value)} kcal`
</script>

<template>
  <section class="card" aria-labelledby="energy-title">
    <header class="card-head">
      <div><p class="eyeline"><Scale :size="13" /> CÂN BẰNG NĂNG LƯỢNG</p><h3 id="energy-title">Calo nạp so với calo thiết bị ghi nhận</h3></div>
    </header>
    <template v-if="rows.length && energy">
      <div class="kpis">
        <div class="kpi"><span>Ngày đủ dữ liệu</span><strong>{{ energy.complete_days }}</strong><em>≥ 2 bữa có calo + số liệu thiết bị</em></div>
        <div class="kpi"><span>Nạp TB</span><strong>{{ fmt(energy.intake_kcal_avg) }}<small>kcal</small></strong></div>
        <div class="kpi"><span>Tiêu hao TB (thiết bị)</span><strong>{{ fmt(energy.device_expenditure_kcal_avg) }}<small>kcal</small></strong></div>
        <div class="kpi"><span>Chênh lệch TB</span><strong>{{ energy.balance_kcal_avg != null ? format(energy.balance_kcal_avg) : '—' }}</strong>
          <em>{{ (energy.balance_kcal_avg ?? 0) < 0 ? 'thâm hụt mỗi ngày' : 'dư mỗi ngày' }}</em></div>
        <div class="kpi"><span>Cân nặng trong kỳ</span><strong>{{ energy.weight_change_kg != null ? `${energy.weight_change_kg > 0 ? '+' : ''}${fmt(energy.weight_change_kg, 2)}` : '—' }}<small>kg</small></strong></div>
      </div>
      <ColumnChart label="Chênh lệch calo nạp trừ tiêu hao theo ngày" :days="data.days" :format="format" :signed="signed"
                   :series="[{ key: 'balance', label: 'Chênh lệch', color: DIVERGING.negative, values }]" />
      <div class="table-wrap">
        <table>
          <thead><tr><th>Ngày</th><th class="num">Nạp</th><th class="num">Tiêu hao</th><th class="num">Chênh lệch</th></tr></thead>
          <tbody><tr v-for="row in [...rows].reverse().slice(0, 7)" :key="row.date">
            <td>{{ dayLabel(row.date) }}</td><td class="num">{{ fmt(row.intake) }}</td><td class="num">{{ fmt(row.out) }}</td><td class="num">{{ format(row.balance) }}</td>
          </tr></tbody>
        </table>
      </div>
      <p class="note">{{ energy.note }}</p>
    </template>
    <div v-else class="empty">Chưa đủ ngày để so sánh.<small>Cần ngày đã qua có ít nhất 2 bữa ăn ghi đủ calo và calo tiêu hao từ thiết bị.</small></div>
  </section>
</template>

<style scoped src="./healthCard.css"></style>
<style scoped>
.table-wrap { margin-top: 14px; }
</style>
