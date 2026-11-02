import type { HealthConnection, HealthRecordKind, HealthRecordRead } from '@/types/api'

const GH = '/api/integrations/google-health'
const RECORDS = '/api/v2/health/records'

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

/**
 * Client mỏng cho Google Health; mọi lời gọi ném HealthApiError khi lỗi.
 *
 * Đồng bộ là một lượt đọc reconcile rồi đẩy gym và bữa ăn; không có job để theo dõi, nên tiến độ
 * được đọc qua `last_sync_at` của kết nối. Buổi thể thao, số đo và nước uống được ghi thẳng lên Google.
 */
export function createHealthApi(fetcher: Fetcher) {
  async function call<T>(url: string, init: RequestInit | undefined, fallback: string): Promise<T> {
    const response = await fetcher(url, init)
    if (!response.ok) throw await failure(response, fallback)
    return (response.status === 204 ? undefined : await response.json()) as T
  }
  const write = (method: string, body: unknown, key: string): RequestInit => ({
    method, body: JSON.stringify(body), headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
  })

  return {
    connection: () => call<HealthConnection>(GH, undefined, 'Không đọc được trạng thái kết nối Google Health.'),
    sync: () => call<{ status: string; detail: string }>(`${GH}/sync`, { method: 'POST' },
      'Không bắt đầu được đồng bộ.'),
    createRecord: (kind: HealthRecordKind, payload: Record<string, unknown>, key: string = crypto.randomUUID()) =>
      call<HealthRecordRead>(`${RECORDS}/${kind}`, write('POST', payload, key), 'Không ghi được lên Google Health.'),
    updateRecord: (kind: HealthRecordKind, id: string, payload: Record<string, unknown>,
                   key: string = crypto.randomUUID()) =>
      call<HealthRecordRead>(`${RECORDS}/${kind}/${id}`, write('PATCH', payload, key), 'Không sửa được bản ghi.'),
    deleteRecord: (kind: HealthRecordKind, id: string, key: string = crypto.randomUUID()) =>
      call<void>(`${RECORDS}/${kind}/${id}`, { method: 'DELETE', headers: { 'Idempotency-Key': key } },
        'Không xoá được bản ghi.'),
  }
}

export type HealthApi = ReturnType<typeof createHealthApi>

type Sleep = (ms: number) => Promise<void>
const wait: Sleep = ms => new Promise<void>(resolve => setTimeout(resolve, ms))

/**
 * Yêu cầu một lượt đồng bộ rồi chờ `last_sync_at` đổi (lượt đó xong, kể cả khi có loại lỗi) hoặc
 * kết nối rời trạng thái ACTIVE. Trả về kết nối mới, hoặc null khi chưa kết nối, bị huỷ hay hết lượt chờ.
 */
export async function syncAndWait(api: HealthApi, {
  attempts = 40, delayMs = 3000, sleep = wait, signal = undefined as AbortSignal | undefined,
} = {}): Promise<HealthConnection | null> {
  const before = await api.connection()
  if (signal?.aborted || before.status !== 'ACTIVE') return null
  await api.sync()
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    await sleep(delayMs)
    if (signal?.aborted) return null
    const current = await api.connection()
    if (signal?.aborted) return null
    // Token hết hạn: backend chuyển NEEDS_REAUTH mà không ghi last_sync_at.
    if (current.status !== 'ACTIVE' || (current.last_sync_at && current.last_sync_at !== before.last_sync_at)) {
      return current
    }
  }
  return null
}

/** Nhãn tiếng Việt của các loại dữ liệu Google Health mà HercFit đọc. */
export const TYPE_LABELS: Record<string, string> = {
  steps: 'Bước chân', distance: 'Quãng đường', floors: 'Số tầng', 'active-minutes': 'Phút vận động',
  'active-zone-minutes': 'Phút vùng tim', 'active-energy-burned': 'Năng lượng vận động',
  'total-calories': 'Tổng năng lượng tiêu hao', 'heart-rate': 'Nhịp tim', 'sedentary-period': 'Thời gian ít vận động',
  'daily-resting-heart-rate': 'Nhịp tim nghỉ', 'daily-heart-rate-variability': 'HRV',
  'daily-oxygen-saturation': 'SpO₂', 'daily-respiratory-rate': 'Nhịp thở',
  'daily-sleep-temperature-derivations': 'Nhiệt độ da ban đêm', 'daily-vo2-max': 'VO₂ max theo ngày',
  weight: 'Cân nặng', height: 'Chiều cao', 'body-fat': '% mỡ', 'vo2-max': 'VO₂ max', 'run-vo2-max': 'VO₂ max khi chạy',
  'respiratory-rate-sleep-summary': 'Nhịp thở khi ngủ', 'blood-glucose': 'Đường huyết',
  'core-body-temperature': 'Nhiệt độ cơ thể', exercise: 'Buổi tập', sleep: 'Giấc ngủ', 'hydration-log': 'Nước uống',
  electrocardiogram: 'ECG', 'irregular-rhythm-notification': 'Cảnh báo nhịp bất thường',
}
export const typeLabel = (type: string) => TYPE_LABELS[type] ?? type

/** Ai giữ bản gốc của từng nhóm dữ liệu: cách HercFit và Google chia việc. */
export const OWNERSHIP: { title: string; detail: string }[] = [
  { title: 'Chỉ đọc từ Google', detail: 'giấc ngủ, nhịp tim, HRV, SpO₂, nhịp thở, nhiệt độ da, bước chân, calo, ECG' },
  { title: 'Ghi thẳng lên Google', detail: 'buổi thể thao (chạy, bóng đá, cầu lông...), cân nặng, chiều cao, % mỡ, nước uống' },
  { title: 'HercFit lưu rồi đẩy lên Google', detail: 'buổi gym (một buổi STRENGTH_TRAINING) và bữa ăn (mỗi món một mục dinh dưỡng)' },
]
