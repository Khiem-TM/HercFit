<script setup lang="ts">
import { computed, shallowRef, useId } from 'vue'
import { ArrowUpRight, Flame, Utensils } from 'lucide-vue-next'
import type { KnowledgeGraph } from '@/types/knowledge'
import { detail, number, numericDetail, records } from './dashboardData'

const props = defineProps<{ graph: KnowledgeGraph }>()
const emit = defineEmits<{ explore: [id: string] }>()
const selectId = useId()
const selectedId = shallowRef<string>()
const meals = computed(() => records(props.graph, 'Meal'))
const meal = computed(() => meals.value.find(item => item.id === selectedId.value) ?? meals.value[0])
const foods = computed(() => props.graph.nodes.filter(node => node.kind === 'MealItem' && node.parent === meal.value?.id))
const macros = computed(() => meal.value ? [
  { label: 'Protein', color: '#a8cf9a', value: numericDetail(meal.value, 'Protein') },
  { label: 'Carb', color: '#d4b77d', value: numericDetail(meal.value, 'Carb') },
  { label: 'Chất béo', color: '#b9a9e3', value: numericDetail(meal.value, 'Chất béo') },
] : [])
const maxMacro = computed(() => Math.max(1, ...macros.value.map(item => item.value ?? 0)))
const incomplete = computed(() => meal.value && (detail(meal.value, 'Ghi chú') || macros.value.some(item => item.value == null) || !detail(meal.value, 'Năng lượng')))
</script>

<template>
  <div class="nutrition-detail">
    <template v-if="meal">
      <label class="meal-label" :for="selectId">Bữa ăn đã ghi <span>{{ meals.length }} bữa gần đây</span></label>
      <select :id="selectId" :value="meal.id" class="meal-select" @change="selectedId = ($event.target as HTMLSelectElement).value"><option v-for="item in meals" :key="item.id" :value="item.id">{{ item.label }}</option></select>
      <div class="energy"><span class="energy-icon"><Flame :size="24" :stroke-width="1.4" /></span><div><span class="energy-label">Năng lượng bữa ăn</span><strong>{{ detail(meal, 'Năng lượng') ?? 'Chưa có dữ liệu' }}</strong></div><span v-if="detail(meal, 'Chất xơ')" class="fiber">Chất xơ <strong>{{ detail(meal, 'Chất xơ') }}</strong></span></div>
      <div class="macros" aria-label="Thành phần dinh dưỡng theo gram"><div v-for="macro in macros" :key="macro.label" class="macro" :style="{ '--macro': macro.color }"><div><span><i />{{ macro.label }}</span><strong>{{ macro.value == null ? 'Chưa có' : `${number(macro.value)} g` }}</strong></div><span class="macro-track" aria-hidden="true"><i :style="{ transform: `scaleX(${(macro.value ?? 0) / maxMacro})` }" /></span></div></div>
      <p class="macro-note">Độ dài thanh so sánh khối lượng (g) giữa các chất trong bữa.</p>
      <p v-if="incomplete" class="incomplete">Bữa ăn còn thiếu dữ liệu dinh dưỡng. Các giá trị trên chỉ phản ánh phần đã ghi nhận.</p>
      <div class="food-heading"><h4>Trong bữa ăn này</h4><span>{{ foods.length }} món có chi tiết</span></div>
      <ul v-if="foods.length" class="foods"><li v-for="food in foods" :key="food.id"><span class="food-icon"><Utensils :size="14" /></span><div><strong>{{ food.label }}</strong><span>{{ detail(food, 'Năng lượng') ?? 'Chưa có năng lượng' }}<template v-if="detail(food, 'Protein')"> · {{ detail(food, 'Protein') }} protein</template></span></div><button type="button" :aria-label="`Xem ${food.label} trên bản đồ`" @click="emit('explore', food.id)"><ArrowUpRight :size="16" /></button></li></ul>
      <p v-else class="empty">{{ meal.summary || 'Bữa ăn này chưa có chi tiết từng món.' }}</p>
      <button class="meal-link" type="button" @click="emit('explore', meal.id)">Xem bữa ăn trên bản đồ <ArrowUpRight :size="14" /></button>
    </template>
    <div v-else class="empty"><Utensils :size="28" :stroke-width="1.2" /><p>Chưa có bữa ăn để xem chi tiết.</p><span>Ghi món ăn và khẩu phần qua trò chuyện để theo dõi dinh dưỡng.</span></div>
  </div>
