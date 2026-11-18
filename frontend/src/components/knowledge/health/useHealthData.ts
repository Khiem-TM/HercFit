import { onUnmounted, shallowRef, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import type {
  BodyMetricRead, DailyAssessment, DailyHealth, DeviceWorkout, HealthConnection, HealthOverview, HealthProfile,
  HealthSample, ProgressDay, SleepSession,
} from '@/types/api'
import { dashboardTimezone, localDay, shiftDay } from '../dashboard/dashboardData'

export interface HealthData {
  start: string
  end: string
  days: string[]
  connection: HealthConnection | null
  profile: HealthProfile | null
  overview: HealthOverview | null
  daily: DailyHealth[]
  sleep: SleepSession[]
  workouts: DeviceWorkout[]
  samples: HealthSample[]
  progress: ProgressDay[]
  /** Số đo cơ thể đồng bộ từ thiết bị (source GOOGLE_HEALTH). */
  measurements: BodyMetricRead[]
  /** Đánh giá hôm nay (độ sẵn sàng, giấc ngủ); backend tự chọn múi giờ của tài khoản. */
  assessment: DailyAssessment | null
}

/**
 * Mọi lần đọc Google Health cho một cửa sổ ngày địa phương. Nguồn nào tải lỗi thì giữ bản tải thành công gần nhất của
 * nguồn đó (không thay bằng dữ liệu rỗng); `failed` là các nguồn lỗi ở lần tải mới nhất, `missing` là các nguồn lỗi
 * chưa từng tải được (không có gì cũ để hiển thị).
 */
export function useHealthData(windowDays: () => number) {
  const { authFetch } = useAuth()
  const data = shallowRef<HealthData | null>(null)
  const loading = shallowRef(false)
  const failed = shallowRef<string[]>([])
  const missing = shallowRef<string[]>([])
  const loaded = new Set<string>()
  let controller: AbortController | undefined

  async function refresh() {
    controller?.abort()
    const current = new AbortController()
    controller = current
    loading.value = true
    const end = localDay(new Date())
    const start = shiftDay(end, 1 - windowDays())
    const range = new URLSearchParams({ start_date: start, end_date: end, timezone: dashboardTimezone, limit: '200' })
    const errors: string[] = []
    const previous = data.value
    async function read<T>(name: string, url: string, fallback: T, kept: T | undefined): Promise<T> {
      try {
        const response = await authFetch(url, { signal: current.signal })
        if (!response.ok) throw new Error(String(response.status))
        const body = await response.json() as T
        if (!current.signal.aborted) loaded.add(name)
        return body
      } catch {
        if (!current.signal.aborted) errors.push(name)
        return loaded.has(name) && kept !== undefined ? kept : fallback
      }
    }
    const [connection, profile, overview, daily, sleep, workouts, samples, progress, metrics, assessment] = await Promise.all([
      read<HealthConnection | null>('connection', '/api/integrations/google-health', null, previous?.connection),
      read<HealthProfile | null>('profile', `/api/health/profile?timezone=${dashboardTimezone}`, null, previous?.profile),
      read<HealthOverview | null>('overview', `/api/health/overview?days=${windowDays()}&timezone=${dashboardTimezone}`, null, previous?.overview),
      read<DailyHealth[]>('daily', `/api/health/daily?${range}`, [], previous?.daily),
      read<SleepSession[]>('sleep', `/api/health/sleep?${range}`, [], previous?.sleep),
      read<DeviceWorkout[]>('workouts', `/api/health/workouts?${range}`, [], previous?.workouts),
      read<HealthSample[]>('samples', `/api/health/samples?${range}`, [], previous?.samples),
      read<{ days: ProgressDay[] }>('progress', `/api/progress?${new URLSearchParams({ start_date: start, end_date: end, timezone: dashboardTimezone })}`,
        { days: [] }, previous ? { days: previous.progress } : undefined),
      read<BodyMetricRead[]>('measurements', `/api/body-metrics?${new URLSearchParams({ recorded_from: `${start}T00:00:00+07:00`, limit: '200' })}`,
        [], previous?.measurements),
      read<DailyAssessment | null>('assessment', '/api/v2/health/daily-assessment', null, previous?.assessment),
    ])
    if (current.signal.aborted) return
    const days: string[] = []
    for (let day = start; day <= end; day = shiftDay(day, 1)) days.push(day)
    data.value = {
      start, end, days, connection, profile, overview, daily, sleep, workouts, samples, progress: progress.days,
      measurements: metrics.filter(metric => metric.source === 'GOOGLE_HEALTH'),
      assessment,
    }
    failed.value = errors
    missing.value = errors.filter(name => !loaded.has(name))
    loading.value = false
  }

  watch(windowDays, refresh, { immediate: true })
  onUnmounted(() => controller?.abort())
  return { data, loading, failed, missing, refresh }
}
