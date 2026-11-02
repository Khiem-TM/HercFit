import type { HealthConnection } from '@/types/api'
import { type HealthApi, syncAndWait } from './api'

/** Mỗi lần mở Tri thức yêu cầu một lượt đồng bộ; chuyển tab trong bảng điều khiển không yêu cầu thêm. */
export async function refreshKnowledgeHealth(api: HealthApi, signal: AbortSignal): Promise<HealthConnection | null> {
  return syncAndWait(api, {
    attempts: 60, signal,
    sleep: ms => new Promise(resolve => {
      const finish = () => { clearTimeout(timer); signal.removeEventListener('abort', finish); resolve() }
      const timer = setTimeout(finish, ms)
      signal.addEventListener('abort', finish, { once: true })
      if (signal.aborted) finish()
    }),
  })
}
