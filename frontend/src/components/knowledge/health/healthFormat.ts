import type { Numeric, ValueSource } from '@/types/api'

/** Cột thập phân đến dưới dạng chuỗi; thiếu thì giữ là thiếu, không bao giờ là số 0. */
export function num(value: Numeric | undefined): number | null {
  if (value == null || value === '') return null
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function fmt(value: Numeric | undefined, digits = 0): string {
  const parsed = num(value)
  return parsed == null ? '—' : new Intl.NumberFormat('vi-VN', { maximumFractionDigits: digits }).format(parsed)
}

/** 400 → "6 g 40", 39 → "39 phút" */
export function duration(minutes: Numeric | undefined): string {
  const parsed = num(minutes)
  if (parsed == null) return '—'
  const rounded = Math.round(parsed)
  if (rounded < 60) return `${rounded} phút`
  return `${Math.floor(rounded / 60)} g ${String(rounded % 60).padStart(2, '0')}`
}

const TZ = 'Asia/Ho_Chi_Minh'
export const dayLabel = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`
export const longDay = (iso: string) => new Intl.DateTimeFormat('vi-VN', { weekday: 'short', day: '2-digit', month: '2-digit', timeZone: 'UTC' })
  .format(new Date(`${iso}T00:00:00Z`))
export const clock = (iso: string) => new Intl.DateTimeFormat('vi-VN', { hour: '2-digit', minute: '2-digit', timeZone: TZ }).format(new Date(iso))
export const moment = (iso: string | null | undefined) => iso
  ? new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', timeStyle: 'short', timeZone: TZ }).format(new Date(iso)) : '—'

export const SOURCE_LABELS: Record<ValueSource, string> = {
  DECLARED: 'Khai báo', MEASURED: 'Thiết bị', PROVIDER: 'Google', DERIVED: 'Suy luận',
}
export const ACTIVITY_LABELS: Record<string, string> = {
  sedentary: 'Ít vận động', light: 'Vận động nhẹ', moderate: 'Vận động vừa', active: 'Năng động', very_active: 'Rất năng động',
}
export const LEVEL_LABELS: Record<string, string> = {
  LIGHT: 'Nhẹ', LIGHTLY_ACTIVE: 'Nhẹ', MODERATE: 'Vừa', MODERATELY_ACTIVE: 'Vừa', VIGOROUS: 'Mạnh', VERY_ACTIVE: 'Mạnh',
  SEDENTARY: 'Tĩnh tại',
}
export const SEX_LABELS: Record<string, string> = { MALE: 'Nam', FEMALE: 'Nữ' }
export const SAMPLE_LABELS: Record<string, string> = { BLOOD_GLUCOSE: 'Đường huyết', CORE_BODY_TEMPERATURE: 'Nhiệt độ cơ thể' }
export const DETAIL_LABELS: Record<string, string> = {
  mealType: 'Bữa', measurementTiming: 'Thời điểm', specimen: 'Mẫu', measurementSource: 'Nguồn đo', measurementLocation: 'Vị trí đo',
}
/** Giá trị enum của nhà cung cấp trong chi tiết mẫu; giá trị lạ hiển thị chữ thường dễ đọc. */
export const DETAIL_VALUES: Record<string, string> = {
  BREAKFAST: 'bữa sáng', LUNCH: 'bữa trưa', DINNER: 'bữa tối', SNACK: 'bữa phụ', FASTING: 'lúc đói',
  BEFORE_MEAL: 'trước ăn', AFTER_MEAL: 'sau ăn', GENERAL: 'bất kỳ', CAPILLARY_BLOOD: 'máu mao mạch',
  INTERSTITIAL_FLUID: 'dịch kẽ', PLASMA: 'huyết tương', SERUM: 'huyết thanh', WHOLE_BLOOD: 'máu toàn phần', TEARS: 'nước mắt',
  ORAL: 'miệng', ARMPIT: 'nách', EAR: 'tai', FOREHEAD: 'trán', RECTAL: 'hậu môn', WRIST: 'cổ tay', FINGER: 'ngón tay',
  TEMPORAL_ARTERY: 'động mạch thái dương', VAGINAL: 'âm đạo', TOE: 'ngón chân', BODY: 'cơ thể',
}
export const detailValue = (value: string) => DETAIL_VALUES[value] ?? value.toLowerCase().replace(/_/g, ' ')
const EXERCISE_LABELS: Record<string, string> = {
  RUNNING: 'Chạy bộ', TREADMILL_RUNNING: 'Chạy máy', WALKING: 'Đi bộ', HIKING: 'Leo núi', BIKING: 'Đạp xe',
  CYCLING: 'Đạp xe', STATIONARY_BIKING: 'Xe đạp tập', SWIMMING: 'Bơi', POOL_SWIMMING: 'Bơi hồ', OPEN_WATER_SWIMMING: 'Bơi ngoài trời',
  WEIGHTLIFTING: 'Tập tạ', STRENGTH_TRAINING: 'Tập sức mạnh', YOGA: 'Yoga', PILATES: 'Pilates', ELLIPTICAL: 'Máy elip',
  ROWING: 'Chèo thuyền', HIIT: 'HIIT', DANCING: 'Nhảy', TENNIS: 'Quần vợt', BADMINTON: 'Cầu lông', FOOTBALL: 'Bóng đá',
  SOCCER: 'Bóng đá', BASKETBALL: 'Bóng rổ', OTHER: 'Khác',
}
export function exerciseLabel(type: string | null | undefined): string {
  if (!type) return 'Vận động'
  return EXERCISE_LABELS[type] ?? type.toLowerCase().replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())
}
export const UNIT_LABELS: Record<string, string> = {
  WEIGHT_UNIT_KILOGRAMS: 'kg', WEIGHT_UNIT_POUNDS: 'lb', WEIGHT_UNIT_STONE: 'stone', HEIGHT_UNIT_CENTIMETERS: 'cm',
  HEIGHT_UNIT_INCHES: 'inch', DISTANCE_UNIT_KILOMETERS: 'km', DISTANCE_UNIT_MILES: 'dặm',
}
export const SCOPE_LABELS: Record<string, string> = {
  activity_and_fitness: 'Vận động', health_metrics_and_measurements: 'Chỉ số cơ thể & tim mạch', sleep: 'Giấc ngủ',
  profile: 'Hồ sơ', settings: 'Cài đặt', nutrition: 'Nước uống',
}
export const scopeKey = (scope: string) => scope.split('googlehealth.')[1]?.replace('.readonly', '') ?? scope
