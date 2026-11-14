import { computed, ref } from 'vue'
import { useAuth } from '@/composables/useAuth'
import type {
  ChatMessage,
  ChatMode,
  ChatResponse,
  FoodChoice,
  PendingAction,
  SessionSummary,
} from '@/types/api'
import { MEDIA_TARGET } from '@/features/chat/confirmation'
import { normalizeClarification } from '@/features/chat/clarification'
import { normalizeFoodGap } from '@/features/chat/foodGap'
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
/** Chế độ của phiên đang mở; được nhớ theo từng phiên cho tới khi người dùng tắt. */
const chatMode = ref<ChatMode>('normal')
let streamController: AbortController | null = null
// run_id của lượt đang stream (sự kiện "run" đầu tiên), để nút dừng huỷ được lượt ở server.
let streamRunId: string | null = null
let viewGeneration = 0
let historyController: AbortController | null = null

function changeView(): number {
  historyController?.abort()
  historyController = null
  isLoadingHistory.value = false
  return ++viewGeneration
}

const MODE_KEY = 'hercfit.chatMode.'

function storedMode(sessionId: string): ChatMode {
  try {
    return localStorage.getItem(MODE_KEY + sessionId) === 'plan' ? 'plan' : 'normal'
  } catch {
    return 'normal'
  }
}

function rememberMode(sessionId: string, value: ChatMode): void {
  try {
    if (value === 'plan') localStorage.setItem(MODE_KEY + sessionId, 'plan')
    else localStorage.removeItem(MODE_KEY + sessionId)
  } catch {
    // Trình duyệt chặn localStorage: chế độ chỉ giữ trong phiên làm việc hiện tại.
  }
}

