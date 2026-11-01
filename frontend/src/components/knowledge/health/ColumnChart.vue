<script setup lang="ts">
import { computed, onMounted, onUnmounted, shallowRef, useTemplateRef } from 'vue'
import { dayLabel, longDay } from './healthFormat'
import { niceScale, tickText } from './chartScale'

export interface ColumnSeries { key: string; label: string; color: string; values: (number | null)[] }
export interface SignedColors { negative: string; positive: string; negativeLabel: string; positiveLabel: string }

const props = withDefaults(defineProps<{
  label: string
  days: string[]
  /** Stacked bottom to top; one entry is a plain column chart. */
  series: ColumnSeries[]
  format: (value: number) => string
  /** A single signed series: bars below zero take the negative colour (diverging). */
  signed?: SignedColors | null
  reference?: { value: number; label: string } | null
  band?: { low: number; high: number; label: string } | null
  /** A fixed axis step, e.g. 2 for hours. */
  tickStep?: number
  height?: number
}>(), { signed: null, reference: null, band: null, tickStep: undefined, height: 190 })

const root = useTemplateRef<HTMLElement>('root')
const width = shallowRef(480)
let observer: ResizeObserver | undefined
onMounted(() => {
  observer = new ResizeObserver(([entry]) => { width.value = Math.max(240, Math.round(entry?.contentRect.width ?? 480)) })
  if (root.value) observer.observe(root.value)
})
onUnmounted(() => observer?.disconnect())

const PAD = { top: 14, right: 10, bottom: 24, left: 42 }
const GAP = 2
const plotW = computed(() => width.value - PAD.left - PAD.right)
const plotH = computed(() => props.height - PAD.top - PAD.bottom)
const present = computed(() => props.days.map((_, i) => props.series.some(s => s.values[i] != null)))
const totals = computed(() => props.days.map((_, i) => props.series.reduce((sum, s) => sum + (s.values[i] ?? 0), 0)))
const scale = computed(() => niceScale(
  [...totals.value.filter((_, i) => present.value[i]), props.reference?.value, props.band?.high, props.band?.low, 0], true, 4, props.tickStep))
const y = (value: number) => PAD.top + (scale.value.hi - value) / (scale.value.hi - scale.value.lo) * plotH.value
const slot = computed(() => plotW.value / Math.max(1, props.days.length))
const barW = computed(() => Math.max(2, Math.min(24, slot.value - GAP, slot.value * .64)))
const cx = (i: number) => PAD.left + slot.value * (i + .5)

/** A bar with a 4px rounded data end and a square end at the baseline. */
function barPath(x: number, from: number, to: number, w: number): string {
  const h = Math.abs(to - from)
  const r = Math.min(4, w / 2, h)
  if (to <= from) { // grows upward: data end at the top
    return `M${x},${from}V${to + r}Q${x},${to} ${x + r},${to}H${x + w - r}Q${x + w},${to} ${x + w},${to + r}V${from}Z`
  }
  return `M${x},${from}V${to - r}Q${x},${to} ${x + r},${to}H${x + w - r}Q${x + w},${to} ${x + w},${to - r}V${from}Z`
}

const bars = computed(() => props.days.map((day, i) => {
  const x = cx(i) - barW.value / 2
  if (props.signed) {
    const value = props.series[0]?.values[i]
    if (value == null || value === 0) return { day, i, parts: [] }
    const color = value < 0 ? props.signed.negative : props.signed.positive
    return { day, i, parts: [{ key: 'v', color, d: barPath(x, y(0), y(value), barW.value) }] }
  }
  const segments = props.series.map(s => ({ key: s.key, color: s.color, value: s.values[i] ?? 0 })).filter(s => s.value > 0)
  let base = 0
  const parts = segments.map((segment, index) => {
    // A 2px surface gap separates stacked segments; the top one carries the rounded end.
    const bottom = y(base) - (index ? GAP : 0)
    base += segment.value
    const top = y(base)
    const d = index === segments.length - 1 ? barPath(x, bottom, top, barW.value) : `M${x},${bottom}V${top}H${x + barW.value}V${bottom}Z`
    return { key: segment.key, color: segment.color, d, visible: bottom - top >= 1 }
  }).filter(part => part.visible)
  return { day, i, parts }
}))

