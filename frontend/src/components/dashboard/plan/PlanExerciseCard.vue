<script setup lang="ts">
import { useId } from 'vue'
import { ChevronDown } from 'lucide-vue-next'
import { itemName, kindLabel, prescriptionSummary, type PlanItem } from '@/features/plan/exercises'
import { useExerciseDetails } from '@/features/plan/useExerciseDetails'
import ExerciseImage from './ExerciseImage.vue'
import PrescriptionDetails from './PrescriptionDetails.vue'
const props = defineProps<{ item: PlanItem; index: number }>()
const { opened, loading, error, details, toggle, load } = useExerciseDetails(() => props.item)
const contentId = useId()
const muscles: Record<string, string> = { CHEST: 'Ngực', BACK: 'Lưng', LATS: 'Lưng xô', SHOULDERS: 'Vai', BICEPS: 'Tay trước', TRICEPS: 'Tay sau', FOREARMS: 'Cẳng tay', QUADS: 'Đùi trước', HAMSTRINGS: 'Đùi sau', GLUTES: 'Mông', CALVES: 'Bắp chân', CORE: 'Cơ trung tâm', ABS: 'Bụng', FULL_BODY: 'Toàn thân', OTHER: 'Khác' }
</script>
<template>
  <article class="exercise" :class="{ expanded: opened }">
    <div class="exercise-top">
      <ExerciseImage :src="details.image_url" :alt="itemName(item)" />
      <div class="exercise-title"><span class="eyebrow">Bài {{ String(index + 1).padStart(2, '0') }} · {{ kindLabel(item.prescription.kind) }}</span><h3>{{ itemName(item) }}</h3><p class="metrics">{{ prescriptionSummary(item.prescription) }}</p></div>
    </div>
    <p v-if="item.note" class="item-note">{{ item.note }}</p>
    <button type="button" class="expand" :aria-expanded="opened" :aria-controls="contentId" @click="toggle">{{ opened ? 'Thu gọn hướng dẫn' : 'Xem hướng dẫn' }}<ChevronDown :size="16" :class="{ rotated: opened }" aria-hidden="true" /></button>
    <div v-if="opened" :id="contentId" class="exercise-detail">
      <div class="instruction">
        <ExerciseImage :src="details.image_url" :alt="itemName(item)" large />
        <p v-if="loading" class="muted" role="status">Đang tải hướng dẫn…</p>
        <div v-if="error" class="load-error" role="status">{{ error }} <button type="button" @click="load">Thử lại</button></div>
        <div v-if="details.muscle_groups?.length || details.equipment?.length" class="facts">
          <p v-if="details.muscle_groups?.length"><span>Nhóm cơ</span>{{ details.muscle_groups.map(m => muscles[m.toUpperCase()] || m).join(', ') }}</p>
          <p v-if="details.equipment?.length"><span>Dụng cụ</span>{{ details.equipment.join(', ') }}</p>
        </div>
        <h4>Cách thực hiện</h4>
        <p class="instructions" :class="{ muted: !details.instructions }">{{ details.instructions || 'Chưa có hướng dẫn cho bài tập này.' }}</p>
      </div>
      <PrescriptionDetails :prescription="item.prescription" />
    </div>
  </article>
</template>
<style scoped>
.exercise { border: 1px solid var(--hf-line); border-radius: 16px; padding: 16px; min-width: 0; background: var(--hf-card); }
.exercise-top { display: flex; gap: 14px; align-items: center; }
.exercise-title { min-width: 0; flex: 1; }
.eyebrow { font-size: 10px; color: var(--hf-muted); font-weight: 600; letter-spacing: .03em; }
h3 { font-weight: 600; font-size: 15px; line-height: 1.5; margin: 3px 0; overflow-wrap: anywhere; }
.metrics { font-size: 12px; color: var(--hf-sub); margin: 0; line-height: 1.7; }
.item-note { font-size: 12px; line-height: 1.6; color: var(--hf-muted); margin: 12px 0 0; white-space: pre-line; }
.expand { display: flex; align-items: center; gap: 6px; min-height: 44px; border: 0; background: transparent; color: var(--hf-ink); font-size: 12px; font-weight: 600; margin: 6px 0 -6px auto; padding: 6px 0 6px 12px; }
.rotated { transform: rotate(180deg); }
.exercise-detail { margin-top: 16px; border-top: 1px solid var(--hf-line); padding-top: 16px; display: grid; gap: 24px; }
.instructions { white-space: pre-line; font-size: 13px; line-height: 1.8; margin: 0; overflow-wrap: anywhere; }
h4 { font-weight: 600; margin: 16px 0 8px; font-size: 13px; }
.muted { color: var(--hf-muted); font-size: 12px; }
.facts { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 10px 24px; }
.facts p { margin: 0; font-size: 12px; line-height: 1.7; }
.facts span { display: block; color: var(--hf-muted); font-size: 11px; }
.load-error { font-size: 12px; color: var(--hf-warn-text); line-height: 1.7; margin-top: 10px; }
.load-error button { color: inherit; background: transparent; border: 0; text-decoration: underline; min-height: 44px; padding: 0 8px; }
@media (min-width: 1280px) { .exercise-detail { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } }
@media (max-width: 600px) { .exercise { padding: 12px; } .exercise-top { gap: 10px; } }
</style>
