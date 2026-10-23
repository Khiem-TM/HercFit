export interface KnowledgeNode {
  id: string
  kind: string
  label: string
  source: string
  updated_at: string | null
  details: Record<string, string | number>
}
export interface KnowledgeGraph {
  nodes: KnowledgeNode[]
  edges: { source: string; target: string; label: string }[]
  status: string
  lag_ms: number | null
}
export const constellationKinds: Record<string, { label: string; color: string }> = {
  User: { label: 'Bạn', color: '#fff1ce' },
  Goal: { label: 'Mục tiêu', color: '#d4b77d' },
  BodyMetric: { label: 'Số đo', color: '#aacbd5' },
  Meal: { label: 'Bữa ăn', color: '#eee4cf' },
  MealItem: { label: 'Khẩu phần', color: '#b0aaa0' },
  Food: { label: 'Thực phẩm', color: '#bdd0ba' },
  Session: { label: 'Hội thoại', color: '#b6b1d1' },
  Run: { label: 'Lượt trò chuyện', color: '#b6b1d1' },
  Execution: { label: 'Thao tác', color: '#c4b5d9' },
}
