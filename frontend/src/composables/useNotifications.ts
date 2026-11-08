import { computed, shallowRef } from 'vue'
import type { AppNotification } from '@/types/api'
import { useAuth } from '@/composables/useAuth'
import { createNotificationApi } from '@/features/notifications/api'

export const POLL_MS = 5 * 60 * 1000

// Trạng thái dùng chung ở mức module (như useAuth/useChat): chuông và bảng cài đặt cùng thấy một hộp thư.
const items = shallowRef<AppNotification[]>([])
const unread = shallowRef(0)
const loading = shallowRef(false)
const error = shallowRef<string | null>(null)
let watchers = 0
let timer: ReturnType<typeof setTimeout> | undefined
let onVisible: (() => void) | undefined

/** Hộp thư thông báo: tải khi mở, mỗi 5 phút khi tab đang hiện, và ngay khi tab hiện lại. */
export function useNotifications() {
  const api = createNotificationApi((url, init) => useAuth().authFetch(url, init))

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
    timer = setTimeout(async () => {
      if (typeof document === 'undefined' || !document.hidden) await refresh()
      if (watchers) schedule()
    }, POLL_MS)
  }

  /** Bắt đầu theo dõi; trả hàm dừng (gọi trong onUnmounted). */
  function start(): () => void {
    watchers += 1
    if (watchers === 1) {
      void refresh()
      schedule()
      if (typeof document !== 'undefined') {
        onVisible = () => { if (!document.hidden) void refresh() }
        document.addEventListener('visibilitychange', onVisible)
      }
    }
    return () => {
      watchers = Math.max(0, watchers - 1)
      if (watchers) return
      clearTimeout(timer)
      timer = undefined
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

  async function runBriefing() {
    const list = await api.runBriefing()
    items.value = list.items
    unread.value = list.unread
  }

  return { items: computed(() => items.value), unread: computed(() => unread.value), loading, error, api,
           refresh, start, markSeen, dismiss, runBriefing }
}
