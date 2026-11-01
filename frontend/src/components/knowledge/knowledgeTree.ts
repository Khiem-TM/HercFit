import type { KnowledgeEdge, KnowledgeGraph, KnowledgeNode } from '@/types/knowledge'

/** Chỉ là trạng thái trình bày: nhánh nào đang mở không bao giờ thay đổi bản ghi của graph. */
export interface TreeIndex {
  byId: Map<string, KnowledgeNode>
  children: Map<string, string[]>
  links: KnowledgeEdge[]
  root?: string
}

export interface Point { x: number; y: number }

export function indexTree(graph: KnowledgeGraph): TreeIndex {
  const byId = new Map(graph.nodes.map(node => [node.id, node]))
  const children = new Map<string, string[]>()
  for (const edge of graph.edges) {
    if (edge.kind !== 'tree' || !byId.has(edge.source) || !byId.has(edge.target)) continue
    children.set(edge.source, [...(children.get(edge.source) ?? []), edge.target])
  }
  return { byId, children, links: graph.edges.filter(edge => edge.kind === 'link'), root: graph.nodes.find(node => !node.parent)?.id }
}

/** Các tổ tiên từ gốc xuống tới node cha trực tiếp. */
export function ancestors(index: TreeIndex, id: string): string[] {
  const path: string[] = []
  let current = index.byId.get(id)?.parent ?? null
  while (current && !path.includes(current)) {
    path.unshift(current)
    current = index.byId.get(current)?.parent ?? null
  }
  return path
}

/** Gốc và các hub luôn hiển thị; node sâu hơn chỉ xuất hiện dưới các nhánh đang mở. */
export function visibleIds(index: TreeIndex, expanded: ReadonlySet<string>): string[] {
  if (!index.root) return []
  const result = [index.root]
  const open = (id: string) => {
    for (const child of index.children.get(id) ?? []) {
      result.push(child)
      if (expanded.has(child)) open(child)
    }
  }
  open(index.root)
  return result
}

export function visibleEdges(index: TreeIndex, visible: ReadonlySet<string>): KnowledgeEdge[] {
  const tree: KnowledgeEdge[] = []
  for (const [source, targets] of index.children) {
    if (!visible.has(source)) continue
    for (const target of targets) if (visible.has(target)) tree.push({ source, target, kind: 'tree', label: null })
  }
  return [...tree, ...index.links.filter(edge => visible.has(edge.source) && visible.has(edge.target))]
}

/** Đóng một nhánh cũng đóng mọi thứ bên dưới, để mở lại sẽ bắt đầu gọn gàng. */
export function collapse(index: TreeIndex, expanded: ReadonlySet<string>, id: string): Set<string> {
  const next = new Set(expanded)
  const close = (node: string) => {
    next.delete(node)
    for (const child of index.children.get(node) ?? []) close(child)
  }
  close(id)
  return next
}

const RADII = [0, 165, 300, 425, 540, 650]

/**
 * Cây toả tròn có trọng số: mỗi node hiển thị sở hữu một hình quạt tỉ lệ với
 * số lá nó hiển thị, nên nhánh vừa mở có chỗ và các nhánh bên cạnh trượt sang bên.
 */
export function radialLayout(index: TreeIndex, visible: readonly string[]): Map<string, Point> {
  const shown = new Set(visible)
  const positions = new Map<string, Point>()
  if (!index.root || !shown.has(index.root)) return positions
  const kids = (id: string) => (index.children.get(id) ?? []).filter(child => shown.has(child))
  const weights = new Map<string, number>()
  const weight = (id: string): number => {
    if (!weights.has(id)) {
      const children = kids(id)
      weights.set(id, children.length ? children.reduce((sum, child) => sum + weight(child), 0) : 1)
    }
    return weights.get(id)!
  }
  const place = (id: string, start: number, end: number, depth: number) => {
    const angle = (start + end) / 2
    const children = kids(id)
    if (depth === 0) positions.set(id, { x: 0, y: 0 })
    if (!children.length) return
    // Một độ lệch giữ hub đang đóng dễ đọc bên cạnh một hub mở rộng.
    const bias = depth === 0 ? 1.6 : .5
    const total = children.reduce((sum, child) => sum + weight(child) + bias, 0)
    // Nhánh sâu xoè quanh node cha thay vì quét cả hình quạt.
    const span = depth === 0 ? end - start : Math.min(end - start, .2 + weight(id) * .2 * (1.3 - depth * .12))
    // Hub đầu tiên (mục tiêu) nằm ở vị trí mười hai giờ; các hình quạt sâu hơn căn giữa theo node cha.
    let cursor = depth === 0 ? -Math.PI / 2 - span * (weight(children[0]) + bias) / total / 2 : angle - span / 2
    children.forEach((child, order) => {
      const share = span * (weight(child) + bias) / total
      const middle = cursor + share / 2
      const crowded = depth >= 1 && span / children.length < .17
      const radius = RADII[Math.min(depth + 1, RADII.length - 1)] + (crowded && order % 2 ? 46 : 0)
      positions.set(child, { x: Math.cos(middle) * radius, y: Math.sin(middle) * radius })
      place(child, cursor, cursor + share, depth + 1)
      cursor += share
    })
  }
  place(index.root, 0, Math.PI * 2, 0)
  return positions
}
