<script setup lang="ts">
import { computed, onBeforeUnmount, shallowRef, useTemplateRef, watch } from 'vue'
import { CalendarRange } from 'lucide-vue-next'
import type { DayRange } from '@/composables/useKnowledgeGraph'
import { hubColor, type HubCounts, type KnowledgeHub, type KnowledgeWindow } from '@/types/knowledge'
import { dayDiff, daysBetween, rangeLength, recentRange, sameRange } from './timeWindow'

const props = defineProps<{
  modelValue: DayRange
  min: string
  max: string
  density: Record<string, HubCounts>
  /** The window the map was last drawn for, with its totals. */
  drawn?: KnowledgeWindow
  loading?: boolean
  failed?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [range: DayRange]; retry: [] }>()

type Grip = 'start' | 'end' | 'band' | 'edge'
const STACK: KnowledgeHub[] = ['body', 'nutrition', 'training', 'conversation']
const NOUNS: Record<string, string> = { Meal: 'bữa ăn', Training: 'buổi tập', BodyMetric: 'lần đo' }
const presets = [{ days: 7, label: '7 ngày' }, { days: 15, label: '15 ngày' }, { days: 30, label: '30 ngày' }, { days: 0, label: 'Tất cả' }]
const track = useTemplateRef<HTMLDivElement>('track')
const draft = shallowRef<DayRange>(props.modelValue)
const grip = shallowRef<Grip>()
const announced = shallowRef('')
let anchor = 0
let origin: DayRange = props.modelValue
let timer: ReturnType<typeof setTimeout> | undefined

const days = computed(() => daysBetween(props.min, props.max))
const count = computed(() => Math.max(1, days.value.length))
const clampIndex = (index: number) => Math.min(Math.max(index, 0), count.value - 1)
const startIndex = computed(() => clampIndex(dayDiff(props.min, draft.value.start)))
const endIndex = computed(() => clampIndex(dayDiff(props.min, draft.value.end)))
const bandStyle = computed(() => ({ '--left': `${startIndex.value / count.value * 100}%`, '--right': `${(endIndex.value + 1) / count.value * 100}%` }))
const total = (counts?: HubCounts) => STACK.reduce((sum, hub) => sum + (counts?.[hub] ?? 0), 0)
const activity = computed(() => days.value.slice(startIndex.value, endIndex.value + 1).reduce((sum, day) => sum + total(props.density[day]), 0))
const quiet = computed(() => !days.value.some(day => total(props.density[day])))

/** Stacked bars per day; a square-root scale keeps light days visible next to busy ones. */
const bars = computed(() => {
  const peak = Math.max(1, ...days.value.map(day => total(props.density[day])))
  return days.value.flatMap((day, i) => {
    const counts = props.density[day]
    const sum = total(counts)
    if (!sum) return []
    let top = 30
    const height = Math.sqrt(sum / peak) * 28
    return STACK.flatMap(hub => {
      const value = counts?.[hub] ?? 0
      if (!value) return []
      const part = height * value / sum
      top -= part
      return [{ key: `${day}:${hub}`, x: i + .16, y: top, height: part, fill: hubColor(hub) }]
    })
  })
})

const ticks = computed(() => days.value.flatMap((day, i) => {
  const at = (i + .5) / count.value * 100
  return day.endsWith('-01') && at > 9 && at < 88 ? [{ day, at, label: `Th${Number(day.slice(5, 7))}` }] : []
}))
const activePreset = computed(() => presets.find(preset => sameRange(draft.value, preset.days
  ? recentRange(props.min, props.max, preset.days) : { start: props.min, end: props.max }))?.days)
const clipped = computed(() => {
  const drawn = props.drawn
  if (!drawn) return []
  return Object.entries(drawn.totals).filter(([, all]) => (all ?? 0) > drawn.limit).map(([kind, all]) => `${drawn.limit}/${all} ${NOUNS[kind] ?? kind}`)
})

const longDate = (day: string) => new Intl.DateTimeFormat('vi-VN', { timeZone: 'UTC', weekday: 'long', day: 'numeric', month: 'numeric', year: 'numeric' })
  .format(new Date(`${day}T12:00:00Z`))
// vi-VN short dates read "11-10"; next to the range dash a slash is clearer.
const dayMonth = (day: string) => `${day.slice(8, 10)}/${day.slice(5, 7)}`

watch(() => props.modelValue, value => { if (!grip.value) draft.value = value })

function commit() {
  clearTimeout(timer)
  if (sameRange(draft.value, props.modelValue)) return
  announced.value = `Bản đồ hiển thị từ ${longDate(draft.value.start)} đến ${longDate(draft.value.end)}`
  emit('update:modelValue', draft.value)
}

function indexAt(event: PointerEvent) {
  const rect = track.value!.getBoundingClientRect()
  return clampIndex(Math.floor((event.clientX - rect.left) / Math.max(1, rect.width) * count.value))
}

