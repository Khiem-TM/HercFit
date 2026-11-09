import type { AppNotification } from '@/types/api'

/**
 * Kênh WebSocket thông báo (/api/v2/notifications/stream).
 *
 * Tin nhắn đầu tiên mang access token (không đặt token trong URL vì URL bị ghi log). Server đóng 4401 khi token
 * hết hạn: làm mới token rồi nối lại. Mất kết nối thì nối lại theo giãn cách tăng dần có jitter; quá STALE_MS
 * không nhận được gì (server ping mỗi 30 giây) thì coi như kết nối đã chết.
 */
export type StreamState = 'connecting' | 'open' | 'closed' | 'stopped'
export type StreamEvent =
  | { type: 'ready'; unread: number }
  | { type: 'notification.created'; notification: AppNotification; unread: number }
  | { type: 'notification.seen'; id: string; seen_at: string | null; unread: number }
  | { type: 'notification.dismissed'; id: string; unread: number }
  | { type: 'resync' }

export const UNAUTHORIZED = 4401
export const TOO_MANY = 4429
export const STALE_MS = 75_000
export const MAX_DELAY_MS = 30_000

interface SocketLike {
  onopen: ((event: unknown) => void) | null
  onmessage: ((event: { data: unknown }) => void) | null
  onclose: ((event: { code: number }) => void) | null
  onerror: ((event: unknown) => void) | null
  send(data: string): void
  close(code?: number, reason?: string): void
}

export interface StreamOptions {
  url: string
  token: () => string | null
  /** Làm mới access token; false khi phiên đã hết. */
  refresh: () => Promise<boolean>
  onEvent: (event: StreamEvent) => void
  onState?: (state: StreamState) => void
  WebSocketImpl?: new (url: string) => SocketLike
  random?: () => number
}

/** Giãn cách lần thử thứ `attempt` (0, 1, 2…): 1 s, 2 s, 4 s… tối đa 30 s, jitter trong nửa trên của khoảng. */
export function backoff(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(MAX_DELAY_MS, 1000 * 2 ** attempt)
  return Math.round(base / 2 + random() * (base / 2))
}

export function streamUrl(location: { protocol: string; host: string }): string {
  return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/v2/notifications/stream`
}

export function createNotificationStream(options: StreamOptions): { stop: () => void } {
  const Socket = options.WebSocketImpl ?? (WebSocket as unknown as new (url: string) => SocketLike)
  let socket: SocketLike | undefined
  let attempt = 0
  let rejected = 0
  let stopped = false
  let retry: ReturnType<typeof setTimeout> | undefined
  let stale: ReturnType<typeof setTimeout> | undefined

  const state = (value: StreamState) => options.onState?.(value)

  function schedule() {
    clearTimeout(retry)
    retry = setTimeout(connect, backoff(attempt++, options.random))
  }

  function alive() {
    clearTimeout(stale)
    stale = setTimeout(() => socket?.close(4000, 'stale'), STALE_MS)
  }

  async function reauthorize() {
    rejected += 1
    const ok = await options.refresh().catch(() => false)
    if (stopped) return
    if (!ok) { stop(); return }  // phiên đã hết: chờ người dùng đăng nhập lại
    if (rejected > 1) schedule()  // vẫn bị từ chối sau khi làm mới: giãn cách thay vì nối lại liên tục
    else connect()
  }

  function connect() {
    if (stopped) return
    const token = options.token()
    if (!token) { void reauthorize(); return }
    state('connecting')
    const current = new Socket(options.url)
    socket = current
    current.onopen = () => { current.send(JSON.stringify({ type: 'auth', token })); alive() }
    current.onmessage = message => {
      alive()
      let event: { type?: string }
      try { event = JSON.parse(String(message.data)) } catch { return }
      if (event.type === 'ping') return
      if (event.type === 'ready') { attempt = 0; rejected = 0; state('open') }
      options.onEvent(event as StreamEvent)
    }
    current.onerror = () => { /* onclose theo sau */ }
    current.onclose = event => {
      if (socket !== current) return
      clearTimeout(stale)
      socket = undefined
      if (stopped) return
      if (event.code === TOO_MANY) { stopped = true; state('stopped'); return }
      state('closed')
      if (event.code === UNAUTHORIZED) void reauthorize()
      else schedule()
    }
  }

  function stop() {
    stopped = true
    clearTimeout(retry)
    clearTimeout(stale)
    const current = socket
    socket = undefined
    current?.close(1000)
    state('stopped')
  }

  connect()
  return { stop }
}
