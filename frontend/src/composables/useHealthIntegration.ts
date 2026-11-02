import { computed, shallowRef } from 'vue'
import { useAuth } from '@/composables/useAuth'
import type { HealthConnection } from '@/types/api'

const BASE = '/api/integrations/google-health'

async function detail(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch { /* non-JSON error body */ }
  return fallback
}

/** Kết nối Google Health: trạng thái, đồng ý OAuth, consent của trợ lý, và ngắt kết nối. */
export function useHealthIntegration() {
  const { authFetch } = useAuth()
  const connection = shallowRef<HealthConnection | null>(null)
  const loading = shallowRef(false)
  const busy = shallowRef(false)
  const error = shallowRef<string | null>(null)

  const needsReauth = computed(() => connection.value?.status === 'NEEDS_REAUTH')
  const isConnected = computed(() => connection.value?.status === 'ACTIVE' || needsReauth.value)

  async function refresh(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const response = await authFetch(BASE)
      if (!response.ok) throw new Error(await detail(response, 'Không đọc được trạng thái kết nối.'))
      connection.value = await response.json()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Không đọc được trạng thái kết nối.'
    } finally {
      loading.value = false
    }
  }

  async function run(request: () => Promise<Response>, fallback: string): Promise<Response | null> {
    busy.value = true
    error.value = null
    try {
      const response = await request()
      if (!response.ok) throw new Error(await detail(response, fallback))
      return response
    } catch (err) {
      error.value = err instanceof Error ? err.message : fallback
      return null
    } finally {
      busy.value = false
    }
  }

  /** Mở màn hình đồng ý của Google; callback của backend quay về /chat?integration=google-health. */
  async function connect(shareWithAssistant: boolean): Promise<void> {
    const response = await run(() => authFetch(`${BASE}/connect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ share_with_assistant: shareWithAssistant }),
    }), 'Không bắt đầu được kết nối Google Health.')
    if (!response) return
    const { authorization_url: url } = await response.json()
    window.location.assign(url)
  }

  async function setConsent(shareWithAssistant: boolean, sensitive?: boolean): Promise<void> {
    const response = await run(() => authFetch(BASE, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ share_with_assistant: shareWithAssistant, share_sensitive_with_assistant: sensitive }),
    }), 'Không cập nhật được quyền chia sẻ.')
    if (response) connection.value = await response.json()
  }

  async function disconnect(purgeData: boolean): Promise<void> {
    const response = await run(() => authFetch(`${BASE}?purge_data=${purgeData}`, { method: 'DELETE' }),
      'Không ngắt được kết nối.')
    if (response) connection.value = await response.json()
  }

  return { connection, loading, busy, error, isConnected, needsReauth, refresh, connect, setConsent, disconnect }
}

export const CONNECT_RESULT_TEXT: Record<string, { tone: 'ok' | 'error'; text: string }> = {
  connected: { tone: 'ok', text: 'Đã kết nối Google Health. Lần đồng bộ đầu tiên đang chạy.' },
  denied: { tone: 'error', text: 'Bạn chưa cấp quyền đọc dữ liệu sức khoẻ nên chưa thể kết nối.' },
  wrong_account: { tone: 'error', text: 'Hãy chọn đúng tài khoản Gmail bạn dùng để đăng nhập HercFit.' },
  error: { tone: 'error', text: 'Kết nối Google Health chưa thành công. Vui lòng thử lại.' },
}