const labelEvery = computed(() => Math.max(1, Math.ceil(props.days.length / Math.max(1, Math.floor(plotW.value / 46)))))
const showLabel = (i: number) => (props.days.length - 1 - i) % labelEvery.value === 0

const active = shallowRef<number | null>(null)
// Reference and band labels live in the key row, never on top of the bars.
const legend = computed(() => [
  ...(props.signed
    ? [{ key: 'neg', label: props.signed.negativeLabel, color: props.signed.negative, kind: 'swatch' },
       { key: 'pos', label: props.signed.positiveLabel, color: props.signed.positive, kind: 'swatch' }]
    : props.series.length > 1 ? props.series.map(s => ({ key: s.key, label: s.label, color: s.color, kind: 'swatch' })) : []),
  ...(props.band ? [{ key: 'band', label: props.band.label, color: '', kind: 'band' }] : []),
  ...(props.reference ? [{ key: 'ref', label: props.reference.label, color: '', kind: 'line' }] : []),
])
const tooltip = computed(() => {
  const i = active.value
  if (i == null) return null
  const rows = props.series.map(s => ({ key: s.key, label: s.label, color: s.color, value: s.values[i] }))
    .filter(row => row.value != null)
  if (props.signed && rows[0]) {
    const negative = (rows[0].value ?? 0) < 0
    rows[0] = { ...rows[0], label: negative ? props.signed.negativeLabel : props.signed.positiveLabel,
                color: negative ? props.signed.negative : props.signed.positive }
  }
  // Beside the hovered column, so the column itself stays visible.
  const right = cx(i) < width.value / 2
  return { day: props.days[i], rows, total: rows.length > 1 ? totals.value[i] : null,
           style: { left: `${cx(i) + (right ? 1 : -1) * (barW.value / 2 + 10)}px`, transform: right ? 'none' : 'translateX(-100%)' } }
})

function keydown(event: KeyboardEvent) {
  const last = props.days.length - 1
  const current = active.value ?? last
  const next = { ArrowLeft: current - 1, ArrowRight: current + 1, Home: 0, End: last }[event.key]
  if (next == null) return
  event.preventDefault()
  active.value = Math.min(last, Math.max(0, next))
}
</script>

<template>
  <figure ref="root" class="column-chart">
    <div v-if="legend.length" class="legend">
      <span v-for="item in legend" :key="item.key"><i :class="item.kind" :style="item.color ? { background: item.color } : undefined" />{{ item.label }}</span>
    </div>
    <div class="plot">
    <svg :width="width" :height="height" role="img" tabindex="0" :aria-label="`${label}. Dùng phím mũi tên để đọc từng ngày.`"
         @keydown="keydown" @focus="active = active ?? days.length - 1" @blur="active = null" @pointerleave="active = null">
      <rect v-if="band" class="band" :x="PAD.left" :width="plotW" :y="y(band.high)" :height="Math.max(0, y(band.low) - y(band.high))" />
      <g class="axis-grid">
        <g v-for="tick in scale.ticks" :key="tick">
          <line :x1="PAD.left" :x2="width - PAD.right" :y1="y(tick)" :y2="y(tick)" :class="{ zero: tick === 0 }" />
          <text :x="PAD.left - 7" :y="y(tick) + 3" text-anchor="end">{{ tickText(tick) }}</text>
        </g>
      </g>
      <g v-for="column in bars" :key="column.day" :class="{ dim: active != null && active !== column.i }" class="column">
        <path v-for="part in column.parts" :key="part.key" :d="part.d" :fill="part.color" />
      </g>
      <line v-if="reference" class="reference" :x1="PAD.left" :x2="width - PAD.right" :y1="y(reference.value)" :y2="y(reference.value)" />
      <g class="x-axis">
        <text v-for="(day, i) in days" v-show="showLabel(i)" :key="day" :x="cx(i)" :y="height - 7" text-anchor="middle"
              :class="{ current: active === i }">{{ dayLabel(day) }}</text>
      </g>
      <!-- The hit target is the whole day slot, not the painted bar. -->
      <rect v-for="(day, i) in days" :key="'hit-' + day" class="hit" :x="PAD.left + slot * i" :y="PAD.top" :width="slot" :height="plotH"
            @pointerenter="active = i" />
    </svg>
    <div v-if="tooltip" class="tooltip" :style="tooltip.style" aria-live="polite">
      <p class="when">{{ longDay(tooltip.day) }}</p>
      <p v-if="!tooltip.rows.length" class="empty">Không có dữ liệu</p>
      <p v-for="row in tooltip.rows" :key="row.key" class="row"><i :style="{ background: row.color }" /><strong>{{ format(row.value!) }}</strong><span>{{ row.label }}</span></p>
      <p v-if="tooltip.total != null" class="row total"><strong>{{ format(tooltip.total) }}</strong><span>Tổng</span></p>
    </div>
    </div>
  </figure>
