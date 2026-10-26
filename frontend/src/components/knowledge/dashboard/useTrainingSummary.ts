import { onUnmounted, shallowRef, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { dashboardTimezone, localDay, shiftDay, type TrainingSummary } from './dashboardData'

export function useTrainingSummary(revision: () => string | null | undefined) {
  const { authFetch } = useAuth()
  const summary = shallowRef<TrainingSummary | null>(null)
  const loading = shallowRef(false)
  const error = shallowRef(false)
  let controller: AbortController | undefined

  async function refresh() {
    controller?.abort()
    const current = new AbortController()
    controller = current
    loading.value = true
    error.value = false
    const today = localDay(new Date())
    const weekday = new Date(`${today}T12:00:00Z`).getUTCDay()
    const start = shiftDay(today, -((weekday + 6) % 7) - 21)
    try {
      const params = new URLSearchParams({ start_date: start, end_date: today, timezone: dashboardTimezone })
      const response = await authFetch(`/api/training/summary?${params}`, { signal: current.signal })
      if (!response.ok) throw new Error('Training summary unavailable')
      const data: TrainingSummary = await response.json()
      if (!Array.isArray(data.weeks)) throw new Error('Invalid training summary')
      if (!current.signal.aborted) summary.value = data
    } catch {
      if (!current.signal.aborted) error.value = true
    } finally {
      if (!current.signal.aborted) loading.value = false
    }
  }

  watch(revision, refresh, { immediate: true })
  onUnmounted(() => controller?.abort())
  return { summary, loading, error, refresh }
}
