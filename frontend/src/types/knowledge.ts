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

/** Các tab của thanh bên tri thức; "Kế hoạch" là checklist lịch tập đang chạy. */
export type KnowledgeTab = 'overview' | 'map' | 'plan'

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
  window?: KnowledgeWindow
}

export const emptyKnowledgeGraph = (status = 'loading'): KnowledgeGraph => ({
  status, lag_ms: null, profile: null, insights: [], intents: [], nodes: [], edges: [],
})

/** Màu nhóm theo thiết kế Dashboard: `light` trên nền sáng, `color` (sáng hơn) trên nền tối. */
export const hubTheme: Record<KnowledgeHub, { label: string; color: string; light: string }> = {
  goal: { label: 'Mục tiêu', color: '#F59E0B', light: '#B45309' },
  body: { label: 'Cơ thể', color: '#60A5FA', light: '#2563EB' },
  nutrition: { label: 'Dinh dưỡng', color: '#4ADE80', light: '#15803D' },
  training: { label: 'Tập luyện', color: '#FB923C', light: '#C2410C' },
  conversation: { label: 'Hội thoại', color: '#C4B5FD', light: '#7C3AED' },
}

const ROOT_COLOR = '#F4F4F5'
const ROOT_LIGHT = '#141416'

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

/** Màu thường cho canvas của bản đồ (canvas không giải được light-dark()). */
export function mapColor(hub: string | null | undefined, dark: boolean): string {
  const theme = hub && hub in hubTheme ? hubTheme[hub as KnowledgeHub] : { color: ROOT_COLOR, light: ROOT_LIGHT }
  return dark ? theme.color : theme.light
}
