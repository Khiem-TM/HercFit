<script setup lang="ts">
import { computed, shallowRef, useId } from 'vue'
import { ArrowDownRight, ArrowUpRight, Minus, Scale } from 'lucide-vue-next'
import type { KnowledgeGraph } from '@/types/knowledge'
import { localDay, number, shiftDay, shortDate, weightPoints } from './dashboardData'

const props = defineProps<{ graph: KnowledgeGraph }>()
const emit = defineEmits<{ explore: [id: string] }>()
const titleId = useId()
const range = shallowRef(30)
const activeId = shallowRef<string>()
const ranges = [{ days: 7, label: '7 ngày' }, { days: 30, label: '30 ngày' }, { days: 0, label: 'Tất cả' }]
const points = computed(() => {
  const today = localDay(props.graph.generated_at || new Date())
  const start = range.value ? shiftDay(today, 1 - range.value) : ''
  return weightPoints(props.graph).filter(point => point.day >= start && point.day <= today)
})
const active = computed(() => points.value.find(point => point.id === activeId.value) ?? points.value.at(-1))
const delta = computed(() => points.value.length > 1 ? points.value.at(-1)!.weight - points.value[0].weight : null)
// A zero baseline keeps bar lengths proportional to the actual measurements.
const ceiling = computed(() => Math.ceil(Math.max(5, ...points.value.map(point => point.weight)) / 10) * 10)
const ticks = computed(() => [ceiling.value, ceiling.value / 2, 0])
const selectedDetails = computed(() => active.value?.node.details.filter(item => ['BMI', 'Mỡ cơ thể', 'Khối cơ'].includes(item.label)) ?? [])
</script>

<template>
  <section class="weight-widget" :aria-labelledby="titleId">
    <header class="widget-head"><div><p class="eyeline"><Scale :size="13" /> CƠ THỂ</p><h3 :id="titleId">Nhịp thay đổi cân nặng</h3></div>
      <div class="range-picker" role="group" aria-label="Khoảng thời gian cân nặng"><button v-for="item in ranges" :key="item.days" type="button" :aria-pressed="range === item.days" @click="range = item.days">{{ item.label }}</button></div>
    </header>
    <template v-if="active">
      <div class="weight-summary"><p><strong>{{ number(active.weight) }}</strong><span>kg</span><small>{{ shortDate(active.at) }} · lần đo đang chọn</small></p>
        <span v-if="delta != null" class="delta"><component :is="delta < 0 ? ArrowDownRight : delta > 0 ? ArrowUpRight : Minus" :size="14" />{{ delta > 0 ? '+' : '' }}{{ number(delta) }} kg<small>đầu → cuối kỳ</small></span>
      </div>
      <div class="plot" role="group" aria-label="Biểu đồ cân nặng. Chọn cột để xem lần đo.">
        <div class="grid-lines" aria-hidden="true"><span v-for="tick in ticks" :key="tick"><i>{{ number(tick) }}</i></span></div>
        <div class="columns" :class="{ crowded: points.length > 14 }">
          <button v-for="(point, i) in points" :key="point.id" type="button" class="column" :class="{ selected: active.id === point.id }"
                  :aria-label="`${shortDate(point.at)}: ${number(point.weight)} kg`" :aria-pressed="active.id === point.id"
                  @mouseenter="activeId = point.id" @focus="activeId = point.id" @click="activeId = point.id">
            <span class="bar-space"><span class="bar" :style="{ height: `${point.weight / ceiling * 100}%`, animationDelay: `${i * 30}ms` }"><span class="bar-tooltip">{{ number(point.weight) }} kg</span></span></span>
            <span class="date-label" :class="{ sparse: points.length > 7 && i % 2 !== 0 && i !== points.length - 1 }">{{ shortDate(point.at) }}</span>
          </button>
        </div>
      </div>
      <div class="measurement" aria-live="polite"><span v-if="!selectedDetails.length">Đã ghi nhận {{ shortDate(active.at) }}</span><span v-for="item in selectedDetails" :key="item.label">{{ item.label }} <strong>{{ item.value }}</strong></span>
        <button type="button" @click="emit('explore', active.id)">Xem số đo <ArrowUpRight :size="12" /></button>
      </div>
      <p class="chart-note">{{ points.length }} lần đo có sẵn · Rê chuột, chạm hoặc dùng Tab để xem.</p>
    </template>
    <div v-else class="empty-chart"><Scale :size="28" :stroke-width="1" /><p>Chưa có số đo trong khoảng này.</p><small>Chọn “Tất cả” hoặc ghi cân nặng qua trò chuyện.</small></div>
  </section>
</template>

