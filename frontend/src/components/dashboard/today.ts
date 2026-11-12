/**
 * Mô hình hiển thị của tab "Hôm nay": hàm thuần từ dữ liệu backend, không tính lại số sức khoẻ nào
 * (điểm, trạng thái, mức nền đều do backend tính). Thiếu dữ liệu thì nói là thiếu, không thành 0.
 */
import type { BodyMetricRead, DailyAssessment, HealthConnection, MetricReading, NutritionTargets } from '@/types/api'
import type { PlanEntry, TrainingPlan } from '@/features/plan/model'
import { num } from '@/components/knowledge/health/healthFormat'
import { ddmm, hoursMinutes, longDate, monday, shift, TZ, vn, WEEKDAY_LONG, WEEKDAY_SHORT, weekday } from './format'
import type { MealRow } from './useDashboardData'

/* ---------------------------------------------------------------- sẵn sàng */

export type ReadinessKind = 'ready' | 'reduce' | 'none'

export interface ReadinessView {
  kind: ReadinessKind
  title: string
  explain: string
  action: string
  confidence: string | null
  signals: { name: string; state: string }[]
  warn: string | null
  canDetail: boolean
  connect: boolean
  score: number | null
}

const TITLES: Record<string, string> = {
  ready: 'Sẵn sàng tập luyện', steady: 'Ổn định, tập theo kế hoạch', ease_off: 'Nên giảm cường độ',
  recover: 'Ưu tiên hồi phục', needs_review: 'Cần xem lại dữ liệu', insufficient_data: 'Chưa đủ dữ liệu để đánh giá',
}
const CONFIDENCE: Record<string, string> = { high: 'Độ tin cậy cao', medium: 'Độ tin cậy vừa', low: 'Độ tin cậy thấp' }
const SIGNALS: [string, string][] = [['sleep_minutes', 'Giấc ngủ'], ['resting_hr_bpm', 'Nhịp tim nghỉ'], ['hrv_ms', 'HRV']]

export function signalState(reading: MetricReading | undefined): string {
  if (!reading || reading.value == null) return 'Chưa có hôm nay'
  if (reading.baseline == null || reading.z == null) return 'Chưa có mức nền'
  if (Math.abs(reading.z) < 1) return 'Gần mức nền'
  return reading.z > 0 ? 'Cao hơn mức nền' : 'Thấp hơn mức nền'
}

export function readinessView(assessment: DailyAssessment | null, connection: HealthConnection | null): ReadinessView {
  const connected = connection?.status === 'ACTIVE' || connection?.status === 'NEEDS_REAUTH'
  if (!assessment || (!connected && assessment.state === 'insufficient_data')) {
    return {
      kind: 'none', title: 'Chưa có dữ liệu phục hồi', score: null,
      explain: 'Chưa kết nối thiết bị nên chưa có giấc ngủ, nhịp tim nghỉ và HRV.',
      action: 'Kết nối Google Health để nhận đánh giá sẵn sàng mỗi ngày. Lịch tập và bữa ăn đã ghi vẫn hiển thị bình thường.',
      confidence: null, signals: [], warn: null, canDetail: false, connect: true,
    }
  }
  const state = assessment.state
  const kind: ReadinessKind = state === 'ready' || state === 'steady' ? 'ready'
    : state === 'ease_off' || state === 'recover' ? 'reduce' : 'none'
  const strong = assessment.reasons.filter(reason => reason.kind !== 'data').map(reason => reason.text)
  const dataNote = assessment.reasons.find(reason => reason.kind === 'data')?.text ?? null
  const by = new Map(assessment.metrics.map(reading => [reading.metric, reading]))
  return {
    kind,
    title: TITLES[state] ?? assessment.label,
    explain: strong.length ? `${strong.slice(0, 2).join('. ')}.` : (dataNote ? `${dataNote}.` : assessment.summary),
    action: assessment.recommendations[0]?.text ?? '',
    confidence: state === 'insufficient_data' ? null : CONFIDENCE[assessment.confidence] ?? null,
    signals: state === 'insufficient_data' ? [] : SIGNALS.map(([metric, name]) => ({ name, state: signalState(by.get(metric)) })),
    warn: state === 'insufficient_data' ? dataNote : (assessment.reasons.find(reason => reason.code === 'NO_DATA')?.text ?? null),
    canDetail: true,
    connect: !connected,
    score: assessment.score ?? null,
  }
}

