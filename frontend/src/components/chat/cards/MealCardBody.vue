<script setup lang="ts">
import { computed } from 'vue'
import { Info } from 'lucide-vue-next'
import CatalogImage from './CatalogImage.vue'
import { fmt, macroShare, num, portion } from '@/features/chat/confirmation'

const props = defineProps<{ meal: Record<string, any> }>()
const items = computed(() => (props.meal.items || []) as Record<string, any>[])
const share = computed(() => macroShare(props.meal))
const incomplete = computed(() => items.value.filter(item => item.nutrition_incomplete).map(item => item.food_snapshot?.name_vi))
</script>

<template>
  <div>
    <ul class="divide-y divide-white/[0.06] px-5" aria-label="Các món trong bữa">
      <li v-for="item in items" :key="item.id" class="flex items-center gap-3.5 py-3">
        <CatalogImage :src="item.food_snapshot?.image_url" :alt="item.food_snapshot?.name_vi || 'Món ăn'" icon="food" class="h-14 w-14 shrink-0" />
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <p class="truncate text-sm font-medium text-primary">{{ item.food_snapshot?.name_vi }}</p>
            <span v-if="item.food_snapshot?.source_type === 'CUSTOM'" class="shrink-0 rounded border border-white/15 px-1.5 font-label-code text-[10px] text-on-surface-variant">CỦA BẠN</span>
          </div>
          <p class="mt-0.5 text-xs text-on-surface-variant">{{ portion(item) }}</p>
        </div>
        <div class="shrink-0 text-right">
          <p class="font-label-code text-sm text-primary">{{ fmt(item.energy_kcal, 0, 'kcal') }}</p>
          <p class="mt-0.5 font-label-code text-[11px] text-on-surface-variant">
            P {{ fmt(item.protein_g) }} · C {{ fmt(item.carbohydrate_g) }} · F {{ fmt(item.fat_g) }}
          </p>
        </div>
      </li>
    </ul>

    <section aria-label="Tổng dinh dưỡng" class="mx-5 mt-2 rounded-xl bg-white/[0.04] p-4">
      <div class="flex items-baseline justify-between">
        <p class="font-label-telemetry text-[11px] uppercase tracking-[0.14em] text-on-surface-variant">Tổng bữa ăn</p>
        <p>
          <span class="font-headline-md text-3xl text-primary">{{ num(meal.energy_kcal) === null ? '—' : fmt(meal.energy_kcal) }}</span>
          <span class="ml-1.5 text-xs text-on-surface-variant">kcal</span>
        </p>
      </div>
      <div v-if="share" class="mb-3 mt-3 flex h-2 gap-0.5 overflow-hidden rounded-full" aria-hidden="true">
        <div class="bg-[#aacbd5]" :style="{ width: `${share.protein}%` }" />
        <div class="bg-[#d4b77d]" :style="{ width: `${share.carb}%` }" />
        <div class="bg-[#e3a98c]" :style="{ width: `${share.fat}%` }" />
      </div>
      <dl class="grid grid-cols-4 gap-2 text-xs">
        <div><dt class="text-on-surface-variant">Protein</dt><dd class="mt-0.5 font-label-code text-sm text-[#aacbd5]">{{ fmt(meal.protein_g, 1, 'g') }}</dd></div>
        <div><dt class="text-on-surface-variant">Carb</dt><dd class="mt-0.5 font-label-code text-sm text-[#d4b77d]">{{ fmt(meal.carbohydrate_g, 1, 'g') }}</dd></div>
        <div><dt class="text-on-surface-variant">Fat</dt><dd class="mt-0.5 font-label-code text-sm text-[#e3a98c]">{{ fmt(meal.fat_g, 1, 'g') }}</dd></div>
        <div><dt class="text-on-surface-variant">Chất xơ</dt><dd class="mt-0.5 font-label-code text-sm text-primary">{{ fmt(meal.fiber_g, 1, 'g') }}</dd></div>
      </dl>
    </section>

    <p v-if="incomplete.length" class="mx-5 mt-3 flex gap-2 rounded-lg border border-[#aacbd5]/25 bg-[#aacbd5]/[0.06] px-3 py-2.5 text-xs leading-5 text-on-surface-variant">
      <Info class="mt-0.5 h-4 w-4 shrink-0 text-[#aacbd5]" aria-hidden="true" />
      <span>{{ incomplete.join(', ') }} thiếu một số chất trong catalog; tổng tương ứng để trống thay vì tính là 0.</span>
    </p>
  </div>
</template>
