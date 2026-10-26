<script setup lang="ts">
import { computed } from 'vue'
import CatalogImage from './CatalogImage.vue'
import { calorieSource, clock, fmt, INTENSITY, minutes, num, pace, SET_TYPE, WORKOUT } from '@/features/chat/confirmation'

const props = defineProps<{ training: Record<string, any> }>()
const items = computed(() => (props.training.items || []) as Record<string, any>[])
const volume = computed(() => items.value.reduce((sum, item) => sum + (num(item.volume_kg) ?? 0), 0))
const distance = computed(() => items.value.reduce((sum, item) => sum + (num(item.distance_meters) ?? 0), 0))

// Session duration when given, otherwise the sum of item durations (moving time for runs).
const duration = computed(() => num(props.training.duration_seconds)
  ?? (items.value.reduce((sum, item) => sum + (num(item.duration_seconds) ?? 0), 0) || null))

const metrics = computed(() => [
  { label: 'Thời lượng', value: minutes(duration.value) },
  { label: 'Tải sRPE', value: num(props.training.training_load) === null ? 'cần RPE' : fmt(props.training.training_load) },
  distance.value
    ? { label: 'Quãng đường', value: fmt(distance.value / 1000, 2, 'km') }
    : { label: 'Volume', value: fmt(volume.value, 0, 'kg') },
  { label: 'Năng lượng', value: num(props.training.energy_kcal) === null ? 'chưa rõ' : `~${fmt(props.training.energy_kcal)} kcal` },
])

// Lap bar: 300 s/km (5:00) fills the track, 450 s/km (7:30) is nearly empty.
function lapWidth(lap: Record<string, any>): string {
  const seconds = (num(lap.duration_seconds) ?? 0) * 1000 / (num(lap.distance_meters) || 1)
  return `${Math.round(Math.min(1, Math.max(0.08, (450 - seconds) / 150)) * 100)}%`
}
const iconFor = (item: Record<string, any>) => item.kind === 'ENDURANCE' ? 'run' : 'exercise'
</script>

