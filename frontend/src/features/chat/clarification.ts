/** Answer state and reply composition for the step-by-step clarification form. */
import type { Clarification, ClarifyQuestion } from '@/types/api'

export interface Answer {
  optionIds: string[]
  text: string
  skipped: boolean
}

export const emptyAnswer = (): Answer => ({ optionIds: [], text: '', skipped: false })

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

/** Options are answered right away; multiple and text questions need an explicit "Tiếp". */
export const choosesOnce = (question: ClarifyQuestion) => question.mode === 'single' || question.mode === 'quick_reply'

export function isAnswered(question: ClarifyQuestion, answer: Answer): boolean {
  if (answer.text.trim()) return true
  if (question.mode !== 'multiple') return answer.optionIds.length > 0
  const count = answer.optionIds.length
  return count >= Math.max(1, question.min_select) && count <= question.max_select
}

/** Typed text wins over picked options. */
export function answerText(question: ClarifyQuestion, answer: Answer): string {
  const typed = answer.text.trim()
  if (typed) return typed
  return question.options.filter(option => answer.optionIds.includes(option.id)).map(option => option.value).join(', ')
}

export function composeReply(form: Clarification, answers: Answer[]): string {
  const [only] = form.questions
  if (form.questions.length === 1) return answerText(only, answers[0] ?? emptyAnswer())
  return form.questions
    .map((question, index) => {
      const answer = answers[index] ?? emptyAnswer()
      const text = answer.skipped || !isAnswered(question, answer) ? 'bỏ qua (bạn tự đề xuất)' : answerText(question, answer)
      return `${question.label}: ${text}`
    })
    .join('\n')
}
