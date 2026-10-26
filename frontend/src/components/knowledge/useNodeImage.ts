import { shallowRef, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import type { MediaTarget } from './knowledgeMedia'

// Moving back and forth between stars should not refetch; uploads elsewhere show up within minutes.
const cache = new Map<string, { at: number; url: string | null }>()
const FRESH_MS = 120_000

/** The cover image of a map node, read from the owner-scoped media API on demand. */
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
      // A missing or replaced record simply has no picture to show.
      const body = response.ok ? await response.json() : null
      const found = typeof body?.image_url === 'string' && body.image_url ? body.image_url : null
      cache.set(key, { at: Date.now(), url: found })
      if (!controller.signal.aborted) url.value = found
    } catch {
      // Aborted or offline: the inspector shows the facts without a picture.
    } finally {
      if (!controller.signal.aborted) loading.value = false
    }
  }, { immediate: true })

  return { url, loading }
}