</template>

<style scoped>
.nutrition-detail { color: #dedfd7; }
.meal-label { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 8px; font-size: 12px; }.meal-label > span { color: #8e998a; font-size: 10px; }
.meal-select { width: 100%; min-width: 0; border: 1px solid #a8cf9a35; border-radius: 10px; background: #141b17; padding: 11px 10px; font-size: 12px; color: #d8e5d1; text-overflow: ellipsis; }
.energy { display: flex; align-items: center; gap: 13px; padding: 22px 0; }
.energy-icon { display: grid; place-items: center; background: #a8cf9a0d; color: #a8cf9a; border: 1px solid #a8cf9a22; border-radius: 14px; width: 48px; height: 54px; flex-shrink: 0; }
.energy-label { color: #a2ad9b; font-size: 11px; }.energy div > strong { display: block; margin-top: 4px; font: 28px 'Playfair Display', serif; color: #ecf0e4; }
.fiber { margin-left: auto; font-size: 10px; color: #99a391; }.fiber strong { display: block; margin-top: 6px; font: 12px 'JetBrains Mono', monospace; color: #d9e2ce; }
.macros { display: grid; gap: 14px; padding: 16px; border: 1px solid #ffffff0d; border-radius: 12px; background: #ffffff02; }
.macro > div { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 11px; }.macro > div > span { display: flex; align-items: center; gap: 7px; color: #b7bdb2; }.macro > div i { width: 5px; height: 5px; border-radius: 50%; background: var(--macro); }.macro strong { color: var(--macro); font: 11px 'JetBrains Mono', monospace; }
.macro-track { display: block; height: 5px; border-radius: 4px; background: #ffffff09; margin-top: 8px; overflow: hidden; }.macro-track i { display: block; height: 100%; width: 100%; background: var(--macro); border-radius: inherit; transform-origin: left; transition: transform 500ms cubic-bezier(.2,.8,.2,1); }
.macro-note { color: #91998c; font-size: 10px; line-height: 1.6; margin: 9px 0 18px; }.incomplete { padding: 10px 12px; border: 1px solid #d4b77d25; background: #d4b77d08; color: #c9bb9b; border-radius: 9px; font-size: 11px; line-height: 1.6; }
.food-heading { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin: 22px 0 8px; }.food-heading h4 { font-size: 12px; font-weight: 500; margin: 0; }.food-heading > span { font-size: 10px; color: #8e998a; }
.foods { list-style: none; padding: 0; margin: 0; }.foods li { display: flex; align-items: center; gap: 10px; padding: 13px 0; border-bottom: 1px solid #ffffff0b; }.food-icon { display: grid; place-items: center; width: 30px; height: 30px; flex-shrink: 0; color: #9dab93; border-radius: 9px; background: #a8cf9a09; }.foods li > div { min-width: 0; }.foods strong { font-size: 12px; font-weight: 400; color: #dde4d5; overflow-wrap: anywhere; }.foods li > div > span { display: block; margin-top: 4px; font-size: 10px; color: #939e8b; }.foods button { margin-left: auto; flex-shrink: 0; padding: 8px; border-radius: 8px; color: #a8cf9a; }.foods button:hover { background: #a8cf9a14; }
.meal-link { display: flex; justify-content: center; align-items: center; gap: 8px; width: 100%; margin-top: 20px; padding: 11px; background: #a8cf9a0c; border: 1px solid #a8cf9a2b; border-radius: 10px; color: #c4dcb8; font-size: 12px; transition: background 180ms; }.meal-link:hover { background: #a8cf9a1c; }
.empty { padding: 22px 0; color: #a2ad9b; font-size: 12px; line-height: 1.7; }.empty > span { font-size: 11px; color: #929b8c; }
@media (prefers-reduced-motion: reduce) { .macro-track i { transition: none; } }
</style>
