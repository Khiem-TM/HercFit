import { nextTick } from 'vue'

const FOCUSABLE = [
  'a[href]', 'button:not([disabled])', 'input:not([disabled]):not([type="hidden"])', 'select:not([disabled])',
  'textarea:not([disabled])', 'summary', '[tabindex]:not([tabindex="-1"])',
].join(',')

// Phần tử nhận focus gần nhất. Khi nền thành `inert` trình duyệt bỏ focus khỏi nút vừa mở hộp thoại (focus về body),
// nhất là với hộp thoại tải async như Dashboard: lúc nó mount, nút đó đã mất focus.
let lastFocused: HTMLElement | null = null
if (typeof document !== 'undefined') {
  document.addEventListener('focusin', event => { if (event.target instanceof HTMLElement) lastFocused = event.target }, true)
}

/**
 * Focus của một hộp thoại modal (mẫu WAI-ARIA dialog): mở thì đưa focus vào hộp thoại, Tab/Shift+Tab đi vòng trong
 * nó, đóng thì trả focus về phần tử đã mở nó. Phần nền phía sau do trang cha đặt `inert` (không bấm, không Tab tới,
 * trình đọc màn hình bỏ qua). `root` trả về phần tử DOM của hộp thoại (phần tử motion: lấy qua `$el`).
 */
export function useDialogFocus(root: () => HTMLElement | null | undefined) {
  let returnTo: HTMLElement | null = null

  async function open(): Promise<void> {
    const active = document.activeElement
    const candidate = active instanceof HTMLElement && active !== document.body ? active : lastFocused
    if (candidate && !root()?.contains(candidate)) returnTo = candidate
    await nextTick()
    root()?.focus({ preventScroll: true })
  }

  /** Gọi sau khi nền đã hết `inert` (watch flush 'post' hoặc onUnmounted), nếu không focus sẽ không vào được. */
  function close(): void {
    const target = returnTo
    returnTo = null
    if (target?.isConnected && !target.closest('[inert]')) target.focus({ preventScroll: true })
  }

  function keydown(event: KeyboardEvent): void {
    const dialog = root()
    if (event.key !== 'Tab' || !dialog) return
    const items = [...dialog.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(item => item.getClientRects().length > 0)
    if (!items.length) {
      event.preventDefault()
      dialog.focus()
      return
    }
    const first = items[0]
    const last = items[items.length - 1]
    const current = document.activeElement
    if (event.shiftKey && (current === first || current === dialog)) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && current === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return { open, close, keydown }
}

/** DOM của ref trỏ vào phần tử thường hoặc component motion (lấy qua `$el`). */
export function domOf(node: unknown): HTMLElement | null {
  const target = node as (HTMLElement & { $el?: HTMLElement }) | null
  return target?.$el ?? target ?? null
}
