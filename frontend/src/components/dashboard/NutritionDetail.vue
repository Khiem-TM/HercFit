<script setup lang="ts">
import { computed } from 'vue'
import { ChevronLeft } from 'lucide-vue-next'
import type { NutritionTargets } from '@/types/api'
import { num } from '@/components/knowledge/health/healthFormat'
import { goalChoices } from '@/features/onboarding/model'
import { clockTime, vn } from './format'
import type { MealRow } from './useDashboardData'

/** Bữa ăn đã ghi hôm nay và mục tiêu ngày do backend tính từ hồ sơ. */
const props = defineProps<{ meals: MealRow[]; targets: NutritionTargets | null }>()
const emit = defineEmits<{ back: []; prefill: [text: string] }>()

const UNIT: Record<string, string> = { G: 'g', ML: 'ml', SERVING: 'khẩu phần' }
const itemName = (snapshot: Record<string, unknown>) => String(snapshot.name_vi || snapshot.name || snapshot.name_en || 'Món')
const amount = (quantity: number | string, unit: string) => `${vn(quantity, 1)} ${UNIT[unit] ?? unit}`
const kcalProtein = (kcal: number | string | null, protein: number | string | null) =>
  num(kcal) == null ? 'Chưa có thông tin' : `${vn(kcal)} kcal · ${vn(protein, 0)} g`
const total = (field: 'energy_kcal' | 'protein_g' | 'carbohydrate_g' | 'fat_g') =>
  props.meals.reduce((sum, meal) => sum + (num(meal[field]) ?? 0), 0)
const macros = computed(() => props.targets?.macros ?? null)
const target = computed(() => (props.targets?.status === 'ok' ? num(props.targets.target_kcal) : null))
const logged = computed(() => [
  { label: 'Năng lượng', value: total('energy_kcal'), goal: target.value, unit: 'kcal' },
  { label: 'Protein', value: total('protein_g'), goal: macros.value?.protein_g ?? null, unit: 'g' },
  { label: 'Carbohydrate', value: total('carbohydrate_g'), goal: macros.value?.carbohydrate_g ?? null, unit: 'g' },
  { label: 'Chất béo', value: total('fat_g'), goal: macros.value?.fat_g ?? null, unit: 'g' },
])
const goalName = computed(() => goalChoices.find(choice => choice.id === props.targets?.goal_type)?.title ?? 'hiện tại')
</script>

<template>
  <div class="layer">
    <button type="button" class="hf-back" @click="emit('back')"><ChevronLeft :size="18" aria-hidden="true" />Hôm nay</button>
    <div class="hf-grid" style="margin-top: 16px">
      <div class="hf-c8 hf-stack">
        <section v-if="!meals.length" class="hf-card empty">
          <div class="hf-sv2">Chưa ghi nhận bữa ăn nào hôm nay</div>
          <p class="hf-mut">Nhắn cho trợ lý món bạn đã ăn; bữa ăn được lưu sau khi bạn xác nhận.</p>
        </section>
        <section v-for="meal in meals" :key="meal.id" class="hf-card meal">
          <div class="hf-hd">
            <h3 class="meal-name">{{ meal.name }} <span class="hf-mut time">· {{ clockTime(meal.consumed_at) }}</span></h3>
            <span class="sum">{{ vn(meal.energy_kcal) }} kcal · {{ vn(meal.protein_g, 0) }} g protein</span>
          </div>
          <div v-for="item in meal.items" :key="item.id" class="hf-kv">
            <div><b>{{ itemName(item.food_snapshot) }}</b><br><span>{{ amount(item.quantity, item.unit) }}</span></div>
            <div class="v small">{{ kcalProtein(item.energy_kcal, item.protein_g) }}</div>
          </div>
          <div v-if="meal.nutrition_incomplete" class="hf-warn">Bữa này có món chưa đủ thông tin dinh dưỡng — tổng năng lượng có thể thấp hơn thực tế.</div>
        </section>
        <button type="button" class="hf-btn pri start" @click="emit('prefill', 'Ghi bữa ăn: ')">Ghi thêm bữa ăn</button>
      </div>
      <div class="hf-c4 hf-stack">
        <section class="hf-card tight">
          <h3 class="hf-h3 head">Đã ghi nhận hôm nay</h3>
          <div v-for="row in logged" :key="row.label" class="hf-kv"><b>{{ row.label }}</b>
            <span class="v">{{ vn(row.value) }}{{ row.goal ? ` / ${vn(row.goal)}` : '' }} {{ row.unit }}</span></div>
        </section>
        <section class="hf-card tight">
          <h3 class="hf-h3 head">Mục tiêu mỗi ngày</h3>
          <template v-if="target">
            <div class="hf-kv"><b>Năng lượng</b><span class="v">{{ vn(target) }} kcal</span></div>
            <template v-if="macros">
              <div class="hf-kv"><b>Protein</b><span class="v">{{ vn(macros.protein_g) }} g</span></div>
              <div class="hf-kv"><b>Carbohydrate</b><span class="v">{{ vn(macros.carbohydrate_g) }} g</span></div>
              <div class="hf-kv"><b>Chất béo</b><span class="v">{{ vn(macros.fat_g) }} g</span></div>
              <div class="hf-kv"><b>Chất xơ</b><span class="v">{{ vn(macros.fiber_g) }} g</span></div>
            </template>
            <p class="hf-mut note">Chất xơ đã ăn chưa được theo dõi — chỉ hiển thị mục tiêu.</p>
            <details class="how">
              <summary>Cách tính mục tiêu</summary>
              <p class="hf-mut">Hệ thống ước tính năng lượng tiêu hao hằng ngày từ hồ sơ (tuổi, giới tính, chiều cao, cân nặng, mức vận động),
                sau đó điều chỉnh theo mục tiêu {{ goalName }}. Mục tiêu protein dựa trên cân nặng hiện tại. Đây là ước tính, không phải
                chỉ định y khoa.</p>
            </details>
          </template>
          <div v-else class="hf-info">Chưa có mục tiêu năng lượng — cần hoàn thiện hồ sơ (chiều cao, cân nặng, tuổi).</div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.empty { align-items: flex-start; padding: 40px; }
.empty p { margin: 0; }
.meal { gap: 6px; }
.meal-name { margin: 0; font-size: 17px; }
.time { font-weight: 500; font-size: 13px; }
.sum { font-weight: 700; font-size: 15px; }
.small { font-size: 14px; }
.start { align-self: flex-start; }
.tight { gap: 4px; }
.head { margin-bottom: 6px; }
.note { font-size: 12px; margin: 8px 0 0; line-height: 1.5; }
.how { margin-top: 6px; border-top: 1px solid var(--hf-line-2); }
.how summary { cursor: pointer; font-weight: 600; font-size: 14px; min-height: 44px; display: flex; align-items: center; list-style: none; }
.how p { margin: 0 0 8px; font-size: 13px; line-height: 1.55; }
</style>
