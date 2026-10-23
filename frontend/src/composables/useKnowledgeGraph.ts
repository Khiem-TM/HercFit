import { onUnmounted, ref } from 'vue'
import { useAuth } from './useAuth'
import type { KnowledgeGraph } from '@/types/knowledge'

export function useKnowledgeGraph() {
  const { authFetch } = useAuth()
  const graph = ref<KnowledgeGraph>({ nodes: [], edges: [], status: 'loading', lag_ms: null })
  const loading = ref(false)
  let controller: AbortController | undefined
  let disposed = false
  async function refresh() {
    controller?.abort()
    const current = new AbortController()
    controller = current
    loading.value = true
    try {
      const response = await authFetch('/api/v1/chat/knowledge-graph', { signal: current.signal })
      if (!response.ok) throw new Error('graph unavailable')
      const data: KnowledgeGraph = await response.json()
      if (!disposed && !current.signal.aborted) graph.value = data
    } catch {
      if (!disposed && !current.signal.aborted) graph.value = { nodes: [], edges: [], status: 'unavailable', lag_ms: null }
    } finally {
      if (!disposed && controller === current) loading.value = false
    }
  }
  onUnmounted(() => { disposed = true; controller?.abort() })
  return { graph, loading, refresh }
}
