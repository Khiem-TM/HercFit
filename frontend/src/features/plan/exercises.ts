/** Read shapes of the backend exercise prescriptions. Planned values are never logged results. */
export interface ExerciseSnapshot {
  name_vi?: string | null
  name?: string | null
  name_en?: string | null
  image_url?: string | null
  instructions?: string | null
  muscle_groups?: string[]
  equipment?: string[]
}
export interface StrengthSet {
  count: number
  set_type?: string
  reps_min?: number | null
  reps_max?: number | null
  hold_seconds?: number | null
  load?: { mode: 'KG' | 'PCT_1RM' | 'RPE' | 'BODYWEIGHT'; value?: number | null } | null
  rpe_target?: number | null
  rir_target?: number | null
  rest_seconds?: number | null
  tempo?: string | null
}
export interface EnduranceStep {
  step_type: 'WARMUP' | 'WORK' | 'RECOVERY' | 'COOLDOWN'
  duration_seconds?: number | null
  distance_meters?: number | null
  target?: { type: 'OPEN' | 'PACE' | 'PACE_ZONE' | 'HR_ZONE' | 'RPE'; zone?: string | null; low?: number | null; high?: number | null }
}
export interface RepeatBlock { repeat: number; steps: EnduranceStep[] }
export type Prescription =
  | { kind: 'STRENGTH'; sets: StrengthSet[]; progression?: { rule: string; increment_kg?: number | null } }
  | { kind: 'ENDURANCE'; workout_type?: string; steps: (EnduranceStep | RepeatBlock)[]; planned_distance_meters?: number; planned_duration_seconds?: number }
  | { kind: 'SPORT'; duration_seconds: number; intensity?: string; rpe_target?: number | null }
export interface PlanItem {
  id?: string
  position?: number
  exercise_id?: string | null
  exercise_snapshot: ExerciseSnapshot
  prescription: Prescription
  note?: string | null
}

const number = (n: number) => new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 }).format(n)
export function duration(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return [minutes ? `${number(minutes)} phút` : '', rest || !minutes ? `${number(rest)} giây` : ''].filter(Boolean).join(' ')
}
export const distance = (meters: number) => meters >= 1000 ? `${number(meters / 1000)} km` : `${number(meters)} m`
export const itemName = (item: PlanItem) => item.exercise_snapshot?.name_vi || item.exercise_snapshot?.name || item.exercise_snapshot?.name_en || 'Bài tập'
export const kindLabel = (kind: string) => ({ STRENGTH: 'Sức mạnh', ENDURANCE: 'Sức bền', SPORT: 'Thể thao' })[kind] || 'Bài tập'
export function loadLabel(load: StrengthSet['load']): string {
  if (!load) return ''
  if (load.mode === 'BODYWEIGHT') return 'Trọng lượng cơ thể'
  if (load.value == null) return ''
  return load.mode === 'KG' ? `${number(load.value)} kg` : load.mode === 'PCT_1RM' ? `${number(load.value)}% 1RM` : `RPE ${number(load.value)}`
}
export function setLabel(set: StrengthSet): string {
  const reps = set.reps_min == null ? '' : set.reps_max != null && set.reps_max !== set.reps_min ? `${set.reps_min}–${set.reps_max}` : String(set.reps_min)
  return [`${set.count} hiệp × ${set.hold_seconds != null ? `giữ ${duration(set.hold_seconds)}` : `${reps} lần`}`, loadLabel(set.load)].filter(Boolean).join(' · ')
}
export function setDetails(set: StrengthSet): string {
  const type = ({ WARMUP: 'Khởi động', WORKING: 'Hiệp chính', BACKOFF: 'Giảm tải', DROP: 'Drop set', FAILURE: 'Đến thất bại' } as Record<string, string>)[set.set_type || ''] || set.set_type
  return [type, set.rest_seconds != null ? `Nghỉ ${duration(set.rest_seconds)}` : '', set.tempo ? `Tempo ${set.tempo}` : '', set.rpe_target != null ? `RPE ${set.rpe_target}` : '', set.rir_target != null ? `RIR ${set.rir_target}` : ''].filter(Boolean).join(' · ')
}
export function pace(seconds: number): string {
  const rounded = Math.round(seconds)
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, '0')}`
}
export function targetLabel(target: EnduranceStep['target']): string {
  if (!target || target.type === 'OPEN') return 'Tự do'
  if (target.type === 'HR_ZONE') return `Nhịp tim ${target.zone}`
  if (target.type === 'PACE_ZONE') return `Pace zone ${target.zone}`
  const format = target.type === 'PACE' ? pace : number
  const range = target.low != null && target.high != null ? (target.low === target.high ? format(target.low) : `${format(target.low)}–${format(target.high)}`)
    : target.low != null ? `≥ ${format(target.low)}` : target.high != null ? `≤ ${format(target.high)}` : '—'
  return target.type === 'PACE' ? `${range} /km` : `RPE ${range}`
}
export const stepName = (step: EnduranceStep) => ({ WARMUP: 'Khởi động', WORK: 'Tập', RECOVERY: 'Hồi phục', COOLDOWN: 'Thả lỏng' })[step.step_type]
export const stepMeasure = (step: EnduranceStep) => step.duration_seconds != null ? duration(step.duration_seconds) : step.distance_meters != null ? distance(step.distance_meters) : ''
export function flatSteps(p: Extract<Prescription, { kind: 'ENDURANCE' }>): EnduranceStep[] {
  return p.steps.flatMap(step => 'steps' in step ? Array.from({ length: step.repeat }, () => step.steps).flat() : [step])
}
export function prescriptionSummary(p: Prescription): string {
  if (p.kind === 'STRENGTH') return p.sets.map(setLabel).join(' · ')
  if (p.kind === 'SPORT') return duration(p.duration_seconds)
  const steps = flatSteps(p)
  const seconds = steps.reduce((sum, step) => sum + (step.duration_seconds || 0), 0)
  const meters = steps.reduce((sum, step) => sum + (step.distance_meters || 0), 0)
  // Mixed workouts contain independent distance and time blocks; never imply a total duration.
  return [seconds ? duration(seconds) : '', meters ? distance(meters) : ''].filter(Boolean).join(' + ')
}
export function sessionMeasure(items: PlanItem[]): string {
  if (!items.length || items.some(item => item.prescription.kind === 'STRENGTH')) return ''
  const steps = items.flatMap<Pick<EnduranceStep, 'duration_seconds' | 'distance_meters'>>(({ prescription: p }) => p.kind === 'ENDURANCE' ? flatSteps(p) : p.kind === 'SPORT' ? [{ duration_seconds: p.duration_seconds, distance_meters: null }] : [])
  if (steps.every(step => step.duration_seconds != null)) return duration(steps.reduce((sum, step) => sum + (step.duration_seconds || 0), 0))
  if (steps.every(step => step.distance_meters != null)) return distance(steps.reduce((sum, step) => sum + (step.distance_meters || 0), 0))
  return ''
}
