import type { Numeric } from '@/types/api'

export const TZ = 'Asia/Ho_Chi_Minh'
export const WEEKDAY_SHORT = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7']
export const WEEKDAY_LONG = ['Chủ nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy']

/** Cột thập phân đến dưới dạng chuỗi; thiếu thì giữ là thiếu, không bao giờ là số 0. */
export function num(value: Numeric | undefined): number | null {
  if (value == null || value === '') return null
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

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

/** Ngày địa phương (Asia/Ho_Chi_Minh) của một thời điểm; thời điểm không hợp lệ cho chuỗi rỗng. */
export function localDate(value: string | Date): string {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  return new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}

export function clockTime(value: string): string {
  return new Intl.DateTimeFormat('vi-VN', { hour: '2-digit', minute: '2-digit', timeZone: TZ }).format(new Date(value))
}

/** "08/11/2026, 08:30" */
export function stamp(value: string | null | undefined): string {
  if (!value) return '—'
  return `${ddmmyyyy(localDate(value))}, ${clockTime(value)}`
}

const EXERCISE_LABELS: Record<string, string> = {
  RUNNING: 'Chạy bộ', TREADMILL_RUNNING: 'Chạy máy', WALKING: 'Đi bộ', HIKING: 'Leo núi', BIKING: 'Đạp xe',
  CYCLING: 'Đạp xe', STATIONARY_BIKING: 'Xe đạp tập', SWIMMING: 'Bơi', POOL_SWIMMING: 'Bơi hồ', OPEN_WATER_SWIMMING: 'Bơi ngoài trời',
  WEIGHTLIFTING: 'Tập tạ', STRENGTH_TRAINING: 'Tập sức mạnh', YOGA: 'Yoga', PILATES: 'Pilates', ELLIPTICAL: 'Máy elip',
  ROWING: 'Chèo thuyền', HIIT: 'HIIT', DANCING: 'Nhảy', TENNIS: 'Quần vợt', BADMINTON: 'Cầu lông', FOOTBALL: 'Bóng đá',
  SOCCER: 'Bóng đá', BASKETBALL: 'Bóng rổ', OTHER: 'Khác', SPORT: 'Thể thao', SWIMMING_POOL: 'Bơi hồ',
  ROWING_MACHINE: 'Máy chèo thuyền', TABLE_TENNIS: 'Bóng bàn', VOLLEYBALL: 'Bóng chuyền', BOXING: 'Quyền anh',
  PICKELBALL: 'Pickleball',
}
export function exerciseLabel(type: string | null | undefined): string {
  if (!type) return 'Vận động'
  return EXERCISE_LABELS[type] ?? type.toLowerCase().replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())
}

const SCOPE_LABELS: Record<string, string> = {
  activity_and_fitness: 'Vận động', health_metrics_and_measurements: 'Chỉ số cơ thể & tim mạch', sleep: 'Giấc ngủ',
  profile: 'Hồ sơ', settings: 'Cài đặt', nutrition: 'Dinh dưỡng & nước uống', ecg: 'ECG', irn: 'Cảnh báo nhịp bất thường',
}
const scopeKey = (scope: string) => scope.split('googlehealth.')[1]?.replace(/\.(readonly|writeonly)$/, '') ?? scope
/** "Vận động" cho quyền đọc, "Ghi vận động" cho quyền ghi (HercFit chỉ ghi những gì nó ghi). */
export function scopeLabel(scope: string): string {
  const label = SCOPE_LABELS[scopeKey(scope)] ?? scopeKey(scope)
  return scope.endsWith('.writeonly') ? `Ghi ${label.toLowerCase()}` : label
}