</template>

<style scoped>
.column-chart { position: relative; margin: 0; min-width: 0; }
svg { display: block; overflow: visible; outline: none; }
svg:focus-visible { outline: 2px solid light-dark(#367689, #8fc3d4); outline-offset: 4px; border-radius: 6px; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 14px; margin-bottom: 10px; font-size: 10.5px; color: light-dark(#53575d, #a3a8ae); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend i { width: 10px; height: 10px; border-radius: 2px; }
.legend i.band { background: light-dark(#18181814, #ffffff14); border: 1px solid light-dark(#1818181f, #ffffff1f); }
.legend i.line { width: 14px; height: 1px; border-radius: 0; background: light-dark(#3c3e42, #c9ccd1); opacity: .7; }
.plot { position: relative; }
.axis-grid line { stroke: light-dark(#18181810, #ffffff10); stroke-width: 1; shape-rendering: crispEdges; }
.axis-grid line.zero { stroke: light-dark(#1818182e, #ffffff2e); }
.axis-grid text, .x-axis text { font: 9px 'JetBrains Mono', monospace; fill: light-dark(#69727c, #7e8792); font-variant-numeric: tabular-nums; }
.x-axis text.current { fill: light-dark(#2a2924, #e9e8e2); }
.band { fill: light-dark(#18181808, #ffffff08); }
.reference { stroke: light-dark(#3c3e42, #c9ccd1); stroke-opacity: .6; stroke-width: 1; shape-rendering: crispEdges; }
.column { transition: opacity 160ms; }
.column.dim { opacity: .45; }
.hit { fill: transparent; cursor: crosshair; }
.tooltip { position: absolute; top: 4px; z-index: 3; min-width: 132px; padding: 8px 10px; border: 1px solid light-dark(#1818181c, #ffffff1c); border-radius: 9px; background: light-dark(#f0efecf2, #0d0f13f2); box-shadow: 0 10px 28px light-dark(#0000003c, #0007); pointer-events: none; }
.tooltip p { margin: 0; }
.when { font-size: 10px; color: light-dark(#53575d, #a3a8ae); margin-bottom: 5px !important; }
.row { display: flex; align-items: center; gap: 7px; font-size: 10.5px; color: light-dark(#53575d, #a3a8ae); line-height: 1.7; }
.row i { width: 10px; height: 2px; border-radius: 2px; flex: none; }
.row strong { color: light-dark(#24231f, #f1f0eb); font-weight: 600; }
.row.total { border-top: 1px solid light-dark(#18181812, #ffffff12); margin-top: 3px !important; padding-top: 3px; }
.row.total strong { margin-left: 17px; }
.empty { font-size: 10.5px; color: light-dark(#60676e, #8d949c); }
@media (prefers-reduced-motion: reduce) { .column { transition: none; } }
</style>