function place(mode: Grip, index: number) {
  const start = dayDiff(props.min, origin.start), end = dayDiff(props.min, origin.end)
  if (mode === 'band') {
    const shift = Math.min(Math.max(index - anchor, -start), count.value - 1 - end)
    draft.value = { start: days.value[start + shift], end: days.value[end + shift] }
  } else if (mode === 'start') {
    draft.value = { start: days.value[Math.min(index, endIndex.value)], end: draft.value.end }
  } else if (mode === 'end') {
    draft.value = { start: draft.value.start, end: days.value[Math.max(index, startIndex.value)] }
  }
}

function grab(event: PointerEvent) {
  if (event.button !== 0 || !track.value) return
  const index = indexAt(event)
  let mode = (event.target as HTMLElement).closest<HTMLElement>('[data-grip]')?.dataset.grip as Grip | undefined
  // Handles of a one- or two-day window overlap; the first movement decides which edge moves.
  if ((mode === 'start' || mode === 'end') && endIndex.value - startIndex.value <= 1) mode = 'edge'
  event.preventDefault()
  track.value.setPointerCapture(event.pointerId)
  origin = draft.value
  anchor = index
  if (!mode) {
    // A tap on the track pulls the nearer edge to that day.
    mode = Math.abs(index - startIndex.value) <= Math.abs(index - endIndex.value) ? 'start' : 'end'
    place(mode, index)
  }
  grip.value = mode
}

function drag(event: PointerEvent) {
  if (!grip.value) return
  const index = indexAt(event)
  if (grip.value === 'edge') {
    if (index === anchor) return
    grip.value = index < anchor ? 'start' : 'end'
  }
  place(grip.value, index)
}

function release() {
  if (!grip.value) return
  grip.value = undefined
  commit()
}

function key(event: KeyboardEvent, edge: 'start' | 'end') {
  const steps: Record<string, number> = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1, PageDown: -7, PageUp: 7 }
  const current = edge === 'start' ? startIndex.value : endIndex.value
  let index: number
  if (event.key in steps) index = current + steps[event.key]
  else if (event.key === 'Home') index = edge === 'start' ? 0 : startIndex.value
  else if (event.key === 'End') index = edge === 'start' ? endIndex.value : count.value - 1
  else return
  event.preventDefault()
  index = edge === 'start' ? Math.min(Math.max(index, 0), endIndex.value) : Math.max(Math.min(index, count.value - 1), startIndex.value)
  draft.value = edge === 'start' ? { start: days.value[index], end: draft.value.end } : { start: draft.value.start, end: days.value[index] }
  // Held keys repeat quickly; ask for the map once they settle.
  clearTimeout(timer)
  timer = setTimeout(commit, 450)
}

function choose(length: number) {
  draft.value = length ? recentRange(props.min, props.max, length) : { start: props.min, end: props.max }
  commit()
}

onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <section class="time-window" :class="{ dragging: grip }" aria-label="Khoảng thời gian trên bản đồ">
    <div class="window-head">
      <p class="range">
        <CalendarRange :size="13" :stroke-width="1.7" aria-hidden="true" />
        <strong>{{ dayMonth(draft.start) }} – {{ dayMonth(draft.end) }}</strong>
        <span>{{ rangeLength(draft) }} ngày · {{ activity }} hoạt động</span>
      </p>
      <div class="presets" role="group" aria-label="Chọn nhanh khoảng thời gian">
        <button v-for="preset in presets" :key="preset.days" type="button" :aria-pressed="activePreset === preset.days" @click="choose(preset.days)">
          {{ preset.label }}
        </button>
      </div>
    </div>

    <div ref="track" class="track" :style="bandStyle" @pointerdown="grab" @pointermove="drag" @pointerup="release" @pointercancel="release" @lostpointercapture="release">
      <span v-if="loading" class="loading-line" aria-hidden="true" />
      <svg class="bars dim" :viewBox="`0 0 ${count} 30`" preserveAspectRatio="none" aria-hidden="true">
        <rect v-for="bar in bars" :key="bar.key" :x="bar.x" :y="bar.y" width=".68" :height="bar.height" :fill="bar.fill" />
      </svg>
      <svg class="bars lit" :viewBox="`0 0 ${count} 30`" preserveAspectRatio="none" aria-hidden="true">
        <rect v-for="bar in bars" :key="bar.key" :x="bar.x" :y="bar.y" width=".68" :height="bar.height" :fill="bar.fill" />
      </svg>
      <span v-if="quiet" class="quiet">Chưa có hoạt động nào trong {{ count }} ngày lưu giữ</span>
      <span class="band" data-grip="band" aria-hidden="true" />
      <span class="handle start" data-grip="start" :class="{ active: grip === 'start' }" role="slider" tabindex="0"
            aria-label="Ngày bắt đầu" aria-valuemin="0" :aria-valuemax="endIndex" :aria-valuenow="startIndex"
            :aria-valuetext="longDate(draft.start)" @keydown="key($event, 'start')" @blur="commit" />
      <span class="handle end" data-grip="end" :class="{ active: grip === 'end' }" role="slider" tabindex="0"
            aria-label="Ngày kết thúc" :aria-valuemin="startIndex" :aria-valuemax="count - 1" :aria-valuenow="endIndex"
            :aria-valuetext="longDate(draft.end)" @keydown="key($event, 'end')" @blur="commit" />
    </div>
    <div class="axis" aria-hidden="true">
      <span class="edge-start">{{ dayMonth(min) }}</span>
      <span v-for="tick in ticks" :key="tick.day" :style="{ left: `${tick.at}%` }">{{ tick.label }}</span>
      <span class="edge-end">Hôm nay</span>
    </div>

    <p v-if="failed" class="note warn" role="status">Chưa tải được khoảng này. <button type="button" @click="emit('retry')">Thử lại</button></p>
    <p v-else-if="clipped.length" class="note" role="status">
      Đang vẽ {{ clipped.join(', ') }} gần nhất. Thu hẹp khoảng thời gian để xem đủ.
    </p>
    <span class="sr-only" aria-live="polite">{{ announced }}</span>
  </section>
