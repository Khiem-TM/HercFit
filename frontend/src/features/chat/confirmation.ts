/** Hàm hỗ trợ trình bày cho thẻ xác nhận. Giá trị lấy từ kết quả chạy thử của server (display). */

/** Khung thẻ: một kết quả chạy thử của server được vẽ bằng thẻ riêng của nó, hoặc các trường có nhãn của payload. */
export type CardKind = 'meal' | 'training' | 'plan' | 'catalog' | 'sport' | 'fields'
export type MediaKind = 'foods' | 'meals' | 'exercises' | 'trainings'
type Row = Record<string, any>

const TOOL_KIND: Record<string, CardKind> = {
  create_meals: 'meal',
  create_trainings: 'training',
  create_training_plans: 'plan',
  update_training_plans: 'plan',
  log_sport_session: 'sport',
  create_foods: 'catalog',
  finalize_foods: 'catalog',
  create_exercises: 'catalog',
  finalize_exercises: 'catalog',
}

/** Bản ghi đã lưu nào mà một lần xác nhận có thể gắn ảnh Cloudinary vào. */
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
  update_metrics: 'Sửa số đo cơ thể',
  delete_metrics: 'Xoá số đo cơ thể',
  create_goals: 'Thiết lập mục tiêu',
  update_goals: 'Sửa mục tiêu',
  delete_goals: 'Xoá mục tiêu',
  complete_goal: 'Hoàn thành mục tiêu',
  cancel_goal: 'Huỷ mục tiêu',
  update_profile: 'Cập nhật hồ sơ',
  merge_personal_info: 'Cập nhật thông tin cá nhân',
  onboard: 'Lưu hồ sơ ban đầu',
  update_training_profile: 'Cập nhật hồ sơ vận động viên',
  log_sport_session: 'Ghi buổi thể thao',
  update_sport_session: 'Sửa buổi thể thao',
  delete_sport_session: 'Xoá buổi thể thao',
  log_water: 'Ghi nước uống',
  delete_water: 'Xoá lần uống nước',
  log_sleep: 'Ghi giấc ngủ',
  delete_sleep: 'Xoá giấc ngủ ghi tay',
}

/** Một lệnh ghi không có chạy thử làm gì, được nói trên thẻ của nó. */
export const ACTION_NOTES: Record<string, string> = {
  update_meals: 'Bữa ăn được lưu thành bản mới; bản cũ vẫn có trong lịch sử.',
  delete_meals: 'Bữa ăn sẽ bị xoá khỏi nhật ký.',
  update_trainings: 'Buổi tập được lưu thành bản mới; bản cũ vẫn có trong lịch sử.',
  delete_trainings: 'Buổi tập sẽ bị xoá khỏi nhật ký.',
  update_metrics: 'Số đo được lưu thành bản mới.',
  delete_metrics: 'Số đo sẽ bị xoá.',
  delete_goals: 'Mục tiêu sẽ bị xoá.',
  complete_goal: 'Mục tiêu sẽ được đánh dấu hoàn thành.',
  cancel_goal: 'Mục tiêu sẽ bị huỷ.',
  end_training_plan: 'Lịch tập sẽ kết thúc; các buổi đã ghi được giữ nguyên.',
  update_sport_session: 'Buổi thể thao trên Google Health được thay bằng bản mới.',
  delete_sport_session: 'Buổi thể thao sẽ bị xoá khỏi Google Health.',
  log_water: 'Ghi thẳng lên Google Health; Google giữ bản gốc.',
  delete_water: 'Lần uống nước sẽ bị xoá khỏi Google Health.',
  log_sleep: 'Ghi thẳng lên Google Health giờ đi ngủ và giờ thức dậy bạn khai; không có giai đoạn ngủ.',
  delete_sleep: 'Giấc ngủ ghi tay sẽ bị xoá khỏi Google Health.',
}

/** Tiêu đề thẻ cho lệnh ghi catalog; bản ghi được dùng lại không phải mục catalog mới. */
export function catalogTitle(tool: string, display?: Row | null): string {
  if (display?.resolution === 'reuse') return display.domain === 'exercises' ? 'Dùng bài tập có sẵn' : 'Dùng món có sẵn'
  return TOOL_TITLES[tool] || tool
}

/** Hạng nguồn do sổ đăng ký nguồn của HercFit đánh giá, không bao giờ do model. */
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

