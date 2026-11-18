<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { Check } from 'lucide-vue-next'
import type { CompletionResult, PlanEntry, TrainingPlan } from '@/features/plan/model'
import { useCompletion } from '@/features/plan/useCompletion'
import { ddmmyyyy } from '../format'
import PlanConfirmDialog from './PlanConfirmDialog.vue'
const props = defineProps<{ plan: TrainingPlan; entry: PlanEntry; today: string }>()
const emit = defineEmits<{ completed: [result: CompletionResult] }>()
const { saving, error, completed, eligible, save } = useCompletion(() => props.plan, () => props.entry, () => props.today)
const confirming = shallowRef(false)
const isDone = computed(() => !!props.entry.completed_at || completed.value?.entry.id === props.entry.id)
const reason = computed(() => props.plan.status === 'ENDED' ? 'Kế hoạch đã kết thúc · chỉ xem'
  : props.entry.scheduled_date < props.today ? 'Buổi đã qua · không thể ghi nhận bù'
  : props.entry.scheduled_date > props.today ? 'Bạn có thể ghi nhận vào ngày tập' : 'Không thể ghi nhận buổi này')
watch(() => props.entry.id, () => { confirming.value = false; error.value = '' })
async function confirm() {
  const result = await save()
  if (result) { confirming.value = false; emit('completed', result) }
}
</script>
<template>
  <div class="completion">
    <div v-if="isDone" class="recorded" role="status"><Check :size="18" aria-hidden="true" />Đã ghi nhận hoàn thành</div>
    <template v-else-if="eligible">
      <p class="hint">Tập xong buổi này? Ghi nhận để cập nhật tiến độ của bạn.</p>
      <button type="button" class="hf-btn pri" :disabled="saving" @click="error = ''; confirming = true"><Check :size="18" aria-hidden="true" />Ghi nhận đã tập</button>
    </template>
    <p v-else class="hint">{{ reason }}</p>
    <PlanConfirmDialog v-if="confirming" :title="`Ghi nhận đã tập ${entry.label}?`"
      :description="`Buổi tập ngày ${ddmmyyyy(entry.scheduled_date)} sẽ được ghi vào nhật ký và cập nhật tiến độ kế hoạch. Thao tác này không hoàn tác được.`"
      :busy="saving" :error="error" confirm-label="Xác nhận ghi nhận" @cancel="confirming = false" @confirm="confirm" />
  </div>
</template>
<style scoped>
.completion { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.hint { color: var(--hf-muted); font-size: 13px; line-height: 1.6; margin: 0; flex: 1 1 200px; }
.recorded { display: flex; align-items: center; gap: 8px; color: var(--hf-ok-text); font-size: 14px; font-weight: 600; }
.hf-btn { min-height: 44px; }
@media (max-width: 600px) { .hf-btn { width: 100%; } }
</style>
