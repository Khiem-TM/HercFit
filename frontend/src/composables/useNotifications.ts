import { computed, shallowRef } from 'vue'
import type { AppNotification } from '@/types/api'
import { useAuth } from '@/composables/useAuth'
import { createNotificationApi } from '@/features/notifications/api'
import { createNotificationStream, streamUrl, type StreamEvent } from '@/features/notifications/stream'

export const POLL_MS = 5 * 60 * 1000

// Trạng thái dùng chung ở mức module (như useAuth/useChat): chuông, toast và bảng cài đặt cùng thấy một hộp thư.
const items = shallowRef<AppNotification[]>([])
const unread = shallowRef(0)
const loading = shallowRef(false)
const error = shallowRef<string | null>(null)
/** WebSocket đang mở: thông báo tới tức thì, không cần polling. */
const live = shallowRef(false)
const arrivals = new Set<(item: AppNotification) => void>()
let watchers = 0
let timer: ReturnType<typeof setTimeout> | undefined
let onVisible: (() => void) | undefined
let stream: { stop: () => void } | undefined

/** Nghe thông báo mới tới qua WebSocket (cho toast); trả hàm huỷ. */
export function onArrival(listener: (item: AppNotification) => void): () => void {
  arrivals.add(listener)
  return () => { arrivals.delete(listener) }
}

/** Áp một sự kiện WebSocket vào hộp thư dùng chung; trả về thông báo mới (nếu có) để báo cho người nghe. */
export function applyEvent(event: StreamEvent, list: AppNotification[]): { items: AppNotification[]; unread?: number;
  arrived?: AppNotification } {
  switch (event.type) {
    case 'notification.created': {
      const known = list.some(item => item.id === event.notification.id)
      return { items: [event.notification, ...list.filter(item => item.id !== event.notification.id)],
               unread: event.unread, arrived: known ? undefined : event.notification }
    }
    case 'notification.seen':
      return { items: list.map(item => (item.id === event.id ? { ...item, seen_at: event.seen_at ?? item.seen_at } : item)),
               unread: event.unread }
    case 'notification.dismissed':
      return { items: list.filter(item => item.id !== event.id), unread: event.unread }
    default:
      return { items: list }
  }
}

/** Hộp thư thông báo: WebSocket khi có thể; mất kết nối thì tải mỗi 5 phút khi tab đang hiện, và khi tab hiện lại. */
export function useNotifications() {
  const auth = useAuth()
  const api = createNotificationApi((url, init) => auth.authFetch(url, init))

  async function refresh() {
    loading.value = true
    try {
      const list = await api.list()
      items.value = list.items
      unread.value = list.unread
      error.value = null
    } catch (failure) {
      error.value = failure instanceof Error ? failure.message : 'Không tải được thông báo.'
    } finally {
      loading.value = false
    }
  }

  function schedule() {
    clearTimeout(timer)
    if (live.value || !watchers) return
    timer = setTimeout(async () => {
      if (typeof document === 'undefined' || !document.hidden) await refresh()
      schedule()
    }, POLL_MS)
  }

  function receive(event: StreamEvent) {
    if (event.type === 'ready' || event.type === 'resync') { void refresh(); return }
    const next = applyEvent(event, items.value)
    items.value = next.items
    if (next.unread !== undefined) unread.value = next.unread
    if (next.arrived) arrivals.forEach(listener => listener(next.arrived!))
  }

  function connect() {
    if (typeof WebSocket === 'undefined' || typeof location === 'undefined') return
    stream = createNotificationStream({
      url: streamUrl(location), token: () => auth.accessToken.value, refresh: auth.refreshSession, onEvent: receive,
      onState: state => {
        live.value = state === 'open'
        if (live.value) clearTimeout(timer)
        else schedule()
      },
    })
  }

  /** Bắt đầu theo dõi; trả hàm dừng (gọi trong onUnmounted). */
  function start(): () => void {
    watchers += 1
    if (watchers === 1) {
      void refresh()
      schedule()
      connect()
      if (typeof document !== 'undefined') {
        onVisible = () => { if (!document.hidden && !live.value) void refresh() }
        document.addEventListener('visibilitychange', onVisible)
      }
    }
    return () => {
      watchers = Math.max(0, watchers - 1)
      if (watchers) return
      clearTimeout(timer)
      timer = undefined
      stream?.stop()
      stream = undefined
      live.value = false
      if (onVisible && typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisible)
      onVisible = undefined
    }
  }

  async function markSeen(id: string) {
    const updated = await api.seen(id)
    items.value = items.value.map(item => (item.id === id ? updated : item))
    unread.value = items.value.filter(item => !item.seen_at).length
  }

  async function dismiss(id: string) {
    await api.dismiss(id)
    items.value = items.value.filter(item => item.id !== id)
    unread.value = items.value.filter(item => !item.seen_at).length
  }

  async function runReview() {
    const list = await api.runReview()
    items.value = list.items
    unread.value = list.unread
  }

  return { items: computed(() => items.value), unread: computed(() => unread.value), live: computed(() => live.value),
           loading, error, api, refresh, start, markSeen, dismiss, runReview }
}
