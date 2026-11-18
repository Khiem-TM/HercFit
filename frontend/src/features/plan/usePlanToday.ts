import { computed, onScopeDispose, shallowRef } from 'vue'
import { today, type TrainingPlan } from './model'

export function usePlanToday(getPlan: () => TrainingPlan | null) {
  const now = shallowRef(new Date())
  const timer = setInterval(() => { now.value = new Date() }, 30_000)
  onScopeDispose(() => clearInterval(timer))
  return computed(() => today(getPlan()?.timezone || 'Asia/Ho_Chi_Minh', now.value))
}
