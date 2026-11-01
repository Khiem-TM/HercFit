import { computed, ref } from 'vue'

/** Dark is HercFit's default look; light and "follow the system" are opt-in. The choice lives in
 * localStorage, and index.html applies it before the first paint so there is no flash. */
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
      // Private mode: the choice lasts for this page only.
    }
    apply()
  }

  /** Flip between the two looks (an explicit choice, so it stops following the system). */
  function toggle(): void {
    setMode(resolved.value === 'light' ? 'dark' : 'light')
  }

  return { mode, resolved, setMode, toggle }
}
