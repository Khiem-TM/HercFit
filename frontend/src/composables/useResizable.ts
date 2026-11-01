import { onBeforeUnmount, shallowRef } from 'vue'

export interface ResizeBounds { min: number; max: number }

export interface ResizeOptions {
  axis: 'x' | 'y'
  /** -1 khi khung lớn lên lúc tay nắm di chuyển sang trái hoặc lên trên. */
  grow: 1 | -1
  bounds: () => ResizeBounds
  /** Kích thước đã render, dùng khi khung vẫn ở kích thước tự nhiên. */
  measure: () => number
  /** Nhớ kích thước theo từng trình duyệt; bộ nhớ có thể không dùng được, nên không bao giờ phụ thuộc vào nó. */
  storageKey?: string
  step?: number
}

export function clampSize(value: number, { min, max }: ResizeBounds): number {
  return Math.round(Math.min(Math.max(value, min), Math.max(min, max)))
}

/** Số pixel tay nắm di chuyển với một phím, theo trục của nó; null với phím nó bỏ qua. */
export function keyOffset(key: string, axis: 'x' | 'y', step: number): number | null {
  const keys = axis === 'x' ? ['ArrowLeft', 'ArrowRight'] : ['ArrowUp', 'ArrowDown']
  return key === keys[0] ? -step : key === keys[1] ? step : null
}

function restore(key?: string): number | null {
  if (!key) return null
  try {
    const value = Number(localStorage.getItem(key))
    return Number.isFinite(value) && value > 0 ? value : null
  } catch {
    return null
  }
}

/**
 * Một khung được đổi kích thước từ một mép bằng con trỏ hoặc bàn phím (WAI-ARIA window splitter).
 * `size` giữ null cho đến khi người dùng đổi kích thước, nên khung giữ kích thước CSS tự nhiên.
 */
export function useResizable(options: ResizeOptions) {
  const size = shallowRef<number | null>(restore(options.storageKey))
  const dragging = shallowRef(false)
  let cleanup: (() => void) | undefined

  function save() {
    if (!options.storageKey) return
    try {
      if (size.value == null) localStorage.removeItem(options.storageKey)
      else localStorage.setItem(options.storageKey, String(size.value))
    } catch { /* private mode or blocked storage: the size lasts for this visit only */ }
  }

  function set(value: number | null, persist = true) {
    size.value = value == null ? null : clampSize(value, options.bounds())
    if (persist) save()
  }

  /** Kẹp lại sau khi viewport hoặc bố cục xung quanh thay đổi. */
  function fit() {
    if (size.value != null) set(size.value, false)
  }

  function start(event: PointerEvent) {
    if (event.button !== 0 || dragging.value) return
    event.preventDefault()
    const handle = event.currentTarget as HTMLElement
    handle.setPointerCapture(event.pointerId)
    const coordinate = (pointer: PointerEvent) => (options.axis === 'x' ? pointer.clientX : pointer.clientY)
    const origin = coordinate(event)
    const from = size.value ?? options.measure()
    let frame = 0
    let next = from
    dragging.value = true
    document.documentElement.classList.add(`is-resizing-${options.axis}`)
    const move = (pointer: PointerEvent) => {
      next = from + (coordinate(pointer) - origin) * options.grow
      // Mỗi khung hình một lần bố cục, dù con trỏ báo nhanh đến đâu.
      frame ||= requestAnimationFrame(() => { frame = 0; set(next, false) })
    }
    const end = () => {
      cleanup?.()
      // Một cú nhấp không di chuyển thì giữ kích thước tự nhiên.
      if (next !== from) set(next)
    }
    cleanup = () => {
      cancelAnimationFrame(frame)
      handle.removeEventListener('pointermove', move)
      handle.removeEventListener('pointerup', end)
      handle.removeEventListener('pointercancel', end)
      document.documentElement.classList.remove(`is-resizing-${options.axis}`)
      dragging.value = false
      cleanup = undefined
    }
    handle.addEventListener('pointermove', move)
    handle.addEventListener('pointerup', end)
    handle.addEventListener('pointercancel', end)
  }

  function keydown(event: KeyboardEvent) {
    const bounds = options.bounds()
    const offset = keyOffset(event.key, options.axis, (options.step ?? 24) * (event.shiftKey ? 4 : 1))
    let value: number | null | undefined
    if (offset != null) value = (size.value ?? options.measure()) + offset * options.grow
    else if (event.key === 'Home') value = bounds.min
    else if (event.key === 'End') value = bounds.max
    else if (event.key === 'Enter') value = null
    else return
    event.preventDefault()
    set(value)
  }

  onBeforeUnmount(() => cleanup?.())
  return { size, dragging, set, fit, start, keydown, reset: () => set(null) }
}
