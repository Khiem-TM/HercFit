import { computed, ref, shallowRef } from 'vue'
import { until } from '@vueuse/core'
import type { RemoteAudioTrack, Room } from 'livekit-client'
import { useAuth } from '@/composables/useAuth'
import { useChat } from '@/composables/useChat'
import { voiceDecision } from '@/features/voice/commands'

/**
 * Lớp hội thoại giọng nói. LiveKit lo micro, nhận dạng và đọc; mỗi lượt nói vẫn chạy qua useChat như khi gõ.
 * Giao thức với backend/voice/worker.py: worker gọi RPC `hercfit.turn` kèm câu vừa nghe (trang trả loại câu đệm),
 * trang chạy lượt chat rồi gửi câu trả lời cuối trên text stream `hercfit.reply`; worker viết lại thành lời nói rồi
 * đọc. RPC `hercfit.cancel` khi người dùng nói chen. Phụ đề lấy từ text stream `lk.transcription` của LiveKit.
 */
export type VoiceState = 'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking'
export interface VoiceCaption { who: 'user' | 'agent'; text: string }

// Worker chưa chạy thì không agent nào vào phòng: báo lỗi thay vì chờ mãi.
const AGENT_JOIN_TIMEOUT_MS = 12000
// Lượt vừa bị nói chen cần một nhịp để đóng trước khi lượt mới bắt đầu.
const BUSY_WAIT_MS = 5000
const BUSY_REPLY = 'Mình đang xử lý dở yêu cầu trước, bạn nói lại sau giây lát nhé.'
// Mức âm (0..1, đã làm mượt) để coi là trợ lý đang thực sự phát tiếng; giữ trạng thái "đang nói" thêm chừng này
// sau tiếng cuối để chỗ ngắt giữa hai câu không làm dock nhấp nháy sang "đang suy nghĩ".
const SPEAKING_LEVEL = 0.02
const SPEAKING_HOLD_MS = 700
const CAPTION_CHARS = 180

const connection = ref<'idle' | 'connecting' | 'connected'>('idle')
const agentState = ref('')
const turnActive = ref(false)
const muted = ref(false)
const userLevel = ref(0)
const agentLevel = ref(0)
const agentAudible = ref(false)
const caption = shallowRef<VoiceCaption | null>(null)

let room: Room | null = null
let joinTimer: ReturnType<typeof setTimeout> | undefined
let frame = 0
let loudAt = 0
let meters: { user?: () => number; agent?: () => number; cleanup: Array<() => Promise<void>> } = { cleanup: [] }

const voiceState = computed<VoiceState>(() => {
  if (connection.value === 'idle') return 'idle'
  if (connection.value === 'connecting' || !agentState.value) return 'connecting'
  if (agentState.value === 'speaking' && agentAudible.value) return 'speaking'
  if (turnActive.value || agentState.value === 'thinking' || agentState.value === 'speaking') return 'thinking'
  return 'listening'
})

function tail(text: string): string {
  const clean = text.replace(/\s+/g, ' ').trim()
  return clean.length > CAPTION_CHARS ? '…' + clean.slice(-CAPTION_CHARS) : clean
}

/** Mức âm làm mượt: lên ngay theo tiếng nói, xuống dần (không nhấp nháy giữa các từ). */
function follow(level: { value: number }, read?: () => number): void {
  const next = read ? Math.min(1, read() * 4) : 0
  level.value = next > level.value ? next : level.value * 0.86
}

function tick(now: number): void {
  follow(userLevel, muted.value ? undefined : meters.user)
  follow(agentLevel, meters.agent)
  if (agentLevel.value > SPEAKING_LEVEL) loudAt = now
  const audible = now - loudAt < SPEAKING_HOLD_MS
  if (audible !== agentAudible.value) agentAudible.value = audible
  frame = requestAnimationFrame(tick)
}

