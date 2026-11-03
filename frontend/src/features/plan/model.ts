/** Lịch tập: bản nháp sửa trên thẻ xác nhận và tiến độ checklist ở thanh bên Kế hoạch. */

type Row = Record<string, any>

/* ---------- Bản nháp trên thẻ xác nhận ---------- */

export interface ItemDraft { item: Row; view: Row }
export interface EntryDraft { key: number; entry: Row; view: Row; items: ItemDraft[] }

/** Payload của lệnh và bản xem trước có cùng thứ tự buổi/bài; bản xem trước chỉ dùng để hiển thị tên và ảnh. */
export function entryDrafts(payload: Row, display: Row): EntryDraft[] {
  const views = (display.entries || []) as Row[]
  return ((payload.entries || []) as Row[]).map((entry, index) => {
    const view = views[index] || {}
    // Payload có thể là proxy reactive của Vue (structuredClone không sao chép được proxy).
    const copy = JSON.parse(JSON.stringify(entry)) as Row
    return {
      key: index,
      entry: copy,
      view,
      items: ((copy.items || []) as Row[]).map((item, position) => ({ item, view: (view.items || [])[position] || {} })),
    }
  })
}

/** Payload đầy đủ sau khi sửa; khoảng ngày của lịch được nới để bao mọi buổi. */
export function draftPayload(payload: Row, name: string, entries: EntryDraft[]): Row {
  const days = entries.map(row => row.entry.scheduled_date as string).filter(Boolean).sort()
  const start = [payload.start_date, days[0]].filter(Boolean).sort()[0]
  const end = [payload.end_date, days[days.length - 1]].filter(Boolean).sort().at(-1)
  const { resource_id: _id, ...rest } = payload
  return {
    ...rest,
    name: name.trim() || payload.name,
    start_date: start,
    end_date: end,
    entries: entries.map(row => ({ ...row.entry, items: row.entry.is_rest ? [] : row.items.map(value => value.item) })),
  }
}

/* ---------- Checklist ---------- */

export interface PlanEntry {
  id: string
  scheduled_date: string
  label: string
  note: string | null
  is_rest: boolean
  completed_at: string | null
  items: Row[]
}

export interface TrainingPlan {
  id: string
  version_id?: number
  status?: 'ACTIVE' | 'ENDED'
  ended_at?: string | null
  end_reason?: string | null
  name: string
  start_date: string
  end_date: string
  timezone: string
  note: string | null
  entries: PlanEntry[]
}

export interface PlanDay { date: string; entries: PlanEntry[] }

export interface PlanProgress { done: number; total: number; due: number; missed: number; percent: number }

/** Ngày địa phương YYYY-MM-DD theo múi giờ của lịch. */
export function today(timezone: string, now = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
}

export function planDays(plan: TrainingPlan): PlanDay[] {
  const days = new Map<string, PlanEntry[]>()
  for (const entry of [...plan.entries].sort((a, b) => a.scheduled_date.localeCompare(b.scheduled_date))) {
    days.set(entry.scheduled_date, [...(days.get(entry.scheduled_date) || []), entry])
  }
  return [...days].map(([date, entries]) => ({ date, entries }))
}

/** done/overdue/cancelled khoá vĩnh viễn; chỉ buổi của hôm nay tick được (ghi buổi tập thật, không hoàn tác). */
export type TaskState = 'done' | 'today' | 'overdue' | 'upcoming' | 'cancelled'

/** Ngày địa phương lịch kết thúc; null khi lịch còn chạy. */
export function endedDay(plan: TrainingPlan): string | null {
  return plan.status === 'ENDED' && plan.ended_at ? today(plan.timezone, new Date(plan.ended_at)) : null
}

export function taskState(entry: PlanEntry, day: string, ended: string | null = null): TaskState {
  if (entry.completed_at) return 'done'
  // Kết thúc sớm huỷ các buổi từ ngày kết thúc; buổi đã tick trước đó luôn được giữ.
  if (ended && entry.scheduled_date >= ended) return 'cancelled'
  if (entry.scheduled_date < day || ended) return 'overdue'
  return entry.scheduled_date === day ? 'today' : 'upcoming'
}

/** Kết quả tick: buổi tập đã ghi vào nhật ký, calo ước tính, số buổi thể thao đã ghi lên Google Health. */
export interface CompletionResult {
  entry: PlanEntry
  training_id: string | null
  energy_kcal: number | null
  google_sessions: number
  notices: string[]
}

export function completionMessage(result: CompletionResult): string {
  const parts = [result.training_id || result.google_sessions ? 'Đã ghi buổi tập' : 'Đã đánh dấu hoàn thành']
  if (result.energy_kcal != null) parts.push(`~${Math.round(result.energy_kcal)} kcal`)
  if (result.google_sessions) parts.push(`${result.google_sessions} buổi lên Google Health`)
  return parts.join(' · ')
}

/** Buổi nghỉ và buổi bị huỷ khi kết thúc sớm không tính; buổi đã qua mà chưa tick là quá hạn (khoá). */
export function planProgress(plan: TrainingPlan, day: string): PlanProgress {
  const ended = endedDay(plan)
  if (ended && ended < day) day = ended
  const sessions = plan.entries.filter(entry => !entry.is_rest && taskState(entry, day, ended) !== 'cancelled')
  const done = sessions.filter(entry => entry.completed_at).length
  const due = sessions.filter(entry => entry.scheduled_date <= day).length
  const missed = sessions.filter(entry => entry.scheduled_date < day && !entry.completed_at).length
  return { done, total: sessions.length, due, missed, percent: sessions.length ? Math.round((done * 100) / sessions.length) : 0 }
}
