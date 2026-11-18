import { computed, onUnmounted, shallowRef, watch } from 'vue'
import { useDocumentVisibility, useIntervalFn } from '@vueuse/core'
import { useAuth } from '@/composables/useAuth'
import type {
  BodyMetricRead, DailyAssessment, DailyHealth, DeviceWorkout, HealthConnection, HealthOverview, HealthProfile,
  HealthSample, NutritionTargets, ProgressDay, SleepSession,
} from '@/types/api'
import type { CompletionResult, TrainingPlan } from '@/features/plan/model'
import type { HealthData } from '@/components/knowledge/health/useHealthData'
import { createHealthApi } from '@/features/health-integration/api'
import { localDate, shift, TZ } from './format'
import { repeatMealPayload } from './today'

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
    food_id: string | null
    note: string | null
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

/** Kết quả một lần làm mới: đủ, thiếu một phần, hay không tải được gì. */
export type RefreshOutcome = 'ok' | 'partial' | 'failed'

/** GET /api/dashboard (backend/domains/analytics/routers/dashboard_router.py): mỗi phần null khi lỗi hoặc không được đọc. */
interface DashboardResponse {
  start_date: string
  end_date: string
  connection: HealthConnection | null
  profile: HealthProfile | null
  overview: HealthOverview | null
  daily: DailyHealth[] | null
  sleep: SleepSession[] | null
  workouts: DeviceWorkout[] | null
  samples: HealthSample[] | null
  progress: { days: ProgressDay[] } | null
  assessment: DailyAssessment | null
  targets: NutritionTargets | null
  plan: TrainingPlan | null
  previous_plan: TrainingPlan | null
  meals: MealRow[] | null
  trainings: TrainingRow[] | null
  metrics: BodyMetricRead[] | null
  /** Phần đọc lỗi ở lần này. */
  errors: string[]
}
type Section = Exclude<keyof DashboardResponse, 'start_date' | 'end_date' | 'errors' | 'previous_plan'>
const SECTIONS: Section[] = ['connection', 'progress', 'targets', 'plan', 'meals', 'trainings', 'metrics', 'profile',
  'overview', 'daily', 'sleep', 'workouts', 'samples', 'assessment']

/**
 * Mọi dữ liệu Dashboard trong một request (/api/dashboard): sức khoẻ 90 ngày, đánh giá hôm nay, lịch tập, mục tiêu
 * dinh dưỡng, bữa ăn, số đo và buổi tập. Phần nào lỗi thì giữ bản tải thành công gần nhất của phần đó trên màn hình.
 * "Hôm nay" được tính lại khi làm mới, khi trang hiện lại và qua nửa đêm (ứng dụng mở qua đêm).
 */
