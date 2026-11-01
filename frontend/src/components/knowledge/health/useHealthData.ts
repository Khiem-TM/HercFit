import { onUnmounted, shallowRef, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import type {
  BodyMetricRead, DailyHealth, DeviceWorkout, HealthConnection, HealthOverview, HealthProfile, HealthSample,
  ProgressDay, SleepSession,
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
}

/** Mọi lần đọc Google Health cho một cửa sổ ngày địa phương. Lần tải lại giữ dữ liệu trước trên màn hình. */
export function useHealthData(windowDays: () => number) {
  const { authFetch } = useAuth()
  const data = shallowRef<HealthData | null>(null)
  const loading = shallowRef(false)
  const failed = shallowRef<string[]>([])
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
    async function read<T>(name: string, url: string, fallback: T): Promise<T> {
      try {
        const response = await authFetch(url, { signal: current.signal })
        if (!response.ok) throw new Error(String(response.status))
        return await response.json() as T
      } catch {
        if (!current.signal.aborted) errors.push(name)
        return fallback
      }
    }
    const [connection, profile, overview, daily, sleep, workouts, samples, progress, metrics] = await Promise.all([
      read<HealthConnection | null>('connection', '/api/integrations/google-health', null),
      read<HealthProfile | null>('profile', `/api/health/profile?timezone=${dashboardTimezone}`, null),
      read<HealthOverview | null>('overview', `/api/health/overview?days=${windowDays()}&timezone=${dashboardTimezone}`, null),
      read<DailyHealth[]>('daily', `/api/health/daily?${range}`, []),
      read<SleepSession[]>('sleep', `/api/health/sleep?${range}`, []),
      read<DeviceWorkout[]>('workouts', `/api/health/workouts?${range}`, []),
      read<HealthSample[]>('samples', `/api/health/samples?${range}`, []),
      read<{ days: ProgressDay[] }>('progress', `/api/progress?${new URLSearchParams({ start_date: start, end_date: end, timezone: dashboardTimezone })}`, { days: [] }),
      read<BodyMetricRead[]>('measurements', `/api/body-metrics?${new URLSearchParams({ recorded_from: `${start}T00:00:00+07:00`, limit: '200' })}`, []),
    ])
    if (current.signal.aborted) return
    const days: string[] = []
    for (let day = start; day <= end; day = shiftDay(day, 1)) days.push(day)
    data.value = {
      start, end, days, connection, profile, overview, daily, sleep, workouts, samples, progress: progress.days,
      measurements: metrics.filter(metric => metric.source === 'GOOGLE_HEALTH'),
    }
    failed.value = errors
    loading.value = false
  }

  watch(windowDays, refresh, { immediate: true })
  onUnmounted(() => controller?.abort())
  return { data, loading, failed, refresh }
}
