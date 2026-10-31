/** Answer state and reply composition for the step-by-step clarification form. */
import type { Clarification, ClarifyQuestion } from '@/types/api'

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
  text: string
  skipped: boolean
  /** Sets editor groups by row id; a row without an entry uses the default group. */
  sets: Record<string, SetGroup[]>
}

export const emptyAnswer = (): Answer => ({ optionIds: [], text: '', skipped: false, sets: {} })
export const defaultGroup = (): SetGroup => ({ sets: 3, reps: 10, kg: null })
export const groupsFor = (answer: Answer, row: SetRow): SetGroup[] => answer.sets[row.id] ?? [defaultGroup()]

/** Accepts the legacy one-question payload as a one-question form. */
export function normalizeClarification(raw: unknown): Clarification | null {
  if (!raw || typeof raw !== 'object') return null
  const data = raw as Record<string, any>
  if (Array.isArray(data.questions)) return data.questions.length ? (data as Clarification) : null
  if (typeof data.question !== 'string') return null
  const { intro, ...rest } = data
  const question: ClarifyQuestion = {
    id: 'q1', label: 'Trả lời', required: true, options: [], allow_free_text: true, min_select: 1, max_select: 1,
    ...rest, question: data.question, mode: data.mode ?? 'single',
  }
  return { intro: intro ?? null, questions: [question] }
}

/** Options are answered right away; multiple, text and sets questions need an explicit "Tiếp". */
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

/** Rows of a sets question: the exercises picked (or typed) in its source questions, else its own options. */
export function setRows(form: Clarification, answers: Answer[], index: number): SetRow[] {
  const question = form.questions[index]
  const sources = (question.for_questions ?? []).map(id => form.questions.findIndex(item => item.id === id)).filter(i => i >= 0)
  if (!sources.length) return question.options.map(({ id, label, image_url }) => ({ id, label, image_url }))
  return sources.flatMap(sourceIndex => {
    const answer = answers[sourceIndex] ?? emptyAnswer()
    const typed = answer.text.trim()
    if (typed) {
      return typed.split(/[,;\n]/).map(name => name.trim()).filter(Boolean)
        .map((label, i) => ({ id: `typed-${sourceIndex}-${i}`, label }))
    }
    return form.questions[sourceIndex].options.filter(option => answer.optionIds.includes(option.id))
      .map(({ id, label, image_url }) => ({ id, label, image_url }))
  })
}

const validGroup = (group: SetGroup) => group.sets >= 1 && group.reps >= 1 && (group.kg === null || group.kg >= 0)

export function isAnswered(question: ClarifyQuestion, answer: Answer, rows: SetRow[] = []): boolean {
  if (answer.text.trim()) return true
  if (question.mode === 'sets') return rows.length > 0 && rows.every(row => groupsFor(answer, row).every(validGroup))
  if (question.mode !== 'multiple') return answer.optionIds.length > 0
  const count = answer.optionIds.length
  return count >= Math.max(1, question.min_select) && count <= question.max_select
}

// Decimal point, never a comma: groups are already separated by ", " in the sent reply. A blank load is said
// explicitly: a bare "3×12" was logged as 0 kg (an unloaded movement) and zeroed the volume.
export const formatGroup = (group: SetGroup) => `${group.sets}×${group.reps}${group.kg === null ? ' (chưa ghi tạ)' : ` @ ${group.kg}kg`}`

/** Typed text wins over picked options and edited sets. */
export function answerText(question: ClarifyQuestion, answer: Answer, rows: SetRow[] = []): string {
  const typed = answer.text.trim()
  if (typed) return typed
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