/** Lý do một kết quả chạy thử không vẽ được bằng khung thẻ của nó, hoặc null; khi đó hiển thị quay về thẻ trường dữ liệu. */
export function displayError(kind: CardKind, display?: Row | null): string | null {
  if (!display || typeof display !== 'object') return 'thiếu dữ liệu xem trước'
  const list = (value: unknown) => (Array.isArray(value) ? (value as Row[]) : null)
  switch (kind) {
    case 'meal': {
      const items = list(display.items)
      if (!items?.length) return 'bữa ăn không có món'
      if (items.some(item => typeof item?.food_snapshot?.name_vi !== 'string')) return 'món ăn thiếu tên'
      return typeof display.consumed_at === 'string' ? null : 'thiếu thời điểm ăn'
    }
    case 'training': {
      const items = list(display.items)
      if (!items?.length) return 'buổi tập không có bài'
      if (items.some(item => typeof item?.exercise_snapshot?.name_vi !== 'string')) return 'bài tập thiếu tên'
      return typeof display.started_at === 'string' ? null : 'thiếu thời điểm bắt đầu'
    }
    case 'plan':
      if (!list(display.entries)) return 'lịch tập không có buổi'
      return typeof display.start_date === 'string' && typeof display.end_date === 'string' ? null : 'thiếu ngày của lịch'
    case 'catalog':
      return display.kind === 'catalog_candidate' && typeof display.record?.name_vi === 'string' ? null : 'bản ghi catalog thiếu tên'
    case 'sport':
      // POST /api/v2/health/records/exercise:preview: data point sẽ gửi lên Google + giá trị HercFit đã suy ra.
      if (display.data_type !== 'exercise' || !display.derived || typeof display.derived !== 'object') return 'thiếu bản xem trước buổi tập'
      return typeof display.data_point?.exercise?.interval?.startTime === 'string' ? null : 'thiếu thời điểm bắt đầu'
    default:
      return null
  }
}

export function cardKind(tool: string, display?: Row | null): CardKind {
  const kind = TOOL_KIND[tool]
  return kind && !displayError(kind, display) ? kind : 'fields'
}

export interface FieldRow { label: string; value: string }

const FIELD_NAMES: Record<string, string> = {
  name: 'Tên', title: 'Tiêu đề', note: 'Ghi chú', description: 'Mô tả', timezone: 'Múi giờ',
  consumed_at: 'Thời điểm ăn', started_at: 'Bắt đầu', ended_at: 'Kết thúc', recorded_at: 'Thời điểm đo',
  start_date: 'Ngày bắt đầu', end_date: 'Ngày kết thúc', target_date: 'Hạn mục tiêu', effective_date: 'Áp dụng từ',
  weight_kg: 'Cân nặng', height_cm: 'Chiều cao', body_fat_pct: 'Tỉ lệ mỡ', muscle_mass_kg: 'Khối lượng cơ',
  goal_types: 'Loại mục tiêu', targets: 'Chỉ tiêu', items: 'Mục', entries: 'Buổi', duration_seconds: 'Thời lượng',
  session_rpe: 'RPE buổi', discipline: 'Loại buổi tập', reason: 'Lý do', level: 'Trình độ', focus: 'Trọng tâm',
  days_per_week: 'Số buổi/tuần', minutes_per_session: 'Phút mỗi buổi', equipment: 'Dụng cụ', sex: 'Giới tính',
  age: 'Tuổi', activity_level: 'Mức vận động', display_name: 'Tên hiển thị', resting_hr: 'Nhịp tim nghỉ',
  max_hr: 'Nhịp tim tối đa', threshold_pace_seconds_per_km: 'Pace ngưỡng', one_rep_maxes: '1RM',
  weight: 'Cân nặng', body_fat: 'Tỉ lệ mỡ', energy_kcal: 'Năng lượng', protein_g: 'Protein',
  amount_ml: 'Lượng nước', performance: 'Thực hiện', distance_meters: 'Quãng đường', intensity: 'Cường độ',
}
// Cùng một trường mang nghĩa khác theo lệnh ghi (nước uống không phải bữa ăn).
const TOOL_FIELD_NAMES: Record<string, Record<string, string>> = {
  log_water: { consumed_at: 'Thời điểm uống' },
  log_sleep: { started_at: 'Giờ đi ngủ', ended_at: 'Giờ thức dậy', minutes_in_bed: 'Thời gian trên giường' },
}
const FIELD_UNITS: Record<string, string> = {
  weight_kg: 'kg', height_cm: 'cm', body_fat_pct: '%', muscle_mass_kg: 'kg', energy_kcal: 'kcal', protein_g: 'g',
  resting_hr: 'bpm', max_hr: 'bpm', amount_ml: 'ml', distance_meters: 'm',
}
// Các trường định danh, phiên bản và nguồn gốc dành cho API, không dành cho người đang xác nhận.
const HIDDEN = new Set(['resource_id', 'expected_version_id', 'source_entry_id', 'data_quality', 'attestation', 'context',
  'additional_metrics', 'payload_hash'])
