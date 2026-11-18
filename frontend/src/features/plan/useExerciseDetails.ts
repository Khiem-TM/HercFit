import { computed, onScopeDispose, shallowRef, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import type { ExerciseSnapshot, PlanItem } from './exercises'

export function useExerciseDetails(getItem: () => PlanItem) {
  const { authFetch } = useAuth()
  const opened = shallowRef(false)
  const loading = shallowRef(false)
  const error = shallowRef('')
  const extra = shallowRef<ExerciseSnapshot | null>(null)
  let generation = 0
  let controller: AbortController | undefined
  const details = computed<ExerciseSnapshot>(() => {
    const snapshot = getItem().exercise_snapshot || {}
    return {
      ...snapshot,
      image_url: snapshot.image_url || extra.value?.image_url,
      instructions: snapshot.instructions || extra.value?.instructions,
      equipment: snapshot.equipment?.length ? snapshot.equipment : extra.value?.equipment,
      muscle_groups: snapshot.muscle_groups?.length ? snapshot.muscle_groups : extra.value?.muscle_groups,
    }
  })
  async function load() {
    const item = getItem()
    if (!item.exercise_id || loading.value || extra.value) return
    const s = item.exercise_snapshot || {}
    if (s.image_url && s.instructions && s.equipment?.length && s.muscle_groups?.length) return
    const token = ++generation
    controller?.abort()
    controller = new AbortController()
    loading.value = true
    error.value = ''
    try {
      const response = await authFetch(`/api/exercises/${encodeURIComponent(item.exercise_id)}?include_inactive=true`, { signal: controller.signal })
      if (!response.ok) throw new Error(response.status === 404 ? 'Bài tập không còn trong thư viện. Đang hiển thị nội dung đã lưu trong lịch.' : 'Chưa tải được hướng dẫn bổ sung.')
      const result = await response.json()
      if (token === generation) extra.value = result
    } catch (cause) {
      if (token === generation) error.value = cause instanceof Error ? cause.message : 'Chưa tải được hướng dẫn bổ sung.'
    } finally { if (token === generation) loading.value = false }
  }
  function toggle() { opened.value = !opened.value; if (opened.value) void load() }
  watch([() => getItem().id, () => getItem().exercise_id], () => {
    ++generation; controller?.abort(); extra.value = null; opened.value = false; loading.value = false; error.value = ''
  })
  onScopeDispose(() => { ++generation; controller?.abort() })
  return { opened, loading, error, details, toggle, load }
}
