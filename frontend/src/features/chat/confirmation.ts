/** Presentation helpers for confirmation cards. Values come from the server dry-run (display). */

export type CardKind = 'meal' | 'training' | 'plan' | 'catalog' | 'generic'
export type MediaKind = 'foods' | 'meals' | 'exercises' | 'trainings'
type Row = Record<string, any>

const TOOL_KIND: Record<string, CardKind> = {
  create_meals: 'meal',
  create_trainings: 'training',
  create_training_plans: 'plan',
  create_foods: 'catalog',
  finalize_foods: 'catalog',
  create_exercises: 'catalog',
  finalize_exercises: 'catalog',
}

/** Which saved record a confirmation can attach a Cloudinary image to. */
export const MEDIA_TARGET: Record<string, MediaKind> = {
  create_meals: 'meals',
  create_trainings: 'trainings',
  create_foods: 'foods',
  finalize_foods: 'foods',
  create_exercises: 'exercises',
  finalize_exercises: 'exercises',
}

export const TOOL_TITLES: Record<string, string> = {
  create_meals: 'Ghi bữa ăn',
  update_meals: 'Sửa bữa ăn',
  delete_meals: 'Xoá bữa ăn',
  create_trainings: 'Ghi buổi tập',
  update_trainings: 'Sửa buổi tập',
  delete_trainings: 'Xoá buổi tập',
  create_training_plans: 'Tạo lịch tập',
  update_training_plans: 'Thay lịch tập',
  end_training_plan: 'Kết thúc lịch tập',
  create_foods: 'Thêm món vào catalog của bạn',
  finalize_foods: 'Thêm món vào catalog của bạn',
  create_exercises: 'Thêm bài tập vào catalog của bạn',
  finalize_exercises: 'Thêm bài tập vào catalog của bạn',
  create_metrics: 'Ghi số đo cơ thể',
  create_goals: 'Thiết lập mục tiêu',
  update_training_profile: 'Cập nhật hồ sơ vận động viên',
}

/** Card title for a catalog write; a reused record is not a new catalog entry. */
export function catalogTitle(tool: string, display?: Row | null): string {
  if (display?.resolution === 'reuse') return display.domain === 'exercises' ? 'Dùng bài tập có sẵn' : 'Dùng món có sẵn'
  return TOOL_TITLES[tool] || tool
}

/** Source tiers are rated by HercFit's source registry, never by the model. */
export const AUTHORITY: Record<string, string> = {
  primary: 'Chính thống', professional: 'Chuyên môn', secondary: 'Tham khảo', unknown: 'Chưa xếp hạng',
}

const FIELD_LABELS: Record<string, string> = {
  energy_kcal: 'năng lượng', protein_g: 'protein', carbohydrate_g: 'carb', fat_g: 'fat', fiber_g: 'chất xơ',
  serving_size: 'khẩu phần', portion_weight_g: 'khối lượng suất', portions: 'khẩu phần hộ gia đình',
  nutrition_information: 'vi chất', muscle_groups: 'nhóm cơ', equipment: 'dụng cụ', instructions: 'hướng dẫn',
  'configuration.category': 'loại bài (đa khớp/đơn khớp)', 'configuration.equipment_type': 'loại dụng cụ',
  'configuration.secondary_muscles': 'cơ phụ', 'configuration.unilateral': 'tập một bên',
  'configuration.movement_pattern': 'kiểu chuyển động', 'configuration.activity': 'loại hoạt động',
  'configuration.environment': 'môi trường', 'configuration.terrain': 'địa hình', 'configuration.default_met': 'MET',
}

/** "MET, nhóm cơ" for fields research left empty because no source supported them. */
export function unverifiedText(fields: unknown): string {
  if (!Array.isArray(fields)) return ''
  return [...new Set(fields.map(field => FIELD_LABELS[field] || field))].join(', ')
}

