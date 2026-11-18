import { computed, shallowRef } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { today, type CompletionResult, type PlanEntry, type TrainingPlan } from './model'
import { canComplete } from './weeks'

/** Shared write path for Today and Plan. Recheck the date at submission, including midnight. */
export function useCompletion(getPlan: () => TrainingPlan | null, getEntry: () => PlanEntry | null, getToday: () => string) {
  const { authFetch } = useAuth()
  const saving = shallowRef(false)
  const error = shallowRef('')
  const completed = shallowRef<CompletionResult | null>(null)
  const eligible = computed(() => canComplete(getPlan(), getEntry(), getToday()) && completed.value?.entry.id !== getEntry()?.id)
  async function save(): Promise<CompletionResult | null> {
    const plan = getPlan(), entry = getEntry()
    if (saving.value || !eligible.value || !plan || !entry) return null
    if (!canComplete(plan, entry, today(plan.timezone))) {
      error.value = 'Ngày tập đã thay đổi. Chỉ có thể ghi nhận buổi của hôm nay.'
      return null
    }
    saving.value = true
    error.value = ''
    try {
      const response = await authFetch(`/api/training-plans/${plan.id}/entries/${entry.id}/complete`, { method: 'POST' })
      if (!response.ok) {
        const body = await response.json().catch(() => ({}))
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Chưa lưu được. Kiểm tra kết nối và thử lại.')
      }
      const result: CompletionResult = await response.json()
      completed.value = result
      return result
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : 'Chưa lưu được. Thử lại sau.'
      return null
    } finally { saving.value = false }
  }
  return { saving, error, completed, eligible, save }
}
