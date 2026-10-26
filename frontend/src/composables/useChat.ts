import { computed, ref } from 'vue'
import { useAuth } from '@/composables/useAuth'
import type {
  ChatMessage,
  ChatResponse,
  PendingAction,
  SessionSummary,
} from '@/types/api'
import { MEDIA_TARGET } from '@/features/chat/confirmation'
import { normalizeClarification } from '@/features/chat/clarification'
import type { ConfirmExtras } from '@/components/chat/cards/ConfirmationCard.vue'

const sessions = ref<SessionSummary[]>([])
const activeSessionId = ref<string>('')
const messages = ref<ChatMessage[]>([])
const isStreaming = ref<boolean>(false)
const isConfirming = ref<boolean>(false)
const isLoadingHistory = ref<boolean>(false)
const activeNode = ref<string | null>(null)
const pendingAction = ref<PendingAction | null>(null)
const isSavingImage = ref<boolean>(false)
const error = ref<string | null>(null)
let streamController: AbortController | null = null

const NODE_LABELS: Record<string, string> = {
  orchestrator: 'Đang phân tích ý định & điều phối...',
  tool: 'Đang truy xuất dữ liệu & công cụ...',
  research: 'Đang tra cứu nguồn dinh dưỡng & vận động...',
  confirmation: 'Đang chuẩn bị bản xem trước xác nhận...',
  execution: 'Đang ghi nhận dữ liệu vào hồ sơ...',
  media: 'Đang lưu ảnh lên Cloudinary...',
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
        (m: { role: string; content: string; name?: string | null; created_at?: string | null }, idx: number) => ({
          id: `${sessionId}-${idx}`,
          role: m.role === 'human' ? 'human' : 'ai',
          content: m.content,
          name: m.name || null,
          // History carries no per-message time unless the server provides it.
          timestamp: m.created_at ?? '',
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
      const lastAi = [...mapped].reverse().find((m) => m.role === 'ai')
      if (lastAi) {
        if (Array.isArray(data.sources) && data.sources.length > 0) lastAi.sources = data.sources
        if (data.status === 'needs_input') lastAi.clarification = normalizeClarification(data.clarification)
        if (Array.isArray(data.illustrations)) lastAi.illustrations = data.illustrations
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
    const controller = new AbortController()
    streamController = controller
    // Index of the assistant bubble being filled by streamed tokens, if any.
    let streamingIndex = -1

    try {
      const resp = await authFetch('/api/v1/chat/stream', {
        method: 'POST',
        signal: controller.signal,
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
        if (resp.status === 429) {
          const wait = resp.headers.get('Retry-After')
          throw new Error((detail?.detail || 'Bạn đang gửi quá nhanh.') + (wait ? ` (thử lại sau ${wait} giây)` : ''))
        }
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
            } else if (event.type === 'token' && typeof event.text === 'string') {
              if (streamingIndex < 0) {
                streamingIndex = messages.value.push({
                  id: `stream-${crypto.randomUUID()}`, role: 'ai', content: '', status: 'streaming',
                  timestamp: new Date().toISOString(),
                }) - 1
              }
              messages.value[streamingIndex].content += event.text
            } else if (
              event.type === 'message' ||
              event.type === 'needs_input' ||
              event.type === 'pending_confirmation'
            ) {
              const pending: PendingAction | null = event.pending_action || null
              pendingAction.value = pending
              const final: ChatMessage = {
                // Keep the streamed bubble's identity: Vue updates it in place instead of replacing the node.
                id: streamingIndex >= 0 ? messages.value[streamingIndex].id : event.run_id || crypto.randomUUID(),
                role: 'ai',
                // The final event is authoritative; streamed text was a preview of it.
                content: event.reply || '',
                sources: Array.isArray(event.sources) ? event.sources : [],
                pending_action: pending,
                clarification: normalizeClarification(event.clarification),
                illustrations: Array.isArray(event.illustrations) ? event.illustrations : [],
                status: event.status,
                timestamp: new Date().toISOString(),
              }
              if (streamingIndex >= 0) messages.value.splice(streamingIndex, 1, final)
              else messages.value.push(final)
              streamingIndex = -1
            } else if (event.type === 'error') {
              const errMsg =
                event.reply || event.detail || 'Đã xảy ra lỗi khi xử lý yêu cầu.'
              // The banner is for failures outside a run (HTTP, auth, service down); a failed
              // run's reply is shown once, as its message.
              if (!event.run_id) error.value = errMsg
              const failed: ChatMessage = {
                id: streamingIndex >= 0 ? messages.value[streamingIndex].id : event.run_id || crypto.randomUUID(),
                role: 'ai',
                content: errMsg,
                sources: Array.isArray(event.sources) ? event.sources : [],
                status: 'failed',
                timestamp: new Date().toISOString(),
              }
              // Like a final message, it replaces the streamed preview instead of adding a copy.
              if (streamingIndex >= 0) messages.value.splice(streamingIndex, 1, failed)
              else messages.value.push(failed)
              streamingIndex = -1
            }
          } catch {
            // Skip malformed SSE frame
          }
        }
      }

      await loadSessions()
    } catch (err) {
      if (controller.signal.aborted) {
        // User pressed stop: keep what was already shown and mark it as stopped.
        if (streamingIndex >= 0) messages.value[streamingIndex].status = 'stopped'
        else messages.value.push({ id: crypto.randomUUID(), role: 'ai', content: '', status: 'stopped', timestamp: new Date().toISOString() })
      } else {
        const msg = err instanceof Error ? err.message : 'Lỗi kết nối với Agent.'
        error.value = msg
        if (streamingIndex >= 0) messages.value[streamingIndex].status = 'failed'
      }
    } finally {
      if (streamController === controller) streamController = null
      isStreaming.value = false
      activeNode.value = null
    }
  }

  /** Cancel the running reply; the server stops the run when the stream closes. */
  function stopStreaming(): void {
    streamController?.abort()
  }

  /** Saved record of the approved action (the write's output carries its action_id). */
  function savedRecord(result: ChatResponse, actionId: string): { id: string; version_id: number } | null {
    const output = result.tool_outputs?.find((o) => o.action_id === actionId && o.ok)?.output as Record<string, unknown> | undefined
    return output && typeof output.id === 'string' && typeof output.version_id === 'number'
      ? { id: output.id, version_id: output.version_id }
      : null
  }

  /** After a successful save: upload the user's photo or import the chosen research picture to Cloudinary. */
  async function attachImage(action: PendingAction, result: ChatResponse, extras: ConfirmExtras): Promise<void> {
    const kind = MEDIA_TARGET[action.tool]
    const wantsPhoto = Boolean(extras.photo) && (kind === 'meals' || kind === 'trainings')
    const wantsImport = Boolean(extras.imageSource) && (kind === 'foods' || kind === 'exercises')
    if (!kind || (!wantsPhoto && !wantsImport)) return
    const saved = savedRecord(result, action.action_id)
    const note = (content: string, failed = false) => messages.value.push({
      id: crypto.randomUUID(), role: 'ai', content, status: failed ? 'failed' : 'completed', timestamp: new Date().toISOString(),
    })
    if (!saved) {
      note('Đã lưu bản ghi nhưng chưa xác định được bản ghi để gắn ảnh. Bạn có thể thêm ảnh trong mục Ảnh.', true)
      return
    }
    isSavingImage.value = true
    activeNode.value = 'media'
    try {
      const endpoint = `/api/media/${kind}/${saved.id}/image`
      let resp: Response
      if (wantsPhoto) {
        const form = new FormData()
        form.append('file', extras.photo as File)
        form.append('expected_version_id', String(saved.version_id))
        resp = await authFetch(endpoint, { method: 'PUT', body: form })
      } else {
        resp = await authFetch(`${endpoint}/import`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source_url: extras.imageSource, expected_version_id: saved.version_id }),
        })
      }
      const body = await resp.json().catch(() => ({}))
      if (!resp.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Không thể lưu ảnh.')
      note(wantsPhoto ? 'Đã lưu ảnh của bạn lên Cloudinary.' : 'Đã lưu ảnh minh hoạ lên Cloudinary.')
    } catch (err) {
      // The record itself is already saved; only the picture failed.
      note(`Đã lưu bản ghi, nhưng chưa lưu được ảnh: ${err instanceof Error ? err.message : 'lỗi không xác định'}. Bạn có thể thử lại trong mục Ảnh.`, true)
    } finally {
      isSavingImage.value = false
    }
  }

  async function confirmAction(decision: 'approve' | 'reject', extras: ConfirmExtras = {}): Promise<void> {
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
          session_id: action.session_id || activeSessionId.value,
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
        clarification: normalizeClarification(result.clarification),
        illustrations: result.illustrations || [],
        status: result.status,
        timestamp: new Date().toISOString(),
      })

      if (decision === 'approve' && result.status !== 'failed') {
        await attachImage(action, result, extras)
      }

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
    isSavingImage,
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
    stopStreaming,
    confirmAction,
  }
}

