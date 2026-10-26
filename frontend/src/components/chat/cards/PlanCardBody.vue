<script setup lang="ts">
import { computed } from 'vue'
import CatalogImage from './CatalogImage.vue'
import { setTarget, shortDate, stepBars, stepSummary, WORKOUT } from '@/features/chat/confirmation'

const props = defineProps<{ plan: Record<string, any> }>()
const VISIBLE = 8
const entries = computed(() => (props.plan.entries || []) as Record<string, any>[])
const tone = { easy: 'bg-[#aacbd5]', hard: 'bg-[#e3a98c]', calm: 'bg-[#5d5c58]' }
</script>

<template>
  <div class="px-5">
    <p class="pt-3 font-label-telemetry text-[11px] uppercase tracking-[0.14em] text-on-surface-variant">
      {{ entries.length }} buổi · {{ plan.start_date }} → {{ plan.end_date }}
    </p>
    <ol class="mt-1 divide-y divide-white/[0.06]">
      <li v-for="entry in entries.slice(0, VISIBLE)" :key="entry.id" class="grid grid-cols-[52px_1fr] gap-3.5 py-3">
        <div class="self-start rounded-lg bg-white/[0.04] py-1.5 text-center">
          <p class="text-[11px] capitalize text-on-surface-variant">{{ shortDate(entry.scheduled_date).dow }}</p>
          <p class="font-label-code text-xs text-primary">{{ shortDate(entry.scheduled_date).day }}</p>
        </div>
        <div class="min-w-0">
          <p class="text-sm font-medium text-primary">{{ entry.is_rest ? 'Nghỉ' : entry.label }}</p>
          <ul class="mt-1.5 space-y-2">
            <li v-for="item in entry.items" :key="item.id" class="flex gap-2.5">
              <CatalogImage :src="item.exercise_snapshot?.image_url" :alt="item.exercise_snapshot?.name_vi || 'Bài tập'" :icon="item.prescription?.kind === 'ENDURANCE' ? 'run' : 'exercise'" rounded="rounded-md" class="h-9 w-9 shrink-0" />
              <div class="min-w-0 flex-1 text-xs">
                <p class="truncate text-primary">{{ item.exercise_snapshot?.name_vi }}</p>
                <template v-if="item.prescription?.kind === 'STRENGTH'">
                  <p v-for="(target, index) in item.prescription.sets" :key="index" class="text-on-surface-variant">{{ setTarget(target) }}</p>
                </template>
                <template v-else-if="item.prescription?.kind === 'ENDURANCE'">
                  <div class="mt-1 flex h-2 gap-px overflow-hidden rounded" aria-hidden="true">
                    <span v-for="(bar, index) in stepBars(item.prescription)" :key="index" :class="tone[bar.tone]" :style="{ flexGrow: bar.grow }" :title="bar.label" />
                  </div>
                  <p class="mt-1 text-on-surface-variant">{{ WORKOUT[item.prescription.workout_type] }} · {{ stepSummary(item.prescription) }}</p>
                </template>
              </div>
            </li>
          </ul>
        </div>
      </li>
    </ol>
    <p v-if="entries.length > VISIBLE" class="pb-1 text-xs text-on-surface-variant">+ {{ entries.length - VISIBLE }} buổi nữa trong lịch</p>
  </div>
</template>
