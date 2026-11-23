import { num } from './format'
import type { ProgressDay } from '@/types/api'

/** Hệ số "ít vận động": phần tiêu hao ngoài BMR và ngoài buổi tập (đi lại, tiêu hoá). Buổi tập được cộng riêng. */
export const BASE_FACTOR = 1.2
export const ESTIMATE_METHOD = 'BMR × 1,2 + calo buổi tập đã ghi'

export interface EnergyOut { kcal: number; source: 'device' | 'estimate' }

/** Ước tính cả ngày khi không có số của thiết bị; null khi chưa có BMR (hồ sơ thiếu) hoặc không có dữ liệu ngày. */
export function estimateOut(day: ProgressDay | undefined, bmr: number | null): EnergyOut | null {
  if (!day || bmr == null) return null
  return { kcal: Math.round(bmr * BASE_FACTOR + (num(day.exercise_calories.known_total) ?? 0)), source: 'estimate' }
}

/** Tiêu hao một ngày: tổng từ thiết bị (Google Health) nếu có, nếu không thì ước tính. */
export function energyOut(day: ProgressDay | undefined, bmr: number | null): EnergyOut | null {
  const device = num(day?.calories_out_actual)
  return device != null ? { kcal: device, source: 'device' } : estimateOut(day, bmr)
}
