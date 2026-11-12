/** Khung trên thẻ của form làm rõ: kiểm tra, trạng thái câu trả lời và soạn câu trả lời. Không gõ văn bản tự do. */
import type { Clarification, ClarifyMode, ClarifyQuestion, DateFrame, NumberFrame, NumberUnit } from '@/types/api'

/** Một dòng của trình sửa set: `sets` set, mỗi set `reps` lần với `kg` (không có tạ ngoài khi null). */
export interface SetGroup {
  sets: number
  reps: number
  kg: number | null
}

/** Một bài tập trong trình sửa set. */
export interface SetRow {
  id: string
  label: string
  image_url?: string | null
}

export interface Answer {
  optionIds: string[]
  /** Khung nhập số: giá trị đã chọn, null cho đến khi có. */
  value: number | null
  /** Khung chọn ngày: ngày ISO 'YYYY-MM-DD' đã chọn, null cho đến khi có. */
  date: string | null
  skipped: boolean
  /** Các nhóm của trình sửa set theo id dòng; dòng chưa có mục dùng nhóm mặc định. */
  sets: Record<string, SetGroup[]>
}

export const emptyAnswer = (): Answer => ({ optionIds: [], value: null, date: null, skipped: false, sets: {} })
/** Khung nhập số và chọn ngày bắt đầu ở giá trị mặc định (hiển thị sẵn đã chọn); mọi khung khác bắt đầu trống. */
export const initialAnswer = (question: ClarifyQuestion): Answer => ({
  ...emptyAnswer(),
  value: question.mode === 'number' ? question.number?.default ?? null : null,
  date: question.mode === 'date' ? question.date_frame?.default ?? null : null,
})

export const SET_LIMITS = { sets: [1, 20], reps: [1, 100], kg: [0, 500] } as const
export const defaultGroup = (): SetGroup => ({ sets: 3, reps: 10, kg: null })
export const groupsFor = (answer: Answer, row: SetRow): SetGroup[] => answer.sets[row.id] ?? [defaultGroup()]

const MODES: ClarifyMode[] = ['single', 'multiple', 'quick_reply', 'number', 'date', 'sets']
/** Khoảng rộng nhất mỗi đơn vị cho phép (NUMBER_UNITS của agent): khung nằm ngoài nó không bao giờ được hiển thị. */
export const UNIT_BOUNDS: Record<NumberUnit, [number, number]> = {
  kg: [0, 500], g: [0, 5000], ml: [0, 5000], kcal: [0, 10000], phút: [1, 1440], giờ: [0.25, 24], km: [0.1, 500],
  cm: [30, 250], '%': [0, 100], bpm: [30, 230], tuổi: [10, 100], RPE: [1, 10], bước: [0, 100000], buổi: [1, 14],
  ngày: [1, 365], tuần: [1, 52], hiệp: [1, 20], reps: [1, 100], lần: [1, 50], suất: [0.25, 20], phần: [0.25, 20],
  quả: [1, 30], ly: [0.5, 10], cốc: [0.5, 10], chai: [0.5, 10], lon: [0.5, 10], hộp: [0.5, 10], bát: [0.5, 10],
  tô: [0.5, 10], đĩa: [0.5, 10], lát: [1, 20], miếng: [1, 20], cái: [1, 20],
}

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

