<script setup lang="ts">
import { computed } from 'vue'
import { Activity, Flame, Footprints, HeartPulse, Moon, Waves } from 'lucide-vue-next'
import type { DailyHealth } from '@/types/api'
import { dayLabel, duration, fmt, num } from './healthFormat'
import type { HealthData } from './useHealthData'

/** Device vitals at a glance: the latest day with data, its trend over the window and the gap to the
 * window's average (other days only). Neutral arrows: a higher or lower value is not judged here. */
const props = defineProps<{ data: HealthData }>()

type Vital = { key: string; label: string; unit: string; icon: typeof Footprints; digits?: number;
  pick: (day: DailyHealth | undefined, date: string) => number | null; show?: (value: number) => string }

const sleepByDay = computed(() => {
  const minutes = new Map<string, number>()
  for (const session of props.data.sleep) {
    if (!session.is_main || session.minutes_asleep == null) continue
    minutes.set(session.local_date, (minutes.get(session.local_date) ?? 0) + session.minutes_asleep)
  }
  return minutes
})

const VITALS: Vital[] = [
  { key: 'steps', label: 'Bước chân', unit: 'bước', icon: Footprints, pick: day => day?.steps ?? null },
  { key: 'sleep', label: 'Giấc ngủ', unit: '', icon: Moon, show: duration,
    pick: (day, date) => day?.sleep_minutes ?? sleepByDay.value.get(date) ?? null },
  { key: 'rhr', label: 'Nhịp tim nghỉ', unit: 'bpm', icon: HeartPulse, pick: day => day?.resting_hr_bpm ?? null },
  { key: 'hrv', label: 'HRV', unit: 'ms', icon: Waves, digits: 1, pick: day => num(day?.hrv_ms) },
  { key: 'active', label: 'Phút vận động', unit: 'phút', icon: Activity, pick: day => day?.active_minutes ?? null },
  { key: 'kcal', label: 'Calo tiêu hao', unit: 'kcal', icon: Flame, pick: day => num(day?.total_kcal) },
]

const byDay = computed(() => new Map(props.data.daily.map(day => [day.local_date, day])))

function lastKnown(series: (number | null)[]): number {
  for (let index = series.length - 1; index >= 0; index -= 1) if (series[index] != null) return index
  return -1
}

const tiles = computed(() => VITALS.flatMap(vital => {
  const series = props.data.days.map(date => vital.pick(byDay.value.get(date), date))
  const last = lastKnown(series)
  if (last < 0) return []
  const latest = series[last] as number
  const others = series.filter((value, index) => value != null && index !== last) as number[]
  const average = others.length >= 3 ? others.reduce((sum, value) => sum + value, 0) / others.length : null
  const delta = average ? (latest - average) / average : null
  return [{
    ...vital, latest, series, last, date: props.data.days[last], count: others.length + 1, average,
    value: vital.show ? vital.show(latest) : fmt(latest, vital.digits ?? 0),
    averageText: average == null ? null : (vital.show ? vital.show(average) : `${fmt(average, vital.digits ?? 0)} ${vital.unit}`),
    delta, path: spark(series),
  }]
}))

/** Sparkline in a 100×32 box; gaps stay gaps, the last point is marked. */
function spark(series: (number | null)[]) {
  const values = series.filter((value): value is number => value != null)
  const min = Math.min(...values), max = Math.max(...values)
  const span = max - min || 1
  const x = (index: number) => series.length < 2 ? 50 : (index / (series.length - 1)) * 100
  const y = (value: number) => 29 - ((value - min) / span) * 26
  const segments: string[] = []
  let current: string[] = []
  series.forEach((value, index) => {
    if (value == null) {
      if (current.length) segments.push(current.join(' '))
      current = []
      return
    }
    current.push(`${current.length ? 'L' : 'M'}${x(index).toFixed(2)},${y(value).toFixed(2)}`)
  })
  if (current.length) segments.push(current.join(' '))
  const lastIndex = lastKnown(series)
  return { d: segments.join(' '), dot: { x: x(lastIndex), y: y(series[lastIndex] as number) } }
}

