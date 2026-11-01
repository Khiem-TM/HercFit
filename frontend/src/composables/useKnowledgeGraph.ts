import { onUnmounted, ref } from 'vue'
import { useAuth } from './useAuth'
import { emptyKnowledgeGraph, type KnowledgeGraph } from '@/types/knowledge'

export interface DayRange { start: string; end: string }

/** Bản đồ cá nhân; với `range`, chỉ các bản ghi của những ngày địa phương đó (tính cả hai đầu). */
export function useKnowledgeGraph(range?: () => DayRange | undefined) {
  const { authFetch } = useAuth()
  const graph = ref<KnowledgeGraph>(emptyKnowledgeGraph())
  const loading = ref(false)
  const failed = ref(false)
  let controller: AbortController | undefined
  let disposed = false
  async function refresh() {
    controller?.abort()
    const current = new AbortController()
    controller = current
    loading.value = true
    const days = range?.()
    const query = days ? `?${new URLSearchParams({ start: days.start, end: days.end })}` : ''
    try {
      const response = await authFetch(`/api/v1/chat/knowledge-graph${query}`, { signal: current.signal })
      if (!response.ok) throw new Error('graph unavailable')
      const data: KnowledgeGraph = { ...emptyKnowledgeGraph('empty'), ...(await response.json()) }
      if (!disposed && !current.signal.aborted) {
        graph.value = data
        failed.value = false
      }
    } catch {
      // Giữ những gì đã vẽ khi làm mới thất bại; chỉ báo lỗi lần đầu.
      if (!disposed && !current.signal.aborted) {
        failed.value = true
        if (!graph.value.nodes.length) graph.value = emptyKnowledgeGraph('unavailable')
      }
    } finally {
      if (!disposed && controller === current) loading.value = false
    }
  }
  onUnmounted(() => { disposed = true; controller?.abort() })
  return { graph, loading, failed, refresh }
}
