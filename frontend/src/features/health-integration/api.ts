import type {
  Capability, DataSource, DevicesRead, ExportConflict, ExportSwitch, HealthLogKind, OperationRead, OperationState,
  ScopeBundle,
} from '@/types/api'

export const V2 = '/api/v2'
const GH = `${V2}/integrations/google-health`
export const FINAL_STATES: OperationState[] = ['SUCCEEDED', 'PARTIAL', 'FAILED', 'UNCERTAIN', 'CANCELLED']

export type Fetcher = (input: string, init?: RequestInit) => Promise<Response>

export class HealthApiError extends Error {
  constructor(message: string, readonly status: number, readonly code: string | null = null,
              readonly extra: Record<string, unknown> = {}) {
    super(message)
  }
}

async function failure(response: Response, fallback: string): Promise<HealthApiError> {
  try {
    const body = await response.json()
    const detail = body?.detail
    if (typeof detail === 'string') return new HealthApiError(detail, response.status)
    if (detail && typeof detail === 'object') {
      return new HealthApiError(String(detail.message ?? fallback), response.status, detail.code ?? null, detail)
    }
  } catch { /* non-JSON error body */ }
  return new HealthApiError(fallback, response.status)
}

function json(body: unknown): RequestInit {
  return { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

/** Thin client for the health platform API; every call throws HealthApiError on failure. */
export function createHealthApi(fetcher: Fetcher) {
  async function call<T>(url: string, init: RequestInit | undefined, fallback: string): Promise<T> {
    const response = await fetcher(url, init)
    if (!response.ok) throw await failure(response, fallback)
    return (response.status === 204 ? undefined : await response.json()) as T
  }

  return {
    scopes: () => call<{ granted: string[]; bundles: ScopeBundle[] }>(`${GH}/scopes`, undefined,
      'Không đọc được quyền đã cấp.'),
    capabilities: () => call<{ ingest_mode: string; capabilities: Capability[] }>(`${GH}/capabilities`, undefined,
      'Không đọc được khả năng đồng bộ.'),
    devices: () => call<DevicesRead>(`${GH}/devices`, undefined, 'Không đọc được thiết bị và nguồn dữ liệu.'),
    startSync: () => call<{ operation_id: string; detail: string }>(`${GH}/sync-jobs`, { method: 'POST' },
      'Không bắt đầu được đồng bộ.'),
    operation: (id: string) => call<OperationRead>(`${V2}/operations/${id}`, undefined,
      'Không đọc được tiến độ.'),
    exportSwitch: () => call<ExportSwitch>(`${GH}/export`, undefined, 'Không đọc được trạng thái đồng bộ lên Google.'),
    /** One switch for syncing to Google. On may answer with Google's consent URL (one screen for every
     * missing permission); the callback then finishes turning it on. */
    setExportSwitch: (enabled: boolean) => call<ExportSwitch>(`${GH}/export`, { method: 'PUT', ...json({ enabled }) },
      'Không cập nhật được đồng bộ lên Google.'),
    conflicts: () => call<ExportConflict[]>(`${GH}/conflicts`, undefined, 'Không đọc được xung đột.'),
    resolveConflict: (id: string, resolution: 'KEEP_LOCAL' | 'ACCEPT_REMOTE') =>
      call<ExportConflict>(`${GH}/conflicts/${id}:resolve`, { method: 'POST', ...json({ resolution }) },
        'Không xử lý được xung đột.'),
    createLog: (kind: HealthLogKind, payload: Record<string, unknown>) =>
      call<Record<string, unknown>>(`${V2}/health/logs/${kind}`, { method: 'POST', ...json(payload) },
        'Không lưu được nhật ký.'),
    logs: (kind: HealthLogKind, limit = 5) =>
      call<{ items: Record<string, unknown>[]; next_cursor: string | null }>(
        `${V2}/health/logs/${kind}?limit=${limit}`, undefined, 'Không đọc được nhật ký.'),
  }
}

export type HealthApi = ReturnType<typeof createHealthApi>

/** Polls an operation until it reaches a final state (or `attempts` runs out). */
export async function waitForOperation(api: HealthApi, id: string, onUpdate: (op: OperationRead) => void, {
  attempts = 40, delayMs = 3000, sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms)),
} = {}): Promise<OperationRead | null> {
  let latest: OperationRead | null = null
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    latest = await api.operation(id)
    onUpdate(latest)
    if (FINAL_STATES.includes(latest.state)) return latest
    await sleep(delayMs)
  }
  return latest
}

export const OPERATION_TEXT: Record<OperationState, string> = {
  PENDING: 'Đang xếp hàng', RUNNING: 'Đang chạy', SUCCEEDED: 'Hoàn tất', PARTIAL: 'Hoàn tất một phần',
  FAILED: 'Thất bại', UNCERTAIN: 'Chưa xác minh được kết quả', CANCELLED: 'Đã huỷ',
}

export const CURSOR_TEXT: Record<string, string> = {
  COMPLETE: 'Đã đồng bộ', UNCLEAN: 'Có dữ liệu bị loại', INCOMPLETE: 'Chưa đọc hết', NOT_GRANTED: 'Chưa cấp quyền',
  UNSUPPORTED: 'Chưa hỗ trợ', PENDING: 'Chờ đồng bộ',
}

const PLATFORM_TEXT: Record<string, string> = {
  FITBIT: 'Fitbit', HEALTH_CONNECT: 'Health Connect', HEALTH_KIT: 'Apple Health', FIT: 'Google Fit',
  FITBIT_WEB_API: 'Fitbit (web)', NEST: 'Nest', GOOGLE_WEB_API: 'Google (web)',
  GOOGLE_PARTNER_INTEGRATION: 'Ứng dụng đối tác',
}
const METHOD_TEXT: Record<string, string> = {
  MANUAL: 'nhập tay', PASSIVELY_MEASURED: 'đo tự động', ACTIVELY_MEASURED: 'đo khi tập', DERIVED: 'tính toán',
}

/** Human label for one recording source: device first, then app, then platform. */
export function sourceLabel(source: DataSource): string {
  const name = source.device || source.application || PLATFORM_TEXT[source.platform ?? ''] || 'Nguồn không rõ'
  const via = source.device || source.application ? PLATFORM_TEXT[source.platform ?? ''] : undefined
  const method = METHOD_TEXT[source.recording_method ?? '']
  return [name, via && via !== name ? `qua ${via}` : null, method].filter(Boolean).join(' · ')
}
