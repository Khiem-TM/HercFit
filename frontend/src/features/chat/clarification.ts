/** Card frames of the clarification form: validation, answer state and reply composition. Nothing is typed as free text. */
import type { Clarification, ClarifyMode, ClarifyQuestion, NumberFrame, NumberUnit } from '@/types/api'

/** One line of the sets editor: `sets` sets of `reps` reps at `kg` (no external load when null). */
export interface SetGroup {
  sets: number
  reps: number
  kg: number | null
}

/** One exercise in the sets editor. */
export interface SetRow {
  id: string
  label: string
  image_url?: string | null
}

export interface Answer {
  optionIds: string[]
  /** Number frames: the value picked, null until one is. */
  value: number | null
  skipped: boolean
  /** Sets editor groups by row id; a row without an entry uses the default group. */
  sets: Record<string, SetGroup[]>
}

export const emptyAnswer = (): Answer => ({ optionIds: [], value: null, skipped: false, sets: {} })
/** A number frame starts at its default (shown preselected); every other frame starts empty. */
export const initialAnswer = (question: ClarifyQuestion): Answer =>
  ({ ...emptyAnswer(), value: question.mode === 'number' ? question.number?.default ?? null : null })

export const SET_LIMITS = { sets: [1, 20], reps: [1, 100], kg: [0, 500] } as const
export const defaultGroup = (): SetGroup => ({ sets: 3, reps: 10, kg: null })
export const groupsFor = (answer: Answer, row: SetRow): SetGroup[] => answer.sets[row.id] ?? [defaultGroup()]

const MODES: ClarifyMode[] = ['single', 'multiple', 'quick_reply', 'number', 'sets']
/** The widest range each unit allows (the agent's NUMBER_UNITS): a frame outside it is never shown. */
export const UNIT_BOUNDS: Record<NumberUnit, [number, number]> = {
  kg: [0, 500], g: [0, 5000], ml: [0, 5000], kcal: [0, 10000], phút: [1, 1440], giờ: [0.25, 24], km: [0.1, 500],
  cm: [30, 250], '%': [0, 100], bpm: [30, 230], tuổi: [10, 100], RPE: [1, 10], bước: [0, 100000], buổi: [1, 14],
  ngày: [1, 365], tuần: [1, 52], hiệp: [1, 20], reps: [1, 100], lần: [1, 50], suất: [0.25, 20], phần: [0.25, 20],
  quả: [1, 30], ly: [0.5, 10], cốc: [0.5, 10], chai: [0.5, 10], lon: [0.5, 10], hộp: [0.5, 10], bát: [0.5, 10],
  tô: [0.5, 10], đĩa: [0.5, 10], lát: [1, 20], miếng: [1, 20], cái: [1, 20],
}

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

/** Why a number frame cannot be drawn, or null. */
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

/** Why a question is not a valid card frame (given the questions kept before it), or null. */
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
 * The valid card frames of a payload, legacy one-question payloads included; null when none is left.
 * Free-text questions of older messages, malformed frames and the questions depending on them are dropped.
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
      // A sets editor keeps only the picks that are still asked.
      for_questions: (Array.isArray(item.for_questions) ? item.for_questions : []).filter((id: string) => kept.some(q => q.id === id)),
      show_if: item.show_if ?? null,
      number: item.number ?? null,
    }
    if (kept.some(q => q.id === question.id) || frameError(question, kept)) continue
    kept.push(question)
  }
  return kept.length ? { intro: typeof data.intro === 'string' ? data.intro : null, questions: kept.slice(0, 8) } : null
}

/** Options are answered right away; multiple, number and sets questions need an explicit "Tiếp". */
export const choosesOnce = (question: ClarifyQuestion) => question.mode === 'single' || question.mode === 'quick_reply'

/** Indexes of the questions to ask, given the answers so far (a show_if question follows its trigger). */
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

/** Rows of a sets question: the exercises picked in its source questions, else its own options. */
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

/** "72.5": a decimal point, as in the sets editor (", " separates answers in the sent reply). */
export const formatNumber = (value: number) => String(Math.round(value * 1000) / 1000)
export const formatValue = (value: number, unit: string) => `${formatNumber(value)} ${unit}`

const decimalsOf = (value: number) => (String(value).split('.')[1] ?? '').length

/** The nearest multiple of the step inside the range, so 72.43 kg with a 0.1 step is 72.4 (and 0.1 + 0.2 stays 0.3). */
export function snap(frame: NumberFrame, value: number): number {
  const decimals = decimalsOf(frame.step)
  const first = Math.ceil(Number((frame.min / frame.step).toFixed(9))) * frame.step
  const last = Math.floor(Number((frame.max / frame.step).toFixed(9))) * frame.step
  const snapped = Math.min(last, Math.max(first, Math.round(value / frame.step) * frame.step))
  return Number(snapped.toFixed(decimals))
}

/** Why a sets group cannot be sent, or null. */
export function groupError(group: SetGroup): string | null {
  const [setsMin, setsMax] = SET_LIMITS.sets
  const [repsMin, repsMax] = SET_LIMITS.reps
  const [kgMin, kgMax] = SET_LIMITS.kg
  if (!Number.isInteger(group.sets) || group.sets < setsMin || group.sets > setsMax) return `Số hiệp từ ${setsMin} đến ${setsMax}`
  if (!Number.isInteger(group.reps) || group.reps < repsMin || group.reps > repsMax) return `Số reps từ ${repsMin} đến ${repsMax}`
  if (group.kg !== null && !(finite(group.kg) && group.kg >= kgMin && group.kg <= kgMax)) return `Mức tạ từ ${kgMin} đến ${kgMax} kg`
  return null
}

/** The validation message of a frame's answer, or null when it can be sent. */
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

// Decimal point, never a comma: groups are already separated by ", " in the sent reply. A blank load is said
// explicitly: a bare "3×12" was logged as 0 kg (an unloaded movement) and zeroed the volume.
export const formatGroup = (group: SetGroup) => `${group.sets}×${group.reps}${group.kg === null ? ' (chưa ghi tạ)' : ` @ ${group.kg}kg`}`

/** The text an answer sends: picked option values, "60 phút", or each exercise's sets. */
export function answerText(question: ClarifyQuestion, answer: Answer, rows: SetRow[] = []): string {
  if (question.mode === 'number') return answer.value === null ? '' : formatValue(answer.value, question.number!.unit)
  if (question.mode === 'sets') return rows.map(row => `${row.label}: ${groupsFor(answer, row).map(formatGroup).join(', ')}`).join('; ')
  return question.options.filter(option => answer.optionIds.includes(option.id)).map(option => option.value).join(', ')
}

export function composeReply(form: Clarification, answers: Answer[]): string {
  const visible = visibleIndexes(form, answers)
  const text = (index: number) => answerText(form.questions[index], answers[index] ?? emptyAnswer(), setRows(form, answers, index))
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
