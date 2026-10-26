<script setup lang="ts">
import { computed, useId } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import type { KnowledgeGraph } from '@/types/knowledge'
import { number } from './dashboardData'
import { missingText, reasonText, useNutritionTargets, warningText } from './useNutritionTargets'

const props = defineProps<{ graph: KnowledgeGraph }>()
const titleId = useId()
const { targets, loading, error, refresh } = useNutritionTargets(() => props.graph.generated_at)

const ready = computed(() => targets.value?.status === 'ok' && targets.value.target_kcal != null)
const eaten = computed(() => targets.value?.today.energy_kcal ?? 0)
const percent = computed(() => {
  const goal = targets.value?.target_kcal
  return goal ? Math.min(100, Math.round((eaten.value / goal) * 100)) : 0
})
const over = computed(() => (targets.value?.today.remaining_kcal ?? 0) < 0)
const macros = computed(() => {
  const m = targets.value?.macros
  if (!m) return []
  return [
    { label: 'Protein', value: `${number(m.protein_g)} g`, note: `${m.protein_g_per_kg} g/kg` },
    { label: 'Carb', value: `${number(m.carbohydrate_g)} g`, note: 'phần còn lại' },
    { label: 'Chất béo', value: `${number(m.fat_g)} g`, note: '25% năng lượng' },
    { label: 'Chất xơ', value: `${number(m.fiber_g)} g`, note: '14 g/1000 kcal' },
  ]
})
const goalLabel = computed(() => ({ fat_loss: 'giảm mỡ', muscle_gain: 'tăng cơ', fitness: 'khoẻ hơn', maintenance: 'duy trì' }[targets.value?.goal_type ?? 'maintenance'] ?? 'duy trì'))
const sparkline = computed(() => {
  const points = targets.value?.weight_trend ?? []
  if (points.length < 2) return null
  const values = points.flatMap(p => [p.weight_kg, p.trend_kg])
  const min = Math.min(...values), max = Math.max(...values)
  const span = max - min || 1
  const x = (i: number) => (i / (points.length - 1)) * 100
  const y = (v: number) => 34 - ((v - min) / span) * 30
  return {
    raw: points.map((p, i) => `${x(i).toFixed(2)},${y(p.weight_kg).toFixed(2)}`).join(' '),
    trend: points.map((p, i) => `${x(i).toFixed(2)},${y(p.trend_kg).toFixed(2)}`).join(' '),
    last: points[points.length - 1],
  }
})
</script>

<template>
  <section class="energy-widget" :aria-labelledby="titleId">
    <div class="widget-head">
      <div><p class="eyeline">NĂNG LƯỢNG HÔM NAY</p><h3 :id="titleId">Mục tiêu do hệ thống tính</h3></div>
      <button class="refresh" type="button" aria-label="Tải lại mục tiêu" :disabled="loading" @click="refresh"><RefreshCw :size="14" :class="{ spinning: loading }" /></button>
    </div>

    <div v-if="loading && !targets" class="loading-state" role="status">Đang tính mục tiêu…<span /></div>
    <p v-else-if="error && !targets" class="notice">Chưa tải được mục tiêu năng lượng. <button type="button" @click="refresh">Thử lại</button></p>
    <p v-else-if="targets && targets.status !== 'ok'" class="notice">
      Cần thêm {{ targets.missing.map(missingText).join(', ') }} để tính mục tiêu. Bạn có thể cập nhật trong Cài đặt hoặc nhắn cho trợ lý.
    </p>
    <template v-else-if="targets && ready">
      <div class="headline">
        <p><strong>{{ number(eaten) }}</strong><span> / {{ number(targets.target_kcal!) }} kcal</span></p>
        <p class="remaining" :class="{ over }">
          {{ over ? `Vượt ${number(-(targets.today.remaining_kcal ?? 0))}` : `Còn ${number(targets.today.remaining_kcal ?? 0)}` }} kcal
        </p>
      </div>
      <div class="track" role="progressbar" :aria-valuenow="percent" aria-valuemin="0" aria-valuemax="100" aria-label="Phần năng lượng đã ăn hôm nay">
        <span :style="{ transform: `scaleX(${percent / 100})` }" :class="{ over }" />
      </div>
      <p class="note">
        Mục tiêu {{ goalLabel }}: BMR {{ number(targets.bmr_kcal!) }} × {{ targets.activity_factor }} = TDEE {{ number(targets.tdee_kcal!) }} kcal<span v-if="targets.weekly_change_kg">, dự kiến {{ targets.weekly_change_kg > 0 ? '+' : '' }}{{ number(targets.weekly_change_kg) }} kg/tuần</span>.
        <span v-if="targets.today.missing_values"> {{ targets.today.missing_values }} bữa hôm nay thiếu số liệu.</span>
      </p>
      <div class="macros">
        <div v-for="item in macros" :key="item.label"><strong>{{ item.value }}</strong><span>{{ item.label }} · {{ item.note }}</span></div>
      </div>
      <div class="adaptive">
        <template v-if="targets.adaptive.status === 'ok'">
          Chi tiêu thực tế ước tính <strong>{{ number(targets.adaptive.expenditure_kcal!) }} kcal/ngày</strong>
          (ăn TB {{ number(targets.adaptive.average_intake_kcal!) }} kcal, cân xu hướng {{ targets.adaptive.trend_change_kg! > 0 ? '+' : '' }}{{ number(targets.adaptive.trend_change_kg!) }} kg trong {{ targets.adaptive.span_days }} ngày).
        </template>
        <template v-else>Ước tính chi tiêu thích ứng: {{ targets.adaptive.reasons.map(reasonText).join('; ') }}.</template>
      </div>
      <figure v-if="sparkline" class="spark">
        <svg viewBox="0 0 100 36" preserveAspectRatio="none" role="img" :aria-label="`Cân nặng gần đây, xu hướng ${number(sparkline.last.trend_kg)} kg`">
          <polyline :points="sparkline.raw" class="raw" />
          <polyline :points="sparkline.trend" class="trend" />
        </svg>
        <figcaption><span class="dot raw" />Cân đo · <span class="dot trend" />Xu hướng {{ number(sparkline.last.trend_kg) }} kg</figcaption>
      </figure>
      <ul v-if="targets.warnings.length" class="warnings"><li v-for="code in targets.warnings" :key="code">{{ warningText(code) }}</li></ul>
    </template>
  </section>