/** Dòng chỉ số ở trang "Cơ sở đánh giá": giá trị và mức nền do backend tính. */
export function metricRows(assessment: DailyAssessment) {
  const value = (reading: MetricReading, raw: number | null | undefined) => raw == null ? null
    : reading.unit === 'min' ? hoursMinutes(raw) : `${vn(raw, reading.unit === 'ms' ? 0 : 0)} ${reading.unit}`
  return SIGNALS.map(([metric, label]) => {
    const reading = assessment.metrics.find(item => item.metric === metric)
    if (!reading) return { label, context: 'Chưa có dữ liệu', value: 'Không có dữ liệu', base: 'Chưa có mức nền' }
    const shown = value(reading, reading.value)
    return {
      label: metric === 'sleep_minutes' ? 'Thời lượng ngủ gần nhất' : label,
      context: reading.measured_on ? (metric === 'sleep_minutes' ? `Đêm kết thúc ${ddmm(reading.measured_on)}` : longDate(reading.measured_on)) : 'Hôm nay',
      value: shown ?? 'Không có dữ liệu',
      base: reading.baseline != null
        ? `Mức nền ${value(reading, reading.baseline)} · ${reading.baseline_n} ngày có dữ liệu`
        : `Chưa có mức nền · ${reading.baseline_n} ngày có dữ liệu`,
    }
  })
}

/* ---------------------------------------------------------------- lịch tập */

export type DayState = 'done' | 'missed' | 'today' | 'up' | 'rest'

export function trainingEntries(plan: TrainingPlan | null, from: string, to: string): PlanEntry[] {
  return (plan?.entries ?? []).filter(entry => !entry.is_rest && entry.scheduled_date >= from && entry.scheduled_date <= to)
    .sort((a, b) => a.scheduled_date.localeCompare(b.scheduled_date))
}

export function entryState(entry: PlanEntry, today: string): Exclude<DayState, 'rest'> {
  if (entry.completed_at) return 'done'
  if (entry.scheduled_date < today) return 'missed'
  return entry.scheduled_date === today ? 'today' : 'up'
}

export interface WeekView {
  range: string
  done: number
  due: number
  total: number
  days: { label: string; glyph: string; state: DayState; sr: string }[]
}

const GLYPH: Record<DayState, string> = { done: '✓', missed: '!', today: '•', up: '', rest: '–' }
const DAY_TEXT: Record<DayState, string> = {
  done: 'Đã tập', missed: 'Chưa hoàn thành', today: 'Hôm nay, chưa ghi nhận', up: 'Sắp tới', rest: 'Nghỉ',
}

export function weekView(plan: TrainingPlan | null, today: string): WeekView {
  const first = monday(today)
  const last = shift(first, 6)
  const entries = trainingEntries(plan, first, last)
  let done = 0
  let due = 0
  const days = Array.from({ length: 7 }, (_, index) => {
    const date = shift(first, index)
    const own = entries.filter(entry => entry.scheduled_date === date)
    const states = own.map(entry => entryState(entry, today))
    done += states.filter(state => state === 'done').length
    due += states.filter(state => state === 'done' || state === 'missed').length
    const state: DayState = !own.length ? 'rest' : states.includes('missed') ? 'missed'
      : states.every(item => item === 'done') ? 'done' : states.includes('today') ? 'today' : 'up'
    return { label: WEEKDAY_SHORT[weekday(date)], glyph: GLYPH[state], state, sr: `${WEEKDAY_LONG[weekday(date)]} ${ddmm(date)}: ${DAY_TEXT[state]}` }
  })
  return { range: `${ddmm(first).slice(0, 2)}–${ddmm(last)}`, done, due, total: entries.length, days }
}

export interface WorkoutView {
  mode: 'session' | 'rest' | 'none'
  entry: PlanEntry | null
  others: PlanEntry[]
  overdue: PlanEntry | null
  next: PlanEntry | null
  done: boolean
}

export function workoutView(plan: TrainingPlan | null, today: string): WorkoutView {
  if (!plan) return { mode: 'none', entry: null, others: [], overdue: null, next: null, done: false }
  const todays = trainingEntries(plan, today, today)
  const pending = todays.filter(entry => !entry.completed_at)
  const entry = pending[0] ?? todays[0] ?? null
  const overdue = trainingEntries(plan, monday(today), shift(today, -1)).filter(item => !item.completed_at).at(-1) ?? null
  const next = trainingEntries(plan, shift(today, 1), plan.end_date)[0] ?? null
  return {
    mode: entry ? 'session' : 'rest', entry, others: todays.filter(item => item !== entry), overdue, next,
    done: !!entry && todays.every(item => item.completed_at),
  }
}

