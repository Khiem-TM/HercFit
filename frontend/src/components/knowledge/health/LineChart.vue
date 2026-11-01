<script setup lang="ts">
import { computed, onMounted, onUnmounted, shallowRef, useTemplateRef } from 'vue'
import { dayLabel, longDay } from './healthFormat'
import { niceScale, tickText } from './chartScale'

const props = withDefaults(defineProps<{
  label: string
  days: string[]
  values: (number | null)[]
  color: string
  format: (value: number) => string
  baseline?: { value: number; label: string } | null
  height?: number
}>(), { baseline: null, height: 150 })

const root = useTemplateRef<HTMLElement>('root')
const width = shallowRef(420)
let observer: ResizeObserver | undefined
onMounted(() => {
  observer = new ResizeObserver(([entry]) => { width.value = Math.max(220, Math.round(entry?.contentRect.width ?? 420)) })
  if (root.value) observer.observe(root.value)
})
onUnmounted(() => observer?.disconnect())

// The right margin holds the direct label of the latest value.
const PAD = { top: 14, right: 58, bottom: 24, left: 36 }
const plotW = computed(() => width.value - PAD.left - PAD.right)
const plotH = computed(() => props.height - PAD.top - PAD.bottom)
const scale = computed(() => niceScale([...props.values, props.baseline?.value], false, 3))
const step = computed(() => plotW.value / Math.max(1, props.days.length - 1))
const x = (i: number) => PAD.left + (props.days.length === 1 ? plotW.value / 2 : step.value * i)
const y = (value: number) => PAD.top + (scale.value.hi - value) / (scale.value.hi - scale.value.lo) * plotH.value

/** Missing days break the line instead of being drawn as zero. */
const path = computed(() => {
  let d = ''
  let open = false
  props.values.forEach((value, i) => {
    if (value == null) { open = false; return }
    d += `${open ? 'L' : 'M'}${x(i).toFixed(1)},${y(value).toFixed(1)}`
    open = true
  })
  return d
})
const isolated = computed(() => props.values.map((value, i) => value != null && props.values[i - 1] == null && props.values[i + 1] == null))
const last = computed(() => {
  for (let i = props.values.length - 1; i >= 0; i--) if (props.values[i] != null) return i
  return null
})
const labelEvery = computed(() => Math.max(1, Math.ceil(props.days.length / Math.max(1, Math.floor(plotW.value / 46)))))

const active = shallowRef<number | null>(null)
function pointer(event: PointerEvent) {
  const box = (event.currentTarget as SVGElement).getBoundingClientRect()
  const i = Math.round((event.clientX - box.left - PAD.left) / (step.value || 1))
  active.value = Math.min(props.days.length - 1, Math.max(0, i))
}
function keydown(event: KeyboardEvent) {
  const end = props.days.length - 1
  const current = active.value ?? end
  const next = { ArrowLeft: current - 1, ArrowRight: current + 1, Home: 0, End: end }[event.key]
  if (next == null) return
  event.preventDefault()
  active.value = Math.min(end, Math.max(0, next))
}
// Beside the crosshair, so the point under it stays visible.
const tooltip = computed(() => {
  if (active.value == null) return null
  const right = x(active.value) < width.value / 2
  return { day: props.days[active.value], value: props.values[active.value],
           style: { left: `${x(active.value) + (right ? 12 : -12)}px`, transform: right ? 'none' : 'translateX(-100%)' } }
})
</script>

