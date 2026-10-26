import { onBeforeUnmount, shallowRef } from 'vue'

export interface ResizeBounds { min: number; max: number }

export interface ResizeOptions {
  axis: 'x' | 'y'
  /** -1 when the pane grows as its handle moves toward the left or the top. */
  grow: 1 | -1
  bounds: () => ResizeBounds
  /** The rendered size, used when the pane still has its natural size. */
  measure: () => number
  /** Remembers the size per browser; storage may be unavailable, so it is never relied upon. */
  storageKey?: string
  step?: number
}

export function clampSize(value: number, { min, max }: ResizeBounds): number {
  return Math.round(Math.min(Math.max(value, min), Math.max(min, max)))
}

/** Pixels the handle moves for a key, along its axis; null for keys it ignores. */
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
 * A pane resized from one edge with a pointer or the keyboard (WAI-ARIA window splitter).
 * `size` stays null until the user resizes, so the pane keeps its natural CSS size.
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

  /** Re-clamp after the viewport or the surrounding layout changed. */
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
      // One layout per frame, however fast the pointer reports.
      frame ||= requestAnimationFrame(() => { frame = 0; set(next, false) })
    }
    const end = () => {
      cleanup?.()
      // A click without movement keeps the natural size.
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
