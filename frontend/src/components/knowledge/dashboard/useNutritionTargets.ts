import { onUnmounted, shallowRef, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import type { NutritionTargets } from '@/types/api'
import { dashboardTimezone } from './dashboardData'

/** Typed targets from the backend; refreshed whenever the knowledge map revision changes. */
export function useNutritionTargets(revision: () => string | null | undefined) {
  const { authFetch } = useAuth()
  const targets = shallowRef<NutritionTargets | null>(null)
  const loading = shallowRef(false)
  const error = shallowRef(false)
  let controller: AbortController | undefined

  async function refresh() {
    controller?.abort()
    const current = new AbortController()
    controller = current
    loading.value = true
    error.value = false
    try {
      const params = new URLSearchParams({ timezone: dashboardTimezone })
      const response = await authFetch(`/api/nutrition/targets?${params}`, { signal: current.signal })
      if (!response.ok) throw new Error('Nutrition targets unavailable')
      const data: NutritionTargets = await response.json()
      if (!current.signal.aborted) targets.value = data
    } catch {
      if (!current.signal.aborted) error.value = true
    } finally {
      if (!current.signal.aborted) loading.value = false
    }
  }

  watch(revision, refresh, { immediate: true })
  onUnmounted(() => controller?.abort())
  return { targets, loading, error, refresh }
}

const WARNING_TEXT: Record<string, string> = {
  sex_unknown_used_average_constant: 'Chưa có giới tính sinh học nên BMR dùng hệ số trung bình.',
  activity_unknown_assumed_sedentary: 'Chưa có mức vận động nên tạm tính là ít vận động.',
  target_date_too_aggressive_rate_capped: 'Mốc thời gian mục tiêu quá gấp; tốc độ giảm được giới hạn 1% cân nặng mỗi tuần.',
  intake_floor_applied: 'Mục tiêu đã được nâng lên mức sàn an toàn (không thấp hơn BMR).',
  minor_maintenance_only: 'Dưới 18 tuổi: chỉ đặt mức duy trì, không đặt thâm hụt calo.',
  target_weight_already_reached: 'Bạn đã đạt cân nặng mục tiêu.',
  protein_and_fat_exceed_target_energy: 'Protein và chất béo đã chiếm hết năng lượng mục tiêu.',
}
const MISSING_TEXT: Record<string, string> = { weight_kg: 'cân nặng', height_cm: 'chiều cao', age: 'tuổi' }
const REASON_TEXT: Record<string, string> = {
  need_4_weigh_ins_in_window: 'cần ít nhất 4 lần cân trong 28 ngày',
  need_14_days_between_weigh_ins: 'các lần cân cần trải qua ít nhất 14 ngày',
  need_10_fully_logged_days: 'cần ít nhất 10 ngày ghi đủ bữa (từ 2 bữa trở lên)',
}

export const warningText = (code: string) => WARNING_TEXT[code] ?? code
export const missingText = (code: string) => MISSING_TEXT[code] ?? code
export const reasonText = (code: string) => REASON_TEXT[code] ?? code
