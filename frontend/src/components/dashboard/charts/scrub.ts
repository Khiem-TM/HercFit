/**
 * Chọn ngày trên biểu đồ theo ngày (kiểu "rê để xem" của ứng dụng sức khoẻ): cả vùng vẽ là một vùng chạm, vị trí ngón
 * tay/chuột theo chiều ngang quyết định ngày, nên 90 cột hẹp vài pixel vẫn chọn chính xác được. Bàn phím: vùng vẽ là
 * một điểm Tab duy nhất (role="slider"), mũi tên ±1 ngày, PageUp/PageDown ±7 ngày, Home/End về đầu/cuối.
 */
export function indexAt(event: PointerEvent, count: number): number {
  const box = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const ratio = box.width > 0 ? (event.clientX - box.left) / box.width : 1
  return Math.max(0, Math.min(count - 1, Math.floor(ratio * count)))
}

const STEPS: Record<string, number> = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1, PageDown: -7, PageUp: 7 }

/** Chỉ số mới sau một phím, hoặc null khi phím không dành cho biểu đồ (để trình duyệt xử lý như thường). */
export function indexAfterKey(event: KeyboardEvent, current: number, count: number): number | null {
  if (event.key === 'Home') return 0
  if (event.key === 'End') return count - 1
  const step = STEPS[event.key]
  if (step == null) return null
  return Math.max(0, Math.min(count - 1, current + step))
}

/** Rê chuột (không cần bấm) hoặc kéo ngón tay đều chọn ngày; chạm một lần cũng chọn. */
export function follows(event: PointerEvent): boolean {
  return event.pointerType === 'mouse' || event.buttons > 0
}