<template>
  <div>
    <dl class="grid grid-cols-2 gap-px border-b border-white/[0.08] bg-white/[0.08] sm:grid-cols-4">
      <div v-for="metric in metrics" :key="metric.label" class="bg-[#181818] px-4 py-3">
        <dt class="text-[11px] text-on-surface-variant">{{ metric.label }}</dt>
        <dd class="mt-1 font-label-code text-base text-primary">{{ metric.value }}</dd>
      </div>
    </dl>

    <section v-for="item in items" :key="item.id" class="border-b border-white/[0.06] px-5 py-4 last:border-b-0">
      <div class="flex items-center gap-3.5">
        <CatalogImage :src="item.exercise_snapshot?.image_url" :alt="item.exercise_snapshot?.name_vi || 'Bài tập'" :icon="iconFor(item)" class="h-16 w-16 shrink-0" />
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-medium text-primary">{{ item.exercise_snapshot?.name_vi }}</p>
          <div class="mt-1 flex flex-wrap gap-1.5">
            <span v-for="tag in (item.exercise_snapshot?.muscle_groups || []).slice(0, 3)" :key="tag" class="rounded border border-white/15 px-1.5 font-label-code text-[10px] text-on-surface-variant">{{ tag }}</span>
            <span v-if="item.performance?.workout_type" class="rounded bg-[#e3a98c] px-1.5 font-label-code text-[10px] text-[#131313]">{{ WORKOUT[item.performance.workout_type] || item.performance.workout_type }}</span>
          </div>
        </div>
      </div>

      <!-- Strength: set table and server-computed metrics -->
      <template v-if="item.kind === 'STRENGTH'">
        <table class="mt-3 w-full text-xs">
          <caption class="sr-only">Các set của {{ item.exercise_snapshot?.name_vi }}</caption>
          <thead>
            <tr class="text-left font-label-code text-[10px] uppercase text-on-surface-variant">
              <th scope="col" class="w-10 py-1.5 font-normal">Set</th>
              <th scope="col" class="py-1.5 font-normal">Loại</th>
              <th scope="col" class="py-1.5 text-right font-normal">Kg</th>
              <th scope="col" class="py-1.5 text-right font-normal">Reps</th>
              <th scope="col" class="py-1.5 text-right font-normal">RPE</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(set, index) in item.performance?.sets || []" :key="index" class="border-t border-white/[0.06]" :class="set.set_type === 'WARMUP' ? 'text-on-surface-variant' : 'text-primary'">
              <td class="py-1.5 font-label-code">{{ set.set_type === 'WARMUP' ? 'K' : index + 1 }}</td>
              <td class="py-1.5">{{ SET_TYPE[set.set_type] || set.set_type }}</td>
              <td class="py-1.5 text-right font-label-code">{{ set.load_mode === 'BODYWEIGHT' ? `BW${set.weight_kg ? ` +${fmt(set.weight_kg, 1)}` : ''}` : fmt(set.weight_kg, 1) }}</td>
              <td class="py-1.5 text-right font-label-code">{{ set.reps ?? `${fmt(set.hold_seconds)}″` }}</td>
              <td class="py-1.5 text-right font-label-code">{{ set.rpe ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p class="mt-2 font-label-code text-[11px] text-on-surface-variant">
          Volume {{ fmt(item.volume_kg, 0, 'kg') }}<template v-if="num(item.best_e1rm_kg) !== null"> · e1RM {{ fmt(item.best_e1rm_kg, 1, 'kg') }}</template> · {{ item.hard_sets ?? 0 }} hard sets
        </p>
      </template>

      <!-- Endurance: headline stats and laps -->
      <template v-else-if="item.kind === 'ENDURANCE'">
        <dl class="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div class="rounded-lg bg-white/[0.04] px-3 py-2"><dt class="text-[11px] text-on-surface-variant">Quãng đường</dt><dd class="font-headline-md text-lg text-primary">{{ fmt(num(item.performance?.distance_meters)! / 1000, 2) }}<span class="text-xs text-on-surface-variant"> km</span></dd></div>
          <div class="rounded-lg bg-white/[0.04] px-3 py-2"><dt class="text-[11px] text-on-surface-variant">Thời gian</dt><dd class="font-headline-md text-lg text-primary">{{ clock(item.performance?.duration_seconds) }}</dd></div>
          <div class="rounded-lg bg-white/[0.04] px-3 py-2"><dt class="text-[11px] text-on-surface-variant">Pace</dt><dd class="font-headline-md text-lg text-primary">{{ pace(item.performance?.pace_seconds_per_km) }}<span class="text-xs text-on-surface-variant"> /km</span></dd></div>
          <div class="rounded-lg bg-white/[0.04] px-3 py-2"><dt class="text-[11px] text-on-surface-variant">Nhịp tim TB</dt><dd class="font-headline-md text-lg text-primary">{{ item.performance?.avg_hr ?? '—' }}<span v-if="item.performance?.avg_hr" class="text-xs text-on-surface-variant"> bpm</span></dd></div>
        </dl>
        <ol v-if="item.performance?.laps?.length" class="mt-3 space-y-1.5" aria-label="Các lap">
          <li v-for="(lap, index) in item.performance.laps" :key="index" class="grid grid-cols-[72px_1fr_52px_40px] items-center gap-3 text-xs">
            <span :class="lap.lap_type === 'WORK' ? 'text-primary' : 'text-on-surface-variant'">{{ lap.lap_type === 'WORK' ? `Lap ${index + 1}` : lap.lap_type === 'WARMUP' ? 'Khởi động' : lap.lap_type === 'COOLDOWN' ? 'Thả lỏng' : 'Hồi phục' }}</span>
            <span class="block h-2 overflow-hidden rounded-full bg-white/[0.06]" aria-hidden="true">
              <span class="block h-2" :class="lap.lap_type === 'WORK' ? 'bg-[#e3a98c]' : 'bg-[#5d5c58]'" :style="{ width: lapWidth(lap) }" />
            </span>
            <span class="text-right font-label-code text-primary">{{ pace(item.performance.lap_paces_seconds_per_km?.[index]) }}</span>
            <span class="text-right font-label-code text-on-surface-variant">{{ lap.avg_hr ?? '' }}</span>
          </li>
        </ol>
      </template>

      <!-- General sport -->
      <p v-else class="mt-3 text-xs text-on-surface-variant">
        {{ minutes(item.performance?.duration_seconds) }} · cường độ {{ INTENSITY[item.performance?.intensity] || item.performance?.intensity }}
        <template v-if="item.performance?.rpe"> · RPE {{ item.performance.rpe }}</template>
      </p>

      <p class="mt-2 text-[11px] leading-4 text-outline">{{ calorieSource(item.calorie_estimate) }}</p>
    </section>
  </div>
</template>
