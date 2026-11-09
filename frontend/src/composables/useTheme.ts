import { computed, ref } from 'vue'

/**
 * Chưa chọn thì mỗi bề mặt có giao diện mặc định riêng: trang giới thiệu tối, ứng dụng (/chat) sáng theo
 * thiết kế Dashboard. Lựa chọn tường minh (tối / sáng / theo hệ thống) được lưu trong localStorage và áp
 * cho mọi trang; index.html áp dụng nó trước lần vẽ đầu tiên nên không bị nháy.
 */
export type ThemeMode = 'dark' | 'light' | 'system'

const KEY = 'hercfit:theme'
const BAR_COLOR = { dark: '#131313', light: '#f4f3f0' } as const
const media = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null

function saved(): ThemeMode | null {
  try {
    const value = localStorage.getItem(KEY)
    return value === 'light' || value === 'system' || value === 'dark' ? value : null
  } catch {
    return null
  }
}

const chosen = ref<ThemeMode | null>(saved())
// Giao diện khi người dùng chưa chọn; ChatPage đặt 'light' khi vào ứng dụng.
const fallback = ref<'dark' | 'light'>(typeof location !== 'undefined' && location.pathname.startsWith('/chat') ? 'light' : 'dark')
const mode = computed<ThemeMode>(() => chosen.value ?? fallback.value)
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

/** Giao diện mặc định của bề mặt đang hiển thị (chỉ có tác dụng khi người dùng chưa tự chọn). */
export function useThemeDefault(next: 'dark' | 'light'): void {
  fallback.value = next
  apply()
}

export function useTheme() {
  function setMode(next: ThemeMode): void {
    chosen.value = next
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
