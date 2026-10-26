import { computed, ref } from 'vue'
import type {
  BodyMetricCreatePayload,
  BodyMetricRead,
  GoalRead,
  OnboardingPayload,
  UserProfile,
  UserUpdatePayload,
} from '@/types/api'

const accessToken = ref<string | null>(null)
const user = ref<UserProfile | null>(null)
const latestBodyMetric = ref<BodyMetricRead | null>(null)
const currentGoal = ref<GoalRead | null>(null)
const isLoading = ref<boolean>(true)
const error = ref<string | null>(null)
let bootstrapPromise: Promise<boolean> | null = null
// One refresh at a time: parallel 401s share it, and other tabs wait on a Web Lock.
// The backend rotates refresh tokens and treats reuse of an old one as theft.
let refreshPromise: Promise<boolean> | null = null
const REFRESH_LOCK = 'hercfit-auth-refresh'

function getCanonicalOrigin(): string {
  const { protocol, hostname, port } = window.location
  const normalizedHost = hostname === '127.0.0.1' ? 'localhost' : hostname
  return `${protocol}//${normalizedHost}${port ? `:${port}` : ''}`
}

export function useAuth() {
  const isAuthenticated = computed(() => Boolean(accessToken.value && user.value))

  async function completeOAuthCallback(code: string, state: string): Promise<boolean> {
    try {
      const redirectUri = `${getCanonicalOrigin()}/auth/callback`
      const query = new URLSearchParams({
        code,
        state,
        redirect_uri: redirectUri,
      })
      const resp = await fetch(`/api/auth/login?${query.toString()}`, {
        method: 'GET',
        credentials: 'include',
        headers: {
          Accept: 'application/json',
        },
      })
      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}))
        error.value = detail?.detail || 'Xác thực Google OAuth thất bại.'
        accessToken.value = null
        user.value = null
        return false
      }
      const data = await resp.json()
      accessToken.value = data.access_token || null
      user.value = data.user || null
      window.history.replaceState({}, '', '/chat')
      window.dispatchEvent(new PopStateEvent('popstate'))
      return Boolean(accessToken.value && user.value)
    } catch {
      error.value = 'Không thể kết nối tới máy chủ xác thực.'
      accessToken.value = null
      user.value = null
      return false
    }
  }

  async function requestRefresh(): Promise<boolean> {
    try {
      const resp = await fetch('/api/auth/refresh', {
        method: 'POST',
        credentials: 'include',
        headers: {
          Accept: 'application/json',
        },
      })
      if (!resp.ok) {
        accessToken.value = null
        user.value = null
        return false
      }
      const data = await resp.json()
      accessToken.value = data.access_token || null
      user.value = data.user || null
      return Boolean(accessToken.value && user.value)
    } catch {
      accessToken.value = null
      user.value = null
      return false
    }
  }

  function refreshSession(): Promise<boolean> {
    if (refreshPromise) return refreshPromise
    refreshPromise = (async () => {
      try {
        const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined
        return locks?.request ? await locks.request(REFRESH_LOCK, () => requestRefresh()) : await requestRefresh()
      } finally {
        refreshPromise = null
      }
    })()
    return refreshPromise
  }

  async function authFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers || {})
    if (accessToken.value) {
      headers.set('Authorization', `Bearer ${accessToken.value}`)
    }
    let resp = await fetch(input, {
      ...init,
      credentials: 'include',
      headers,
    })
    if (resp.status === 401) {
      const refreshed = await refreshSession()
      if (refreshed && accessToken.value) {
        const retryHeaders = new Headers(init.headers || {})
        retryHeaders.set('Authorization', `Bearer ${accessToken.value}`)
        resp = await fetch(input, {
          ...init,
          credentials: 'include',
          headers: retryHeaders,
        })
      }
    }
    return resp
  }

  async function fetchProfileDetails(): Promise<void> {
    if (!accessToken.value) return
    try {
      const [profileResp, metricResp, goalResp] = await Promise.all([
        authFetch('/api/profile'),
        authFetch('/api/body-metrics/latest'),
        authFetch('/api/goals/current'),
      ])
      if (profileResp.ok) {
        user.value = await profileResp.json()
      }
      if (metricResp.ok) {
        latestBodyMetric.value = await metricResp.json()
      } else if (metricResp.status === 404) {
        latestBodyMetric.value = null
      }
      if (goalResp.ok) {
        currentGoal.value = await goalResp.json()
      } else if (goalResp.status === 404) {
        currentGoal.value = null
      }
    } catch {
      // Non-fatal auxiliary fetch failure
    }
  }

  async function bootstrapAuth(force = false): Promise<boolean> {
    if (bootstrapPromise && !force) {
      return bootstrapPromise
    }
    isLoading.value = true
    error.value = null
    bootstrapPromise = (async () => {
      try {
        const params = new URLSearchParams(window.location.search)
        const code = params.get('code')
        const state = params.get('state')
        const oauthError = params.get('error')

        if (oauthError) {
          error.value = `Google OAuth từ chối truy cập: ${oauthError}`
          window.history.replaceState({}, '', '/chat')
          window.dispatchEvent(new PopStateEvent('popstate'))
          return false
        }

        const ok =
          code && state
            ? await completeOAuthCallback(code, state)
            : await refreshSession()

        if (ok) {
          await fetchProfileDetails()
        }
        return ok
      } finally {
        isLoading.value = false
      }
    })()
    return bootstrapPromise
  }

  function loginWithGoogle(): void {
    const origin = getCanonicalOrigin()
    const redirectUri = `${origin}/auth/callback`
    window.location.href = `${origin}/api/auth/login?mode=oauth&redirect_uri=${encodeURIComponent(redirectUri)}`
  }

  async function updateProfile(payload: UserUpdatePayload): Promise<UserProfile> {
    const resp = await authFetch('/api/profile', {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': crypto.randomUUID(),
      },
      body: JSON.stringify(payload),
    })
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}))
      throw new Error(detail?.detail || 'Không thể cập nhật thông tin cá nhân.')
    }
    const updated: UserProfile = await resp.json()
    user.value = updated
    return updated
  }

  async function recordBodyMetric(payload: BodyMetricCreatePayload): Promise<BodyMetricRead> {
    const resp = await authFetch('/api/body-metrics', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': crypto.randomUUID(),
      },
      body: JSON.stringify(payload),
    })
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}))
      throw new Error(detail?.detail || 'Không thể lưu chỉ số cơ thể.')
    }
    const created: BodyMetricRead = await resp.json()
    latestBodyMetric.value = created
    return created
  }

  async function completeOnboarding(payload: OnboardingPayload, idempotencyKey: string): Promise<void> {
    const resp = await authFetch('/api/profile/onboarding', {
      method: 'POST',
      signal: AbortSignal.timeout(30000),
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(payload),
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}))
      let message = 'Không thể lưu thông tin. Vui lòng thử lại.'
      if (resp.status === 409) message = 'Hồ sơ hoặc mục tiêu đã thay đổi. Vui lòng tải lại trang để kiểm tra trước khi tiếp tục.'
      else if (Array.isArray(data.detail)) message = 'Một số thông tin chưa hợp lệ. Vui lòng kiểm tra lại họ tên, số đo và ngày mục tiêu.'
      else if (typeof data.detail === 'string') message = data.detail
      const failure = new Error(message) as Error & { status: number }
      failure.status = resp.status
      throw failure
    }
    const profile: UserProfile = await resp.json()
    // Refresh auxiliary facts before routing away from onboarding.
    await fetchProfileDetails()
    user.value = profile
  }

  /** Download every record the backend holds for this account (JSON). */
  async function exportData(): Promise<void> {
    const resp = await authFetch('/api/profile/export')
    if (!resp.ok) throw new Error('Không xuất được dữ liệu. Vui lòng thử lại.')
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `hercfit-export-${new Date().toISOString().slice(0, 10)}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  /** Permanently erase conversations (agent) and then the account (backend). */
  async function eraseAccount(confirmEmail: string): Promise<void> {
    const conversations = await authFetch('/api/v1/chat/me', { method: 'DELETE' })
    if (!conversations.ok) {
      throw new Error('Chưa xoá được lịch sử trò chuyện nên tài khoản chưa bị xoá. Vui lòng thử lại.')
    }
    const resp = await authFetch('/api/profile/erase', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm_email: confirmEmail }),
    })
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}))
      throw new Error(typeof detail?.detail === 'string' ? detail.detail : 'Không xoá được tài khoản.')
    }
    accessToken.value = null
    user.value = null
    latestBodyMetric.value = null
    currentGoal.value = null
    bootstrapPromise = null
    refreshPromise = null
    window.history.pushState({}, '', '/')
    window.dispatchEvent(new PopStateEvent('popstate'))
  }

  async function logout(): Promise<void> {
    try {
      if (accessToken.value) {
        await authFetch('/api/auth/logout', { method: 'POST' })
      }
    } finally {
      accessToken.value = null
      user.value = null
      latestBodyMetric.value = null
      currentGoal.value = null
      bootstrapPromise = null
      refreshPromise = null
      window.history.pushState({}, '', '/')
      window.dispatchEvent(new PopStateEvent('popstate'))
    }
  }

  return {
    accessToken,
    user,
    latestBodyMetric,
    currentGoal,
    isAuthenticated,
    isLoading,
    error,
    bootstrapAuth,
    loginWithGoogle,
    fetchProfileDetails,
    completeOnboarding,
    updateProfile,
    recordBodyMetric,
    exportData,
    eraseAccount,
    logout,
    authFetch,
  }
}
