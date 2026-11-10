import { computed, onUnmounted, shallowRef } from 'vue'
import { useAuth } from '@/composables/useAuth'
import type { BodyMetricRead } from '@/types/api'
import type { TrainingPlan } from '@/features/plan/model'
import { useHealthData } from '@/components/knowledge/health/useHealthData'
import { useNutritionTargets } from '@/components/knowledge/dashboard/useNutritionTargets'
import { localDate, shift, TZ } from './format'

/** Bữa ăn như /api/meals trả về (chỉ các trường Dashboard dùng). */
export interface MealRow {
  id: string
  name: string
  consumed_at: string
  energy_kcal: number | string | null
  protein_g: number | string | null
  carbohydrate_g: number | string | null
  fat_g: number | string | null
  nutrition_incomplete: boolean
  items: {
    id: string
    quantity: number | string
    unit: 'G' | 'ML'
    food_snapshot: Record<string, unknown>
    energy_kcal: number | string | null
    protein_g: number | string | null
    nutrition_incomplete: boolean
  }[]
}

/** Buổi tập trong nhật ký HercFit (/api/trainings). */
export interface TrainingRow {
  id: string
  name: string
  started_at: string
  duration_seconds: number | null
  energy_kcal: number | string | null
  discipline: string
  source_entry_id: string | null
}

export const HISTORY_DAYS = 90

/**
 * Mọi dữ liệu Dashboard đọc: sức khoẻ 90 ngày (Google Health + đánh giá hôm nay), lịch tập, mục tiêu dinh dưỡng,
 * bữa ăn, số đo và buổi tập. Lần tải lại giữ dữ liệu cũ trên màn hình cho tới khi có dữ liệu mới.
 */
export function useDashboardData() {
  const { authFetch } = useAuth()
  const today = localDate(new Date())
  const start = shift(today, 1 - HISTORY_DAYS)
  const health = useHealthData(() => HISTORY_DAYS)
  const revision = shallowRef(0)
  const nutrition = useNutritionTargets(() => String(revision.value))

  const plan = shallowRef<TrainingPlan | null>(null)
  const previousPlan = shallowRef<TrainingPlan | null>(null)
  const meals = shallowRef<MealRow[]>([])
  const metrics = shallowRef<BodyMetricRead[]>([])
  const trainings = shallowRef<TrainingRow[]>([])
  const loading = shallowRef(true)
  const failed = shallowRef<string[]>([])
  let controller: AbortController | undefined

  async function read<T>(name: string, url: string, fallback: T, signal: AbortSignal, errors: string[]): Promise<T> {
    try {
      const response = await authFetch(url, { signal })
      if (response.status === 404) return fallback
      if (!response.ok) throw new Error(String(response.status))
      return await response.json() as T
    } catch {
      if (!signal.aborted) errors.push(name)
      return fallback
    }
  }

  async function load() {
    controller?.abort()
    const current = new AbortController()
    controller = current
    loading.value = true
    const errors: string[] = []
    const from = `${start}T00:00:00+07:00`
    const range = (extra: Record<string, string> = {}) => new URLSearchParams({ recorded_from: from, limit: '200', ...extra })
    const [active, ended, mealRows, metricRows, trainingRows] = await Promise.all([
      read<TrainingPlan | null>('plan', '/api/training-plans/current', null, current.signal, errors),
      read<TrainingPlan | null>('plan', '/api/training-plans/previous', null, current.signal, errors),
      read<MealRow[]>('meals', `/api/meals?${range({ timezone: TZ })}`, [], current.signal, errors),
      // Không giới hạn ngày: vòng đo có thể được đo từ lâu.
      read<BodyMetricRead[]>('metrics', '/api/body-metrics?limit=200', [], current.signal, errors),
      read<TrainingRow[]>('trainings', `/api/trainings?${range({ timezone: TZ })}`, [], current.signal, errors),
    ])
    if (current.signal.aborted) return
    plan.value = active
    previousPlan.value = active ? null : ended
    meals.value = mealRows
    metrics.value = metricRows
    trainings.value = trainingRows
    failed.value = [...new Set(errors)]
    loading.value = false
  }

  async function refresh() {
    revision.value += 1
    await Promise.all([load(), health.refresh()])
  }

  void load()
  onUnmounted(() => controller?.abort())

  const mealsToday = computed(() => meals.value.filter(meal => localDate(meal.consumed_at) === today)
    .sort((a, b) => a.consumed_at.localeCompare(b.consumed_at)))

  return {
    today, start, health: health.data, healthLoading: health.loading, healthFailed: health.failed,
    targets: nutrition.targets, plan, previousPlan, meals, mealsToday, metrics, trainings,
    loading: computed(() => loading.value || (health.loading.value && !health.data.value)),
    failed: computed(() => [...failed.value, ...health.failed.value]),
    refresh, reloadPlan: load,
  }
}

export type DashboardData = ReturnType<typeof useDashboardData>