<template>
  <figure ref="root" class="line-chart">
    <p v-if="baseline" class="key"><i />{{ baseline.label }}</p>
    <div class="plot">
    <svg :width="width" :height="height" role="img" tabindex="0" :aria-label="`${label}. Dùng phím mũi tên để đọc từng ngày.`"
         @pointermove="pointer" @pointerleave="active = null" @keydown="keydown" @focus="active = active ?? last" @blur="active = null">
      <g class="axis-grid">
        <g v-for="tick in scale.ticks" :key="tick">
          <line :x1="PAD.left" :x2="PAD.left + plotW" :y1="y(tick)" :y2="y(tick)" />
          <text :x="PAD.left - 7" :y="y(tick) + 3" text-anchor="end">{{ tickText(tick) }}</text>
        </g>
      </g>
      <line v-if="baseline" class="baseline" :x1="PAD.left" :x2="PAD.left + plotW" :y1="y(baseline.value)" :y2="y(baseline.value)" />
      <path :d="path" class="trend" :stroke="color" />
      <template v-for="(value, i) in values" :key="days[i]">
        <circle v-if="value != null && isolated[i] && i !== last" :cx="x(i)" :cy="y(value)" r="3" :fill="color" />
      </template>
      <g v-if="active != null" class="crosshair">
        <line :x1="x(active)" :x2="x(active)" :y1="PAD.top" :y2="PAD.top + plotH" />
        <circle v-if="values[active] != null" :cx="x(active)" :cy="y(values[active]!)" r="4" :fill="color" class="ring" />
      </g>
      <g v-if="last != null">
        <circle :cx="x(last)" :cy="y(values[last]!)" r="4" :fill="color" class="ring" />
        <text class="end-label" :x="x(last) + 9" :y="y(values[last]!) + 3">{{ format(values[last]!) }}</text>
      </g>
      <g class="x-axis">
        <text v-for="(day, i) in days" v-show="(days.length - 1 - i) % labelEvery === 0" :key="day" :x="x(i)" :y="height - 7"
              text-anchor="middle" :class="{ current: active === i }">{{ dayLabel(day) }}</text>
      </g>
    </svg>
    <div v-if="tooltip" class="tooltip" :style="tooltip.style" aria-live="polite">
      <p class="when">{{ longDay(tooltip.day) }}</p>
      <p v-if="tooltip.value != null" class="row"><i :style="{ background: color }" /><strong>{{ format(tooltip.value) }}</strong></p>
      <p v-else class="row">Không có dữ liệu</p>
      <p v-if="baseline" class="row muted"><i class="base" /><span>{{ baseline.label }}</span></p>
    </div>
    </div>
  </figure>
</template>

<style scoped>
.line-chart { position: relative; margin: 0; min-width: 0; }
svg { display: block; overflow: visible; outline: none; cursor: crosshair; }
svg:focus-visible { outline: 2px solid light-dark(#367689, #8fc3d4); outline-offset: 4px; border-radius: 6px; }
.axis-grid line { stroke: light-dark(#18181810, #ffffff10); stroke-width: 1; shape-rendering: crispEdges; }
.axis-grid text, .x-axis text { font: 9px 'JetBrains Mono', monospace; fill: light-dark(#69727c, #7e8792); font-variant-numeric: tabular-nums; }
.x-axis text.current { fill: light-dark(#2a2924, #e9e8e2); }
.baseline { stroke: light-dark(#3c3e42, #c9ccd1); stroke-opacity: .6; stroke-width: 1; shape-rendering: crispEdges; }
.key { display: flex; align-items: center; gap: 6px; margin: 0 0 6px; font-size: 10px; color: light-dark(#53575d, #a3a8ae); }
.key i { width: 14px; height: 1px; background: light-dark(#3c3e42, #c9ccd1); opacity: .7; }
.plot { position: relative; }
.trend { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.ring { stroke: light-dark(#fdfcf9, #14171d); stroke-width: 2; }
.end-label { font: 600 10.5px Geist, sans-serif; fill: light-dark(#24231f, #f1f0eb); }
.crosshair line { stroke: light-dark(#18181845, #ffffff45); stroke-width: 1; shape-rendering: crispEdges; }
.tooltip { position: absolute; top: 4px; z-index: 3; min-width: 120px; padding: 8px 10px; border: 1px solid light-dark(#1818181c, #ffffff1c); border-radius: 9px; background: light-dark(#f0efecf2, #0d0f13f2); box-shadow: 0 10px 28px light-dark(#0000003c, #0007); pointer-events: none; }
.tooltip p { margin: 0; }
.when { font-size: 10px; color: light-dark(#53575d, #a3a8ae); margin-bottom: 5px !important; }
.row { display: flex; align-items: center; gap: 7px; font-size: 10.5px; color: light-dark(#53575d, #a3a8ae); line-height: 1.7; }
.row i { width: 10px; height: 2px; border-radius: 2px; flex: none; }
.row i.base { background: light-dark(#3c3e42, #c9ccd1); opacity: .6; }
.row strong { color: light-dark(#24231f, #f1f0eb); font-weight: 600; }
</style>
