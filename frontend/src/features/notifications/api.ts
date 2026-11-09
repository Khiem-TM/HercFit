import type { NotificationList, NotificationPreferences, AppNotification } from '@/types/api'
import { type Fetcher, HealthApiError } from '@/features/health-integration/api'

const BASE = '/api/v2/notifications'

async function failure(response: Response, fallback: string): Promise<HealthApiError> {
  try {
    const detail = (await response.json())?.detail
    if (typeof detail === 'string') return new HealthApiError(detail, response.status)
  } catch { /* thân lỗi không phải JSON */ }
  return new HealthApiError(fallback, response.status)
}

/** Hộp thư trong ứng dụng và tuỳ chọn thông báo chủ động; lệnh ghi mang Idempotency-Key. */
export function createNotificationApi(fetcher: Fetcher) {
  async function call<T>(url: string, init: RequestInit | undefined, fallback: string): Promise<T> {
    const response = await fetcher(url, init)
    if (!response.ok) throw await failure(response, fallback)
    return (response.status === 204 ? undefined : await response.json()) as T
  }
  const post = (body?: unknown, method = 'POST'): RequestInit => ({
    method, headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  const item = (id: string, action: 'seen' | 'dismiss') => `${BASE}/${encodeURIComponent(id)}:${action}`

  return {
    list: (unreadOnly = false) => call<NotificationList>(`${BASE}?status=${unreadOnly ? 'unread' : 'all'}`, undefined,
      'Không tải được thông báo.'),
    seen: (id: string) => call<AppNotification>(item(id, 'seen'), post(), 'Không cập nhật được thông báo.'),
    dismiss: (id: string) => call<void>(item(id, 'dismiss'), post(), 'Không bỏ qua được thông báo.'),
    preferences: () => call<NotificationPreferences>(`${BASE}/preferences`, undefined, 'Không đọc được tuỳ chọn thông báo.'),
    savePreferences: (prefs: NotificationPreferences) => {
      const { timezone: _zone, ...body } = prefs
      return call<NotificationPreferences>(`${BASE}/preferences`, post(body, 'PUT'), 'Không lưu được tuỳ chọn thông báo.')
    },
    runReview: () => call<NotificationList>(`${BASE}/review:run`, post(), 'Chưa tạo được đánh giá hôm nay.'),
  }
}