<style scoped>
.weight-widget { container: weight / inline-size; min-width: 0; padding: clamp(16px, 2.2cqi, 24px); border: 1px solid #8fc3d426; border-radius: 18px; background: linear-gradient(125deg, #8fc3d408, transparent 60%), #14171d; }
.widget-head { display: flex; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.eyeline { display: flex; align-items: center; gap: 6px; margin: 0 0 7px; font: 9px 'JetBrains Mono', monospace; letter-spacing: .12em; color: #8fc3d4; }
h3 { margin: 0; font-size: 14px; font-weight: 500; color: #e9e8e2; }
.range-picker { display: flex; align-self: flex-start; background: #0e1116; padding: 3px; border-radius: 9px; border: 1px solid #ffffff0e; }
.range-picker button { padding: 6px 9px; border-radius: 6px; font-size: 10px; color: #9b9fa5; transition: background 180ms, color 180ms; }
.range-picker button[aria-pressed=true] { background: #8fc3d41c; color: #b8deeb; }
.weight-summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 22px 0 14px; }
.weight-summary p { margin: 0; }
.weight-summary strong { font-family: 'Playfair Display', serif; font-size: clamp(28px, 8cqi, 42px); color: #e7f0f1; letter-spacing: -.03em; transition: font-size 200ms; }
.weight-summary p > span { margin-left: 6px; font-size: 12px; color: #8fc3d4; }
.weight-summary small { display: block; font-size: 10px; font-weight: 400; color: #959ca4; margin-top: 3px; }
.delta { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 3px; max-width: 130px; font: 12px 'JetBrains Mono', monospace; color: #b8deeb; }
.delta small { width: 100%; text-align: right; font-family: Geist, sans-serif; }
/* The chart grows with the widget, so a wide panel gets a taller, easier-to-read plot. */
.plot { position: relative; height: clamp(170px, 36cqi, 280px); padding-left: 30px; transition: height 200ms; }
.grid-lines { position: absolute; inset: 0 0 25px 0; display: flex; flex-direction: column; justify-content: space-between; pointer-events: none; }
.grid-lines span { border-top: 1px dashed #ffffff10; margin-left: 30px; position: relative; }
.grid-lines i { position: absolute; right: calc(100% + 7px); top: -6px; font: 9px 'JetBrains Mono', monospace; color: #7e8792; }
.columns { display: flex; gap: 5px; height: 100%; position: relative; }
.column { min-width: 0; flex: 1; display: flex; align-items: center; flex-direction: column; border-radius: 5px; }
.column:focus-visible { outline: 2px solid #8fc3d4; outline-offset: 2px; }
.bar-space { display: flex; align-items: flex-end; justify-content: center; flex: 1; min-height: 0; width: 100%; }
.bar { position: relative; width: 70%; max-width: 48px; min-width: 5px; border-radius: 5px 5px 1px 1px; background: linear-gradient(180deg, #8fc3d4b3, #8fc3d42b); border-top: 2px solid #8fc3d4; transform-origin: bottom; animation: rise 650ms cubic-bezier(.2,.8,.2,1) backwards; transition: height 400ms, background 180ms, box-shadow 180ms; }
.selected .bar { background: linear-gradient(180deg, #b8deeb, #8fc3d462); box-shadow: 0 0 20px #8fc3d41a; }
.bar-tooltip { position: absolute; bottom: calc(100% + 6px); left: 50%; transform: translate(-50%, 4px); opacity: 0; white-space: nowrap; padding: 4px 6px; background: #d0ebf2; color: #182a32; border-radius: 5px; font: 9px 'JetBrains Mono', monospace; pointer-events: none; z-index: 2; transition: opacity 160ms, transform 160ms; }
.column:hover .bar-tooltip, .column:focus-visible .bar-tooltip { opacity: 1; transform: translate(-50%, 0); }
.column:first-child .bar-tooltip { left: 0; transform: translateY(0); }
.column:last-child .bar-tooltip { left: auto; right: 0; transform: translateY(0); }
/* 9px + 16px: the band under the bars that the grid lines leave free. */
.date-label { flex: none; height: 16px; margin-top: 9px; font: 9px/16px 'JetBrains Mono', monospace; color: #8e98a2; white-space: nowrap; }
.date-label.sparse { visibility: hidden; }
.selected .date-label { color: #c2e5ee; }
.measurement { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; margin-top: 14px; padding: 11px 0; border-block: 1px solid #ffffff0c; color: #9aa4ae; font-size: 10px; }
.measurement strong { margin-left: 4px; color: #dce7ec; font-weight: 500; }
.measurement button { display: flex; align-items: center; gap: 4px; margin-left: auto; color: #8fc3d4; min-height: 24px; }
.chart-note { margin: 10px 0 0; color: #8c949c; font-size: 10px; line-height: 1.5; }
.empty-chart { min-height: 180px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; text-align: center; color: #a2b6be; font-size: 12px; }
.empty-chart p { margin: 0; }.empty-chart small { color: #8c949c; }
@keyframes rise { from { transform: scaleY(0); } }
@container weight (max-width: 400px) { .date-label { font-size: 8px; } .columns { gap: 3px; } }
@container weight (min-width: 560px) { .columns:not(.crowded) .date-label.sparse { visibility: visible; } .columns { gap: 8px; } }
@media (prefers-reduced-motion: reduce) { .bar { animation: none; transition: none; } }
</style>