const isId = (key: string) => key === 'id' || key.endsWith('_id') || key.endsWith('_ids')
const OPERATORS: Record<string, string> = { eq: '=', gte: '≥', lte: '≤' }
// Các mã backend lưu, theo cách người dùng đọc chúng (loại mục tiêu là chữ thường trong API, chấp nhận mọi kiểu chữ).
const VALUE_LABELS: Record<string, Record<string, string>> = {
  goal_types: { fat_loss: 'Giảm mỡ', muscle_gain: 'Tăng cơ', maintenance: 'Duy trì', fitness: 'Khoẻ hơn' },
  discipline: { strength: 'Gym', endurance: 'Sức bền', sport: 'Thể thao', mixed: 'Kết hợp' },
  intensity: { light: 'Nhẹ', moderate: 'Vừa', vigorous: 'Mạnh' },
}
const valueLabel = (key: string, value: string) => VALUE_LABELS[key]?.[value.toLowerCase()] ?? value

function target(value: Row): string {
  const unit = value.unit ? ` ${value.unit}` : ''
  const goal = value.operator === 'range' ? `${fmt(value.min, 2)}–${fmt(value.max, 2)}${unit}`
    : `${OPERATORS[value.operator] ?? ''} ${fmt(value.value, 2)}${unit}`.trim()
  return value.baseline !== undefined && value.baseline !== null ? `${goal} (từ ${fmt(value.baseline, 2)}${unit})` : goal
}

function day(value: string): string {
  const [year, month, date] = value.split('-')
  return `${date}/${month}/${year}`
}

/** Một giá trị payload theo cách người dùng đọc: đơn vị, giờ địa phương, "Có/Không", số đếm cho danh sách bản ghi. */
export function fieldText(key: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'boolean') return value ? 'Có' : 'Không'
  if (key === 'duration_seconds') return minutes(value)
  if (key.endsWith('pace_seconds_per_km')) return `${pace(value)} /km`
  if (typeof value === 'number' || (FIELD_UNITS[key] && num(value) !== null)) return fmt(value, 2, FIELD_UNITS[key] ?? '')
  if (typeof value === 'string') {
    if (/^\d{4}-\d{2}-\d{2}T/.test(value)) return when(value) || value
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return day(value)
    return valueLabel(key, value)
  }
  if (Array.isArray(value)) {
    if (value.every(item => item === null || typeof item !== 'object')) {
      return value.filter(item => item !== null && item !== '').map(item => valueLabel(key, String(item))).join(', ')
    }
    return `${value.length} mục`
  }
  if (typeof value === 'object') {
    return Object.entries(value as Row)
      .filter(([name, item]) => !HIDDEN.has(name) && !isId(name) && item !== null && item !== undefined && item !== '')
      .map(([name, item]) => `${FIELD_NAMES[name] || name}: ${item && typeof item === 'object' && !Array.isArray(item) && 'operator' in item
        ? target(item) : fieldText(name, item)}`)
      .join(' · ')
  }
  return String(value)
}

/** Các dòng có nhãn của một lệnh ghi không có thẻ chạy thử; id và phiên bản được ẩn. */
export function fieldRows(payload?: Row | null, tool = ''): FieldRow[] {
  const names = { ...FIELD_NAMES, ...TOOL_FIELD_NAMES[tool] }
  return Object.entries(payload || {})
    .filter(([key]) => !HIDDEN.has(key) && !isId(key))
    .map(([key, value]) => ({ label: names[key] || key.replace(/_/g, ' '), value: fieldText(key, value) }))
    .filter(row => row.value)
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

/** Tỉ lệ năng lượng từ protein/carb/chất béo (4/4/9 kcal mỗi g); null khi có macro chưa biết. */
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

/** Làm phẳng các bước sức bền thành các đoạn thanh tỉ lệ (thời lượng, hoặc quãng đường ở ~6 phút/km). */
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