</template>

<style scoped>
.energy-widget { container: energy / inline-size; min-width: 0; padding: clamp(16px, 2.2cqi, 24px); border: 1px solid #9fd3b026; border-radius: 18px; background: linear-gradient(125deg, #9fd3b008, transparent 60%), #14171d; }
.widget-head { display: flex; justify-content: space-between; gap: 12px; }
.eyeline { margin: 0 0 7px; font: 9px 'JetBrains Mono', monospace; letter-spacing: .12em; color: #9fd3b0; }
h3 { margin: 0; font-size: 14px; font-weight: 500; color: #e9e8e2; }
.refresh { align-self: flex-start; display: grid; place-items: center; width: 30px; height: 30px; border: 1px solid #ffffff13; border-radius: 50%; color: #9fc4ad; }
.refresh:hover { background: #9fd3b012; }
.headline { display: flex; align-items: flex-end; justify-content: space-between; gap: 10px; margin: 20px 0 12px; flex-wrap: wrap; }
.headline p { margin: 0; }
.headline strong { font-family: 'JetBrains Mono', monospace; font-size: clamp(26px, 7cqi, 40px); color: #e6f2ea; transition: font-size 200ms; }
.headline span { color: #a6b5ab; font-size: 12px; }
.remaining { font: 13px 'JetBrains Mono', monospace; color: #9fd3b0; }.remaining.over { color: #f0a58f; }
.track { height: 10px; border-radius: 8px; overflow: hidden; background: #ffffff0a; }
.track > span { display: block; width: 100%; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #4f8f6a, #a6e0bb); transform-origin: left; transition: transform 600ms cubic-bezier(.2,.8,.2,1); }
.track > span.over { background: linear-gradient(90deg, #b5654c, #f0a58f); }
.note { color: #a9b3ad; font-size: 11px; margin: 10px 0 16px; line-height: 1.6; }
.macros { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; padding: 14px 0; border-block: 1px solid #ffffff0c; }
.macros > div { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.macros strong { color: #e6f2ea; font: 16px 'JetBrains Mono', monospace; }.macros span { color: #9ea8a2; font-size: 10px; }
.adaptive { margin-top: 14px; font-size: 11px; line-height: 1.6; color: #b3bdb7; }.adaptive strong { color: #e6f2ea; font-weight: 600; }
.spark { margin: 14px 0 0; }
.spark svg { width: 100%; height: clamp(44px, 11cqi, 84px); display: block; }
.spark polyline { fill: none; stroke-width: 1.4; vector-effect: non-scaling-stroke; }
.spark polyline.raw { stroke: #ffffff40; stroke-dasharray: 2 2; }.spark polyline.trend { stroke: #9fd3b0; stroke-width: 2; }
.spark figcaption { display: flex; align-items: center; gap: 6px; font-size: 10px; color: #9ea8a2; margin-top: 4px; }
.dot { display: inline-block; width: 8px; height: 2px; }.dot.raw { background: #ffffff60; }.dot.trend { background: #9fd3b0; }
.warnings { margin: 12px 0 0; padding-left: 16px; font-size: 10.5px; color: #d9c79a; line-height: 1.6; }
.notice { margin-top: 16px; padding: 12px; border: 1px solid #9fd3b033; border-radius: 10px; font-size: 11px; color: #bcd2c3; line-height: 1.6; }.notice button { text-decoration: underline; margin-left: 4px; }
.loading-state { padding: 30px 0; color: #a9b3ad; font-size: 11px; }.loading-state span { display: block; margin-top: 14px; height: 10px; border-radius: 6px; background: #9fd3b015; }
.spinning { animation: spin 1s linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }
@container energy (max-width: 440px) { .macros { grid-template-columns: repeat(2, minmax(0, 1fr)); row-gap: 14px; } }
@container energy (min-width: 640px) { .macros strong { font-size: 18px; } .note, .adaptive { font-size: 12px; } }
@media (prefers-reduced-motion: reduce) { .track > span { transition: none; } .spinning { animation: none; } }
</style>