/** Mô tả ngắn một bài trong lịch: "Sức mạnh · 4 hiệp × 8–12 lần · 50 kg". */
export function exerciseLine(item: Record<string, any>): string {
  const p = item.prescription || {}
  if (p.kind === 'STRENGTH') {
    const sets = (p.sets || []) as Record<string, any>[]
    const parts = sets.map(set => {
      const reps = set.reps_max && set.reps_max !== set.reps_min ? `${set.reps_min}–${set.reps_max}` : set.reps_min
      const load = set.load?.mode === 'KG' ? ` · ${vn(set.load.value, 1)} kg` : ''
      const hold = set.duration_seconds ? `giữ ${set.duration_seconds} giây` : `${reps ?? '?'} lần`
      return `${set.count ?? 1} hiệp × ${hold}${load}`
    })
    return ['Sức mạnh', ...parts].join(' · ')
  }
  if (p.kind === 'ENDURANCE') {
    const seconds = (p.steps || []).reduce((sum: number, step: Record<string, any>) => sum + (step.duration_seconds || 0) * (step.repeat || 1), 0)
    return ['Sức bền', seconds ? `${Math.round(seconds / 60)} phút` : null].filter(Boolean).join(' · ')
  }
  if (p.kind === 'SPORT') return ['Thể thao', p.duration_seconds ? `${Math.round(p.duration_seconds / 60)} phút` : null].filter(Boolean).join(' · ')
  return ''
}

export function exerciseKind(item: Record<string, any>): string {
  return ({ STRENGTH: 'Sức mạnh', ENDURANCE: 'Sức bền', SPORT: 'Thể thao' } as Record<string, string>)[item.prescription?.kind] ?? 'Bài tập'
}

export function exerciseName(item: Record<string, any>): string {
  const snapshot = item.exercise_snapshot || {}
  return String(snapshot.name_vi || snapshot.name || snapshot.name_en || 'Bài tập')
}

/* ---------------------------------------------------------------- dinh dưỡng */

export interface NutritionView {
  has: boolean
  meals: number
  energy: number
  target: number | null
  remaining: number | null
  protein: number
  proteinTarget: number | null
  missing: number
  missingProfile: string[]
  dots: boolean[]
}

const MISSING: Record<string, string> = { weight_kg: 'cân nặng', height_cm: 'chiều cao', age: 'tuổi' }

export function nutritionView(targets: NutritionTargets | null): NutritionView {
  const today = targets?.today
  const target = targets?.status === 'ok' ? num(targets.target_kcal) : null
  const energy = num(today?.energy_kcal) ?? 0
  const filled = target ? Math.min(160, Math.round((energy / target) * 160)) : 0
  return {
    has: (today?.meal_count ?? 0) > 0,
    meals: today?.meal_count ?? 0,
    energy,
    target,
    remaining: target != null ? target - energy : null,
    protein: num(today?.protein_g) ?? 0,
    proteinTarget: num(targets?.macros?.protein_g),
    missing: today?.missing_values ?? 0,
    missingProfile: (targets?.missing ?? []).map(code => MISSING[code] ?? code),
    dots: Array.from({ length: 160 }, (_, index) => index < filled),
  }
}

/* ---------------------------------------------------------------- hồ sơ */

const CIRCUMFERENCE = ['chest_cm', 'waist_cm', 'hip_cm'] as const

/** Số đo vòng mới nhất (mỗi vòng có thể từ một lần đo khác nhau) và lần đo mỡ gần nhất. */
export function latestMeasures(metrics: BodyMetricRead[]) {
  const sorted = [...metrics].sort((a, b) => b.recorded_at.localeCompare(a.recorded_at))
  const pick = (field: (typeof CIRCUMFERENCE)[number] | 'body_fat_pct') => {
    const found = sorted.find(metric => num(metric[field] as number | string | null) != null)
    return found ? { value: num(found[field] as number | string | null) as number, at: found.recorded_at } : null
  }
  return { chest: pick('chest_cm'), waist: pick('waist_cm'), hip: pick('hip_cm'), fat: pick('body_fat_pct') }
}

/* ---------------------------------------------------------------- ghi nhanh */

/** Bữa ghi lại được khi mọi món còn bản ghi catalog (món đã bị xoá khỏi danh mục thì không có food_id). */
export function canRepeatMeal(meal: MealRow): boolean {
  return meal.items.length > 0 && meal.items.every(item => Boolean(item.food_id))
}

/** POST /api/meals ghi lại đúng các món, lượng và đơn vị của một bữa đã có, vào thời điểm bấm. */
export function repeatMealPayload(meal: MealRow, now: Date) {
  return {
    name: meal.name,
    timezone: TZ,
    consumed_at: now.toISOString(),
    items: meal.items.map(item => ({ food_id: item.food_id, quantity: Number(item.quantity), unit: item.unit, note: item.note })),
  }
}
