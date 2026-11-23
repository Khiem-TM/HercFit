import type { DayRange } from '@/composables/useKnowledgeGraph'
import { shift } from '@/components/dashboard/format'

/** Ngày là chuỗi `YYYY-MM-DD` theo giờ địa phương (Asia/Ho_Chi_Minh); khoảng tính cả hai đầu. */
export const DEFAULT_WINDOW_DAYS = 15

export function dayDiff(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T12:00:00Z`) - Date.parse(`${from}T12:00:00Z`)) / 86_400_000)
}

export function clampDay(day: string, min: string, max: string): string {
  return day < min ? min : day > max ? max : day
}

export function rangeLength(range: DayRange): number {
  return dayDiff(range.start, range.end) + 1
}

export function sameRange(a?: DayRange, b?: DayRange): boolean {
  return a?.start === b?.start && a?.end === b?.end
}

/** `days` ngày gần nhất tính tới `max`, không bao giờ trước `min`. */
export function recentRange(min: string, max: string, days = DEFAULT_WINDOW_DAYS): DayRange {
  return { start: clampDay(shift(max, 1 - days), min, max), end: max }
}

/** Mọi ngày từ `min` tới `max`, tính cả hai. */
export function daysBetween(min: string, max: string): string[] {
  const count = Math.max(0, dayDiff(min, max) + 1)
  return Array.from({ length: count }, (_, i) => shift(min, i))
}