</template>

<style scoped>
.time-window { --accent: #d4b77d; display: flex; flex-direction: column; gap: 6px; padding: 0 var(--gutter, 26px) 10px; }
.window-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px 12px; }
.range { display: flex; align-items: center; gap: 8px; min-width: 0; margin: 0; font-size: 10px; color: #8f8c84; }
.range svg { flex-shrink: 0; color: var(--accent); }
.range strong { font: 500 11px 'JetBrains Mono', monospace; color: #efe3c4; letter-spacing: .02em; white-space: nowrap; }
.range span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.presets { display: flex; gap: 2px; padding: 2px; border: 1px solid #ffffff0c; border-radius: 9px; background: #0c0d11; }
.presets button { padding: 4px 9px; border-radius: 7px; font-size: 10px; color: #8f8c84; white-space: nowrap; transition: color 200ms, background 200ms; }
.presets button:hover { color: #efe3c4; }
.presets button[aria-pressed=true] { background: #d4b77d1f; color: #f3e6c6; }
.track { position: relative; height: 40px; border: 1px solid #ffffff0b; border-radius: 10px; background: linear-gradient(#0c0d11, #0f1015); cursor: pointer; user-select: none; touch-action: pan-y; }
.bars { position: absolute; left: 0; top: 5px; width: 100%; height: calc(100% - 10px); pointer-events: none; }
.bars.dim { opacity: .22; filter: saturate(.5); }
.bars.lit { clip-path: inset(0 calc(100% - var(--right)) 0 var(--left)); transition: clip-path 120ms ease-out; }
.dragging .bars.lit { transition: none; }
.quiet { position: absolute; inset: 0; display: grid; place-items: center; font-size: 10px; color: #6f6c65; pointer-events: none; }
.band { position: absolute; top: 0; bottom: 0; left: var(--left); width: calc(var(--right) - var(--left)); border-radius: 9px; background: linear-gradient(180deg, #d4b77d17, #d4b77d06); box-shadow: inset 0 0 0 1px #d4b77d45, 0 0 22px #d4b77d12; cursor: grab; transition: left 120ms ease-out, width 120ms ease-out; }
.dragging .band { cursor: grabbing; transition: none; }
.handle { position: absolute; top: -4px; bottom: -4px; left: var(--left); width: 16px; margin-left: -8px; display: flex; justify-content: center; cursor: ew-resize; touch-action: none; outline: none; transition: left 120ms ease-out; }
.handle.end { left: var(--right); }
.dragging .handle { transition: none; }
.handle::before { content: ''; width: 4px; height: 100%; border-radius: 3px; background: linear-gradient(#f3e6c6, #d4b77d); box-shadow: 0 0 12px #d4b77d70; transition: transform 200ms, box-shadow 200ms; }
.handle:hover::before, .handle.active::before { transform: scaleX(1.6); box-shadow: 0 0 16px #d4b77d; }
.handle:focus-visible::before { box-shadow: 0 0 0 2px #101216, 0 0 0 4px #f3e6c6; }
.axis { position: relative; height: 11px; font: 8px 'JetBrains Mono', monospace; color: #6f6c65; letter-spacing: .04em; }
.axis span { position: absolute; top: 0; transform: translateX(-50%); white-space: nowrap; }
.axis .edge-start { left: 0; transform: none; }
.axis .edge-end { left: auto; right: 0; transform: none; }
.loading-line { position: absolute; left: 8px; right: 8px; top: -1px; height: 1px; background: linear-gradient(90deg, transparent, #f3e6c6, transparent) no-repeat; background-size: 35% 100%; animation: scan 1.1s linear infinite; }
.note { margin: 0; font-size: 10px; line-height: 1.5; color: #b9a98a; }
.note.warn { color: #e8b99d; }
.note button { margin-left: 4px; text-decoration: underline; }
@keyframes scan { from { background-position: -40% 0; } to { background-position: 140% 0; } }
@media (pointer: coarse) { .handle { width: 26px; margin-left: -13px; } .track { height: 46px; } }
@media (prefers-reduced-motion: reduce) { .loading-line { animation: none; } .band, .handle, .bars.lit { transition: none; } }
</style>