const today = computed(() => props.data.end)
</script>

<template>
  <div v-if="tiles.length" class="vitals" role="list" aria-label="Chỉ số từ thiết bị">
    <article v-for="tile in tiles" :key="tile.key" class="vital" :class="tile.key" role="listitem">
      <header>
        <span class="icon"><component :is="tile.icon" :size="14" :stroke-width="1.7" /></span>
        <span class="label">{{ tile.label }}</span>
        <span class="when">{{ tile.date === today ? 'hôm nay' : dayLabel(tile.date) }}</span>
      </header>
      <p class="value">{{ tile.value }}<small v-if="tile.unit">{{ tile.unit }}</small></p>
      <span class="spark" aria-hidden="true">
        <svg viewBox="0 0 100 32" preserveAspectRatio="none"><path :d="tile.path.d" /></svg>
        <i :style="{ left: `${tile.path.dot.x}%`, top: `${(tile.path.dot.y / 32) * 100}%` }" />
      </span>
      <p class="compare">
        <template v-if="tile.delta != null">
          <b :class="tile.delta > 0.005 ? 'up' : tile.delta < -0.005 ? 'down' : 'flat'">
            {{ tile.delta > 0.005 ? '↑' : tile.delta < -0.005 ? '↓' : '→' }} {{ fmt(Math.abs(tile.delta) * 100, 0) }}%
          </b>
          so với TB {{ tile.averageText }}
        </template>
        <template v-else>{{ tile.count }} ngày có số liệu</template>
      </p>
    </article>
  </div>
</template>

<style scoped>
.vitals { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }
.vital { --accent: light-dark(#367689, #8fc3d4); container: vital / inline-size; display: flex; flex-direction: column; gap: 6px; min-width: 0; padding: 14px 14px 12px; border: 1px solid light-dark(#18181810, #ffffff10); border-radius: 16px; background: radial-gradient(ellipse at 100% 0, color-mix(in srgb, var(--accent) 12%, transparent), transparent 65%), light-dark(#fefdfa, #15181e); }
.vital.steps { --accent: light-dark(#2067b8, #6fa8f0); }
.vital.sleep { --accent: light-dark(#6955b4, #a99cf0); }
.vital.rhr { --accent: light-dark(#ab4046, #ef8f8f); }
.vital.hrv { --accent: light-dark(#127f63, #6fd0b0); }
.vital.active { --accent: light-dark(#916305, #e3b46f); }
.vital.kcal { --accent: light-dark(#a15219, #f0a070); }
header { display: flex; align-items: center; gap: 7px; min-width: 0; }
.icon { display: grid; place-items: center; width: 24px; height: 24px; flex: none; border-radius: 8px; color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); }
.label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; color: light-dark(#3c3f42, #c9ccd0); }
.when { margin-left: auto; font: 9px 'JetBrains Mono', monospace; color: light-dark(#686e74, #858b92); white-space: nowrap; }
.value { margin: 2px 0 0; font: 600 clamp(20px, 16cqi, 26px) Geist, sans-serif; letter-spacing: -.01em; color: light-dark(#24231f, #f1f0eb); font-variant-numeric: tabular-nums; }
.value small { margin-left: 4px; font-size: 11px; font-weight: 400; color: light-dark(#53575d, #a3a8ae); }
.spark { position: relative; display: block; height: 32px; }
.spark svg { width: 100%; height: 100%; overflow: visible; }
.spark path { fill: none; stroke: var(--accent); stroke-width: 1.6; stroke-linejoin: round; stroke-linecap: round; vector-effect: non-scaling-stroke; opacity: .85; }
.spark i { position: absolute; width: 6px; height: 6px; margin: -3px 0 0 -3px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent); }
.compare { margin: 0; font-size: 10px; line-height: 1.45; color: light-dark(#60676e, #8d949c); }
.compare b { font-weight: 600; color: light-dark(#363530, #d9d8d2); }
@container vital (max-width: 150px) { .when { display: none; } }
</style>
