import type { KnowledgeGraph, KnowledgeNode } from '@/types/knowledge'

export const dashboardTimezone = 'Asia/Ho_Chi_Minh'
export const number = (value: number) => new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 }).format(value)

export function detail(node: KnowledgeNode, label: string): string | undefined {
  return node.details.find(item => item.label === label)?.value
}

// The map exposes formatted facts, with a dot or comma as the decimal separator.
// Missing values must remain missing (especially for nutrition), never become zero.
export function numericDetail(node: KnowledgeNode, label: string): number | null {
  const raw = detail(node, label)?.trim().match(/^(-?\d+(?:[.,]\d+)?)(?:\s|$)/)?.[1]
  const value = raw == null ? NaN : Number(raw.replace(',', '.'))
  return Number.isFinite(value) ? value : null
}

export function localDay(value: string | Date): string {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: dashboardTimezone, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(date)
  return ['year', 'month', 'day'].map(type => parts.find(part => part.type === type)?.value).join('-')
}

export function shiftDay(day: string, offset: number): string {
  const date = new Date(`${day}T12:00:00Z`)
  date.setUTCDate(date.getUTCDate() + offset)
  return date.toISOString().slice(0, 10)
}

export function shortDate(value: string): string {
  return new Intl.DateTimeFormat('vi-VN', { timeZone: dashboardTimezone, day: '2-digit', month: '2-digit' }).format(new Date(value))
}

export function records(graph: KnowledgeGraph, kind: string): KnowledgeNode[] {
  return graph.nodes.filter(node => node.kind === kind)
    .sort((a, b) => (b.at ?? '').localeCompare(a.at ?? ''))
}

export interface WeightPoint {
  id: string
  at: string
  day: string
  weight: number
  node: KnowledgeNode
}

export function weightPoints(graph: KnowledgeGraph): WeightPoint[] {
  return records(graph, 'BodyMetric').flatMap(node => {
    const weight = numericDetail(node, 'Cân nặng')
    const day = node.at ? localDay(node.at) : ''
    return weight != null && weight > 0 && day && node.at
      ? [{ id: node.id, at: node.at, day, weight, node }] : []
  }).sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime())
}

export interface TrainingWeek {
  week_start: string
  sessions: number
  planned_sessions: number
  completed_planned_sessions: number
  duration_seconds: number | string
}

export interface TrainingSummary {
  start_date: string
  end_date: string
  weeks: TrainingWeek[]
}
