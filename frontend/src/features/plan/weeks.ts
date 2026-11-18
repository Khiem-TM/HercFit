import { endedDay, taskState, type PlanEntry, type TrainingPlan, type TaskState } from './model'
import { monday, shift } from '@/components/dashboard/format'

export const STATUS: Record<TaskState, { text: string; glyph: string; tone: string }> = {
  done: { text: 'Đã tập', glyph: '✓', tone: 'done' },
  today: { text: 'Hôm nay', glyph: '●', tone: 'today' },
  overdue: { text: 'Chưa hoàn thành', glyph: '!', tone: 'overdue' },
  upcoming: { text: 'Sắp tới', glyph: '○', tone: 'upcoming' },
  cancelled: { text: 'Đã hủy', glyph: '×', tone: 'cancelled' },
}
export interface WeekDay {
  date: string; outside: boolean; rest: boolean; sessions: PlanEntry[]
  text: string; glyph: string; tone: string
}
export interface PlanWeek { start: string; end: string; days: WeekDay[]; sessions: PlanEntry[] }
export function planWeeks(plan: TrainingPlan, today: string): PlanWeek[] {
  const weeks: PlanWeek[] = []
  const ended = endedDay(plan)
  for (let start = monday(plan.start_date); start <= plan.end_date; start = shift(start, 7)) {
    const days = Array.from({ length: 7 }, (_, i): WeekDay => {
      const date = shift(start, i)
      const entries = plan.entries.filter(e => e.scheduled_date === date)
      const sessions = entries.filter(e => !e.is_rest)
      const states = sessions.map(e => taskState(e, today, ended))
      const outside = date < plan.start_date || date > plan.end_date
      const rest = entries.some(e => e.is_rest) && !sessions.length
      const state = states.length ? states.every(s => s === 'done') ? 'done' : states.includes('overdue') ? 'overdue' : states.includes('today') ? 'today' : states.includes('upcoming') ? 'upcoming' : 'cancelled' : null
      return { date, outside, rest, sessions, ...(state ? STATUS[state] : { text: outside ? 'Ngoài kế hoạch' : rest ? 'Nghỉ theo kế hoạch' : 'Không có buổi tập', glyph: '–', tone: 'rest' }) }
    })
    weeks.push({ start, end: shift(start, 6), days, sessions: days.flatMap(d => d.sessions) })
  }
  return weeks
}
export function currentWeekIndex(weeks: PlanWeek[], today: string): number {
  if (!weeks.length || today < weeks[0].start) return 0
  const index = weeks.findIndex(w => today >= w.start && today <= w.end)
  return index < 0 ? weeks.length - 1 : index
}
export function preferredSession(week: PlanWeek, today: string): PlanEntry | null {
  return week.sessions.find(e => e.scheduled_date === today && !e.completed_at)
    ?? week.sessions.find(e => !e.completed_at) ?? week.sessions[0] ?? null
}
export function canComplete(plan: TrainingPlan | null, entry: PlanEntry | null, today: string): boolean {
  return !!plan && plan.status !== 'ENDED' && !!entry && !entry.is_rest && !entry.completed_at
    && entry.scheduled_date === today && plan.entries.some(e => e.id === entry.id && !e.completed_at && !e.is_rest && e.scheduled_date === today)
}
