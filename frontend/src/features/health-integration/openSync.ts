import type { HealthConnection } from '@/types/api'
import { type HealthApi, syncAndWait } from './api'

let pending: Promise<HealthConnection | null> | null = null

/**
 * Tần suất đồng bộ "Khi mở ứng dụng": một lượt đồng bộ cho mỗi lần tải trang. Lời gọi sau dùng chung lượt đó;
 * kết nối "hourly" (vòng nền) hoặc "manual" (chỉ khi bấm) không đồng bộ ở đây. Trả về kết nối mới khi đã đồng bộ.
 */
export function syncOnOpen(api: HealthApi): Promise<HealthConnection | null> {
  if (!pending) {
    pending = (async () => {
      const connection = await api.connection()
      if (connection.status !== 'ACTIVE' || connection.sync_frequency !== 'open') return null
      return syncAndWait(api)
    })().catch(() => null)
  }
  return pending
}
