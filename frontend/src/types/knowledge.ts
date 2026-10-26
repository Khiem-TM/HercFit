export type KnowledgeHub = 'goal' | 'body' | 'nutrition' | 'training' | 'conversation'

export interface KnowledgeDetail {
  label: string
  value: string
}

export interface KnowledgeNode {
  id: string
  kind: string
  label: string
  parent: string | null
  hub: KnowledgeHub | null
  depth: number
  summary: string | null
  details: KnowledgeDetail[]
  at: string | null
  count: number | null
  children: number
}

export interface KnowledgeEdge {
  source: string
  target: string
  kind: 'tree' | 'link'
  label: string | null
}

export interface KnowledgeInsight {
  id: string
  hub: KnowledgeHub
  title: string
  value: string
  caption?: string | null
  detail?: string | null
  progress?: number | null
  series?: number[]
  bars?: (number | null)[]
  tone: 'positive' | 'warning' | 'neutral'
}

export interface KnowledgeIntent {
  intent: string
  label: string
  hub: string
  count: number
  last_at: string | null
  node_id: string
}

export interface KnowledgeEvent {
  id: string
  hub: KnowledgeHub
  at: string
  title: string
  subtitle: string | null
  node_id: string
}

export interface KnowledgeProfile {
  age: number | null
  height_cm: number | null
  weight_kg: number | null
  bmi: number | null
  experience: string | null
  focus: string | null
  available_days: number | null
  session_minutes: number | null
  equipment: string[]
}

export type HubCounts = Partial<Record<KnowledgeHub, number>>

/** Inclusive local days the map was drawn for, clamped by the server to the retained history. */
export interface KnowledgeWindow {
  start: string
  end: string
  min: string
  max: string
  /** At most this many records of each kind are drawn; `totals` counts all of them in the window. */
  limit: number
  totals: Partial<Record<'BodyMetric' | 'Meal' | 'Training', number>>
  /** Activity per local day over the whole retained history; quiet days are absent. */
  density: Record<string, HubCounts>
}

export interface KnowledgeGraph {
  status: string
  mode: string | null
  lag_ms: number | null
  model_at?: string | null
  generated_at?: string | null
  profile: KnowledgeProfile | null
  insights: KnowledgeInsight[]
  intents: KnowledgeIntent[]
  nodes: KnowledgeNode[]
  edges: KnowledgeEdge[]
  timeline: KnowledgeEvent[]
  window?: KnowledgeWindow
}

export const emptyKnowledgeGraph = (status = 'loading'): KnowledgeGraph => ({
  status, mode: null, lag_ms: null, profile: null, insights: [], intents: [], nodes: [], edges: [], timeline: [],
})

export const hubTheme: Record<KnowledgeHub, { label: string; color: string }> = {
  goal: { label: 'Mục tiêu', color: '#d4b77d' },
  body: { label: 'Cơ thể', color: '#8fc3d4' },
  nutrition: { label: 'Dinh dưỡng', color: '#a8cf9a' },
  training: { label: 'Tập luyện', color: '#e3a37f' },
  conversation: { label: 'Hội thoại', color: '#b9a9e3' },
}

export const ROOT_COLOR = '#fff1ce'

export const kindLabels: Record<string, string> = {
  User: 'Hồ sơ của bạn', Hub: 'Nhóm tri thức', Group: 'Nhóm con', Goal: 'Mục tiêu', BodyMetric: 'Số đo cơ thể',
  Meal: 'Bữa ăn', MealItem: 'Khẩu phần', Food: 'Thực phẩm', Training: 'Buổi tập', TrainingItem: 'Bài trong buổi tập',
  Exercise: 'Bài tập', Intent: 'Ý định hội thoại', Run: 'Lượt hội thoại',
}

export function hubColor(hub: string | null | undefined): string {
  return hub && hub in hubTheme ? hubTheme[hub as KnowledgeHub].color : ROOT_COLOR
}