export function cardKind(tool: string, display?: Row | null): CardKind {
  const kind = TOOL_KIND[tool]
  if (!kind || !display) return 'generic'
  if (kind === 'catalog' && display.kind !== 'catalog_candidate') return 'generic'
  return kind
}

export function num(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const vi = (digits = 0) => new Intl.NumberFormat('vi-VN', { maximumFractionDigits: digits })

export function fmt(value: unknown, digits = 0, unit = ''): string {
  const parsed = num(value)
  return parsed === null ? 'chưa rõ' : `${vi(digits).format(parsed)}${unit ? ` ${unit}` : ''}`
}

/** 330 s/km -> "5:30" */
export function pace(seconds: unknown): string {
  const value = num(seconds)
  if (value === null) return '—'
  const total = Math.round(value)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

/** 2822 -> "47:02", 4500 -> "1:15:00" */
export function clock(seconds: unknown): string {
  const value = num(seconds)
  if (value === null) return '—'
  const total = Math.round(value)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = String(total % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

export function minutes(seconds: unknown): string {
  const value = num(seconds)
  return value === null ? '—' : `${Math.round(value / 60)} phút`
}

export function when(iso: unknown, timezone = 'Asia/Ho_Chi_Minh'): string {
  if (typeof iso !== 'string') return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('vi-VN', {
    timeZone: timezone, weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(date)
}

export function shortDate(value: unknown): { dow: string; day: string } {
  if (typeof value !== 'string') return { dow: '', day: '' }
  const date = new Date(`${value}T00:00:00`)
  return {
    dow: new Intl.DateTimeFormat('vi-VN', { weekday: 'short' }).format(date),
    day: new Intl.DateTimeFormat('vi-VN', { day: '2-digit', month: '2-digit' }).format(date),
  }
}

const UNIT: Record<string, string> = { G: 'g', ML: 'ml', SERVING: 'khẩu phần' }
export function portion(item: Row): string {
  const quantity = fmt(item.quantity, 2)
  return `${quantity} ${UNIT[item.unit] || item.unit || ''}`.trim()
}

/** Share of energy from protein/carb/fat (4/4/9 kcal per g); null when any macro is unknown. */
export function macroShare(record: Row): { protein: number; carb: number; fat: number } | null {
  const p = num(record.protein_g)
  const c = num(record.carbohydrate_g)
  const f = num(record.fat_g)
  if (p === null || c === null || f === null) return null
  const total = p * 4 + c * 4 + f * 9
  if (!total) return null
  return { protein: (p * 4 * 100) / total, carb: (c * 4 * 100) / total, fat: (f * 9 * 100) / total }
}

export const SET_TYPE: Record<string, string> = {
  WARMUP: 'Khởi động', WORKING: 'Set chính', BACKOFF: 'Back-off', DROP: 'Drop set', FAILURE: 'Đến kiệt sức',
}
export const WORKOUT: Record<string, string> = {
  EASY: 'Chạy nhẹ', RECOVERY: 'Hồi phục', LONG: 'Chạy dài', TEMPO: 'Tempo', THRESHOLD: 'Ngưỡng',
  INTERVAL: 'Interval', FARTLEK: 'Fartlek', HILL: 'Chạy dốc', PROGRESSION: 'Tăng tốc dần', RACE: 'Thi đấu / chạy thử',
  WALK_RUN: 'Chạy xen đi bộ', OTHER: 'Khác',
}
export const DISCIPLINE: Record<string, string> = {
  STRENGTH: 'Gym', ENDURANCE: 'Sức bền', SPORT: 'Thể thao', MIXED: 'Kết hợp',
}
export const INTENSITY: Record<string, string> = { LIGHT: 'Nhẹ', MODERATE: 'Vừa', VIGOROUS: 'Mạnh' }

export function calorieSource(estimate: Row | undefined): string {
  if (!estimate || num(estimate.kcal) === null) return 'Chưa ước tính được calo (thiếu cân nặng).'
  const method: Record<string, string> = {
    ACSM_RUNNING: 'phương trình ACSM (chạy)', ACSM_WALKING: 'phương trình ACSM (đi bộ)',
    MET_STRENGTH: 'MET tập tạ (Compendium)', MET_SPORT: 'MET thể thao (Compendium)', MET_ENDURANCE: 'MET (Compendium)',
  }
  if (estimate.source === 'HERCFIT_ESTIMATE') return `Calo ước tính bằng ${method[estimate.method] || estimate.method}.`
  return `Calo theo ${estimate.source}${estimate.method ? ` · ${estimate.method}` : ''}.`
}

/** "4 × 8–12 @RPE 8 · nghỉ 2′" for one prescribed set group. */
export function setTarget(target: Row): string {
  const reps = target.hold_seconds
    ? `${fmt(target.hold_seconds)}″`
    : target.reps_max ? `${target.reps_min}–${target.reps_max}` : `${target.reps_min}`
  const load = target.load?.mode === 'PCT_1RM' ? ` @${fmt(target.load.value)}% 1RM`
    : target.load?.mode === 'KG' ? ` @${fmt(target.load.value, 1)} kg` : ''
  const effort = target.rpe_target ? ` @RPE ${fmt(target.rpe_target, 1)}` : target.rir_target !== undefined && target.rir_target !== null ? ` RIR ${fmt(target.rir_target)}` : ''
  const rest = target.rest_seconds ? ` · nghỉ ${Math.round(target.rest_seconds / 60 * 10) / 10}′` : ''
  return `${target.count || 1} × ${reps}${load}${effort}${rest}`
}

export interface StepBar { grow: number; tone: 'easy' | 'hard' | 'calm'; label: string }

/** Flatten endurance steps into proportional bar segments (duration, or distance at ~6 min/km). */
export function stepBars(prescription: Row): StepBar[] {
  const bars: StepBar[] = []
  const add = (step: Row) => {
    const seconds = num(step.duration_seconds) ?? (num(step.distance_meters) ?? 0) * 0.36
    const zone = step.target?.zone || ''
    const hard = step.step_type === 'WORK' && (['T', 'I', 'R', 'M', 'Z4', 'Z5'].includes(zone) || (step.target?.type === 'RPE' && (num(step.target.low) ?? 0) >= 6))
    const tone = step.step_type === 'WARMUP' || step.step_type === 'COOLDOWN' || step.step_type === 'RECOVERY' ? 'calm' : hard ? 'hard' : 'easy'
    const size = step.distance_meters ? `${fmt(num(step.distance_meters)! / 1000, 2)} km` : `${fmt(num(step.duration_seconds)! / 60, 1)}′`
    bars.push({ grow: Math.max(seconds, 1), tone, label: `${size}${zone ? ` vùng ${zone}` : ''}` })
  }
  for (const step of prescription.steps || []) {
    if (step.repeat) for (let i = 0; i < step.repeat; i++) (step.steps || []).forEach(add)
    else add(step)
  }
  return bars
}

export function stepSummary(prescription: Row): string {
  return (prescription.steps || []).map((step: Row) => {
    if (step.repeat) return `${step.repeat} × (${(step.steps || []).map((s: Row) => stepText(s)).join(', ')})`
    return stepText(step)
  }).join(' · ')
}

function stepText(step: Row): string {
  const size = step.distance_meters ? `${fmt(num(step.distance_meters)! / 1000, 2)} km` : `${fmt(num(step.duration_seconds)! / 60, 1)}′`
  const target = step.target || {}
  const goal = target.type === 'PACE_ZONE' || target.type === 'HR_ZONE' ? ` vùng ${target.zone}`
    : target.type === 'RPE' ? ` RPE ${fmt(target.low)}–${fmt(target.high)}`
    : target.type === 'PACE' ? ` pace ${pace(target.low)}–${pace(target.high)}` : ''
  return `${size}${goal}`
}