/** Lý do một khung nhập số không vẽ được, hoặc null. */
export function numberFrameError(frame: NumberFrame | null | undefined): string | null {
  if (!frame || typeof frame !== 'object') return 'thiếu khoảng giá trị'
  const bounds = UNIT_BOUNDS[frame.unit]
  if (!bounds) return 'đơn vị không hỗ trợ'
  if (![frame.min, frame.max, frame.step].every(finite) || !(frame.step > 0)) return 'khoảng giá trị không hợp lệ'
  if (!(bounds[0] <= frame.min && frame.min < frame.max && frame.max <= bounds[1])) return 'khoảng giá trị vượt giới hạn đơn vị'
  if (Math.ceil(Number((frame.min / frame.step).toFixed(9))) * frame.step > frame.max) return 'bước nhảy không khớp khoảng giá trị'
  if (frame.default != null && !(finite(frame.default) && frame.min <= frame.default && frame.default <= frame.max)) return 'giá trị mặc định ngoài khoảng'
  if ((frame.presets ?? []).some(value => !finite(value) || value < frame.min || value > frame.max)) return 'giá trị gợi ý ngoài khoảng'
  return null
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/
/** Ngày ISO có thật trên lịch ('2026-02-30' thì không). */
export const isDay = (value: unknown): value is string =>
  typeof value === 'string' && ISO_DAY.test(value) && new Date(`${value}T00:00:00Z`).toISOString().startsWith(value)
/** "08/12/2026" từ "2026-12-08". */
export const formatDay = (iso: string) => iso.split('-').reverse().join('/')

/** Lý do một khung chọn ngày không vẽ được, hoặc null. Ngày ISO so sánh được như chuỗi. */
export function dateFrameError(frame: DateFrame | null | undefined): string | null {
  if (!frame || typeof frame !== 'object') return 'thiếu khoảng ngày'
  if (!isDay(frame.min) || !isDay(frame.max) || frame.min > frame.max) return 'khoảng ngày không hợp lệ'
  const inside = (day: unknown) => isDay(day) && frame.min <= day && day <= frame.max
  if (frame.default != null && !inside(frame.default)) return 'ngày mặc định ngoài khoảng'
  if ((frame.presets ?? []).some(preset => !preset || typeof preset.label !== 'string' || !inside(preset.value))) {
    return 'mốc gợi ý ngoài khoảng'
  }
  return null
}

/** Lý do một câu hỏi không phải khung thẻ hợp lệ (dựa trên các câu hỏi được giữ trước nó), hoặc null. */
export function frameError(question: ClarifyQuestion, earlier: ClarifyQuestion[] = []): string | null {
  if (!question.id || !question.question) return 'thiếu nội dung'
  if (!MODES.includes(question.mode)) return 'không phải khung thẻ'
  const options = question.options
  if (options.some(option => !option || typeof option.id !== 'string' || typeof option.label !== 'string' || typeof option.value !== 'string')) {
    return 'lựa chọn không hợp lệ'
  }
  if (new Set(options.map(option => option.id)).size !== options.length) return 'lựa chọn trùng'
  switch (question.mode) {
    case 'single':
    case 'quick_reply':
      if (!options.length) return 'thiếu lựa chọn'
      break
    case 'multiple':
      if (options.length < 2 || !(question.min_select >= 1 && question.min_select <= question.max_select && question.max_select <= options.length)) {
        return 'số lựa chọn không hợp lệ'
      }
      break
    case 'number':
      if (options.length) return 'khung số không có lựa chọn'
      return numberFrameError(question.number) ?? showIfError(question, earlier)
    case 'date':
      if (options.length) return 'khung ngày không có lựa chọn'
      return dateFrameError(question.date_frame) ?? showIfError(question, earlier)
    case 'sets':
      if (!(question.for_questions ?? []).length && !options.length) return 'thiếu bài tập'
      break
  }
  return showIfError(question, earlier)
}

function showIfError(question: ClarifyQuestion, earlier: ClarifyQuestion[]): string | null {
  const rule = question.show_if
  if (!rule) return null
  const trigger = earlier.find(item => item.id === rule.question)
  const ids = Array.isArray(rule.option_ids) ? rule.option_ids : []
  return trigger && ids.length && ids.every(id => trigger.options.some(option => option.id === id)) ? null : 'điều kiện hiển thị không hợp lệ'
}

/**
 * Các khung thẻ hợp lệ của một payload, kể cả payload một câu hỏi kiểu cũ; null khi không còn khung nào.
 * Câu hỏi văn bản tự do của tin nhắn cũ, khung sai định dạng và các câu hỏi phụ thuộc vào chúng bị bỏ.
 */
export function normalizeClarification(raw: unknown): Clarification | null {
  if (!raw || typeof raw !== 'object') return null
  const data = raw as Record<string, any>
  let items: any[]
  if (Array.isArray(data.questions)) items = data.questions
  else if (typeof data.question === 'string') {
    const { intro: _intro, ...rest } = data
    items = [{ id: 'q1', label: 'Trả lời', ...rest, mode: data.mode ?? 'single' }]
  } else return null
  const kept: ClarifyQuestion[] = []
  for (const item of items) {
    if (!item || typeof item !== 'object') continue
    const question: ClarifyQuestion = {
      id: String(item.id ?? ''),
      label: String(item.label ?? ''),
      question: String(item.question ?? ''),
      mode: item.mode,
      options: Array.isArray(item.options) ? item.options : [],
      required: item.required !== false,
      min_select: Number(item.min_select ?? 1),
      max_select: Number(item.max_select ?? 1),
      // Trình sửa set chỉ giữ những lựa chọn vẫn còn được hỏi.
      for_questions: (Array.isArray(item.for_questions) ? item.for_questions : []).filter((id: string) => kept.some(q => q.id === id)),
      show_if: item.show_if ?? null,
      number: item.number ?? null,
      date_frame: item.date_frame ?? null,
    }
    if (kept.some(q => q.id === question.id) || frameError(question, kept)) continue
    kept.push(question)
  }
  return kept.length ? { intro: typeof data.intro === 'string' ? data.intro : null, questions: kept.slice(0, 8) } : null
}

/** Lựa chọn được trả lời ngay; câu hỏi chọn nhiều, số, ngày và set cần nút "Tiếp" tường minh. */
export const choosesOnce = (question: ClarifyQuestion) => question.mode === 'single' || question.mode === 'quick_reply'

/** Chỉ số các câu hỏi cần hỏi, dựa trên câu trả lời đến lúc này (câu hỏi show_if đi sau câu kích hoạt nó). */
export function visibleIndexes(form: Clarification, answers: Answer[]): number[] {
  const visible: number[] = []
  form.questions.forEach((question, index) => {
    const rule = question.show_if
    if (rule) {
      const trigger = form.questions.findIndex(item => item.id === rule.question)
      if (!visible.includes(trigger)) return
      const picked = answers[trigger]?.optionIds ?? []
      if (!rule.option_ids.some(id => picked.includes(id))) return
    }
    visible.push(index)
  })
  return visible
}

/** Các dòng của câu hỏi set: bài tập đã chọn ở các câu hỏi nguồn, nếu không thì các lựa chọn riêng của nó. */
export function setRows(form: Clarification, answers: Answer[], index: number): SetRow[] {
  const question = form.questions[index]
  const sources = (question.for_questions ?? []).map(id => form.questions.findIndex(item => item.id === id)).filter(i => i >= 0)
  if (!sources.length) return question.options.map(({ id, label, image_url }) => ({ id, label, image_url }))
  return sources.flatMap(sourceIndex => {
    const picked = (answers[sourceIndex] ?? emptyAnswer()).optionIds
    return form.questions[sourceIndex].options.filter(option => picked.includes(option.id))
      .map(({ id, label, image_url }) => ({ id, label, image_url }))
  })
}

/** "72.5": dấu chấm thập phân, như trong trình sửa set (", " ngăn cách các câu trả lời trong tin nhắn gửi đi). */
export const formatNumber = (value: number) => String(Math.round(value * 1000) / 1000)
export const formatValue = (value: number, unit: string) => `${formatNumber(value)} ${unit}`

const decimalsOf = (value: number) => (String(value).split('.')[1] ?? '').length

/** Bội số gần nhất của bước nằm trong khoảng, nên 72.43 kg với bước 0.1 là 72.4 (và 0.1 + 0.2 vẫn là 0.3). */
export function snap(frame: NumberFrame, value: number): number {
  const decimals = decimalsOf(frame.step)
  const first = Math.ceil(Number((frame.min / frame.step).toFixed(9))) * frame.step
  const last = Math.floor(Number((frame.max / frame.step).toFixed(9))) * frame.step
  const snapped = Math.min(last, Math.max(first, Math.round(value / frame.step) * frame.step))
  return Number(snapped.toFixed(decimals))
}

/** Lý do một nhóm set không gửi được, hoặc null. */
export function groupError(group: SetGroup): string | null {
  const [setsMin, setsMax] = SET_LIMITS.sets
  const [repsMin, repsMax] = SET_LIMITS.reps
  const [kgMin, kgMax] = SET_LIMITS.kg
  if (!Number.isInteger(group.sets) || group.sets < setsMin || group.sets > setsMax) return `Số hiệp từ ${setsMin} đến ${setsMax}`
  if (!Number.isInteger(group.reps) || group.reps < repsMin || group.reps > repsMax) return `Số reps từ ${repsMin} đến ${repsMax}`
  if (group.kg !== null && !(finite(group.kg) && group.kg >= kgMin && group.kg <= kgMax)) return `Mức tạ từ ${kgMin} đến ${kgMax} kg`
  return null
}

/** Thông báo kiểm tra cho câu trả lời của một khung, hoặc null khi gửi được. */
export function answerError(question: ClarifyQuestion, answer: Answer, rows: SetRow[] = []): string | null {
  switch (question.mode) {
    case 'number': {
      const frame = question.number as NumberFrame
      if (answer.value === null) return `Chọn một giá trị (${frame.unit})`
      if (!finite(answer.value) || answer.value < frame.min || answer.value > frame.max) {
        return `Giá trị từ ${formatNumber(frame.min)} đến ${formatNumber(frame.max)} ${frame.unit}`
      }
      return null
    }
    case 'date': {
      const frame = question.date_frame as DateFrame
      if (answer.date === null) return 'Chọn một ngày'
      if (!isDay(answer.date) || answer.date < frame.min || answer.date > frame.max) {
        return `Ngày từ ${formatDay(frame.min)} đến ${formatDay(frame.max)}`
      }
      return null
    }
    case 'sets':
      if (!rows.length) return 'Chưa có bài tập nào được chọn ở câu trước'
      return rows.flatMap(row => groupsFor(answer, row)).map(groupError).find(Boolean) ?? null
    case 'multiple': {
      const count = answer.optionIds.length
      const least = Math.max(1, question.min_select)
      if (count < least) return least > 1 ? `Chọn ít nhất ${least}` : 'Chọn ít nhất một lựa chọn'
      if (count > question.max_select) return `Chọn tối đa ${question.max_select}`
      return null
    }
    default:
      return answer.optionIds.length ? null : 'Chọn một lựa chọn'
  }
}

export const isAnswered = (question: ClarifyQuestion, answer: Answer, rows: SetRow[] = []) => answerError(question, answer, rows) === null

// Dấu chấm thập phân, không bao giờ là dấu phẩy: các nhóm đã được ngăn bằng ", " trong tin nhắn gửi đi. Mức tạ để trống
// được nói rõ: một chuỗi "3×12" trần từng bị ghi thành 0 kg (động tác không tạ) và làm khối lượng tập về 0.
export const formatGroup = (group: SetGroup) => `${group.sets}×${group.reps}${group.kg === null ? ' (chưa ghi tạ)' : ` @ ${group.kg}kg`}`

/**
 * Văn bản một câu trả lời: giá trị các lựa chọn đã chọn, "60 phút", một ngày, hoặc các set của từng bài tập.
 * Tin nhắn gửi đi (`message`) kèm ngày ISO để router không đọc nhầm ngày/tháng.
 */
export function answerText(question: ClarifyQuestion, answer: Answer, rows: SetRow[] = [], message = false): string {
  if (question.mode === 'number') return answer.value === null ? '' : formatValue(answer.value, question.number!.unit)
  if (question.mode === 'date') return answer.date === null ? '' : formatDay(answer.date) + (message ? ` (${answer.date})` : '')
  if (question.mode === 'sets') return rows.map(row => `${row.label}: ${groupsFor(answer, row).map(formatGroup).join(', ')}`).join('; ')
  return question.options.filter(option => answer.optionIds.includes(option.id)).map(option => option.value).join(', ')
}

export function composeReply(form: Clarification, answers: Answer[]): string {
  const visible = visibleIndexes(form, answers)
  const text = (index: number) => answerText(form.questions[index], answers[index] ?? emptyAnswer(), setRows(form, answers, index), true)
  if (visible.length === 1) return text(visible[0])
  return visible
    .map(index => {
      const question = form.questions[index]
      const answer = answers[index] ?? emptyAnswer()
      const skipped = answer.skipped || !isAnswered(question, answer, setRows(form, answers, index))
      return `${question.label}: ${skipped ? 'bỏ qua (bạn tự đề xuất)' : text(index)}`
    })
    .join('\n')
}
