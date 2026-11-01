import { computed, ref } from 'vue'

/**
 * Tối là giao diện mặc định của HercFit; sáng và "theo hệ thống" là tuỳ chọn. Lựa chọn được lưu trong
 * localStorage, và index.html áp dụng nó trước lần vẽ đầu tiên nên không bị nháy.
 */
export type ThemeMode = 'dark' | 'light' | 'system'

const KEY = 'hercfit:theme'
const BAR_COLOR = { dark: '#131313', light: '#f4f3f0' } as const
const media = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null

function saved(): ThemeMode {
  try {
    const value = localStorage.getItem(KEY)
    return value === 'light' || value === 'system' ? value : 'dark'
  } catch {
    return 'dark'
  }
}

const mode = ref<ThemeMode>(saved())
const systemLight = ref(media?.matches ?? false)
const resolved = computed<'dark' | 'light'>(() => (mode.value === 'system' ? (systemLight.value ? 'light' : 'dark') : mode.value))

function apply(): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  const light = resolved.value === 'light'
  root.classList.toggle('light', light)
  root.classList.toggle('dark', !light)
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', BAR_COLOR[resolved.value])
}

media?.addEventListener('change', event => {
  systemLight.value = event.matches
  apply()
})

export function initTheme(): void {
  apply()
}

export function useTheme() {
  function setMode(next: ThemeMode): void {
    mode.value = next
    try {
      localStorage.setItem(KEY, next)
    } catch {
      // Chế độ riêng tư: lựa chọn chỉ có hiệu lực trong trang này.
    }
    apply()
  }

  /** Chuyển qua lại giữa hai giao diện (một lựa chọn tường minh, nên ngừng theo hệ thống). */
  function toggle(): void {
    setMode(resolved.value === 'light' ? 'dark' : 'light')
  }

  return { mode, resolved, setMode, toggle }
}
