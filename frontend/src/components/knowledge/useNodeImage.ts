import { shallowRef, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import type { MediaTarget } from './knowledgeMedia'

// Chuyển qua lại giữa các ngôi sao không nên tải lại; ảnh tải lên ở nơi khác sẽ hiện trong vài phút.
const cache = new Map<string, { at: number; url: string | null }>()
const FRESH_MS = 120_000

/** Ảnh bìa của một node trên bản đồ, đọc từ media API theo chủ sở hữu khi cần. */
export function useNodeImage(target: () => MediaTarget | null) {
  const { authFetch } = useAuth()
  const url = shallowRef<string | null>(null)
  const loading = shallowRef(false)

  watch(target, async (value, _, onCleanup) => {
    url.value = null
    loading.value = false
    if (!value) return
    const key = `${value.kind}/${value.id}`
    const hit = cache.get(key)
    if (hit && Date.now() - hit.at < FRESH_MS) {
      url.value = hit.url
      return
    }
    const controller = new AbortController()
    onCleanup(() => controller.abort())
    loading.value = true
    try {
      const response = await authFetch(`/api/media/${key}/image`, { signal: controller.signal })
      // Bản ghi bị thiếu hoặc đã bị thay thì đơn giản là không có ảnh để hiển thị.
      const body = response.ok ? await response.json() : null
      const found = typeof body?.image_url === 'string' && body.image_url ? body.image_url : null
      cache.set(key, { at: Date.now(), url: found })
      if (!controller.signal.aborted) url.value = found
    } catch {
      // Bị huỷ hoặc mất mạng: bảng chi tiết hiển thị thông tin mà không có ảnh.
    } finally {
      if (!controller.signal.aborted) loading.value = false
    }
  }, { immediate: true })

  return { url, loading }
}