export function useDashboardData() {
  const { authFetch } = useAuth()
  const day = shallowRef(localDate(new Date()))
  const snapshot = shallowRef<DashboardResponse | null>(null)
  const plan = shallowRef<TrainingPlan | null>(null)
  const previousPlan = shallowRef<TrainingPlan | null>(null)
  const loading = shallowRef(true)
  // Lần đọc đầu đã xong (thành công hay lỗi): trước đó tab Hôm nay hiện khung chờ, sau đó không chớp khi làm mới.
  const settled = shallowRef(false)
  const failed = shallowRef<string[]>([])
  const loaded = new Set<string>()
  let controller: AbortController | undefined

  /** Ngày địa phương đã sang ngày mới thì cập nhật và trả true. */
  function rollDay(): boolean {
    const now = localDate(new Date())
    if (now === day.value) return false
    day.value = now
    return true
  }

  async function refresh(): Promise<RefreshOutcome> {
    controller?.abort()
    const current = new AbortController()
    controller = current
    loading.value = true
    rollDay()
    let outcome: RefreshOutcome = 'ok'
    try {
      const query = new URLSearchParams({ days: String(HISTORY_DAYS), timezone: TZ })
      const response = await authFetch(`/api/dashboard?${query}`, { signal: current.signal })
      if (!response.ok) throw new Error(String(response.status))
      const body = await response.json() as DashboardResponse
      if (current.signal.aborted) return 'ok'
      const kept = { ...body } as Record<string, unknown>
      const previous = snapshot.value as Record<string, unknown> | null
      for (const name of body.errors) if (previous) kept[name] = previous[name]
      if (body.errors.includes('plan') && previous) kept.previous_plan = previous.previous_plan
      snapshot.value = kept as unknown as DashboardResponse
      if (!body.errors.includes('plan')) {
        plan.value = body.plan
        previousPlan.value = body.previous_plan
      }
      SECTIONS.filter(name => !body.errors.includes(name)).forEach(name => loaded.add(name))
      failed.value = body.errors
      outcome = body.errors.length ? 'partial' : 'ok'
    } catch {
      if (current.signal.aborted) return 'ok'
      // Cả request lỗi: mọi phần giữ bản cũ (nếu có).
      failed.value = [...SECTIONS]
      outcome = 'failed'
    } finally {
      if (controller === current) {
        loading.value = false
        settled.value = true
      }
    }
    return outcome
  }

  const meals = computed(() => snapshot.value?.meals ?? [])
  const trainings = computed(() => snapshot.value?.trainings ?? [])
  const metrics = computed(() => snapshot.value?.metrics ?? [])
  const targets = computed(() => snapshot.value?.targets ?? null)

  /** Cùng dạng useHealthData trả về, cho các thẻ sức khoẻ dùng chung. */
  const health = computed<HealthData | null>(() => {
    const data = snapshot.value
    if (!data) return null
    const days: string[] = []
    for (let current = data.start_date; current <= data.end_date; current = shift(current, 1)) days.push(current)
    const from = `${data.start_date}T00:00:00+07:00`
    return {
      start: data.start_date, end: data.end_date, days,
      connection: data.connection, profile: data.profile, overview: data.overview,
      daily: data.daily ?? [], sleep: data.sleep ?? [], workouts: data.workouts ?? [], samples: data.samples ?? [],
      progress: data.progress?.days ?? [],
      // Số đo thiết bị trong khoảng ngày: server trả chung danh sách số đo (không đọc hai lần).
      measurements: (data.metrics ?? []).filter(metric => metric.source === 'GOOGLE_HEALTH'
        && new Date(metric.recorded_at) >= new Date(from)),
      assessment: data.assessment,
    }
  })

  // Ghi nhanh từ tab Hôm nay: mỗi lần bấm là một lệnh ghi mới (khoá idempotency mới); lỗi ném ra cho nơi gọi báo.
  const healthApi = createHealthApi((url, init) => authFetch(url, init))

  async function logMealAgain(meal: MealRow) {
    const response = await authFetch('/api/meals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify(repeatMealPayload(meal, new Date())),
    })
    if (!response.ok) throw new Error(String(response.status))
    await refresh()
  }

  async function logWater(milliliters: number) {
    await healthApi.createRecord('hydration', { amount_ml: milliliters, consumed_at: new Date().toISOString(), timezone: TZ })
    await refresh()
  }

  void refresh()
  // Trang hiện lại (mở lại tab, mở khoá máy) hoặc đồng hồ qua nửa đêm: sang ngày mới thì tải lại.
  watch(useDocumentVisibility(), visible => { if (visible === 'visible' && rollDay()) void refresh() })
  useIntervalFn(() => { if (rollDay()) void refresh() }, 60_000)
  onUnmounted(() => controller?.abort())

  const mealsToday = computed(() => meals.value.filter(meal => localDate(meal.consumed_at) === day.value)
    .sort((a, b) => a.consumed_at.localeCompare(b.consumed_at)))

  function applyPlanCompletion(result: CompletionResult) {
    const current = plan.value
    if (!current?.entries.some(entry => entry.id === result.entry.id)) return
    plan.value = { ...current, entries: current.entries.map(entry => entry.id === result.entry.id ? result.entry : entry) }
  }

  return {
    planLoading: loading, applyPlanCompletion,
    // Getter: computed và template đọc data.today vẫn theo dõi được khi sang ngày mới.
    get today() { return day.value },
    get start() { return shift(day.value, 1 - HISTORY_DAYS) },
    health, targets, plan, previousPlan, meals, mealsToday, metrics, trainings,
    /** Đang có request (nút làm mới quay). */
    loading,
    settled,
    failed,
    // Phần lỗi chưa từng tải được: không có dữ liệu cũ nào đang hiển thị thay cho nó.
    missing: computed(() => failed.value.filter(name => !loaded.has(name))),
    refresh, reloadPlan: refresh, logMealAgain, logWater,
  }
}

export type DashboardData = ReturnType<typeof useDashboardData>
