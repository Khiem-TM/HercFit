import type { OnboardingPayload, UserProfile } from '../../types/api'

export const goalChoices = [
  { id: 'fat_loss', title: 'Giảm mỡ', description: 'Theo dõi cân nặng và xây dựng thói quen ăn uống.' },
  { id: 'muscle_gain', title: 'Tăng cơ', description: 'Ghi nhận tập luyện và tiến bộ của cơ thể.' },
  { id: 'maintenance', title: 'Giữ cân', description: 'Duy trì nhịp vận động và dinh dưỡng ổn định.' },
  { id: 'fitness', title: 'Khỏe hơn mỗi ngày', description: 'Bắt đầu từ những thay đổi nhỏ, đều đặn.' },
] as const
export const activityChoices = [
  { value: 'sedentary', label: 'Chủ yếu ngồi, ít vận động' },
  { value: 'light', label: 'Vận động nhẹ' },
  { value: 'moderate', label: 'Vận động vừa phải' },
  { value: 'active', label: 'Vận động thường xuyên' },
] as const
export const sexChoices = [
  { value: 'FEMALE', label: 'Nữ' },
  { value: 'MALE', label: 'Nam' },
] as const
// Plausible human ranges; the backend rejects values outside them as well.
export const MEASUREMENT_LIMITS = {
  weight: { min: 20, max: 400 },
  height: { min: 50, max: 260 },
  bodyFat: { min: 2, max: 75 },
  muscleMass: { min: 1, max: 200 },
} as const
export interface OnboardingForm {
  fullname: string; nickname: string; age: string; sex: string; activity: string; notes: string
  metricsEnabled: boolean; weight: string; height: string; bodyFat: string; muscleMass: string
  goalEnabled: boolean; goalType: string; goalTitle: string; startDate: string; targetDate: string; targetWeight: string
  confirmed: boolean
}
export type FieldErrors = Partial<Record<keyof OnboardingForm, string>>
export function todayInVietnam(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Ho_Chi_Minh', year:'numeric',month:'2-digit',day:'2-digit' }).formatToParts(now)
  const get = (type: string) => parts.find(p => p.type === type)!.value
  return `${get('year')}-${get('month')}-${get('day')}`
}
function object(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
export function initialForm(user: UserProfile, hasGoal = false): OnboardingForm {
  const level = object(user.personal_info.activity).level
  const notes = object(user.personal_info.preferences).notes
  return { fullname:user.fullname, nickname:user.nick_name ?? '', age:user.age?.toString() ?? '', sex:user.sex ?? '',
    activity:activityChoices.some(c => c.value === level) ? String(level) : '', notes:typeof notes === 'string' ? notes : '',
    metricsEnabled:true,weight:'',height:'',bodyFat:'',muscleMass:'',goalEnabled:!hasGoal,
    goalType:'',goalTitle:'',startDate:todayInVietnam(),targetDate:'',targetWeight:'',confirmed:false }
}
function measurement(value: string, limits: { min: number; max: number }, decimalsAllowed = 3) {
  if (!/^\d+(?:\.\d+)?$/.test(value.trim())) return false
  const n = Number(value)
  const decimals = value.trim().split('.')[1]?.replace(/0+$/, '').length ?? 0
  return Number.isFinite(n) && n >= limits.min && n <= limits.max && decimals <= decimalsAllowed
}
function validDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000')) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0,10) === value
}
export function validateStep(form: OnboardingForm, step: number): FieldErrors {
  const errors: FieldErrors = {}
  if (step === 0) {
    if (!form.fullname.trim() || form.fullname.trim().length > 255) errors.fullname = 'Nhập họ tên từ 1 đến 255 ký tự.'
    if (form.nickname.length > 100) errors.nickname = 'Biệt danh tối đa 100 ký tự.'
    if (form.age && (!/^\d+$/.test(form.age) || Number(form.age) < 1 || Number(form.age) > 120)) errors.age = 'Tuổi phải là số nguyên từ 1 đến 120.'
    if (form.activity && !activityChoices.some(c => c.value === form.activity)) errors.activity = 'Chọn mức vận động trong danh sách.'
    if (form.sex && !sexChoices.some(c => c.value === form.sex)) errors.sex = 'Chọn giới tính trong danh sách.'
  }
  if (step === 1 && form.metricsEnabled) {
    const { weight, height, bodyFat, muscleMass } = MEASUREMENT_LIMITS
    if (!measurement(form.weight, weight)) errors.weight = `Nhập cân nặng từ ${weight.min} đến ${weight.max} kg, tối đa 3 số thập phân.`
    if (form.height && !measurement(form.height, height)) errors.height = `Nhập chiều cao từ ${height.min} đến ${height.max} cm.`
    if (form.muscleMass && !measurement(form.muscleMass, muscleMass)) errors.muscleMass = `Nhập khối cơ từ ${muscleMass.min} đến ${muscleMass.max} kg.`
    if (form.bodyFat && !measurement(form.bodyFat, bodyFat, 2)) errors.bodyFat = `Tỷ lệ mỡ từ ${bodyFat.min} đến ${bodyFat.max}%, tối đa 2 số thập phân.`
  }
  if (step === 2 && form.goalEnabled) {
    if (!goalChoices.some(c => c.id === form.goalType)) errors.goalType = 'Chọn một hướng đi cho mục tiêu.'
    if (!form.goalTitle.trim() || form.goalTitle.trim().length > 255) errors.goalTitle = 'Nhập tên mục tiêu từ 1 đến 255 ký tự.'
    if (!validDate(form.startDate)) errors.startDate = 'Chọn ngày bắt đầu hợp lệ.'
    if (form.targetDate && (!validDate(form.targetDate) || form.targetDate < form.startDate)) errors.targetDate = 'Ngày mục tiêu phải từ ngày bắt đầu trở đi.'
    if (form.targetWeight && !measurement(form.targetWeight, MEASUREMENT_LIMITS.weight)) errors.targetWeight = 'Nhập cân nặng đích từ 20 đến 400 kg.'
  }
  if (step === 3 && !form.confirmed) errors.confirmed = 'Vui lòng xác nhận thông tin trước khi lưu.'
  return errors
}
export function buildOnboardingPayload(form: OnboardingForm, user: UserProfile): OnboardingPayload {
  const errors = [0,1,2,3].flatMap(step => Object.values(validateStep(form,step)))
  if (errors.length) throw new Error(errors[0])
  const payload: OnboardingPayload = { fullname:form.fullname.trim(), nick_name:form.nickname.trim() || null }
  if (form.age) payload.age = Number(form.age)
  else if (user.age !== null) payload.age = null
  if (form.sex === 'MALE' || form.sex === 'FEMALE') payload.sex = form.sex
  else if (user.sex) payload.sex = null
  const info: Record<string, unknown> = {}
  if (form.activity) info.activity = { ...object(user.personal_info.activity), level:form.activity }
  else if (object(user.personal_info.activity).level !== undefined) {
    const activity = { ...object(user.personal_info.activity) }; delete activity.level; info.activity = activity
  }
  if (form.notes.trim() || object(user.personal_info.preferences).notes !== undefined) info.preferences = { ...object(user.personal_info.preferences), notes:form.notes.trim() }
  if (Object.keys(info).length) payload.personal_info = info
  if (form.metricsEnabled) {
    payload.body_metric = { weight_kg:Number(form.weight) }
    if (form.height) payload.body_metric.height_cm = Number(form.height)
    if (form.bodyFat) payload.body_metric.body_fat_pct = Number(form.bodyFat)
    if (form.muscleMass) payload.body_metric.muscle_mass_kg = Number(form.muscleMass)
  }
  if (form.goalEnabled) {
    payload.goal = { title:form.goalTitle.trim(), start_date:form.startDate, goal_types:[form.goalType], targets:{} }
    if (form.targetDate) payload.goal.target_date = form.targetDate
    if (form.targetWeight) {
      payload.goal.targets.weight_kg = { unit:'kg',operator:'eq',value:Number(form.targetWeight) }
      if (form.metricsEnabled) payload.goal.targets.weight_kg.baseline = Number(form.weight)
    }
  }
  return payload
}
export function authenticatedDestination(path: string, completed: boolean): string {
  if (!completed) return '/onboarding'
  return path.startsWith('/chat') ? path : '/chat'
}