export function useVoice() {
  const { authFetch } = useAuth()
  const { isStreaming, isConfirming, isLoadingHistory, pendingAction, error, sendMessage, confirmAction, stopStreaming } = useChat()
  const busy = computed(() => isStreaming.value || isConfirming.value || isLoadingHistory.value)

  async function runTurn(current: Room, turnId: string, text: string, decision: 'approve' | 'reject' | null): Promise<void> {
    turnActive.value = true
    let reply = ''
    const speak = (content: string) => { reply = content }
    try {
      await until(busy).toBe(false, { timeout: BUSY_WAIT_MS })
      if (busy.value) reply = BUSY_REPLY
      else if (decision && pendingAction.value) await confirmAction(decision, {}, speak)
      else await sendMessage(text, { speak })
    } finally {
      try {
        const writer = await current.localParticipant.streamText({ topic: 'hercfit.reply', attributes: { turn_id: turnId } })
        if (reply) await writer.write(reply)
        await writer.close()
      } catch {
        // Phòng đã đóng: worker tự hết hạn lượt.
      }
      turnActive.value = false
    }
  }

  async function startVoice(): Promise<void> {
    if (connection.value !== 'idle') return
    connection.value = 'connecting'
    error.value = null
    // Thư viện LiveKit chỉ được tải khi người dùng bật micro lần đầu.
    const { Room, RoomEvent, Track, createAudioAnalyser } = await import('livekit-client')
    const current = room = new Room()
    try {
      const resp = await authFetch('/api/v1/chat/voice/token', { method: 'POST' })
      const grant = await resp.json().catch(() => ({}))
      if (!resp.ok) throw new Error(grant?.detail || 'Không bật được trò chuyện bằng giọng nói.')

      current
        .on(RoomEvent.TrackSubscribed, (track) => {
          if (track.kind !== Track.Kind.Audio) return
          document.body.appendChild(track.attach())
          if (track.source === Track.Source.Microphone || !meters.agent) {
            const analyser = createAudioAnalyser(track as RemoteAudioTrack, { cloneTrack: true })
            meters.agent = analyser.calculateVolume
            meters.cleanup.push(analyser.cleanup)
          }
        })
        .on(RoomEvent.TrackUnsubscribed, (track) => track.detach().forEach((element) => element.remove()))
        .on(RoomEvent.ParticipantAttributesChanged, (changed, participant) => {
          const state = participant.isAgent ? changed['lk.agent.state'] : undefined
          if (!state || room !== current) return
          clearTimeout(joinTimer)
          agentState.value = state
        })
        .on(RoomEvent.Disconnected, () => { if (room === current) reset() })
      current.registerTextStreamHandler('lk.transcription', async (reader, participant) => {
        const who = participant.identity === current.localParticipant.identity ? 'user' : 'agent'
        if (who === 'user') {
          // Mỗi bản nhận dạng tạm thời là một stream chứa toàn câu đến lúc đó.
          const text = await reader.readAll().catch(() => '')
          if (text.trim() && room === current) caption.value = { who, text: tail(text) }
          return
        }
        let text = ''
        try {
          for await (const chunk of reader) {
            text += chunk
            if (room === current) caption.value = { who, text: tail(text) }
          }
        } catch {
          // Lời nói bị ngắt giữa chừng: giữ phần đã hiện.
        }
      })
      current.registerRpcMethod('hercfit.turn', async (data) => {
        const { turn_id, text } = JSON.parse(data.payload)
        const decision = pendingAction.value ? voiceDecision(text) : null
        void runTurn(current, turn_id, text, decision)
        return JSON.stringify({ kind: decision ?? 'chat' })
      })
      current.registerRpcMethod('hercfit.cancel', async () => {
        void stopStreaming()
        return 'ok'
      })

      await current.connect(grant.url, grant.token)
      await current.localParticipant.setMicrophoneEnabled(true)
      if (room !== current) return void current.disconnect()
      connection.value = 'connected'
      const mic = current.localParticipant.getTrackPublication(Track.Source.Microphone)?.audioTrack
      if (mic) {
        const analyser = createAudioAnalyser(mic, { cloneTrack: true })
        meters.user = analyser.calculateVolume
        meters.cleanup.push(analyser.cleanup)
      }
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(tick)
      joinTimer = setTimeout(() => {
        if (room !== current || agentState.value) return
        error.value = 'Trợ lý giọng nói chưa sẵn sàng. Bạn thử lại sau nhé.'
        void stopVoice()
      }, AGENT_JOIN_TIMEOUT_MS)
    } catch (err) {
      if (room !== current) return
      error.value = err instanceof DOMException && err.name === 'NotAllowedError'
        ? 'Trình duyệt chưa được cấp quyền dùng micro.'
        : err instanceof Error ? err.message : 'Không bật được trò chuyện bằng giọng nói.'
      await stopVoice()
    }
  }

  function reset(): void {
    clearTimeout(joinTimer)
    cancelAnimationFrame(frame)
    meters.cleanup.forEach((cleanup) => void cleanup().catch(() => undefined))
    meters = { cleanup: [] }
    room = null
    connection.value = 'idle'
    agentState.value = ''
    turnActive.value = false
    muted.value = false
    userLevel.value = 0
    agentLevel.value = 0
    agentAudible.value = false
    caption.value = null
  }

  async function stopVoice(): Promise<void> {
    const current = room
    reset()
    await current?.disconnect()
  }

  function toggleVoice(): Promise<void> {
    return connection.value === 'idle' ? startVoice() : stopVoice()
  }

  async function toggleMute(): Promise<void> {
    if (!room) return
    muted.value = !muted.value
    await room.localParticipant.setMicrophoneEnabled(!muted.value).catch(() => { muted.value = !muted.value })
  }

  return { voiceState, userLevel, agentLevel, caption, muted, toggleVoice, stopVoice, toggleMute }
}
