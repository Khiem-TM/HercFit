import type { OperationRead } from '@/types/api'
import { type HealthApi, waitForOperation } from './api'

/** One visit requests one refresh; switching dashboard tabs never requests another. */
export async function refreshKnowledgeHealth(api: HealthApi, signal: AbortSignal,
  onUpdate: (operation: OperationRead) => void): Promise<OperationRead | null> {
  const connection = await api.connection()
  if (signal.aborted || connection.status !== 'ACTIVE') return null
  const { operation_id: id } = await api.startSync()
  if (signal.aborted) return null
  return waitForOperation(api, id, onUpdate, {
    attempts: Infinity, signal,
    sleep: ms => new Promise(resolve => {
      const finish = () => { clearTimeout(timer); signal.removeEventListener('abort', finish); resolve() }
      const timer = setTimeout(finish, ms)
      signal.addEventListener('abort', finish, { once: true })
      if (signal.aborted) finish()
    }),
  })
}
