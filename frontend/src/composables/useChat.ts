import { computed, ref } from 'vue'
import { useAuth } from '@/composables/useAuth'
import type {
  ChatMessage,
  ChatResponse,
  PendingAction,
  SessionSummary,
} from '@/types/api'

const sessions = ref<SessionSummary[]>([])
const activeSessionId = ref<string>('')
const messages = ref<ChatMessage[]>([])
const isStreaming = ref<boolean>(false)
const isConfirming = ref<boolean>(false)
const isLoadingHistory = ref<boolean>(false)
const activeNode = ref<string | null>(null)
const pendingAction = ref<PendingAction | null>(null)
const error = ref<string | null>(null)

const NODE_LABELS: Record<string, string> = {
  orchestrator: 'Đang phân tích ý định & điều phối...',
  tool: 'Đang truy xuất dữ liệu & công cụ...',
  research: 'Đang tra cứu nguồn dinh dưỡng & vận động...',
  confirmation: 'Đang chuẩn bị bản xem trước xác nhận...',
  execution: 'Đang ghi nhận dữ liệu vào hồ sơ...',
  answer: 'Đang tổng hợp câu trả lời...',
}

export function useChat() {
  const { authFetch } = useAuth()

  const activeNodeLabel = computed(() => {
    if (!activeNode.value) return 'Đang kết nối...'
    return NODE_LABELS[activeNode.value] || `Đang xử lý (${activeNode.value})...`
  })

  const hasMessages = computed(() => messages.value.length > 0)

  async function loadSessions(): Promise<void> {
    try {
      const resp = await authFetch('/api/v1/chat/sessions')
      if (!resp.ok) return
      const data = await resp.json()
      sessions.value = Array.isArray(data.sessions) ? data.sessions : []
    } catch {
      // Ignore transient session list errors
    }
  }

  function createNewSession(): void {
    activeSessionId.value = crypto.randomUUID()
    messages.value = []
    pendingAction.value = null
    activeNode.value = null
    error.value = null
  }

  async function selectSession(sessionId: string): Promise<void> {
    if (isStreaming.value) return
    activeSessionId.value = sessionId
    isLoadingHistory.value = true
    error.value = null
    pendingAction.value = null
    try {
      const resp = await authFetch(`/api/v1/chat/history/${encodeURIComponent(sessionId)}`)
      if (!resp.ok) {
        messages.value = []
        return
      }
      const data = await resp.json()
      const rawMessages = Array.isArray(data.messages) ? data.messages : []
      const mapped: ChatMessage[] = rawMessages.map(
        (m: { role: string; content: string; name?: string | null }, idx: number) => ({
          id: `${sessionId}-${idx}`,
          role: m.role === 'human' ? 'human' : 'ai',
          content: m.content,
          name: m.name || null,
          timestamp: new Date().toISOString(),
        }),
      )
      if (data.status === 'pending_confirmation' && data.pending_action) {
        pendingAction.value = data.pending_action
        const lastMsg = mapped[mapped.length - 1]
        if (!lastMsg || lastMsg.role === 'human') {
          mapped.push({
            id: `${sessionId}-pending`,
            role: 'ai',
            content: 'Vui lòng kiểm tra và xác nhận thao tác trước khi lưu.',
            status: 'pending_confirmation',
            pending_action: data.pending_action,
            timestamp: new Date().toISOString(),
          })
        } else {
          lastMsg.pending_action = data.pending_action
          lastMsg.status = 'pending_confirmation'
        }
      }
      if (Array.isArray(data.sources) && data.sources.length > 0 && mapped.length > 0) {
        const lastAi = [...mapped].reverse().find((m) => m.role === 'ai')
        if (lastAi) {
          lastAi.sources = data.sources
        }
      }
      messages.value = mapped
    } catch {
      error.value = 'Không thể tải lịch sử hội thoại.'
    } finally {
      isLoadingHistory.value = false
    }
  }

  async function deleteSession(sessionId: string): Promise<void> {
    try {
      const resp = await authFetch(`/api/v1/chat/history/${encodeURIComponent(sessionId)}`, {
        method: 'DELETE',
      })
      if (!resp.ok && resp.status !== 404) {
        const detail = await resp.json().catch(() => ({}))
        throw new Error(detail?.detail || 'Không thể xóa hội thoại.')
      }
      sessions.value = sessions.value.filter((s) => s.session_id !== sessionId)
      if (activeSessionId.value === sessionId) {
        createNewSession()
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Không thể xóa hội thoại.'
    }
  }

  async function sendMessage(rawText: string): Promise<void> {
    const text = rawText.trim()
    if (!text || isStreaming.value) return

    if (!activeSessionId.value) {
      activeSessionId.value = crypto.randomUUID()
    }
    const currentSessionId = activeSessionId.value
    error.value = null
    pendingAction.value = null

    messages.value.push({
      id: crypto.randomUUID(),
      role: 'human',
      content: text,
      timestamp: new Date().toISOString(),
    })

    isStreaming.value = true
    activeNode.value = 'orchestrator'

    try {
      const resp = await authFetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          session_id: currentSessionId,
          message: text,
        }),
      })

      if (!resp.ok || !resp.body) {
        const detail = await resp.json().catch(() => ({}))
        throw new Error(detail?.detail || 'Không thể kết nối tới dịch vụ AI Agent.')
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''

        for (const block of parts) {
          const line = block
            .split('\n')
            .find((l) => l.startsWith('data: '))
          if (!line) continue
          const payloadStr = line.slice(6).trim()
          if (!payloadStr || payloadStr === '[DONE]') continue

          try {
            const event = JSON.parse(payloadStr)
            if (event.type === 'progress') {
              activeNode.value = event.node || null
            } else if (
              event.type === 'message' ||
              event.type === 'needs_input' ||
              event.type === 'pending_confirmation'
            ) {
              const pending: PendingAction | null = event.pending_action || null
              pendingAction.value = pending
              messages.value.push({
                id: event.run_id || crypto.randomUUID(),
                role: 'ai',
                content: event.reply || '',
                sources: Array.isArray(event.sources) ? event.sources : [],
                pending_action: pending,
                status: event.status,
                timestamp: new Date().toISOString(),
              })
            } else if (event.type === 'error') {
              const errMsg =
                event.reply || event.detail || 'Đã xảy ra lỗi khi xử lý yêu cầu.'
              error.value = errMsg
              messages.value.push({
                id: crypto.randomUUID(),
                role: 'ai',
                content: errMsg,
                status: 'failed',
                timestamp: new Date().toISOString(),
              })
            }
          } catch {
            // Skip malformed SSE frame
          }
        }
      }

      await loadSessions()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Lỗi kết nối với Agent.'
      error.value = msg
    } finally {
      isStreaming.value = false
      activeNode.value = null
    }
  }

  async function confirmAction(decision: 'approve' | 'reject'): Promise<void> {
    if (!pendingAction.value || isConfirming.value) return
    const action = pendingAction.value
    isConfirming.value = true
    error.value = null
    activeNode.value = decision === 'approve' ? 'execution' : 'answer'

    try {
      const resp = await authFetch('/api/v1/chat/confirm', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          session_id: action.session_id,
          action_id: action.action_id,
          revision: action.revision,
          decision,
        }),
      })

      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}))
        throw new Error(detail?.detail || 'Không thể xác nhận thao tác.')
      }

      const result: ChatResponse = await resp.json()
      pendingAction.value = result.pending_action || null

      messages.value.push({
        id: result.run_id || crypto.randomUUID(),
        role: 'ai',
        content: result.reply,
        sources: result.sources || [],
        pending_action: result.pending_action || null,
        status: result.status,
        timestamp: new Date().toISOString(),
      })

      await loadSessions()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Xác nhận thao tác thất bại.'
    } finally {
      isConfirming.value = false
      activeNode.value = null
    }
  }

  return {
    sessions,
    activeSessionId,
    messages,
    isStreaming,
    isConfirming,
    isLoadingHistory,
    activeNode,
    activeNodeLabel,
    pendingAction,
    hasMessages,
    error,
    loadSessions,
    createNewSession,
    selectSession,
    deleteSession,
    sendMessage,
    confirmAction,
  }
}