const NODE_LABELS: Record<string, string> = {
  orchestrator: 'Đang phân tích ý định & điều phối...',
  nutrition: 'Agent dinh dưỡng đang xử lý bữa ăn & thực phẩm...',
  training_log: 'Agent tập luyện đang xử lý buổi tập & bài tập...',
  body_health: 'Agent cơ thể đang đọc số đo...',
  daily_health: 'Agent sức khoẻ hằng ngày đang phân tích dữ liệu thiết bị...',
  coach: 'Agent huấn luyện đang xử lý mục tiêu & lịch tập...',
  delegate: 'Các agent đang xử lý song song từng phần yêu cầu...',
  join: 'Đang gộp kết quả của các agent...',
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
      // Bỏ qua lỗi tạm thời khi tải danh sách phiên
    }
  }

  function setChatMode(value: ChatMode): void {
    chatMode.value = value
    if (activeSessionId.value) rememberMode(activeSessionId.value, value)
  }

  function createNewSession(): void {
    if (isStreaming.value) return
    changeView()
    activeSessionId.value = crypto.randomUUID()
    chatMode.value = 'normal'
    messages.value = []
    pendingAction.value = null
    activeNode.value = null
    error.value = null
  }

  async function selectSession(sessionId: string): Promise<void> {
    if (isStreaming.value) return
    const generation = changeView()
    const controller = new AbortController()
    historyController = controller
    const current = () => generation === viewGeneration && activeSessionId.value === sessionId
    activeSessionId.value = sessionId
    messages.value = []
    activeNode.value = null
    chatMode.value = storedMode(sessionId)
    isLoadingHistory.value = true
    error.value = null
    pendingAction.value = null
    try {
      const resp = await authFetch(`/api/v1/chat/history/${encodeURIComponent(sessionId)}`, { signal: controller.signal })
      if (!current()) return
      if (!resp.ok) {
        messages.value = []
        return
      }
      const data = await resp.json()
      if (!current()) return
      const rawMessages = Array.isArray(data.messages) ? data.messages : []
      const mapped: ChatMessage[] = rawMessages.map(
        (m: { id?: string; role: string; content: string; name?: string | null; created_at?: string | null }, idx: number) => ({
          id: m.id || `${sessionId}-${idx}`,
          role: m.role === 'human' ? 'human' : 'ai',
          content: m.content,
          name: m.name || null,
          // Lịch sử không mang thời gian theo từng tin nhắn trừ khi server cung cấp.
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
        if (data.status === 'needs_input') {
          // Form chỉ mở ở tin nhắn needs_input; khi thiếu trạng thái này, tải lại trang chỉ còn cách trả lời bằng gõ chữ.
          lastAi.clarification = normalizeClarification(data.clarification)
          lastAi.food_gap = normalizeFoodGap(data.food_gap)
          lastAi.status = 'needs_input'
        }
        if (Array.isArray(data.illustrations)) lastAi.illustrations = data.illustrations
      }
      messages.value = mapped
    } catch {
      if (current()) error.value = 'Không thể tải lịch sử hội thoại.'
    } finally {
      if (current()) {
        isLoadingHistory.value = false
        historyController = null
      }
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

  /** `extra.food_choices`: lựa chọn trên thẻ món thiếu; server chỉ dùng khi thẻ đó đang mở. */
  async function sendMessage(rawText: string, extra: { food_choices?: FoodChoice[] } = {}): Promise<void> {
    const text = rawText.trim()
    if (!text || isStreaming.value || isConfirming.value || isLoadingHistory.value) return

    if (!activeSessionId.value) {
      activeSessionId.value = crypto.randomUUID()
    }
    const currentSessionId = activeSessionId.value
    const mode = chatMode.value
    rememberMode(currentSessionId, mode)
    error.value = null
    pendingAction.value = null

    messages.value.push({
      id: crypto.randomUUID(),
      role: 'human',
      content: text,
      mode,
      timestamp: new Date().toISOString(),
    })

    isStreaming.value = true
    activeNode.value = 'orchestrator'
    const controller = new AbortController()
    streamController = controller
    // Chỉ số của bong bóng trợ lý đang được điền bằng token stream, nếu có.
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
          mode,
          ...(extra.food_choices?.length ? { food_choices: extra.food_choices } : {}),
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
            if (event.type === 'run' && typeof event.run_id === 'string') {
              if (streamController === controller) streamRunId = event.run_id
            } else if (event.type === 'progress') {
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
                // Giữ định danh của bong bóng đang stream: Vue cập nhật tại chỗ thay vì thay node.
                id: streamingIndex >= 0 ? messages.value[streamingIndex].id : event.run_id || crypto.randomUUID(),
                role: 'ai',
                // Sự kiện cuối có thẩm quyền; văn bản stream chỉ là bản xem trước của nó.
                content: event.reply || '',
                sources: Array.isArray(event.sources) ? event.sources : [],
                pending_action: pending,
                clarification: normalizeClarification(event.clarification),
                food_gap: normalizeFoodGap(event.food_gap),
                illustrations: Array.isArray(event.illustrations) ? event.illustrations : [],
                suggested_mode: event.suggested_mode === 'plan' ? 'plan' : null,
                status: event.status,
                timestamp: new Date().toISOString(),
              }
              if (streamingIndex >= 0) messages.value.splice(streamingIndex, 1, final)
              else messages.value.push(final)
              streamingIndex = -1
            } else if (event.type === 'error') {
              const errMsg =
                event.reply || event.detail || 'Đã xảy ra lỗi khi xử lý yêu cầu.'
              // Banner dành cho lỗi ngoài một lượt chạy (HTTP, xác thực, dịch vụ ngừng); câu trả lời
              // của lượt chạy thất bại chỉ hiển thị một lần, dưới dạng tin nhắn của nó.
              if (!event.run_id) error.value = errMsg
              const failed: ChatMessage = {
                id: streamingIndex >= 0 ? messages.value[streamingIndex].id : event.run_id || crypto.randomUUID(),
                role: 'ai',
                content: errMsg,
                sources: Array.isArray(event.sources) ? event.sources : [],
                status: 'failed',
                timestamp: new Date().toISOString(),
              }
              // Giống tin nhắn cuối, nó thay bản xem trước đang stream thay vì thêm một bản sao.
              if (streamingIndex >= 0) messages.value.splice(streamingIndex, 1, failed)
              else messages.value.push(failed)
              streamingIndex = -1
            }
          } catch {
            // Bỏ qua frame SSE sai định dạng
          }
        }
      }

      await loadSessions()
    } catch (err) {
      if (controller.signal.aborted) {
        // Người dùng nhấn dừng: giữ những gì đã hiển thị và đánh dấu là đã dừng.
        if (streamingIndex >= 0) messages.value[streamingIndex].status = 'stopped'
        else messages.value.push({ id: crypto.randomUUID(), role: 'ai', content: '', status: 'stopped', timestamp: new Date().toISOString() })
      } else {
        const msg = err instanceof Error ? err.message : 'Lỗi kết nối với Agent.'
        error.value = msg
        if (streamingIndex >= 0) messages.value[streamingIndex].status = 'failed'
      }
    } finally {
      if (streamController === controller) {
        streamController = null
        streamRunId = null
      }
      isStreaming.value = false
      activeNode.value = null
    }
  }

  /** Huỷ câu trả lời đang chạy: báo server dừng lượt (nếu đã biết run_id) rồi đóng stream. Lỗi khi huỷ (lượt vừa
   *  xong, đang lưu thao tác đã xác nhận) không chặn việc đóng stream; server vẫn dừng khi thấy client rời đi. */
  async function stopStreaming(): Promise<void> {
    const controller = streamController
    const runId = streamRunId
    if (runId) {
      await authFetch(`/api/v1/chat/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' }).catch(() => undefined)
    }
    controller?.abort()
  }

  /** Bản ghi đã lưu của hành động đã duyệt (output của lệnh ghi mang action_id của nó). */
  function savedRecord(result: ChatResponse, actionId: string): { id: string; version_id: number } | null {
    const output = result.tool_outputs?.find((o) => o.action_id === actionId && o.ok)?.output as Record<string, unknown> | undefined
    return output && typeof output.id === 'string' && typeof output.version_id === 'number'
      ? { id: output.id, version_id: output.version_id }
      : null
  }

  /** Sau khi lưu thành công: tải ảnh của người dùng hoặc nhập ảnh tra cứu đã chọn lên Cloudinary. */
  async function attachImage(action: PendingAction, result: ChatResponse, extras: ConfirmExtras, current: () => boolean): Promise<void> {
    const kind = MEDIA_TARGET[action.tool]
    const wantsPhoto = Boolean(extras.photo) && (kind === 'meals' || kind === 'trainings')
    const wantsImport = Boolean(extras.imageSource) && (kind === 'foods' || kind === 'exercises')
    if (!kind || (!wantsPhoto && !wantsImport)) return
    const saved = savedRecord(result, action.action_id)
    const note = (content: string, failed = false) => current() && messages.value.push({
      id: crypto.randomUUID(), role: 'ai', content, status: failed ? 'failed' : 'completed', timestamp: new Date().toISOString(),
    })
    if (!saved) {
      note('Đã lưu bản ghi nhưng chưa xác định được bản ghi để gắn ảnh. Bạn có thể thêm ảnh trong mục Ảnh.', true)
      return
    }
    isSavingImage.value = true
    if (current()) activeNode.value = 'media'
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
      // Bản thân bản ghi đã được lưu; chỉ ảnh bị lỗi.
      note(`Đã lưu bản ghi, nhưng chưa lưu được ảnh: ${err instanceof Error ? err.message : 'lỗi không xác định'}. Bạn có thể thử lại trong mục Ảnh.`, true)
    } finally {
      isSavingImage.value = false
    }
  }

  async function confirmAction(decision: 'approve' | 'reject', extras: ConfirmExtras = {}): Promise<void> {
    if (!pendingAction.value || isConfirming.value || isStreaming.value || isLoadingHistory.value) return
    const action = pendingAction.value
    const generation = viewGeneration
    const sessionId = activeSessionId.value
    const current = () => generation === viewGeneration && activeSessionId.value === sessionId
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
          ...(decision === 'approve' && extras.payload ? { payload: extras.payload } : {}),
        }),
      })

      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}))
        throw new Error(detail?.detail || 'Không thể xác nhận thao tác.')
      }

      const result: ChatResponse = await resp.json()
      if (current()) {
        pendingAction.value = result.pending_action || null
        // Yêu cầu người dùng vừa trả lời không còn cần xác nhận; huy hiệu của nó cho biết đã quyết định gì.
        const asked = messages.value.find((m) => m.status === 'pending_confirmation' && m.pending_action?.action_id === action.action_id)
        if (asked) asked.status = decision === 'reject' ? 'rejected' : result.status === 'failed' ? 'completed' : 'confirmed'

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
      }

      if (decision === 'approve' && result.status !== 'failed') {
        await attachImage(action, result, extras, current)
      }

      await loadSessions()
    } catch (err) {
      if (current()) error.value = err instanceof Error ? err.message : 'Xác nhận thao tác thất bại.'
    } finally {
      isConfirming.value = false
      if (current()) activeNode.value = null
    }
  }

  /** Nút "Hỏi ở chế độ Plan": bật chế độ Plan cho phiên rồi gửi lại đúng câu hỏi. */
  async function askInPlan(text: string): Promise<void> {
    if (isStreaming.value) return
    setChatMode('plan')
    await sendMessage(text)
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
    chatMode,
    setChatMode,
    askInPlan,
  }
}

