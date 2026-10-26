import type { DayRange } from '@/composables/useKnowledgeGraph'
import { shiftDay } from './dashboard/dashboardData'

/** Days are local (Asia/Ho_Chi_Minh) `YYYY-MM-DD` strings; ranges include both ends. */
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

/** The last `days` days up to `max`, never before `min`. */
export function recentRange(min: string, max: string, days = DEFAULT_WINDOW_DAYS): DayRange {
  return { start: clampDay(shiftDay(max, 1 - days), min, max), end: max }
}

/** Keep the range's length and move it so `day` sits in its middle, inside the bounds. */
export function centreOn(range: DayRange, day: string, min: string, max: string): DayRange {
  const span = Math.min(dayDiff(range.start, range.end), dayDiff(min, max))
  let start = clampDay(shiftDay(day, -Math.floor(span / 2)), min, max)
  let end = shiftDay(start, span)
  if (end > max) {
    end = max
    start = shiftDay(max, -span)
  }
  return { start, end }
}

/** Every day from `min` to `max`, both included. */
export function daysBetween(min: string, max: string): string[] {
  const count = Math.max(0, dayDiff(min, max) + 1)
  return Array.from({ length: count }, (_, i) => shiftDay(min, i))
}
