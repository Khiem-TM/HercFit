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

/** Các ngày địa phương (tính cả hai đầu) mà bản đồ được vẽ, đã được server kẹp vào lịch sử còn lưu. */
export interface KnowledgeWindow {
  start: string
  end: string
  min: string
  max: string
  /** Mỗi loại bản ghi chỉ vẽ tối đa chừng này; `totals` đếm tất cả trong cửa sổ. */
  limit: number
  totals: Partial<Record<'BodyMetric' | 'Meal' | 'Training', number>>
  /** Hoạt động theo ngày địa phương trên toàn bộ lịch sử còn lưu; ngày yên ắng không có mặt. */
  density: Record<string, HubCounts>
}

export interface KnowledgeGraph {
  status: string
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
  status, lag_ms: null, profile: null, insights: [], intents: [], nodes: [], edges: [], timeline: [],
})

/** `color` vẽ trên nền tối (và trên bản đồ sao, vốn luôn là bầu trời đêm); `light` đọc được trên nền giấy. */
export const hubTheme: Record<KnowledgeHub, { label: string; color: string; light: string }> = {
  goal: { label: 'Mục tiêu', color: '#d4b77d', light: '#87671a' },
  body: { label: 'Cơ thể', color: '#8fc3d4', light: '#367689' },
  nutrition: { label: 'Dinh dưỡng', color: '#a8cf9a', light: '#517c40' },
  training: { label: 'Tập luyện', color: '#e3a37f', light: '#9b552a' },
  conversation: { label: 'Hội thoại', color: '#b9a9e3', light: '#715d9d' },
}

export const ROOT_COLOR = '#fff1ce'
const ROOT_LIGHT = '#7a6230'

export const kindLabels: Record<string, string> = {
  User: 'Hồ sơ của bạn', Hub: 'Nhóm tri thức', Group: 'Nhóm con', Goal: 'Mục tiêu', BodyMetric: 'Số đo cơ thể',
  Meal: 'Bữa ăn', MealItem: 'Khẩu phần', Food: 'Thực phẩm', Training: 'Buổi tập', TrainingItem: 'Bài trong buổi tập',
  Exercise: 'Bài tập', Intent: 'Ý định hội thoại', Run: 'Lượt hội thoại',
}

/** Màu CSS theo theme (light-dark()) cho style; không có hub nghĩa là gốc của chính người dùng. */
export function hubColor(hub: string | null | undefined): string {
  const theme = hub && hub in hubTheme ? hubTheme[hub as KnowledgeHub] : { color: ROOT_COLOR, light: ROOT_LIGHT }
  return `light-dark(${theme.light}, ${theme.color})`
}

/** Màu thường cho bản đồ sao (canvas không giải được light-dark()); bản đồ là bầu trời đêm ở cả hai theme. */
export function skyColor(hub: string | null | undefined): string {
  return hub && hub in hubTheme ? hubTheme[hub as KnowledgeHub].color : ROOT_COLOR
}
