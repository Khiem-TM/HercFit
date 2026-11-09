import { num } from '@/components/knowledge/health/healthFormat'
import type { Numeric } from '@/types/api'

export const TZ = 'Asia/Ho_Chi_Minh'
export const WEEKDAY_SHORT = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7']
export const WEEKDAY_LONG = ['Chủ nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy']

/** Số kiểu Việt Nam: 1.850 · 72,4 · dấu trừ thật (−). */
export function vn(value: Numeric | undefined, digits = 0): string {
  const parsed = num(value)
  if (parsed == null) return '—'
  const text = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: digits }).format(Math.abs(parsed))
  return parsed < 0 ? `−${text}` : text
}

export function signed(value: number, digits = 1): string {
  return `${value > 0 ? '+' : ''}${vn(value, digits)}`
}

/** 440 → "7 giờ 20 phút" */
export function hoursMinutes(minutes: number | null | undefined): string {
  if (minutes == null || !Number.isFinite(minutes)) return '—'
  const total = Math.round(minutes)
  const hours = Math.floor(total / 60)
  const rest = total % 60
  return hours ? `${hours} giờ ${String(rest).padStart(2, '0')} phút` : `${rest} phút`
}

const day = (iso: string) => new Date(`${iso.slice(0, 10)}T12:00:00Z`)
export const weekday = (iso: string) => day(iso).getUTCDay()
export const ddmm = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`
export const ddmmyyyy = (iso: string) => `${ddmm(iso)}/${iso.slice(0, 4)}`
/** "Chủ nhật, 08/11" */
export const longDate = (iso: string) => `${WEEKDAY_LONG[weekday(iso)]}, ${ddmm(iso)}`

export function shift(iso: string, days: number): string {
  const date = day(iso)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

/** Thứ Hai của tuần chứa ngày này. */
export const monday = (iso: string) => shift(iso, -((weekday(iso) + 6) % 7))

/** Ngày địa phương (Asia/Ho_Chi_Minh) của một thời điểm. */
export function localDate(value: string | Date): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value))
}

export function clockTime(value: string): string {
  return new Intl.DateTimeFormat('vi-VN', { hour: '2-digit', minute: '2-digit', timeZone: TZ }).format(new Date(value))
}

/** "08/11/2026, 08:30" */
export function stamp(value: string | null | undefined): string {
  if (!value) return '—'
  return `${ddmmyyyy(localDate(value))}, ${clockTime(value)}`
}
