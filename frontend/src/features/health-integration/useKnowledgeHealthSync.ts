import { onMounted, onUnmounted, ref } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { createHealthApi, OPERATION_TEXT } from './api'
import { refreshKnowledgeHealth } from './knowledgeSync'

export function useKnowledgeHealthSync(onComplete: () => void) {
  const { authFetch } = useAuth()
  const controller = new AbortController()
  const api = createHealthApi((url, init) => authFetch(url, { ...init, signal: controller.signal }))
  const message = ref('')
  const revision = ref(0)
  onMounted(async () => {
    try {
      const result = await refreshKnowledgeHealth(api, controller.signal, op => {
        message.value = op.state === 'SUCCEEDED' ? 'Đã cập nhật từ Google Health.'
          : `Google Health: ${OPERATION_TEXT[op.state].toLowerCase()}.`
      })
      if (result && !controller.signal.aborted) {
        revision.value += 1
        onComplete()
      }
    } catch {
      if (!controller.signal.aborted) message.value = 'Chưa cập nhật được từ Google Health. Đang hiển thị dữ liệu đã lưu.'
    }
  })
  onUnmounted(() => controller.abort())
  return { message, revision }
}
