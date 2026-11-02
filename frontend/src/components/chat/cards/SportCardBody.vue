<script setup lang="ts">
import { computed } from 'vue'
import { Info } from 'lucide-vue-next'
import { calorieSource, fmt, minutes, when } from '@/features/chat/confirmation'
import { exerciseLabel } from '@/components/knowledge/health/healthFormat'

/** Buổi thể thao sẽ ghi thẳng lên Google Health: loại hoạt động Google, thời lượng và calo HercFit ước tính. */
const props = defineProps<{ preview: Record<string, any>; timezone?: string }>()

const exercise = computed(() => props.preview.data_point?.exercise ?? {})
const derived = computed(() => props.preview.derived ?? {})
const rows = computed(() => [
  { label: 'Hoạt động trên Google', value: exerciseLabel(derived.value.exercise_type ?? exercise.value.exerciseType) },
  { label: 'Bắt đầu', value: when(exercise.value.interval?.startTime, props.timezone) },
  { label: 'Thời lượng', value: minutes(derived.value.duration_seconds) },
  { label: 'Quãng đường', value: derived.value.distance_m ? fmt(Number(derived.value.distance_m) / 1000, 2, 'km') : '' },
  { label: 'Năng lượng', value: derived.value.energy_kcal != null ? fmt(derived.value.energy_kcal, 0, 'kcal') : 'chưa rõ' },
  { label: 'Ghi chú', value: exercise.value.notes ?? '' },
].filter(row => row.value))
</script>

<template>
  <div class="px-5 pt-4">
    <dl class="divide-y divide-ink/[0.06] rounded-xl border border-ink/[0.06] bg-sunken" aria-label="Buổi thể thao sẽ ghi">
      <div v-for="row in rows" :key="row.label" class="flex flex-col gap-0.5 px-3.5 py-2.5 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
        <dt class="shrink-0 text-xs text-on-surface-variant">{{ row.label }}</dt>
        <dd class="min-w-0 break-words text-sm text-primary sm:text-right">{{ row.value }}</dd>
      </div>
    </dl>
    <p class="mt-3 flex gap-2 rounded-lg border border-mist/25 bg-mist/[0.06] px-3 py-2.5 text-xs leading-5 text-on-surface-variant">
      <Info class="mt-0.5 h-4 w-4 shrink-0 text-mist" aria-hidden="true" />
      <span>{{ calorieSource(derived.calorie_estimate) }} Buổi tập được ghi thẳng lên Google Health; Google giữ bản gốc.</span>
    </p>
  </div>
</template>
