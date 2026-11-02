import { onMounted, onUnmounted, ref } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { createHealthApi, HealthApiError } from './api'
import { refreshKnowledgeHealth } from './knowledgeSync'

export function useKnowledgeHealthSync(onComplete: () => void) {
  const { authFetch } = useAuth()
  const controller = new AbortController()
  const api = createHealthApi((url, init) => authFetch(url, { ...init, signal: controller.signal }))
  const message = ref('')
  const revision = ref(0)
  onMounted(async () => {
    try {
      const connection = await refreshKnowledgeHealth(api, controller.signal)
      if (!connection || controller.signal.aborted) return
      if (connection.status === 'NEEDS_REAUTH') {
        message.value = 'Kết nối Google Health đã hết hạn. Hãy kết nối lại trong Cài đặt.'
        return
      }
      message.value = connection.last_error_code
        ? 'Đã cập nhật từ Google Health; một vài loại dữ liệu chưa đọc được.'
        : 'Đã cập nhật từ Google Health.'
      revision.value += 1
      onComplete()
    } catch (err) {
      if (controller.signal.aborted) return
      // 429: vừa đồng bộ cách đây ít phút; dữ liệu đã lưu vẫn mới.
      if (err instanceof HealthApiError && err.status === 429) return
      message.value = 'Chưa cập nhật được từ Google Health. Đang hiển thị dữ liệu đã lưu.'
    }
  })
  onUnmounted(() => controller.abort())
  return { message, revision }
}
